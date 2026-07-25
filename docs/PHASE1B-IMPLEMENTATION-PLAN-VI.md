---
id: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
title: Alpha3S I-B — Implementation Plan (M0 chi tiết + M1-M6 skeleton)
document_type: implementation_plan
parent: A3S-PHASE1B-FEASIBILITY-REPORT-001
report_version: 0.1.1
responds_to_review: A3S-PHASE1B-CA-CHECK-IMPL-M0-002
owner: Alpha3S
author_role: Dev
version: 0.1.3
status: revised_for_ca_reapproval
plan_completeness: partial (M0 detailed, M1-M6 skeleton)
created_at: 2026-07-24
last_updated: 2026-07-24
language: vi-VN
---

# Alpha3S I-B — Implementation Plan

> **PARTIAL PLAN** (Phương án B): **M0 chi tiết + M1-M6 skeleton** (§13).
> **v0.1.3** — sửa theo CA-CHECK-IMPL-M0-002 (M0 DEVELOPMENT APPROVED; focused delta): điền approved
> description, sửa `serving_size_g=2 → NULL`, thêm serving assertions, scope known-bad theo SKU 3S-100G.
> Các amendment v0.1.1/v0.1.2 đã được CA xác nhận SATISFIED — giữ nguyên.
> **CA đã duyệt M0 development.** Production migration **CHƯA** được duyệt; chưa bật RBAC / chưa đổi session
> trên production. Migration `013` đã tạo file cho rehearsal — **KHÔNG chạy production**.

## 0. Changelog

**v0.1.2 → v0.1.3 (CA-CHECK-IMPL-M0-002):**

| CA check | Nội dung | Xử lý |
|---|---|---|
| §2 | Approved product description được cấp | §5.6: điền vào corrective; file `migrations/014_correct_product_seed.sql` **đã tạo** (số 014 sau rehearsal, §5.5) |
| **§3-4** | `serving_size_g=2` không có canonical support (tool suy ~50 ly/hũ = Product Fact chưa duyệt) | §5.6: `013` set `serving_size_g = NULL` (2 statement); §5.7 assertions |
| §5 | Mô hình dữ liệu về sau (tách spoon vs serving) | §5.9 ghi định hướng (migration riêng sau M0) |
| §6 | Serving-related fresh DB assertions | §5.7 bổ sung |
| §7 | Known-bad check scope theo SKU | §5.7: rule theo `3S-100G`, KHÔNG assertion toàn hệ thống |
| §9 | Production gates không đổi | §12.1 liệt kê |

**Rehearsal (2026-07-24, §5.10):** đã chạy fresh + existing DB rehearsal trong development — **PASS**;
phát hiện collision `013` (data_deletion đã commit) → corrective dịch sang `014`, M0 → 015/016/017. **Chưa
chạy production.**

*(Changelog v0.1.0→v0.1.1→v0.1.2 giữ ở cuối §0.)*

**Tóm tắt lịch sử:** v0.1.1 xử lý 2 P0 (audit fail-closed, no permission cache) + amendment kiến trúc →
SATISFIED. v0.1.2 xử lý corrective migration "100% Robusta" + fresh-DB assertions + manifest + temp-password
expiry + audit DB privilege → SATISFIED.

---

## 1. Nguyên tắc & giới hạn quyền (CA)

**Dev ĐƯỢC (CA-CHECK §8):** M0 **development implementation** (tạo runner, migration files, services, tests
trong development); M0.0 production audit read-only sau khi PO cho truy cập.

**Dev CHƯA ĐƯỢC:** chạy migration **production**; bật RBAC production; đổi session mechanism production; gỡ
initdb path trước khi runner test trên cả DB mới và DB đã tồn tại.

Nguyên tắc: expand-only, forward-only (**không sửa file `001`/`012`** — sửa bằng migration mới); không thêm
dependency nặng; M0 không đụng business state ngoài corrective seed `013`.

---

## 2. Repo structure (đã khóa)

Giữ cấu trúc hiện hữu; không source root mới; không đặt source trong `CA-docs`. Path canonical:

