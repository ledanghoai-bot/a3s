---
id: A3S-PHASE1B-M0-DEV-REPORT-001
title: Alpha3S I-B — Dev Report gửi CA: M0 development + rehearsal (v1.0.4)
document_type: dev_report_to_ca
responds_to: A3S-PHASE1B-CA-REVIEW-M0-DEV-001
reports_on: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
plan_version: 0.1.3
owner: Alpha3S
author_role: Dev
version: 1.0.4
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

## 8. MỚI (v1.0.3) — M0.2 DB pool + KB layer-3 smoke

**M0.2 DB pool standardization (DONE):** chuyển **8 service** (`handoff, orders, price_overrides,
knowledge_entries, metrics, auth_service, tools, rag`) từ `asyncpg.connect()` per-call sang pool
(`acquire/release`, giữ nguyên cấu trúc try/finally — diff tối thiểu). Sizing config `min=1/max=5`/process
+ `command_timeout` (CA §9); pool lazy (sau fork); lifecycle `close_pool` (FastAPI lifespan + arq
on_shutdown). **Smoke trên DB dev thật PASS**: tools/orders/metrics/staff qua pool; dev api không vỡ
(import OK, health 200). *(Rollout đủ 8/8 service.)*

**KB layer-3 smoke (đã chạy, DeepSeek):** 4 câu brand-truth/serving qua orchestrator trên dev stack (sender
test, đã dọn net-zero). Kết quả:
- **Brand claim OK** (KB V2 SKL-PRD-002 bảo vệ): "Robusta **và** Arabica của Việt Nam"; "tỷ lệ **chưa công
  bố**"; **không** claim "100% Robusta". → lớp 3 brand-truth **PASS** kể cả trên dev 012.
- **Serving claim (pre-014)**: bot khẳng định *"pha được khoảng 50 ly, ~2g/ly"* — đúng canonical issue CA
  §3. Migration 014 (serving_size_g=NULL) chặn việc này; đã verify deterministic ở lớp 1/2 (search_products
  không trả serving_info khi serving NULL). → post-014 sẽ hết.

**⚠️ PHÁT HIỆN NGOÀI M0 (nghiêm trọng, live):** DeepSeek đã **deprecate tên model `deepseek-chat`** (config
hiện tại) → API 400 *"supported: deepseek-v4-pro | deepseek-v4-flash"*. Không override thì **bot trả
fallback "Đội ngũ 3S Coffee sẽ phản hồi bạn ngay" cho MỌI tin nhắn** (LLM path hỏng). Xác nhận trên dev;
**production nhiều khả năng cũng bị** nếu dùng cùng model name. Đây **không phải hạng mục M0** (vendor/config
incident) — cần PO/ops: chọn model thay thế (`deepseek-v4-flash` là bản thế cận nhất của tier cũ) + cập nhật
`LLM_MODEL` trong `.env` **dev + production**.
**Cập nhật (v1.0.4):** Dev đã **fix DEV** — `.env` dev + `config.py` default → `deepseek-v4-flash`,
`up -d --force-recreate` (env_file nạp lúc create, `restart` không đủ); bot dev **hoạt động lại**
(verified: trả lời thật "Robusta và Arabica", không fallback). **PRODUCTION chưa sửa** — ops cập nhật
`.env` production + recreate (config default không cứu vì `.env` production override).

## 9. MỚI (v1.0.4) — Auth session decision record + Layer-3 post-014

**Auth session decision record (ĐÃ ĐIỀN — CA §7.3):** plan §9.1. Spike: API và dashboard khác subdomain →
HttpOnly cookie cần `SameSite=None; Secure` + CSRF (không drop-in). **Dev đề xuất: Temporary exception cho
M0** (localStorage + CSP chặt dashboard + cân nhắc rút TTL) với **deadline bắt buộc: migrate HttpOnly
cookie + CSRF trước M6** (khi dashboard chạm payment). **Risk owner: PO/CA phải ký chấp nhận** (CA §12.1).
*(Nếu PO/CA muốn cookie ngay M0, Dev làm.)*

**Layer-3 post-014 (serving) — CONFIRMED:** chạy câu "pha 1 hũ bao nhiêu ly?" qua orchestrator trên
throwaway **đã áp 014** (serving_size_g=NULL) + `deepseek-v4-flash`. Kết quả: bot **KHÔNG** khẳng định
"50 ly" / "2g/ly" (trả lời thật, không fallback). So với pre-014 (dev, serving=2) bot nói "~50 ly" → **014
đóng loop serving end-to-end**. (Throwaway đã hủy; không đụng dev DB.)

## 7. Đề nghị CA
Ghi nhận M0.2 DB pool + M0.3/M0.4/M0.5 + auth decision record (đã điền) + layer-3 post-014 confirmed.
**Còn lại M0:** DB-role separation cho audit (deferred, defense-in-depth). **Ngoài M0:** sự cố model
DeepSeek — DEV đã fix, **production cần ops cập nhật `.env`** (§8).

## Ký
```text
DEV REPORT — A3S-PHASE1B-M0-DEV-REPORT-001 v1.0.4
v1.0.1: 4 P0 runner. v1.0.2: M0.3/4/5 audit/RBAC/security. v1.0.3: M0.2 pool 8/8 + KB layer-3 + phat hien
su co model DeepSeek. v1.0.4: auth session decision record DA DIEN (temporary exception + deadline M6, cho
PO/CA accept) + layer-3 post-014 serving CONFIRMED (bot khong con "50 ly") + FIX model DEV (deepseek-v4-flash,
recreate, bot dev hoat dong lai) — PRODUCTION cho ops cap nhat .env. Production KHONG thay doi (chi dev).
Commit branch phase1b-m0. Author role: Dev (Alpha3S). Ngay: 2026-07-25
```
