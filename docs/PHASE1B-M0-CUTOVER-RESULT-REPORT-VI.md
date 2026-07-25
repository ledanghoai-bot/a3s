---
id: A3S-PHASE1B-M0-CUTOVER-RESULT-REPORT-001
title: Alpha3S I-B M0 — Cutover Result Report (production)
document_type: cutover_result_report
responds_to: A3S-PHASE1B-CA-M0-RELEASE-DECISION-001
owner: Alpha3S
author_role: Dev
version: 1.0.0
status: cutover_complete_submitted_to_ca
release_sha: 8a702d616eab54d5def9292a40593ff1b1540b04
release_tag: ib-m0-rc1
created_at: 2026-07-25 15:49 GMT+7
language: vi-VN
---

# M0 — Cutover Result Report (CA-M0-RELEASE-DECISION §9)

> **KẾT QUẢ: M0 PRODUCTION CUTOVER THÀNH CÔNG.** Toàn bộ migration 014–018 áp + validation pass, RBAC strict
> active, nonce CSP verify trên dashboard host, anomaly dữ liệu đã sửa. Không rollback, không forward-fix.
> Báo cáo **DUY NHẤT** theo CA §9 (không mở thêm chuỗi review). **Không PII** (staff theo id + role).

## 1. Release đã deploy
- **Release SHA:** `8a702d616eab54d5def9292a40593ff1b1540b04` · **Tag:** `ib-m0-rc1` (checkout detached trên VPS).
- **Deploy:** `git fetch origin --tags` → `git checkout tags/ib-m0-rc1` (HEAD == full SHA, verified) →
  `docker compose -f docker-compose.prod.yml up -d --build api worker telegram_bot telegram_customer_bot dashboard`.
- **CI auto-deploy KHÔNG kích hoạt** (chỉ push `main` mới trigger; ta push branch+tag). PO duyệt phiên đầy đủ.

## 2. Thời gian (VPS wall-clock ≈ GMT+7)
| Mốc | Giá trị |
|---|---|
| Backup pre-cutover | `20260725T153703Z` (VPS clock) |
| Maintenance ON (dashboard stop) | `15:43:48` |
| Maintenance OFF (dashboard start) | `15:47:11` |
| **Maintenance window** | **≈ 3 phút 23 giây** |
> Đồng hồ VPS set theo GMT+7 (nhãn `Z` của VPS là wall-clock GMT+7); duration chính xác không phụ thuộc nhãn TZ.

## 3. Backup / restore evidence (§1.1)
- **Backup:** `/srv/backups/alpha3s_pre_m0cutover_20260725T153703Z.sql.gz` (857.500 bytes).
  **sha256:** `e7f36b547b81f07d430d24cbd4e675816359ce0d5aefa1fcf9fddd8c4813879c`.
- **Restore-check:** khôi phục vào container throwaway → **counts khớp production** (products=1, orders=2,
  staff_users=2, customers=2) + `3S-100G` md5 khớp → throwaway đã xóa. **PASS.**
- Cron backup ngày: healthy (bản gần nhất trong 24h, cron `30 3 * * *`).

## 4. Migration exit codes (§3)
| Bước | Lệnh | Exit | Kết quả |
|---|---|---|---|
| Baseline-13 | `migrate.py baseline --manifest baseline_manifest_13.json` | **0** | `Baselined 13 … KHONG baseline (phai chay): 014,015,016,017,018` |
| Up 014-018 | `migrate.py up` | **0** | `Applied 5 migration(s)`; `Post-migration validations pass (1 file)` |
- Từng migration transactional. `schema_migrations` = **18 rows** (001–018). Không migration nào rollback.

## 5. Data anomaly — đã sửa (014, §3 verify)
| Chỉ số | Trước | Sau |
|---|---|---|
| `3S-100G` description | "100% Robusta" (md5 `d352bd9f…`, khớp `v_bad1` IN-list) | approved (md5 `91d892ba…`) |
| `serving_size_g` | 2 | **NULL** |
| `net_weight_g` | 100 | 100 (giữ) |
| Toàn bảng: còn "100% Robusta" | 1 | **0** |
| Toàn bảng: còn `serving_size_g=2` | 1 | **0** |
> §1.3 gate pre-cutover: production description md5 = `d352bd9f…` = **đúng `v_bad1`** trong IN-list 014 →
> 014 match & correct, postcondition pass (không unknown-bad variant).

## 6. RBAC assignment verdict (§3A — KHÔNG PII)
- Seed = migration `018_rbac_seed.sql`: **6 roles, 21 permissions, 35 role_permission mappings**.
- Controlled mapping file: `/root/staff_roles.txt` perm `600 root`, **sha256 `e8d0ae12e57fe36414516013bc6bbcb4b1654ebe485bd0e241a6a0e581765aca`**, 2 dòng mapping (copy vào container lúc chạy, đã xóa copy; bản gốc access-controlled).
- `assign_staff_roles.py` exit **0**: `gán role 2 staff; active_admin=2; active_staff_thiếu_role=0`.
- **Verify cardinality:** `active_staff_without_role = 0`; `active_admins = 2`. (2 active staff → role `admin`, theo PO chốt.)
- `admin` role: **21/21 permissions** (gồm `staff.manage`, `payment.cod_record`).

