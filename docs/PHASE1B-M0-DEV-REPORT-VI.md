---
id: A3S-PHASE1B-M0-DEV-REPORT-001
title: Alpha3S I-B — Dev Report gửi CA: M0 development + rehearsal (v1.0.2)
document_type: dev_report_to_ca
responds_to: A3S-PHASE1B-CA-REVIEW-M0-DEV-001
reports_on: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
plan_version: 0.1.3
owner: Alpha3S
author_role: Dev
version: 1.0.2
status: submitted_to_ca
created_at: 2026-07-25
language: vi-VN
---

# Dev Report gửi CA — M0 development + rehearsal (v1.0.2)

Gửi CA. v1.0.1 đã đóng 4 P0 của rehearsal gate (runner). **v1.0.2 báo cáo tiếp: đã implement M0.3 (audit),
M0.4 (RBAC/permission), M0.5 (security)** trong development, **backward-compatible** (không vỡ stack dev ở
schema 012). Mọi thứ **chứng minh bằng chạy thật**. **Production không đụng.**

## 1. Phần v1.0.1 (đã đóng — nhắc lại gọn)
4 P0 runner đã fix + chứng minh: baseline threshold + `never_baseline:014` (B2/B1); manifest enforcement đủ
constraints/indexes/data-assertions (B1 STOP); corrective 014 executable pre/postcondition fail-closed (C:
`RaiseError`, `v014_recorded=0`, rollback); validation nối vào `up` (exit≠0 khi fail). P1: advisory lock
fail-fast (doc §5.3); non-transactional recovery note (§5.4).

## 2. MỚI — M0.3/M0.4/M0.5 implementation

**M0.3 Audit foundation** (`app/services/audit_service.py`, migration `015_audit_log.sql`):
- Nhóm A **fail-closed**: `record(conn=…)` dùng chính connection của transaction mutation → audit + mutation
  commit/rollback cùng nhau. Nhóm B best-effort (`record_best_effort`) cho telemetry (login).
- **Redaction**: `before/after` loc secret/PII (password/token/…) trước khi lưu JSONB.
- Actor model `actor_type/actor_ref/actor_staff_id`; append-only convention (DB-role tách = deferred, đã
  disclose §7.4).

**M0.4 RBAC + permission** (`016_rbac.sql`, `app/services/permission_service.py`, `app/api/auth.py`):
- `roles` canonical + `permissions` catalog + `role_permissions`; `staff_users.role_key` nullable.
- **Mapping role→permission KHÔNG seed trong migration** (CA §11.3) — đề xuất least-privilege ở
  `scripts/rbac_seed_proposed.sql` **chờ PO duyệt** rồi mới thành migration.
- **Không cache** permission (CA §6): `validate_session` query `role_permissions` mỗi request.
- `require_permission(key)` server-side (403 nếu thiếu). **Backward-compat:** DB trước 016 → RBAC
  unprovisioned → degrade về `require_staff_session` (không vỡ dashboard 012).
- **Staff CRUD hardened** (`auth_router.py`): gate `staff.manage`; **last-admin guard**; **no
  privilege-escalation** (role gán phải có quyền ⊆ quyền actor; không tự đổi role mình); audit fail-closed.

**M0.5 Security** (`app/security/`, `017_auth_hardening.sql`, `main.py`):
- **Login throttling** đa chiều (per-IP + per-username + global, Redis, **fail-open** khi Redis lỗi); lỗi
  login generic (không lộ tài khoản tồn tại); audit login fail/success.
- **Password change** (`/dashboard/auth/password`) + **revoke-all-sessions**; `must_change_password` +
  `temporary_password_expires_at`; **restricted session** (`require_active_session` chặn business endpoint
  khi phải đổi mật khẩu — đã gắn vào dashboard router).
- **Security headers middleware** (nosniff/X-Frame-Options/Referrer-Policy/CSP frame-ancestors) — API layer;
  dashboard Next + Caddy tự set (CA §12.2).