| Asset | Path |
|---|---|
| Production audit SQL / report | `scripts/prod_audit.sql` · `docs/PHASE1B-PROD-AUDIT-VI.md` |
| Migration runner / manifest | `scripts/migrate.py` · `scripts/baseline_manifest.json` |
| Migration files | `migrations/013_*.sql` trở đi |
| Audit / Permission service | `app/services/audit_service.py` · `app/services/permission_service.py` |
| Auth service / deps / routes | `app/services/auth_service.py` · `app/api/auth.py` · `app/api/auth_router.py` |
| Security middleware | `app/security/` |
| Tests / Dashboard / Docs | `tests/` · `dashboard/lib/`,`dashboard/app/` · `docs/` |

---

## 3. M0 — Foundation: tổng quan & thứ tự

| Sub | Hạng mục | Phụ thuộc | Chặn bởi |
|---|---|---|---|
| **M0.0** | Production audit (DB + cutover, read-only) | — | — · chặn mọi migration |
| **M0.1** | Migration runner + **corrective `013`** + baseline có manifest | M0.0 | M0.0 |
| **M0.2** | Chuẩn hóa DB pool (8 service) | — (song song) | — |
| **M0.3** | Audit foundation (fail-closed) | M0.1 | M0.1 |
| **M0.4** | Permission + RBAC (không cache) + hardening | M0.1, M0.3 | PO tick ma trận |
| **M0.5** | Security baseline | M0.1, M0.3 | PO risk-accept nếu giữ localStorage |

---

## 4. M0.0 — Production audit

**Tách 2 phần.** *Database audit* (`scripts/prod_audit.sql`, read-only): schema objects; constraints/
indexes; row counts (aggregate); migration drift so `001-012`; **data anomalies — quét known-bad
description "100% Robusta" VÀ `serving_size_g=2` cho `3S-100G`**. *Channel/cutover audit* (evidence provider/
config/deployment, không suy từ DB): Meta webhook config; Telegram bot ownership; container/deployment
identity; git commit/image tag.

**Không PII** (chỉ counts/aggregate/prefix). **Report identity block:** host/env; UTC+local time; git
commit/image tag; DB name; schema fingerprint/checksum; người thực hiện; read-only statement; kết quả +
anomalies. **Gate:** không sang M0.1 khi chưa có report; audit liệt kê description + serving của mọi SKU để
hoàn thiện known-bad list.

---

## 5. M0.1 — Migration runner + corrective migration + baseline

### 5.1. Bootstrap `schema_migrations` (dưới advisory lock, không baseline mù)
```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY, checksum TEXT NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT,
  transactional BOOLEAN NOT NULL DEFAULT true
);
```

### 5.2. Baseline manifest (critical data checks)
`scripts/baseline_manifest.json` có hoặc tham chiếu: expected schema objects; critical constraints/indexes;
critical seed assertions (§5.7); known-bad data checks (theo SKU, §5.7). Existing DB: baseline `001-012` chỉ
ghi applied sau schema/data audit; **`013` vẫn PENDING, phải chạy qua runner**; không đánh dấu applied nếu
chưa chạy + chưa xác minh postcondition.

### 5.3. Advisory lock (FAIL-FAST — CA-REVIEW-M0-DEV §9)
Key ổn định namespace Alpha3S; giữ cùng session suốt lần chạy; **`pg_try_advisory_lock` = FAIL-FAST**:
lock đang bị process khác giữ → **dừng ngay, KHÔNG chờ/không timeout-retry** (CA chấp nhận fail-fast cho
M0 vì đơn giản + an toàn). Release ở `finally` (session chết → PostgreSQL tự release). Nếu sau này cần
wait-with-timeout thì implement retry/deadline riêng + ghi lại contract.

### 5.4. Transaction semantics + non-transactional recovery (CA-REVIEW-M0-DEV §10)
Metadata `transactional: true|false` (mặc định `true`) qua header comment. **Hiện CHƯA có migration
non-transactional** → chưa chặn M0 code. **Trước migration non-transactional ĐẦU TIÊN**, runner phải bổ
sung: precondition + postcondition; recovery instruction cho case "SQL apply OK nhưng ghi
`schema_migrations` fail"; **KHÔNG retry mù**; manual reconciliation command / documented forward-fix.