## 7. Strict RBAC + startup readiness (§3A.4-5)
- Đặt `RBAC_STRICT=true` (.env) **sau khi** assignment pass → `up -d --force-recreate api worker`.
- **Startup readiness:** `[startup] readiness: RBAC ready (permissions=21, mappings=35)` → api boot OK (không
  half-provisioned, không degrade). **health = 200.**
- **Endpoint gate active:** probe **unauthenticated** `/dashboard/auth/staff`, `/dashboard/orders`,
  `/dashboard/products` → **401** (require_staff_session). Negative-permission enforcement chứng minh bằng
  E9/E10 rehearsal tại đúng SHA. **Authenticated admin-OK smoke:** để PO đăng nhập xác nhận (Dev không giữ credential).

## 8. CSP smoke (§1.4 pre + §4 post, errata §6.1 — DASHBOARD HOST)
- `GET https://a3s-dash.robanme.com/` (pre-release và post-release) →
  `script-src 'self' 'nonce-<random>' 'strict-dynamic'` — **KHÔNG `unsafe-inline`**; nonce present;
  `frame-ancestors 'none'`, `object-src 'none'`, `x-content-type-options: nosniff`, `x-frame-options: DENY`,
  `referrer-policy: no-referrer`. **PASS** cả hai lần.

## 9. Health / dashboard / bot / audit
- **Containers:** 8/8 Up (api, worker, dashboard, db, redis, caddy, telegram_bot, telegram_customer_bot).
- **Dashboard:** reopen sau maintenance, HTTP 200, Ready.
- **audit_log:** bảng tồn tại (015). Bản ghi audit thực tế sẽ xuất hiện khi có thao tác gated đầu tiên (PO login).
- **Bot data:** serving NULL → tools `_serving_info` trả None → bot không suy "≈50 ly"; LLM_MODEL=`deepseek-v4-flash` (OK).

## 10. Anomaly / lưu ý (không phải lỗi migration)
1. **Admin telegram bot `409 Conflict` getUpdates:** do **máy dev vẫn chạy `alpha3s-telegram_bot-1`** (2h) poll
   cùng token với VPS → dual-poller. **Tồn tại trước cutover, không phải hồi quy migration.** Khuyến nghị:
   dừng bot trên máy dev để VPS sở hữu kênh sạch.
2. **VPS đang ở detached HEAD** tại tag `ib-m0-rc1`. Production chạy đúng release code. **Follow-up (governance):**
   để bền vững qua reboot/CI, cân nhắc merge `phase1b-m0` → `main` trong một phiên có kiểm soát (sẽ re-deploy
   cùng code qua CI). Chưa làm trong phiên này (tránh auto-deploy ngoài kế hoạch).
3. **Controlled mapping file** giữ tại `/root/staff_roles.txt` (600) cho an toàn idempotent; xóa/archive theo
   retention policy của PO sau khi ổn định.

## 11. Rollback/forward-fix
- **Không có.** Mọi gate pass tuyến tính; không migration nào rollback; không cần forward-fix.
- Backup §3 + restore-check sẵn sàng nếu về sau cần (expand-only; data 014 forward-fix nếu cần, không revert ngược).

## 12. Addendum — post-cutover dashboard CSP hydration hotfix (SHA delta, CA §2)
Sau cutover, PO đăng nhập nhưng **dashboard không hiện form login**. Root cause: dưới production build
(`next start`), trang `/` **static-optimized** → Next KHÔNG gắn nonce vào `<script>` (12/12 script thiếu
nonce) → `'strict-dynamic'` chặn mọi script → React không hydrate → form login (client component) không
render. (Bản dev smoke `next dev` luôn dynamic nên không lộ lỗi này.)

**Fix (giữ nguyên security posture — nonce + strict-dynamic, KHÔNG unsafe-inline):**
1. `dashboard/middleware.js`: set CSP **lên cả request header** để Next đọc nonce (rc2, `0859f68`).
2. `dashboard/app/layout.js`: `export const dynamic = "force-dynamic"` → ép mọi route render động
   per-request → Next gắn nonce vào **12/12 script** (rc3, `d2ece24`).

**Verify sau fix:** script tags 12/12 có `nonce=` khớp CSP header; **browser smoke production** — form login
(Tên đăng nhập / Mật khẩu / Đăng nhập) render đầy đủ, **0 CSP violation, 0 console error**; CSP vẫn
`script-src 'self' 'nonce-…' 'strict-dynamic'` (no unsafe-inline). Chỉ rebuild `dashboard` (api/worker/bot
code không đổi).

