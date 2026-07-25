---
id: A3S-PHASE1B-PROD-MIGRATION-RUNBOOK-001
title: Alpha3S I-B M0 — Production Migration Runbook
document_type: production_migration_runbook
parent: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
depends_on: A3S-PHASE1B-PROD-AUDIT-001
gate_reference: A3S-PHASE1B-CA-REVIEW-M0-DEV-004
owner: Alpha3S
author_role: Dev
version: 1.0.2
status: draft_pending_ca_release_approval
created_at: 2026-07-25
last_updated: 2026-07-25 15:07 GMT+7
language: vi-VN
---

# Production Migration Runbook — I-B M0 (v1.0.2)

> Đưa **production (host alias `alpha3s-vps`)** từ schema **012+013** lên M0 (014 corrective + 015 audit +
> 016 rbac + 017 auth + 018 rbac_seed). **CHƯA được phép chạy** — chỉ khi §0 gates PASS. Gate reference:
> CA-REVIEW-M0-DEV-004 + Evidence Package **v1.0.2** (release-candidate SHA `8a702d6…`).
> Nguyên tắc: expand-only, forward-only, **immutable release SHA/tag**, backup + restore-check BẮT BUỘC,
> **maintenance/quiesce staff traffic quanh RBAC cutover**, mỗi bước verify, rollback rõ. Mọi thao tác
> production PO approve từng phiên. **Dùng host alias, không lặp IP.**
>
> **v1.0.2 — thay đổi P0 (CA-REVIEW-M0-DEV-004 §4):** BỎ tuyên bố sai rằng `RBAC_STRICT=false` khôi phục
> được truy cập sau migration 016. **Sự thật:** sau 016, `rbac_provisioned()` = true ngay; staff chưa gán
> role có `permissions = ∅`; `require_permission()` chỉ degrade khi `rbac_provisioned=false`. ⇒ Sau 016,
> staff chưa có role bị **403 bất kể `RBAC_STRICT`**. Vì vậy M0 dùng **Phương án A — maintenance cutover**
> (CA ưu tiên): chặn staff traffic TRƯỚC 016, gán role trong maintenance, verify, bật strict, recreate,
> smoke, RỒI mới mở traffic. Lever khôi phục KHÔNG phải `RBAC_STRICT=false` mà là: (a) giữ maintenance +
> sửa/chạy lại assignment, hoặc (b) redeploy **code cũ RBAC-unaware** (`c210a84`) — code này không truy vấn
> `role_permissions` nên staff đăng nhập bình thường trên schema đã expand.

## 0. Gate tiên quyết (đủ TẤT CẢ)
- [ ] **CA release approval** (Evidence **v1.0.2** verified-closed + review 004 amendments đóng: runbook A,
      nonce CSP, audit endpoint tests đủ, E9/E10 executable).
- [ ] **PO khóa policy** (TRƯỚC maintenance window): duyệt ma trận role→permission; **điền staff worksheet**
      (gán role cho từng staff hiện hữu, chỉ định initial active admin); xác nhận PII masking/export;
      **xác nhận `payment.cod_record` cho support/delivery**; ký **ADR localStorage** (temporary session
      exception — nay đã đủ điều kiện: **nonce CSP đã implement + verify**, TTL≤48h).
- [ ] **Release freeze:** dùng **release-candidate SHA `8a702d6…`** (đề xuất tag `ib-m0-rc1`). KHÔNG dùng
      `931943d…` (đó là evidence v1.0.1 cũ) hay checkout branch/commit ad hoc.
- [ ] **Cleanup**: `.env.bak.pre-llmfix` (untracked, benign) chuyển `/srv/backups/`; **cron pg_dump ngày**
      đã chạy — verify (§0.1); kiểm mô tả `3S-100G` production khớp IN-list 014.
- [ ] **Controlled mapping file** (§8): file tồn tại trên target, permission hạn chế, dry-run không in
      username/PII, checksum ghi vào evidence access-controlled.
- [ ] Maintenance window + **người thực thi (executor) / người quan sát (observer) / go-no-go owner /
      evidence location** ghi rõ TRƯỚC khi bắt đầu.