## 3. Evidence — chạy thật (container tạm cô lập, đã xóa)

| Kịch bản | Kết quả |
|---|---|
| **Backward-compat** (dev api reload trên 012) | `import app.main OK`, `/health=200` — không vỡ; RBAC unprovisioned → degrade |
| **Fresh DB 001-017** | `migrate up` → 17 migration + post-validation → `up_exit=0` |
| **RBAC seed** | `rbac_seed_proposed.sql` áp OK (mô phỏng PO duyệt) |
| **M0 foundation validation** | **PASS**: RBAC provisioned; `admin ⊇ staff.manage`; `sales` KHÔNG có `staff.manage`/`inventory.adjust`; **audit fail-closed rollback** (record trong txn rồi raise → audit_log không tăng); **secret redaction** (`password→***REDACTED***`, field thường giữ) |
| *(v1.0.1)* Fresh/Existing/Negative runner | up+validation exit 0; baseline skip 013/014; 014 postcondition fail-closed exit 1 |

## 4. 3 lớp validation (CA §8 — tách, không gom 1 PASS)
- **Lớp 1 SQL** (`fresh_db_seed_validation.sql`, qua runner): exact approved description + exact tiers +
  serving NULL + net_weight 100 → **PASS**.
- **Lớp 2 application** (`app_integration_validation.py`): `search_products` không trả `serving_info` →
  **PASS**; (`m0_foundation_validation.py`): audit/permission model → **PASS**.
- **Lớp 3 KB/UAT smoke** (cần LLM): UAT-011/027/079 + serving smoke — **CHƯA chạy**, báo cáo riêng khi có
  môi trường LLM. Không gộp vào PASS lớp 1-2.

## 5. Artifact + commit (CA §12/§14)
Branch **`phase1b-m0`** (không main, không push). **Commit SHA mới gửi kèm trong transmittal message.**
Mới thêm: `migrations/015_audit_log.sql`, `016_rbac.sql`, `017_auth_hardening.sql`,
`scripts/rbac_seed_proposed.sql`, `scripts/m0_foundation_validation.py`, `app/services/audit_service.py`,
`app/services/permission_service.py`, `app/security/{__init__,headers,throttle}.py`; sửa
`app/services/auth_service.py`, `app/api/{auth,auth_router,dashboard}.py`, `app/main.py`,
`scripts/create_staff_user.py`.

## 6. Cô lập + production gates
Rehearsal chạy container tạm, **đã xóa** (0 sót); dev stack 7/7; **DB dev vẫn 012** (không audit_log/roles,
còn "100% Robusta") — rehearsal không chạm. **Production VPS không truy cập.** Chưa chạy production migration
/ chưa baseline production / chưa bật RBAC production / chưa gỡ initdb. Cần: PO cấp VPS read-only (M0.0), PO
duyệt `rbac_seed_proposed.sql` (Phụ lục A), CA release approval.

## 7. Đề nghị CA
Ghi nhận M0.3/M0.4/M0.5 implemented + rehearsal PASS. Còn lại M0: DB pool standardization (8 service);
auth session decision record (điền §9.1 trước release gate); lớp 3 KB smoke; DB-role separation (deferred).

## Ký
```text
DEV REPORT — A3S-PHASE1B-M0-DEV-REPORT-001 v1.0.2
v1.0.1: 4 P0 runner DONE. v1.0.2: M0.3 audit (fail-closed + redaction) + M0.4 RBAC/permission (no-cache,
require_permission, staff CRUD hardened, seed proposed cho PO) + M0.5 security (throttling fail-open,
password change/revoke, must_change_password restricted session, security headers) — backward-compatible,
chung minh bang chay that (foundation validation PASS). Production KHONG thay doi. Commit branch phase1b-m0
(SHA gui kem). Author role: Dev (Alpha3S). Ngay: 2026-07-25
```
