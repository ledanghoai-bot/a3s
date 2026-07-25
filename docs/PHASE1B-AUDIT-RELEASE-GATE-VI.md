---
id: A3S-PHASE1B-AUDIT-RELEASE-GATE-001
title: Alpha3S I-B M0 — Audit Release-Gate (group-A events, redaction, DB-enforcement)
document_type: audit_release_gate
parent: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
owner: Alpha3S
author_role: Dev
version: 1.0.0
status: submitted_to_ca
created_at: 2026-07-25
language: vi-VN
---

# Audit Release-Gate (CA-REVIEW-M0-DEV-002 §8)

## 1. Nhóm A — sensitive mutation FAIL-CLOSED (audit + mutation cùng transaction)
Danh sách CHÍNH XÁC các sự kiện nhóm A: **audit_log insert nằm CÙNG transaction với mutation; ghi audit
fail → ROLLBACK mutation.**

| Action | Entity | Trạng thái implement |
|---|---|---|
| `staff.create` | staff_user | ✅ `auth_router.create_staff` (audit cùng txn) |
| `staff.update` (activate/deactivate/role) | staff_user | ✅ `auth_router.update_staff` |
| `auth.password_change` | staff_user | ✅ `auth_service.change_password` |
| `auth.revoke_sessions` | staff_user | ✅ (kèm password_change/deactivate) |
| `role.assign` / `permission.change` | staff_user/role | ✅ qua staff.update (role_key) |
| `customer.export` (PII export) | customer | 🔜 khi có endpoint export (M0.x/M6) |
| `price.override` | price_override | 🔜 milestone pricing |
| `inventory.adjust` | inventory | 🔜 M2 |
| `address.override` | order/address | 🔜 M5 |
| `refund` / `payment.reconcile` | payment | 🔜 M6 |
| `approval.decide` (approve/reject) | approval | 🔜 approval framework |

*(Các dòng 🔜 chưa có endpoint ở M0; khi implement PHẢI theo pattern nhóm A. Nhóm B best-effort chỉ cho
telemetry: `auth.login`/`auth.login_failed`.)*

## 2. Bằng chứng test (§8)
- **Audit fail-closed rollback (service-primitive):** `m0_foundation_validation.py` — Evidence E3.
- **Audit fail-closed rollback (ENDPOINT-LEVEL, CA §9):** `audit_rollback_endpoint_test.py` — force audit
  insert fail (`CHECK(false) NOT VALID`) → **`staff.create` + `password_change` ROLLBACK mutation** (staff
  không được tạo / mật khẩu không đổi); audit-ok path ghi `audit_log`. **Evidence E7** (Evidence Package
  v1.0.1, SHA `931943d…`).
- **Redaction (credential + PII + nested):** cùng script — payload lồng nhau `{phone, customer:{email,
  address, token, name}, items:[{sdt}]}` → phone/email/address/token/sdt = `***REDACTED***` ở MỌI cấp,
  field thường (`name`) giữ nguyên. Evidence E3 (`redaction secret+PII nested OK`). Allowlist nghịch:
  `app/services/audit_service.py:_SENSITIVE_KEYS` (password/hash/token/secret/api_key/private_key +
  phone/sdt/email/address/psid/external_id), `_redact_value` đệ quy.

## 3. Append-only DB-enforcement — TIME-BOXED EXCEPTION (§8)
**Hiện trạng:** app + migration production dùng **cùng một DB role `alpha3s`** (owner). REVOKE UPDATE/DELETE
trên `audit_log` khỏi owner **không có tác dụng** (owner bypass grant). Append-only hiện chỉ ở mức
**convention** (không có endpoint update/delete audit; code chỉ INSERT/SELECT).

**Đề xuất DB-enforcement thật (defense-in-depth):** tách 2 role —
- `alpha3s_migrate` (owner, chạy migration).
- `alpha3s_app` (runtime app): `GRANT INSERT, SELECT ON audit_log` nhưng **KHÔNG** `UPDATE/DELETE`; đổi
  `DATABASE_URL` runtime sang role này.

**TIME-BOXED EXCEPTION (xin CA duyệt):**
- **Nội dung:** M0 giữ single-role + append-only convention; DB-role separation **hoãn**.
- **Owner:** Dev (kỹ thuật) + PO (chấp nhận rủi ro tồn dư — **PO phải ký**).
- **Deadline (CA §9 — KHÔNG kéo tới M6):** tách DB runtime/migration role **trước nhóm mutation thương
  mại nhạy cảm tiếp theo và KHÔNG muộn hơn M2 production release**.
- **Rủi ro tồn dư:** nếu app runtime bị chiếm quyền SQL tùy ý, có thể sửa/xóa audit. Giảm nhẹ: không có
  code path update/delete audit; audit là INSERT-only trong app; log/alert bất thường.
- **KHÔNG tuyên bố** "DB enforced" cho tới khi tách role — chỉ tuyên bố "convention + no update/delete
  endpoint" (đúng CA §8).

## 4. Còn lại (khi có endpoint tương ứng)
- Wire audit nhóm A cho các action 🔜 ở §1 khi implement (M2/M5/M6).
- Integration test rollback mở rộng cho từng action nhóm A mới.

## Ký
```text
AUDIT RELEASE-GATE — group-A liet ke; fail-closed rollback + redaction (secret+PII+nested) DA TEST (E3);
DB-enforcement = TIME-BOXED EXCEPTION (owner Dev+PO, deadline M6), KHONG tuyen bo DB-enforced o M0.
Author role: Dev (Alpha3S). Ngay: 2026-07-25.
```