### 0.1. Verify cron backup đang khỏe (CA §9.5)
```bash
crontab -l | grep pg_backup_daily            # 30 3 * * * đúng lịch
ls -lt /srv/backups/*.sql.gz | head -3       # có bản gần nhất trong 24h
tail -5 /srv/backups/pg_backup_daily.log     # exit 0 + verify OK dòng cuối
```
Cron backup **không thay thế** backup riêng ngay trước cutover (§1.1).

## 1. Pre-flight
**1.1. Backup DB riêng + RESTORE-CHECK BẮT BUỘC** (không phải tùy chọn — CA §10.3; luôn tạo backup mới
ngay trước cutover kể cả cron đã chạy):
```bash
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U alpha3s -d alpha3s \
  | gzip > /srv/backups/alpha3s_pre_m0_$(date -u +%Y%m%dT%H%M%SZ).sql.gz
# RESTORE-CHECK: khoi phuc vao container throwaway, verify row counts khop, roi xoa throwaway.
```
**1.2.** Chạy `scripts/prod_audit.sql` (read-only) → xác nhận 012+013, anomaly còn.
**1.3. Verify IN-list 014:** so mô tả `3S-100G` với 2 chuỗi known-bad trong `014`. **Nếu khác → DỪNG**,
tạo **migration forward mới** sửa IN-list, **rehearsal lại**, **xin approval lại** — **KHÔNG sửa 014 đã
rehearsal ngay trong phiên cutover** (CA §10.4).
**1.4. CSP pre-release check** (CA §9.4): trên build dashboard sắp deploy, `GET /` phải trả header
`Content-Security-Policy` có `script-src 'self' 'nonce-…' 'strict-dynamic'` và **KHÔNG** `unsafe-inline`
trong `script-src` (xem §4 để lặp lại sau cutover).

## 2. Deploy code (backward-compat, immutable SHA)
Code M0 feature-detect → chạy được trên 012+013 (RBAC unprovisioned → `require_permission` degrade;
startup readiness skip hợp lệ). Deploy TRƯỚC, migrate SAU.
- **Dùng immutable release SHA/tag `8a702d6…`** (đề xuất tag `ib-m0-rc1`) qua CI/CD (merge→main→deploy)
  HOẶC checkout đúng tag trên VPS — **không checkout branch/commit ad hoc**.
- `docker compose -f docker-compose.prod.yml up -d --force-recreate api worker telegram_bot telegram_customer_bot dashboard`.
- **Verify:** health 200; login OK (degrade vì chưa provision); bot trả lời; log sạch; **CSP header đúng
  (§1.4)**.
- **Rollback bước này:** redeploy SHA cũ (`c210a84`) + recreate. DB nguyên (chưa migrate).

## 2A. MAINTENANCE ON — quiesce staff traffic (CA §4, §9.2) — TRƯỚC §3
> Vì sau 016 mọi staff chưa gán role bị 403, KHÔNG được để staff request chạm `require_permission` trong
> lúc DB half-provisioned. Chặn staff traffic TRƯỚC khi migrate 016.
1. **Thông báo 2 staff** không đăng nhập trong cửa sổ (volume thấp — audit xác nhận 2 đơn/1 SP).
2. **Dừng dashboard** (chặn staff UI): `docker compose -f docker-compose.prod.yml stop dashboard`.
3. Customer channel (Messenger webhook + telegram_customer_bot) **giữ chạy** — không đụng staff RBAC path.
4. Ghi mốc `maintenance_on` (time + executor) vào evidence.

