# M4-9 — Operator Runbook (Tiered)

> Authority: `docs/M4-9-DASHBOARD-TRIGGER-DESIGN-VI.md`,
> `CA-Docs/PHASE1B-M4-9-TIERED-MODEL-POLICY-REVIEW-64-VI.md` (tiered model).
> **Tier A** (routine) là việc thường ngày — đọc §1 là đủ. **Tier B** (production KMS) hiếm — §2.

---

## §1. TIER A — Routine evidence batch ("1 người, 1 màn hình")

Cho việc thường xuyên: đóng dấu toàn vẹn batch transcript (eval PII / lưu bằng chứng nội bộ).
Blast radius thấp, tự purge, **không** non-repudiation. **1 operator**, không USB, không SoD.

### Cần gì
- Tài khoản có quyền `m4.signing.run.start` + `operate` + `approve` (một người đủ cho Tier A).
- **Không** cần USB, không cần người thứ hai, không nhập PIN/khóa.

### Làm gì (toàn bộ trên dashboard `/signing`)
1. Bấm **Start Production Signing Run** → chọn **"Tier A — Routine evidence batch"**, điền scope
   (ví dụ `batch_size`), window, quota → **Tạo**.
2. Bấm **Chạy Preflight** → màn hình hiện **checklist xanh/đỏ** (window / scope / quota / dormant).
   **Đọc màn hình** — tất cả xanh mới đi tiếp. Đỏ thì sửa theo dòng mô tả.
3. Bấm **Ghi Ceremony** (Tier A: chỉ ghi một ghi chú công khai, không USB).
4. Bấm **Yêu cầu Canary** → **Duyệt Canary** (Tier A: **chính bạn** duyệt được — không cần người khác).
5. Bấm **Thực thi** → hệ thống chạy nền; theo dõi state chuyển `EXECUTING` → `CLOSED`.
6. Xong: state `CLOSED`, quota + audit hiện trên chi tiết. Đó là bằng chứng đã đóng gói.

### Check thế nào
- **Chỉ nhìn màn hình:** state machine (xanh = xong), preflight checklist, lịch sử event.
- Không cần đọc log CLI, không cần biết trạng thái DB.

### Nếu đỏ / sự cố
- Preflight đỏ → đọc dòng mô tả (vd "ngoài window", "quota hết") → sửa hoặc tạo run mới.
- Bất thường giữa chừng → bấm **Abort** (nhập lý do). Hệ thống tự cleanup về dormant.

### Hệ thống TỰ nâng lên Tier B (bạn không phải nhớ)
Nếu run khai một trong: cần non-repudiation / giao nộp ngoài / PII chưa mask / cross-tenant /
`batch_size` > 260 / quota > 5 → dashboard **tự** chuyển run thành Tier B (hiện nhãn "đã nâng
cấp") và **khóa** cho tới khi làm đủ ceremony §2. Đây là fail-closed — an toàn, không cần bạn tự quyết.

---

## §2. TIER B — Production KMS signing (hiếm, có ceremony)

Chỉ khi cần **non-repudiation mật mã** cho audit ngoài / pháp lý. Giữ đầy đủ kiểm soát như H2-B.

### Khác Tier A
| Khía cạnh | Tier B |
|---|---|
| Số người | **2 người** — operator ≠ approver (SoD, ép ở backend + DB) |
| Ceremony | **USB CA02 offline** ký leaf cert mới (TTL ≤24h) — theo ceremony runbook riêng |
| Backend ký | **Ed25519 qua Google KMS** (non-repudiation) |
| Data boundary | **bắt buộc** khai tường minh (tenant/khoảng thời gian) |

### Trình tự (thêm so với Tier A)
1. Start → chọn **"Tier B — Production KMS"**, khai data-boundary.
2. Preflight (như Tier A) + **fresh IAM/WIF check**.
3. **Ceremony USB CA02** (offline) → nhập fingerprint/serial **công khai** vào dashboard (KHÔNG PIN/khóa).
4. **Canary** do **người thứ hai** (approver ≠ operator) duyệt — dashboard chặn nếu cùng người.
5. Execute → giám sát → CLOSED. Cleanup về dormant.

### Human checkpoints Tier B
- Ceremony USB: PO/custodian giữ USB + passphrase (ngoài dashboard).
- Approve Canary: approver đọc kết quả trước khi gật; cùng người với operator → **bị chặn**.

---

## §3. RACI (giai đoạn xây dựng — Directive 70)

| Vai | Người hiện tại | Tier A | Tier B |
|---|---|---|---|
| Service Owner / PO | **HOAI** | ✓ | ✓ |
| Tier A Operator | **signer1** (role `m4_signing_operator`) | vận hành + tự approve | — |
| Tier B Operator / Approver | (PO chỉ định) | — | operator ≠ approver (SoD máy ép) |
| Security Custodian (USB CA02) | PO | — | ✓ |
| Incident Owner | **HOAI** | nhận `CLEANUP_FAILED` | nhận alert |

Tên "Staff N" là placeholder; PO chỉ định người thật sau go-live (xem acceptance §5).

## §5. Provisioning operator + break-glass (hardened — Directive 70 + 70A)

Cấp/thu hồi operator ký + reset admin **chỉ qua CLI version-controlled** (không qua dashboard;
`/staff` UI có subset-check chặn). Ai chạy: **PO hoặc operator chính được PO ủy quyền** (custody SSH).

**Bắt buộc mọi lần:** `--actor` (người thực hiện) + `--ticket` (change ticket) + `--reason` — thiếu
là fail-closed. Chạy `--dry-run` xem plan trước, thêm `--yes` mới thực thi. Mật khẩu nhập **ẩn qua
terminal** (getpass), không qua lệnh/env. Mỗi lần ghi **audit bất biến** (`audit_log`: actor/target/
role/grants/ticket/reason/result — không secret).

| Việc | Lệnh (trong container api, KHÔNG -T) |
|---|---|
| Cấp operator (plan) | `python scripts/provision_m4_signing_operator.py <user> --actor hoai --ticket <T> --reason "..." --dry-run` |
| Cấp operator (thực thi) | như trên, bỏ `--dry-run`, thêm `--yes` (sẽ hỏi mật khẩu) |
| **Thu hồi** operator → dormant | `... provision_m4_signing_operator.py <user> --revoke --actor hoai --ticket <T> --reason "..." --yes` |
| Reset admin | `python scripts/reset_admin_user.py <user> --actor hoai --ticket <T> --reason "..." --yes` |

**Bất biến:** role `m4_signing_operator` chỉ có đúng 5 quyền `m4.signing.run.*` (migration 048 chốt +
DB trigger allowlist chống cấp quyền ngoài); script **chỉ gán role cố định**, không tạo/grant quyền
→ không escalation. **Assignment ≠ activation** — có operator vẫn cần Activation Gate riêng mới ký thật.

## §6. RACI cũ (Tier A/B — tham chiếu)

| Vai | Tier A | Tier B |
|---|---|---|
| Operator | 1 người (kiêm approve) | operator |
| Approver | (kiêm) | **người khác** operator |
| Security Custodian (USB) | — | PO/custodian |
| Incident Owner | nhận alert `CLEANUP_FAILED` | nhận alert |

## §4. Điều luôn đúng (cả hai tầng — máy tự lo)
fail-closed preflight · ledger/audit bất biến · no-secret (không nhập PIN/khóa/token qua dashboard) ·
không nút force/skip · abort luôn có · `CLEANUP_FAILED` → alert · kết thúc dormant.
