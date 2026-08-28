# M4-9 — Dashboard Trigger cho Production Signing Run: Thiết kế baseline (freeze)

> Authority: `CA-Docs/PHASE1B-M4-9-OPERATIONAL-HANDOVER-GOVERNANCE-DIRECTIVE-58-VI.md`,
> `…-DASHBOARD-TRIGGER-ADDENDUM-59-VI.md`, `…-DASHBOARD-TRIGGER-IMPLEMENTATION-PACKAGE-60-VI.md`,
> `…-CONSOLIDATED-DEV-PROCESS-ADDENDUM-61-VI.md`.
> Baseline này freeze interface/policy theo Addendum 61 §3.1. Mọi thay đổi baseline phải ghi vào
> §"Change log" cuối file.

## 1. Mục tiêu & ranh giới

Xây một **control/approval surface** trên dashboard để PO/Operator khởi động và giám sát một đợt
ký transcript (production signing run), **không tự thực thi ký**. Dashboard chỉ tạo run request +
thu approval + hiển thị trạng thái; **backend worker/pipeline là execution authority** — bọc CLI
đã có (`scripts/m4_stage0p_rehearsal_runner.py`) chứ không viết lại logic ký.

**Trong phạm vi M4-9 (Package 60):** code + test + **synthetic rehearsal** (dùng đúng đường
`run --dry-run` và E2E synthetic của runner). **Ngoài phạm vi:** merge main, deploy, production
credential, start signer thật, STS/KMS production sign, customer data, IAM/KMS/WIF mutation.

## 2. Nguyên tắc bất biến (từ Addendum 59/60 §3)

1. Dashboard = control/approval; backend = execution authority. Dashboard **không chứa** business
   secret, private key, PIN, raw token, customer data — trong request/UI/log/evidence.
2. **Không** nút `force` / `retry unlimited` / `skip preflight`. Retry chỉ cho lỗi transient, nằm
   trong quota. **Attempt counter không reset** bởi retry/UI refresh (đếm ở DB, server-side).
3. Preflight **fail-closed**: bất kỳ check nào fail → khóa nút. Nút bị khóa khi ngoài window,
   thiếu change approval, stale/drift preflight, scope drift, hoặc prerequisite dormant không đạt.
4. **PO approval bắt buộc** trước bước signer/canary. **Abort luôn khả dụng.** Break-glass cần PO
   confirmation + reason.
5. **RBAC + dual-control (SoD)**: `approve` ≠ `operate` (đã ép ở tầng Postgres — không nới lỏng).
6. Mọi click/approval/abort là **audit event**. Raw output tên bất biến theo run-id; không overwrite.

## 3. State machine (nguồn sự thật ở DB — bảng `m4_signing_run`)

```
CREATED ─confirm→ CONFIRMED ─preflight(pass)→ PREFLIGHT_PASSED ─ceremony→ CEREMONY_RECORDED
   │                                                 │ (fail)                    │
   │                                                 ▼                           ▼
   └──────────────── ABORTED ◄─── (abort ở bất kỳ state active) ────────► CANARY_PENDING
                        ▲                                                        │ approve
                        │                                                        ▼
   FAILED ◄─(lifecycle/cleanup lỗi)─ EXECUTING ◄──────── canary approve ── CANARY_APPROVED
                                        │ success
                                        ▼
                                     CLOSED  (cleanup + dormant proof đã ghi)
```

- **Terminal states:** `CLOSED` (success), `ABORTED` (PO chủ động), `FAILED` (lifecycle/cleanup lỗi
  — trạng thái NGUY HIỂM: `CLEANUP_FAILED` từ runner → alert riêng).
- Mỗi transition kiểm precondition server-side; transition không hợp lệ → 409, không đổi state.
- `attempt_ledger`: mỗi lần chạm STS/sign (qua adapter) ghi 1 row bất biến; không có đường reset.
- Một run active (chưa terminal) khóa bằng advisory lock — không cho 2 run song song.

## 4. Bước ↔ transition ↔ authority