## 3. Migration qua runner (baseline-13 → up) — trong maintenance
`schema_migrations` chưa có + `data_deletion_requests` đã có → **baseline_through=13**.
```bash
docker compose -f docker-compose.prod.yml exec -T api python /srv/scripts/migrate.py baseline --manifest scripts/baseline_manifest_13.json
docker compose -f docker-compose.prod.yml exec -T api python /srv/scripts/migrate.py up
```
- baseline: `Baselined 13 … KHONG baseline (phai chay): 014,015,016,017,018` (verify data_deletion khớp).
- up: áp **014→018** + post-validation. **014 fail-closed** nếu unknown variant → về §1.3.
- **Verify (read-only):** `3S-100G` description approved, `serving_size_g NULL`, không "100% Robusta";
  `schema_migrations` có 001-018; `audit_log`/`roles`/`role_permissions` tồn tại; `role_permissions` đã
  seed (018).

## 3A. RBAC CUTOVER UNIT (trong maintenance — CA §4, §5)
> Một unit liên tục, `RBAC_STRICT` bật SAU CÙNG, **staff traffic vẫn đóng** cho tới §3B.
1. **Seed mapping đã PO duyệt = migration `018_rbac_seed.sql`** (đã áp ở §3 up) — KHÔNG chạy file proposal
   trực tiếp bằng psql.
2. **Gán role staff** bằng `scripts/assign_staff_roles.py` (transactional, idempotent, cardinality
   fail-closed), mapping đọc từ **file kiểm soát truy cập** (§8):
   ```bash
   docker compose -f docker-compose.prod.yml exec -T api python scripts/assign_staff_roles.py --mapping /path/staff_roles.txt
   ```
   Script FAIL-CLOSED nếu: role không hợp lệ / staff không tồn tại / **<1 active admin** / **còn active
   staff thiếu role** → ROLLBACK.
3. **Verify**: `SELECT count(*) FROM staff_users WHERE is_active AND role_key IS NULL` = 0; ≥1 active admin;
   `role_permissions` có mapping (readiness sẽ pass).
4. **CHỈ bây giờ** đặt **`RBAC_STRICT=true`** (env) → recreate api/worker → **startup readiness pass**
   (nếu half-provisioned → api KHÔNG start → về §3A.6).
5. **Positive/negative permission smoke** (vẫn trong maintenance, dùng tài khoản được duyệt): non-admin gọi
   `staff.manage` → 403; admin → OK; disable admin cuối → 409.
6. **Nếu seed/assignment/readiness FAIL** (CA §9.3 — exact rollback):
   - **GIỮ maintenance** (dashboard vẫn stop, staff traffic vẫn đóng) — KHÔNG mở traffic.
   - `RBAC_STRICT=false` **KHÔNG** khôi phục truy cập (staff chưa role vẫn 403) → **không dùng làm recovery**.
   - Chọn một: **(a)** sửa file mapping → chạy lại `assign_staff_roles.py` (idempotent) → tiếp §3A.3; hoặc
     **(b) ABORT:** redeploy **code cũ `c210a84`** (RBAC-unaware, không truy vấn `role_permissions`) +
     recreate → staff đăng nhập lại bình thường trên schema đã expand (expand-only, DB giữ nguyên 018).
   - Chỉ sang §3B khi **mọi active staff có role + strict pass + smoke pass**.

## 3B. MAINTENANCE OFF — mở staff traffic (chỉ sau khi §3A pass)
1. `docker compose -f docker-compose.prod.yml start dashboard`.
2. Verify staff login thật (admin) OK; ghi mốc `maintenance_off` (time) vào evidence.

## 4. Post-migration verification
- [ ] `prod_audit.sql` khớp target; bot smoke (không "100% Robusta"/"50 ly").
- [ ] Dashboard: 1 thao tác gated → `audit_log` ghi đúng; **KHÔNG test throttling vào tài khoản thật**
      (dùng tài khoản/cửa sổ test được duyệt — CA §10.6).
- [ ] **CSP post-release check** (CA §9.4): `GET https://a3s.robanme.com/` header CSP có nonce + strict-dynamic,
      **không** `unsafe-inline` trong `script-src`; browser console **không** CSP violation; dashboard render OK.
- [ ] **KHÔNG "tạo đơn test rồi xóa"** trên production — synthetic marker + cancel/void hợp lệ + giữ audit.
- [ ] Log sạch 30-60 phút; ghi start/end + `maintenance_on/off` time + evidence location.