## 13. Durability — merge → main + CI + trạng thái production cuối
Sau khi fix login, đưa production về **branch `main`** (thay vì detached HEAD tại tag) để bền vững qua
reboot/CI (trước đó `main = c210a84` pre-M0 → mọi `reset --hard origin/main` sẽ revert production về pre-M0).

**Fast-forward `main` → M0 code.** Phát sinh + đã xử lý:
- **CI lint (ruff):** M0 pool-standardization để sót **5 `asyncpg` import không dùng** + 1 import chưa sort
  → `ruff --fix` (import-only, không đổi logic) → **rc4 `ib-m0-rc4`**.
- **CI test (pytest):** `pytest -v` (không path) collect nhầm `scripts/*_test.py` (evidence script chạy tay,
  `from app` ImportError) → thêm **`pytest.ini` `testpaths = tests`** → **rc5 `ib-m0-rc5`**. Sau fix:
  ruff clean + **pytest 42 passed** → **CI lint+test XANH**.
- **CI deploy step FAIL — `ssh: connect … port 22: Connection timed out`:** GitHub-hosted runner bị **VPS
  firewall chặn SSH** (hạ tầng tiền-tồn; auto-deploy chưa từng có đường tới VPS). Deploy job chạy SAU
  lint-test nên **production KHÔNG bị đụng khi CI đỏ**. → **Deploy TAY** (đường sanctioned):
  `git checkout -B main origin/main && bash scripts/deploy.sh`.

**Verify sau deploy main:** VPS `/srv/alpha3s` **branch `main` @ `fb2a46b`**; api health **200**; readiness
`RBAC ready (permissions=21, mappings=35)`; `RBAC_STRICT=true`; dashboard **12/12 script có nonce**, CSP
`script-src 'self' 'nonce-…' 'strict-dynamic'` (no unsafe-inline), **form login render OK**; `schema_migrations=18`,
`robusta=0`, 2 admin. **remote `main = fb2a46b`** (bền vững).

**SHA delta tổng (CA §2):** `8a702d6` (rc1, approved) → `d2ece24` (rc3, dashboard hydration fix) → **`fb2a46b`
(rc5, ruff import cleanup + pytest.ini config)**. Delta từ rc1 = **dashboard hydration (2 file) + import/config
cho CI**; **migration/RBAC/audit runtime code byte-identical với rc1 đã CA duyệt**. Tags `ib-m0-rc1..rc5` đã push.

**Follow-up (không chặn vận hành):**
- **CI auto-deploy hỏng** — VPS firewall chặn SSH từ GitHub runner; cần allow IP runner HOẶC self-hosted
  runner trên VPS. Tới khi sửa: deploy làm tay.
- **Authenticated admin-OK smoke:** PO đăng nhập dashboard (đã vào được sau fix login) làm 1 thao tác gated
  → xác nhận `audit_log` ghi đúng (bước §4 Dev không tự làm — không giữ credential staff).

## Ký
```text
CUTOVER RESULT REPORT v1.0.0 (+addendum §12/§13) — M0 PRODUCTION CUTOVER THANH CONG.
Trang thai cuoi: VPS branch main @ fb2a46b; health 200; RBAC ready + RBAC_STRICT=true; dashboard nonce CSP
12/12 script (no unsafe-inline) + login render OK; schema_migrations=18, robusta=0, 2 admin. remote main=fb2a46b (ben vung).
SHA delta rc1 8a702d6 -> rc3 d2ece24 (login hydration fix) -> rc5 fb2a46b (ruff cleanup + pytest.ini); migration/RBAC runtime byte-identical rc1.
CI lint+test xanh; CI deploy step ssh-timeout (VPS firewall chan GitHub runner) -> deploy tay. Khong rollback/forward-fix migration.
Author role: Dev (Alpha3S). Ngay cap nhat: 2026-07-25 (GMT+7).

--- (§12 post-cutover dashboard hotfix) ---
Post-cutover: dashboard nonce-CSP hydration hotfix (rc1 8a702d6 -> rc3 d2ece24, chi 2 file dashboard) ->
login render OK, 0 CSP violation, van giu no-unsafe-inline. Migration/RBAC khong doi.
--- (nguyen ban cutover) ---
CUTOVER RESULT REPORT v1.0.0 — M0 PRODUCTION CUTOVER THANH CONG.
Release 8a702d6 / tag ib-m0-rc1. Baseline exit 0 + up(014-018) exit 0 + validation pass; schema_migrations=18.
Anomaly 3S-100G sua (serving NULL, khong con 100% Robusta). RBAC: 6 roles/21 perms/35 maps; 2 active staff->admin;
active_without_role=0; RBAC_STRICT=true; readiness RBAC ready; health 200; endpoint gate 401 unauth.
Nonce CSP verify tren a3s-dash.robanme.com (pre+post), khong unsafe-inline. Maintenance window ~3m23s.
Khong rollback/forward-fix. Luu y: admin-bot 409 (dev dual-poller, tien-ton); VPS detached HEAD tai tag.
Author role: Dev (Alpha3S). Ngay: 2026-07-25 15:49 GMT+7.
```