| Bước UI (Addendum 59) | State đích | Permission HTTP | Human/checkpoint |
|---|---|---|---|
| Start Production Signing Run | CREATED | `m4.signing.run.start` | PO khởi tạo (run-id, scope, window, quota, data-boundary) |
| Review & Confirm | CONFIRMED | `m4.signing.run.start` | PO xác nhận plan |
| Automated preflight | PREFLIGHT_PASSED | (server tự chạy) | fail-closed, không human |
| Human ceremony checkpoint | CEREMONY_RECORDED | `m4.signing.run.operate` | PO làm USB/offline, nhập **public metadata/fingerprint** (KHÔNG PIN/khóa) |
| Approve Canary | CANARY_APPROVED | `m4.signing.run.approve` | PO duyệt — **SoD: người approve ≠ operator** |
| Bounded execution | EXECUTING→CLOSED | `m4.signing.run.operate` | live status + nút Abort |
| Abort / Break-glass | ABORTED | `m4.signing.run.abort` | PO confirm + reason |

`m4.signing.run.approve` và `m4.signing.run.operate` **không được** cùng một staff trong một run
(SoD kiểm server-side, phản chiếu SoD `approve`≠`operate` của tầng stage0p Postgres).

## 5. Backend adapter → CLI contract (bọc, không viết lại)

Adapter (arq worker job) map từng bước sang lệnh runner đã có:

| Bước | Lệnh CLI | Tín hiệu PASS |
|---|---|---|
| preflight | `run --dry-run` | exit 0 + stdout `"dry_run_ready"` |
| canary probe | `signing_probe mint-token` → `submit` (2 danh tính) | exit 0 + `"m4_signing_probe_ok"` |
| execute | `run` (execute) | exit 0 + stdout `"rehearsal_execute_succeeded"` |
| cleanup guard | (trong `run`) | **vắng** `"CLEANUP_FAILED"` |

Adapter **luôn parse JSON log** (`[m4-rehearsal-runner] {...}`) + exit code; `CLEANUP_FAILED`
(exit≠0) là trạng thái nguy hiểm → `FAILED` + alert. Không gọi 2 `run` song song (advisory lock
single-writer của runner). DSN chuẩn hóa qua `m4_dsn_utils`, không log lại.

## 6. Xử lý credential (design decision — known limitation)

`pin_secret`/`staff_id` của tầng stage0p là **bespoke credential**, chưa nối JWT/HTTP auth
(blocker F-M4-0P-T9-03 chưa đóng — ngoài phạm vi M4-9). Theo luật "no secret qua dashboard":

- Dashboard **chỉ** truyền `staff_id` + `reason` + public metadata; **không bao giờ** `pin_secret`.
- Backend worker lấy `pin_secret` từ **nguồn server-side ngoài luồng** (env/secret-file của worker,
  provisioned bởi superuser — như runbook stage0p hiện tại). Trong **synthetic rehearsal** dùng
  pin_secret sandbox provisioned qua `m4_stage0p_actor_credentials`.
- Hệ quả khai rõ: mô hình auth production đầy đủ (nối JWT staff ↔ pinned actor) là **việc sau**,
  cần gate riêng; M4-9 chứng minh control-surface + orchestration, không đóng T9-03.

## 7. RBAC mới

Thêm 5 permission vào catalog `permissions` (migration 046): `m4.signing.run.start`,
`m4.signing.run.operate`, `m4.signing.run.approve`, `m4.signing.run.abort`, `m4.signing.run.view`.
Chưa seed vào role nào mặc định (PO gán tường minh) — trừ `admin` được `view`. Enforce HTTP qua
`require_permission(...)`; SoD approve≠operate kiểm ở service layer + tái khẳng định ở Postgres.

## 8. Evidence & rehearsal

Synthetic rehearsal (Acceptance Addendum 59): từ nút dashboard → tạo run-id → preflight →
approval checkpoint → bounded canary → audit/metric/alert → cleanup → dormant proof. Chứng minh
**không có đường bypass** dashboard/policy và mọi human action của PO được audit. Evidence đóng
theo schema 10 phần Addendum 61 §4.

## 9. Change log
- v1 (28/8): baseline freeze ban đầu.