## 5. Rollback
| Thời điểm | Rollback |
|---|---|
| Sau §2, trước §3 | Redeploy SHA `c210a84` + recreate. DB nguyên. |
| Migration lỗi (§3) | Mỗi migration 1 txn; forward-fix + `up` lại. 014 fail-closed không ghi. |
| RBAC cutover fail (§3A) | **Giữ maintenance**; (a) sửa mapping + chạy lại assignment, hoặc (b) redeploy code cũ `c210a84` (RBAC-unaware → staff truy cập lại). **`RBAC_STRICT=false` KHÔNG khôi phục** (staff chưa role vẫn 403). |
| Sau §3B, phát hiện sai | Expand-only → redeploy code cũ `c210a84` (RBAC-unaware) + recreate → staff truy cập lại; 014-data KHÔNG rollback ngược (forward-fix). **Không dựa vào `RBAC_STRICT=false`.** |
| Hỏng nặng | **Restore từ backup §1.1** (đã restore-check). |

## 6. Ràng buộc
KHÔNG gỡ initdb (CA §8.4); KHÔNG bỏ backup+restore-check; KHÔNG default staff role; KHÔNG chạy khi §0
chưa đủ; KHÔNG sửa 014 trong cutover; **KHÔNG mở staff traffic khi còn active staff thiếu role**; KHÔNG
coi `RBAC_STRICT=false` là recovery sau 016; production audit ≠ migration approval.

## 7. Cutover ledger (điền trước khi bắt đầu — CA §9.6)
| Trường | Giá trị |
|---|---|
| Release SHA / tag | `8a702d6…` / `ib-m0-rc1` |
| Executor | ______ |
| Observer | ______ |
| Go/No-Go owner | ______ |
| Evidence location (access-controlled) | ______ |
| Backup file (§1.1) + restore-check | ______ |
| Controlled mapping file + sha256 (§8) | ______ |
| maintenance_on / maintenance_off time | ______ / ______ |

## 8. Controlled mapping file — operational checks (CA §8)
Trước go/no-go, operator (không đưa nội dung mapping vào repo/CA doc):
- [ ] File tồn tại trên target: `test -f /path/staff_roles.txt`.
- [ ] Permission hạn chế: `chmod 600 /path/staff_roles.txt; stat -c '%a %U' /path/staff_roles.txt` = `600 <owner>`.
- [ ] **Dry-run** `assign_staff_roles.py` (validation) **không in username/PII** ra report phát hành rộng —
      chỉ in count/verdict.
- [ ] Ghi `sha256sum /path/staff_roles.txt` vào **evidence access-controlled** (không repo).
- [ ] Sau cutover: **xóa hoặc archive** file theo retention policy.

## Ký
```text
PROD MIGRATION RUNBOOK v1.0.2 (DRAFT) — amendment CA-REVIEW-M0-DEV-004 §4/§8/§9:
- BO tuyen bo sai: RBAC_STRICT=false KHONG khoi phuc truy cap sau 016 (staff chua role -> 403 bat ke strict).
- Phuong an A maintenance cutover: chan staff traffic (stop dashboard) TRUOC 016 -> migrate -> assign role
  trong maintenance -> verify -> RBAC_STRICT=true -> recreate -> smoke -> MOI mo traffic (2A/3B).
- Exact rollback khi assignment fail: giu maintenance + (a) sua+chay lai assignment hoac (b) redeploy code cu
  c210a84 (RBAC-unaware). Khong dua vao RBAC_STRICT=false.
- CSP nonce verify vao pre-release (§1.4) + post-release (§4). Cron backup verify (§0.1) + backup rieng truoc cutover.
- Release SHA 8a702d6 (tag ib-m0-rc1), khong dung 931943d. Cutover ledger executor/observer/go-no-go/evidence.
- Controlled mapping file checks (§8): ton tai/permission 600/dry-run no-PII/checksum/archive.
CHUA duoc chay — cho CA release approval + PO gates. Author role: Dev (Alpha3S). Ngay: 2026-07-25 15:07 GMT+7.
```
