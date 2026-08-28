# M4-9 — Threat Model & Security Controls (Dashboard Signing Trigger)

> Authority: `docs/M4-9-DASHBOARD-TRIGGER-DESIGN-VI.md`, Package 60 §3, Addendum 61 §H.
> Phạm vi: control/approval surface + orchestration. Không bao gồm mật mã KMS/WIF (đã có gate H2-A/H2-B).

## 1. Tài sản cần bảo vệ

| Tài sản | Vị trí | Rủi ro nếu lộ/lạm dụng |
|---|---|---|
| pin_secret (actor) | `m4_stage0p_actor_credentials` (bcrypt), env worker | mạo danh actor → bật capture/ký |
| Khóa ký (HMAC/auth) | bảng signing keys (role-restricted), env signer | giả mạo transcript/authorization |
| Private key leaf / CA02 | tmpfs VPS / USB offline | non-repudiation bị phá |
| Access token (STS/WIF) | runtime signer (TTL ngắn) | gọi KMS trái phép |
| Customer transcript | DB (capture zone) | lộ PII |

## 2. Ranh giới tin cậy

```
[Dashboard UI] --HTTP(JWT)--> [FastAPI router] --enqueue--> [arq worker] --subprocess--> [CLI runner]
   control/approval              gate RBAC HTTP                 execution authority        --socket--> [signer]
                                                                                            RBAC Postgres (pinned actor)
```

Dashboard **không** vượt qua ranh giới nào để chạm secret: nó chỉ tạo state + approval. Mọi
execution đi qua worker→CLI→Postgres RBAC.

## 3. Threats & controls (STRIDE rút gọn)

| # | Threat | Control (đã implement) |
|---|---|---|
| T1 | **Spoofing** actor qua UI | JWT staff session (`require_active_session`) + `require_permission` mỗi endpoint; pin_secret **không** qua UI — worker lấy server-side. |
| T2 | **Tampering** attempt counter (reset để vượt quota) | ledger `m4_signing_run_attempt` **append-only** (trigger chặn UPDATE/DELETE); quota đếm theo số row; UI refresh không đổi count. |
| T3 | **Repudiation** hành động PO | mọi transition + human action ghi `m4_signing_run_event` bất biến (actor + reason + timestamp). |
| T4 | **Info disclosure** secret vào log/evidence | `redact()` ở adapter; CHECK `no_secret` trên mọi cột JSON (scope/metadata/attempt/event); `_assert_no_secret` ở service; `_worker_env` từ chối secret-key từ caller. |
| T5 | **Elevation** — operator tự duyệt canary | **Tiered (Review 64):** SoD `approve≠operate` ép cho **`run_kind='production'`** (service `SoDViolation` + DB CHECK `m4_signing_run_sod` state-aware); Tier A (`evidence_batch`/synthetic) là single-operator hợp lệ (blast-radius thấp, no non-repudiation). Auto-escalate Tier A→production fail-closed nếu non-repudiation/PII-ngoài-scope/batch>260/quota>5. |
| T6 | **Bypass preflight** (chạy ngoài window/khi drift) | preflight fail-closed; ceremony/execute yêu cầu **preflight còn tươi (≤15')**; state machine allowlist chặn nhảy bước. |
| T7 | **Race** 2 run song song | partial unique index `single_active`; runner có advisory lock single-writer. |
| T8 | **Confused deputy** — dashboard bị lừa gọi signing | dashboard không có đường gọi signer trực tiếp; chỉ enqueue job; worker + Postgres RBAC là nơi thực thi. |
| T9 | **Dangerous silent success** (`CLEANUP_FAILED`) | adapter grep `CLEANUP_FAILED` → run=FAILED + alert; không bao giờ báo success khi hệ chưa an toàn. |

## 4. Data-boundary proof

- Cột JSON của M4-9 (`scope`/`data_boundary`/`public_metadata`/`detail`) **không** chứa
  plaintext/PII/secret — enforce 3 lớp (service regex + DB CHECK + no plaintext transcript trong
  bảng M4-9; transcript chỉ digest, do stage0p quản lý).
- Ceremony chỉ nhận **fingerprint/serial công khai**.
- Synthetic rehearsal dùng dữ liệu tổng hợp (prefix `m4synthrehearsalv1_`), không customer data.

## 5. Known limitations (khai chủ động)

1. **pin_secret ↔ JWT chưa nối** (blocker F-M4-0P-T9-03 chưa đóng, ngoài phạm vi M4-9): dashboard
   truyền `staff_id`; worker lấy pin_secret server-side. Mô hình auth production đầy đủ là gate sau.
2. **RBAC nút ở frontend**: `/me` chưa trả `permissions` → UI hiện nút cho mọi user đã login;
   backend chặn 403. Ẩn nút theo quyền là cải tiến optional.
3. **Production run**: cần Decision Record + Activation Gate riêng (M4-9 chỉ chứng minh
   control-surface + synthetic rehearsal; không tự cho phép ký production).
