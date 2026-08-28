# M4-9 — Operator Runbook & RACI (Dashboard-triggered Signing Run)

> Authority: `docs/M4-9-DASHBOARD-TRIGGER-DESIGN-VI.md`,
> `CA-Docs/PHASE1B-M4-9-OPERATIONAL-HANDOVER-GOVERNANCE-DIRECTIVE-58-VI.md`.
> Đối tượng: Operations tự vận hành sau handover; CA/Dev KHÔNG tham gia routine.

## 1. RACI

| Vai trò | Trách nhiệm |
|---|---|
| **PO / Service Owner** | Chốt scope/window/quota/data-boundary; quyết định abort/rollback; custody USB CA02 + passphrase. |
| **Operator / SRE** | Thao tác dashboard (start→confirm→preflight→ceremony→execute), giám sát live status. **Không** kiêm approver của cùng run (SoD). |
| **Approver** | Duyệt canary (bước `canary-approve`). **Phải khác Operator.** |
| **Security Custodian** | Giữ pin_secret provisioning (server-side, ngoài dashboard) và khóa/USB. |
| **Incident Owner** | Nhận alert `CLEANUP_FAILED`/health-degradation; điều phối break-glass. |

Dual-control bắt buộc: (a) `approve` ≠ `operate` (ép ở service + Postgres); (b) USB/secret do PO/Custodian giữ, không qua dashboard.

## 2. Tiền điều kiện mỗi đợt (kiểm trước khi bấm Start)

1. Production đang **dormant** (không signer container chạy; capture OFF).
2. Có **approval_ref** hợp lệ (window + purpose, chưa revoke) đã ghi qua `rehearsal_runner record-approval` (server-side, PO/approval-recorder).
3. **pin_secret** của operator/reviewer đã provisioned ngoài luồng (superuser, `m4_stage0p_actor_credentials`) — **không** nhập qua dashboard.
4. Với production run: **data-boundary** đã khai tường minh (tenant/khoảng thời gian) và tập dữ liệu đã mask/không-PII theo Decision Record.

## 3. Trình tự thao tác (dashboard `/signing`)

| Bước | Nút | Điều kiện khoá (server enforce) |
|---|---|---|
| 1 | **Start Production Signing Run** | quyền `m4.signing.run.start`; không có run active khác |
| 2 | **Confirm** | state=CREATED |
| 3 | **Chạy Preflight** | state=CONFIRMED; fail-closed nếu ngoài window/scope rỗng/quota hết/capture ON |
| 4 | **Ghi Ceremony** | state=PREFLIGHT_PASSED **và preflight còn tươi (≤15')**; chỉ nhập fingerprint/serial **công khai** |
| 5 | **Yêu cầu Canary** → **Duyệt Canary** | approve bởi người **khác** operator (SoD) |
| 6 | **Thực thi** | preflight còn tươi; nhập manifest/approval_ref/reviewer (tham chiếu, không secret) → enqueue arq |
| 7 | tự động | worker chạy CLI runner; success→CLOSED, lỗi→FAILED, `CLEANUP_FAILED`→FAILED+alert |

**Abort** khả dụng ở mọi state active (yêu cầu reason). Không có nút force/skip/retry-unlimited.

## 4. Human checkpoints (PO đọc output, xác nhận có timestamp)

- **Ceremony (bước 4):** PO thực hiện USB CA02 offline (theo `docs/…` ceremony runbook), chỉ nhập metadata công khai vào dashboard.
- **Approve Canary (bước 5):** approver đọc kết quả canary trước khi gật; không gật → không execute.
- **Trong Execute (bước 6-7):** operator giám sát attempt counter + audit/metric; bất thường → Abort.

## 5. Break-glass / rollback

- **Mặc định:** Abort → run sang ABORTED; runner tự cleanup (capture-off, retire keys, purge synthetic, terminalize batch). Không mutation ngoài phạm vi.
- **Emergency provider disable** (nghi lộ khóa/lạm dụng): **chỉ PO** ra lệnh; dùng lệnh exact trong Execution Directive; **không** thao tác từ dashboard; re-enable qua gate CA mới.
- **`CLEANUP_FAILED`** (exit≠0, trạng thái nguy hiểm nhất): run=FAILED, Incident Owner vào cuộc — **không** báo thành công, giữ nguyên hiện trường, đối chiếu `m4_selection_batches.status`/`capture_progress`.

## 6. Key/certificate lifecycle

- Cert leaf: mới mỗi ceremony, TTL ≤ window+1h & ≤24h; hủy sau lifecycle (shred tmpfs).
- Signing keys (HMAC/auth): provision qua `rehearsal_runner provision-keys` trước, `retire-keys` sau (runner tự retire trong cleanup).
- pin_secret: provisioned ngoài luồng; xoay khi nghi lộ.

## 7. Quan sát & bằng chứng

Mỗi run để lại: `m4_signing_run` (state), `m4_signing_run_attempt` (ledger quota bất biến),
`m4_signing_run_event` (audit transition). Log adapter đã redact secret. Evidence đóng theo
schema 10 phần (Addendum 61 §4).