### 5.5. Numbering M0 (đã sửa sau rehearsal — §5.10)
```text
013_data_deletion_requests.sql  <-- ĐÃ TỒN TẠI trong repo (Meta data deletion) — KHÔNG phải M0
014_correct_product_seed.sql    <-- CORRECTIVE (đã tạo file), chạy TRƯỚC các migration M0 mới
015_audit_log.sql
016_rbac.sql
017_auth_hardening.sql
```
> Rehearsal phát hiện `013` đã bị `013_data_deletion_requests` (đã commit) chiếm → dịch corrective sang
> `014`, M0 mới thành 015/016/017. Corrective vẫn chạy TRƯỚC các thay đổi M0 (CA §4).

### 5.6. Corrective migration `014_correct_product_seed.sql` — ĐÃ TẠO FILE

**Đã tạo `migrations/014_correct_product_seed.sql`** (đánh số 014 sau rehearsal, §5.5) với approved
description do CA cấp (CA-CHECK §2) và sửa
`serving_size_g=2 → NULL`. Approved description (đối chiếu SKL-PRD-002/004, SKL-BRAND-001):

> `3S Coffee – Cà phê hòa tan sấy lạnh, sử dụng cà phê nhân xanh Robusta và Arabica của Việt Nam. Hũ 100 g,
> kèm muỗng; 1 muỗng khoảng 1 g. Có thể pha với nước nóng hoặc nước nguội và điều chỉnh độ đậm nhạt theo
> khẩu vị.`

**Hai statement (CA §4):** (1) exact-match IN 2 chuỗi known-bad → set description approved + `serving_size_g
= NULL`; (2) nếu description đã hợp lệ nhưng `serving_size_g=2` còn → chỉ set `serving_size_g = NULL`, không
đụng description. **`net_weight_g=100` giữ nguyên.** KHÔNG dùng `LIKE '%Robusta%'` (ghi đè nhầm mô tả hợp
lệ có nhắc Robusta/Arabica).

**Vì sao null `serving_size_g`:** `serving_size_g=2` không có canonical support (CA §3) — `1 muỗng ≈ 1 g`
là khối lượng dụng cụ đo, không phải liều/ly. `app/services/tools.py:_serving_info` trả `None` khi
`serving_size_g` falsy → tool **không** trả `serving_info` → bot **không** suy `~50 ly/hũ` hay giá/ly. Đây
là baseline an toàn cho M0.

**Trạng thái thực thi:** file đã tạo cho **rehearsal (development)**. **Chưa chạy production** (CA: production
migration NOT APPROVED). Existing DB (gồm DB local hiện còn known-bad #1) chỉ được sửa khi chạy qua runner ở
bước được duyệt.

### 5.7. Fresh DB seed assertions (CA-CHECK §6, §7)

Rehearsal fresh DB kiểm dữ liệu seed sau `001..latest` — test `fresh_db_seed_validation`. **Scope theo SKU
`3S-100G`** (CA §7: KHÔNG assertion toàn hệ thống "không product nào chứa 100% Robusta", vì SKU khác tương
lai có thể có Product Fact riêng). Rule đúng: *không dùng claim "100% Robusta" cho `3S-100G`*.

- [ ] `3S-100G.description` = approved description.
- [ ] `3S-100G.description` không chứa `100% Robusta`.
- [ ] `3S-100G.serving_size_g IS NULL` (tới khi reference serving được PO duyệt).
- [ ] `3S-100G.net_weight_g = 100` giữ nguyên.
- [ ] SKU `3S-100G` tồn tại đúng một lần; giá/tier khớp source.
- [ ] Tool `search_products` **không** trả `serving_info`; **không** suy `~50 ly/hũ`; **không** suy giá/ly.
- [ ] Migration checksum/manifest khớp.
- [ ] KB/FAQ/UAT liên quan Robusta–Arabica **và serving** pass.

Fail bất kỳ → **`MIGRATION REHEARSAL FAIL`**, API/worker không start.

### 5.8. Runner-only theo 2 bước
Bước 1: chứng minh runner trên fresh DB VÀ existing DB (rehearsal, gồm §5.7). Bước 2 mới gỡ auto-run initdb.
One-shot service `migrate`: chờ DB healthy → xong trước api/worker → startup FAIL nếu migration/rehearsal
fail → không auto-baseline production.

### 5.9. Mô hình dữ liệu về sau (CA-CHECK §5 — định hướng, ngoài M0)
Không dùng 1 trường cho 2 khái niệm. Nếu business cần tính giá/ly, migration riêng **sau M0** (Product/
Pricing milestone) tách: `measuring_spoon_g` (=1, có canonical support) và `reference_serving_g` (chỉ có giá
trị sau khi PO duyệt reference recipe; `NULL` → tool không tính ly/hũ hay giá/ly). **Không đổi tên field cũ
trong migration đã apply.**

### 5.10. Rehearsal results (development, container tạm) — ĐÃ CHẠY 2026-07-24

Chạy trong Postgres container tạm (`pgvector:pg16`) trên network dev; runner `scripts/migrate.py` chạy
trong container `api` (asyncpg 0.31). **Không đụng DB dev đang chạy, không đụng production VPS.**

- **Phát hiện (rehearsal bắt lỗi):** `013` đã bị `013_data_deletion_requests` (đã commit) chiếm →
  corrective dịch sang `014` (§5.5).
- **Fresh DB:** `up` áp 001→014 (14 migration); `up` lần 2 = "không có pending" (idempotent); `3S-100G`:
  description = approved, `serving_size_g=NULL`, `net_weight_g=100`; **seed assertions PASS**.
- **Existing DB (giả lập DB dev tại 012):** PRE = có "100% Robusta" + `serving_size_g=2`; `baseline 12`
  (manifest verify OK → ghi 001-012 applied, KHÔNG chạy); `up` chỉ áp `013_data_deletion` + `014_correct`
  (2 migration); POST = hết claim, `serving_size_g=NULL`, `net_weight_g=100` giữ nguyên; **assertions PASS**.
- **Guard kiểm chứng:** manifest verify chặn baseline mù (DB rỗng → STOP đúng); advisory lock + checksum
  forward-only sẵn trong runner.
- **Nuance cho M0.0:** DB dev thật **đã có** bảng `data_deletion_requests` (013 áp tay ngoài luồng) nhưng
  **chưa có** `schema_migrations` và vẫn ở product-seed 012 → **baseline threshold theo từng môi trường**
  (env có 013 sẵn cần baseline tới 013) do production audit quyết định; `013` dùng `IF NOT EXISTS` nên `up`
  lại là no-op an toàn.

Artifact: `scripts/migrate.py`, `scripts/baseline_manifest.json`, `scripts/fresh_db_seed_validation.sql`,
`migrations/014_correct_product_seed.sql` (đã tạo). **Chưa chạy trên production.**

---

## 6. M0.2 — Chuẩn hóa DB pool
Chuyển 8 service (`handoff, orders, price_overrides, knowledge_entries, metrics, auth_service, tools, rag`)
sang `get_pool()`. Pool lifecycle cho cả API + arq worker (lifespan + `close_pool()`); không tạo pool trước
fork; config `min/max/command timeout` qua env; staging load test + theo dõi usage; rollout từng service.
Baseline `min_size=1, max_size=5`/process (đo rồi chỉnh).

---

## 7. M0.3 — Audit foundation (fail-closed)

### 7.1. Hai nhóm
**Nhóm A — fail-closed, cùng transaction:** staff CRUD; role/permission change; password reset; revoke
session; export PII; price override; inventory adjustment; address override; refund/payment reconciliation;
approval/rejection. `Mutation + audit insert = 1 transaction; không ghi được → ROLLBACK`.
**Nhóm B — best-effort:** login failure, diagnostic, non-business notification.

### 7.2. API
```python
async def record(conn, actor_type, action, *, actor_ref=None, actor_staff_id=None,
                 entity_type=None, entity_id=None, before=None, after=None,
                 reason=None, request_id=None, correlation_id=None) -> None: ...
```
`conn` = connection của transaction đang mở (nhóm A).

### 7.3. Audit schema `015_audit_log.sql`
```sql
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  actor_type TEXT NOT NULL, actor_ref TEXT, actor_staff_id BIGINT REFERENCES staff_users(id),
  action TEXT NOT NULL, entity_type TEXT, entity_id TEXT,
  before JSONB, after JSONB, reason TEXT, request_id TEXT, correlation_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_log_entity_idx ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS audit_log_actor_idx  ON audit_log(actor_type, actor_staff_id);
CREATE INDEX IF NOT EXISTS audit_log_created_idx ON audit_log(created_at DESC);
```
Redaction (allowlist, không lưu secret/PII thừa vào before/after); append-only (không endpoint update/delete).

### 7.4. Audit table DB privileges
App + migration hiện dùng **cùng DB role `alpha3s`** (verified) có full CRUD → append-only ở M0 chỉ là
convention + không endpoint update/delete. **Tách DB role (runtime không `UPDATE/DELETE` audit_log; migration
role riêng) = defense-in-depth DEFERRED**, KHÔNG tuyên bố enforce ở DB.

---

## 8. M0.4 — Permission + RBAC (không cache)

### 8.1. Không cache permission ở M0
`validate_session()` join `role_permissions` mỗi request → tránh "admin thu hồi quyền nhưng process giữ
cache cũ".

### 8.2. RBAC schema `016_rbac.sql` — roles table canonical
```sql
CREATE TABLE IF NOT EXISTS roles (
  key TEXT PRIMARY KEY, name TEXT NOT NULL,
  is_system BOOLEAN NOT NULL DEFAULT false, is_active BOOLEAN NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS permissions (key TEXT PRIMARY KEY, description TEXT);
CREATE TABLE IF NOT EXISTS role_permissions (
  role_key TEXT NOT NULL REFERENCES roles(key) ON DELETE CASCADE,
  permission_key TEXT NOT NULL REFERENCES permissions(key) ON DELETE CASCADE,
  PRIMARY KEY (role_key, permission_key)
);
ALTER TABLE staff_users ADD COLUMN IF NOT EXISTS role_key TEXT REFERENCES roles(key);  -- nullable trước
-- Seed từ Phụ lục A (SAU khi PO tick).
```

### 8.3. Migration staff hiện có
Không mặc định `viewer` trước audit: audit → PO gán role → backfill → migration sau `SET NOT NULL`. 0 staff
→ bootstrap admin qua `scripts/create_staff_user.py --role admin`.

### 8.4. Authorization & hardening
`require_permission(key)` (403 nếu thiếu); `require_staff_session` trả thêm `role_key`+`permissions`. **Vá lỗ
hổng `auth_router.py:42-78`**: gate `staff.manage`; không disable/demote admin cuối; không tự nâng quyền; mọi
thao tác → audit nhóm A. M0 không có UI sửa matrix (seed migration PO-approved).

---

## 9. M0.5 — Security baseline

### 9.1. Auth session decision record (bearer token)
Không defer tới M6. M0 design spike, chốt 1 trong 2 **trước release gate** (ô trống chấp nhận trong design):
Preferred (HttpOnly+Secure+SameSite+CSRF+session rotation) / Temporary exception (localStorage chỉ khi có
risk acceptance PO/CA + CSP test + deadline cụ thể).
> **Quyết định (điền trước release gate):** ______ · Risk owner: ______ · Deadline nếu exception: ______

### 9.2. Security headers
Caddy/reverse proxy + Next.js middleware (dashboard) + FastAPI (API). Test trên cả `a3s.robanme.com` +
`a3s-dash.robanme.com`.

### 9.3. Login throttling đa chiều
Per-IP + per-normalized-username + global threshold; lỗi không tiết lộ tài khoản tồn tại; TTL; structured
security event; policy khi Redis lỗi (global in-memory cap/process + alarm, không khóa toàn bộ login).

### 9.4. Password reset restricted session + expiry
Cột `temporary_password_expires_at` (017). `must_change_password=true` → session chỉ `/me`, logout,
change-password; business endpoint trả "yêu cầu đổi mật khẩu"; password tạm hết hạn → admin cấp lại; reset
revoke toàn bộ session cũ.

### 9.5. Khác
Revoke-all-sessions; session cleanup (cron/sweep); audit auth events.

---

## 10. Updated schema drafts

`014_correct_product_seed.sql` (§5.6, **đã tạo**) · `015_audit_log.sql` (§7.3) · `016_rbac.sql` (§8.2) ·
`017_auth_hardening.sql`:
```sql
ALTER TABLE staff_users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE staff_users ADD COLUMN IF NOT EXISTS temporary_password_expires_at TIMESTAMPTZ;
ALTER TABLE staff_users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
```
Expand-only, `IF NOT EXISTS`, forward-only.

---

## 11. M0 release gates

- [ ] Production baseline được xác minh (DB + cutover; report không PII).
- [ ] Permission enforced server-side (thiếu quyền → 403); revoke có hiệu lực trên MỌI API worker.
- [ ] Audit failure rollback sensitive mutation (nhóm A); PII/secret không trong audit payload.
- [ ] Không disable admin cuối; existing staff không bị hạ role ngoài ý muốn.
- [ ] Migration: status/checksum/lock; baseline từ chối drift; **fresh DB + existing DB rehearsal pass**;
      API/worker không start nếu migration/rehearsal fail.
- [ ] **Fresh DB seed assertions pass (§5.7, scope `3S-100G`)**: description = approved; không "100% Robusta";
      `serving_size_g IS NULL`; `net_weight_g=100`; `search_products` không trả `serving_info`, không suy
      50 ly/giá-ly; KB Brand Truth + serving smoke pass.
- [x] **Corrective `014`** (rehearsal PASS §5.10): postcondition xác minh (description approved, serving
      NULL, net_weight giữ); exact-match IN không overwrite mô tả hợp lệ. *(Production: chờ audit + approval.)*
- [x] **Fresh + existing DB rehearsal PASS** trong development (§5.10). *(Production rehearsal: chờ audit.)*
- [ ] Login throttling + revoke-all-sessions + password-reset restricted session hoạt động; **auth decision
      record §9.1 đã điền**.
- [ ] Security headers pass trên cả API và dashboard domains.

## 12. Rollback & production gates

**Rollback M0:** expand-only → revert code; bảng mới không đọc; cột mới nullable/default vô hại; `013` chỉ
sửa description/serving (forward-fix bằng migration mới nếu cần).

### 12.1. Production gates không đổi (CA-CHECK §9)
Trước production vẫn cần: production audit; fresh DB + existing DB rehearsal; PO role–permission decisions;
auth session decision record; **backup/restore readiness**; **migration dry-run**; **production rollout
approval**.

---

## 13. Skeleton M1-M6 (Phương án B)

Mỗi milestone: Objective · Dependency · Schema delta · API/tool delta · Migration boundary · Release gate ·
PO decision gate.

### M1 — Reliable command & receipt
- **Obj:** command idempotency; transactional outbox + semantics; deterministic receipt; gỡ marker-string
  guard sau khi replacement chứng minh. **Dep:** M0. **Schema:** `outbox_messages`, `delivery_attempts`,
  `business_events`. **API/tool:** receipt template; outbox dispatcher cron. **Boundary:** expand-only.
  **Gate:** không receipt nếu txn không commit; retry không tạo action trùng; crash-after-provider-call test;
  dead-letter+replay audit. **PO gate:** —
### M2 — Order & inventory correctness
- **Obj:** 2-trục order; transition matrix; timeline; inventory balance + reservation + immutable ledger;
  cancel/expire/release. **Dep:** M0,M1. **Schema:** `order_events`, `inventory_balances`,
  `inventory_movements`, `stock_reservations`. **Boundary:** `products.stock`→legacy. **Gate:** illegal
  transition reject; no oversell concurrent; release đúng reservation; ledger↔balance reconcile. **PO gate:**
  reservation TTL + thời điểm.
### M3 — Customer visibility & follow-up
- **Obj:** authorized order-read tools; shipping status; confirmation reminder; shipping update; outbound
  queue staff thấy. **Dep:** M1,M2. **Schema:** `followup_jobs`. **API/tool:** `get_order/get_order_status/
  get_customer_orders/get_delivery_status`; followup scheduler cron. **Boundary:** expand-only. **Gate:**
  customer chỉ đọc đơn của mình; không lộ qua đoán ID; follow-up theo channel policy. **PO gate:** follow-up
  use cases + consent + opt-out.
### M4 — Customer identity & multi-location
- **Obj:** canonical customer; channel identities; default-location backfill; store/warehouse/fulfillment
  location. **Dep:** M0. **Schema:** `customer_identities`, `locations`. **API/tool:** bỏ suy kênh từ prefix.
  **Boundary:** `customers.psid`→legacy; backfill 1 lần. **Gate:** không mất lịch sử; merge an toàn. **PO
  gate:** chính sách merge.
### M5 — Address Verification
- **Obj:** versioned admin dataset; current verification; legacy mapping; customer confirmation; staff review
  queue; snapshot; provenance + rollback. **Dep:** M4. **Schema:** `admin_units` versioned, order address
  snapshot. **API/tool:** `verify_shipping_address`, `quote_shipping(verified_address_id)`. **Boundary:**
  dataset không auto-activate. **Gate:** dataset validation; current→legacy→staff; ambiguous không
  auto-select; không cước từ address chưa verified; rollback dataset. **PO gate:** license + owner cập nhật.
### M6 — Delivery & payment baseline
- **Obj:** fulfillment board; carrier/tracking nhập tay; delivery attempts/status; payment status/evidence
  độc lập; COD record; notification qua outbox. **Dep:** M2. **Schema:** `shipments`, `payments`. **API/
  tool:** dashboard fulfillment. **Boundary:** expand-only. **Gate:** delivery/payment status độc lập order
  status; notification bind trạng thái thật; COD evidence tách reconciliation authority. **PO gate:** phạm vi
  payment/COD.

*(Commerce Growth P2 — plan riêng khi tới.)*

---

## 14. Quyết định (CA)

**CA đã khóa:** repo structure §2; lightweight runner; runner-only sau transition; audit fail-closed; không
cache permission M0; business state thuộc App; corrective migration bắt buộc trước fresh-DB rehearsal;
**approved product description cho 3S-100G (CA-CHECK §2 — ĐÃ CẤP)**.

**PO cần khóa:** (1) role–permission matrix (Phụ lục A); (2) initial production admin; (3) owner cấp/thu tài
khoản; (4) approval owner; (5) export policy; (6) localStorage temporary risk acceptance nếu không làm cookie
M0; (7) *(tương lai)* reference recipe cho `reference_serving_g` nếu muốn khôi phục tính giá/ly (§5.9).
*(Approved description đã hết là mục PO-blocking — CA cấp trực tiếp.)*

## 15. Self-check
CA review-1 §15 & CA re-review §9: SATISFIED (audit/permission consistency, manifest, auth decision, schema
drafts, corrective migration, dịch số, fresh-DB assertions, temp-password expiry, audit DB privileges).
CA-CHECK §8: (1) approved description điền ✔ (§5.6, file 013); (2) `serving_size_g=2→NULL` ✔ (§5.6); (3)
serving assertions ✔ (§5.7); (4) known-bad scope theo SKU ✔ (§5.7); (5) self-check/release gate dịch ✔
(§11).

## Ký
```text
Implementation Plan v0.1.3 — Dev sign-off
Xử lý CA-CHECK-IMPL-M0-002: điền approved description (CA §2) + sửa serving_size_g=2→NULL (canonical issue)
vào migration 014 (file: migrations/014_correct_product_seed.sql, 2 statement, exact-match IN, giữ
net_weight_g); thêm serving fresh-DB assertions; scope known-bad theo SKU 3S-100G; định hướng tách
spoon/serving field (§5.9, sau M0). Đã build runner (scripts/migrate.py) + manifest + assertions; chạy
FRESH + EXISTING DB rehearsal trong development -> PASS (§5.10); rehearsal phat hien collision 013 -> 014.
Prior amendments: SATISFIED. M0 development APPROVED. TUYET DOI chua thay doi production (chua chay
migration production / chua bat RBAC / chua doi session). Author role: Dev (Alpha3S). Ngay: 2026-07-24
```
