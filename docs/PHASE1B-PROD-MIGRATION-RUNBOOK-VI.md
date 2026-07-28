---
id: A3S-PHASE1B-PROD-MIGRATION-RUNBOOK-001
title: Alpha3S I-B M0 — Production Migration Runbook
document_type: production_migration_runbook
parent: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
depends_on: A3S-PHASE1B-PROD-AUDIT-001
gate_reference: A3S-PHASE1B-CA-M0-RELEASE-DECISION-001
owner: Alpha3S
author_role: Dev
version: 1.0.3
status: ca_approved_controlled_cutover_pending_po_session
release_candidate_sha: 8a702d616eab54d5def9292a40593ff1b1540b04
release_candidate_tag: ib-m0-rc1
created_at: 2026-07-25
last_updated: 2026-07-25 15:41 GMT+7
language: vi-VN
---

# Production Migration Runbook — I-B M0 (v1.0.3)

> Đưa **production (host alias `alpha3s-vps`)** từ schema **012+013** lên M0 (014 corrective + 015 audit +
> 016 rbac + 017 auth + 018 rbac_seed). **CHƯA được phép chạy** — chỉ khi §0 gates PASS. Gate reference:
> CA-REVIEW-M0-DEV-004 + Evidence Package **v1.0.2** (release-candidate SHA `8a702d6…`).
> Nguyên tắc: expand-only, forward-only, **immutable release SHA/tag**, backup + restore-check BẮT BUỘC,
> **maintenance/quiesce staff traffic quanh RBAC cutover**, mỗi bước verify, rollback rõ. Mọi thao tác
> production PO approve từng phiên. **Dùng host alias, không lặp IP.**
>
> **v1.0.3 — CA FINAL DECISION (A3S-PHASE1B-CA-M0-RELEASE-DECISION-001, 25/7):** M0 controlled production
> cutover **ĐÃ PHÊ DUYỆT** cho release candidate `8a702d6` / tag **`ib-m0-rc1`**, **subject to** PO phê duyệt
> phiên + toàn bộ preflight/go-no-go gate. Bản này vá **2 errata bắt buộc** của CA (không mở submission mới):
> **(1) §6.1** CSP verify tại **dashboard host `a3s-dash.robanme.com`** (KHÔNG phải API host `a3s.robanme.com`)
> — sửa §1.4 + §4; **(2) §6.2** quiesce staff traffic triệt để (2 staff xác nhận ngừng + operator kiểm không
> có staff mutation in-flight + fallback temporary staff-API/route block nếu stop dashboard chưa đủ) — sửa §2A.
> **CHƯA được chạy tự động** — CA: "không phải lệnh tự động triển khai". Chạy khi §0 + §7 go/no-go đạt.
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
- [x] **CA release approval — ĐÃ CẤP** (A3S-PHASE1B-CA-M0-RELEASE-DECISION-001, 25/7: M0 dev gate CLOSED,
      4 P0 CLOSED, Evidence v1.0.2 ACCEPTED, controlled cutover APPROVED cho `8a702d6`/`ib-m0-rc1` — subject
      to PO session + preflight/go-no-go). **2 errata bắt buộc đã vá (§1.4/§4 CSP dashboard-host, §2A quiesce).**
- [ ] **PO phê duyệt ĐÚNG PHIÊN production change** (CA §7 — bắt buộc mỗi phiên; chưa có → NO-GO).
- [ ] **Tag `ib-m0-rc1` trỏ đúng `8a702d6…`** (CA §2) + working tree/build context clean + KHÔNG kèm commit
      code ngoài release SHA. (Nếu release SHA đổi → chạy regression + xin CA xác nhận delta trước cutover.)
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
**1.4. CSP pre-release check** (CA §9.4 + **errata §6.1 — lấy header từ DASHBOARD HOST thật**):
`GET https://a3s-dash.robanme.com/` (KHÔNG dùng API host `a3s.robanme.com`) phải trả header
`Content-Security-Policy` có `script-src 'self' 'nonce-…' 'strict-dynamic'` và **KHÔNG** `unsafe-inline`
trong `script-src`. Lưu header vào evidence (§4 lặp lại sau cutover cùng host).

## 2. Deploy code (backward-compat, immutable SHA)
Code M0 feature-detect → chạy được trên 012+013 (RBAC unprovisioned → `require_permission` degrade;
startup readiness skip hợp lệ). Deploy TRƯỚC, migrate SAU.
- **Dùng immutable release SHA/tag `8a702d6…`** (đề xuất tag `ib-m0-rc1`) qua CI/CD (merge→main→deploy)
  HOẶC checkout đúng tag trên VPS — **không checkout branch/commit ad hoc**.
- `docker compose -f docker-compose.prod.yml up -d --force-recreate api worker telegram_bot telegram_customer_bot dashboard`.
- **Verify:** health 200; login OK (degrade vì chưa provision); bot trả lời; log sạch; **CSP header đúng
  (§1.4)**.
- **Rollback bước này:** redeploy SHA cũ (`c210a84`) + recreate. DB nguyên (chưa migrate).

## 2A. MAINTENANCE ON — quiesce staff traffic (CA §4, §9.2 + **errata §6.2**) — TRƯỚC §3
> Vì sau 016 mọi staff chưa gán role bị 403, KHÔNG được để staff request chạm `require_permission` trong
> lúc DB half-provisioned. Chặn staff traffic TRƯỚC khi migrate 016. **CA §6.2: dừng dashboard container
> CHƯA tuyệt đối chặn direct API call từ browser/session đã mở** → phải thêm xác nhận + kiểm in-flight +
> fallback block.
1. **2 staff XÁC NHẬN đã ngừng thao tác** (không chỉ thông báo — CA §6.2): nhận confirm rõ ràng từ cả 2
   trước khi tiếp tục (volume thấp — audit xác nhận 2 đơn/1 SP).
2. **Dừng dashboard** (chặn staff UI) **trước migration 016**: `docker compose -f docker-compose.prod.yml stop dashboard`.
3. **Operator kiểm KHÔNG có staff mutation đang chạy** (in-flight): quan sát log api không còn request ghi
   của staff; (tùy chọn) `SELECT count(*) FROM pg_stat_activity WHERE state='active' AND query ILIKE '%staff%'`
   = 0 ngoài phiên migrate.
4. **Nếu KHÔNG bảo đảm chặn được direct staff-API call** (session bearer đã mở vẫn gọi thẳng api): bật
   **temporary staff-API/route block** — chặn tầng gateway/reverse-proxy các route staff/dashboard-API
   (giữ Messenger webhook mở), hoặc tạm `stop api` nếu customer channel không phụ thuộc (⚠ kiểm phụ thuộc
   trước). Ghi rõ cơ chế block đã dùng vào evidence.
5. Customer channel (Messenger webhook + telegram_customer_bot) **giữ chạy** — không đụng staff RBAC path
   (trừ khi §2A.4 buộc stop api; khi đó ghi rõ downtime customer + ưu tiên phương án chặn route thay vì stop api).
6. Ghi mốc `maintenance_on` (time + executor) + cơ chế quiesce vào evidence.

> **Không mở lại dashboard cho tới khi role assignment + strict readiness + permission smoke đều pass (§3B).**

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

### 3.1. Hai lớp post-migration validation (CA F-R1-01 — bắt buộc hiểu trước mọi deploy)
`migrate.py up` (deploy path production, kể cả M1/M2 `019→028`) **chỉ** chạy lớp **OPERATIONAL** —
`scripts/operational_seed_validation.sql` trong `post_migration_validations`. Lớp này **existing-safe**:
kiểm 1 product `3S-100G` · description approved · không "100% Robusta" · `serving_size_g NULL` ·
`net_weight_g=100` · **≥1** price tier · structural invariant tier (min_qty≥1, unit_price_vnd>0).
**KHÔNG** assert exact count / exact canonical price-tier values → production đã có thêm price tier hợp lệ
(staff tạo qua chức năng M0) **vẫn PASS**, `up` **exit 0**.

Lớp **FRESH-INSTALL-ONLY** — `scripts/fresh_db_seed_validation.sql` (exact canonical: `1/170k, 5/160k,
20/140k`, đúng 3 tier) — **KHÔNG** nằm trong `up`. Chỉ chạy ở **fresh-DB bootstrap/test**, gọi **tường minh**:
```bash
docker compose -f docker-compose.prod.yml exec -T api python /srv/scripts/migrate.py fresh-validate
```
Manifest key `fresh_install_validations` (versioned) trỏ lớp này; runner có command `fresh-validate` riêng
(không heuristic đoán môi trường). **Fresh install mới** = chạy `up` (operational) **rồi** `fresh-validate`
(canonical). **Existing production deploy** = chỉ `up` (operational); **KHÔNG** chạy `fresh-validate` trên
production có giá thật (sẽ fail đúng thiết kế vì prod có tier ngoài canonical).
> Bối cảnh: R1 rehearsal trên restored production phát hiện `fresh_db_seed_validation` (exact 3 tier) làm
> `up` exit 1 vì prod đã có 5 tier hợp lệ → deploy abort. Split này (CA remediation F-R1-01) khắc phục:
> operational tolerant trong deploy path, canonical giữ nguyên nhưng chuyển sang fresh-only tường minh.

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
- [ ] **CSP post-release check** (CA §9.4 + **errata §6.1 — DASHBOARD HOST**): `GET https://a3s-dash.robanme.com/`
      header CSP có nonce + strict-dynamic, **không** `unsafe-inline` trong `script-src`; browser console
      **không** CSP violation; dashboard render+hydrate OK. **Nếu CSP thiếu nonce / còn unsafe-inline / có
      violation làm hỏng hydration → DỪNG hoặc rollback dashboard release** (CA §4).
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

## 8B. Go/No-Go checklist (CA §7 — thiếu 1 điều kiện = NO-GO)
- [ ] PO phê duyệt đúng phiên production change.  - [ ] Tag/SHA đúng §0/§2 (`ib-m0-rc1`→`8a702d6`).
- [ ] Cutover ledger (§7) đã điền.  - [ ] Cron backup khỏe (§0.1).  - [ ] Backup mới + restore-check pass (§1.1).
- [ ] Production audit vẫn khớp `012+013` (§1.2).  - [ ] Mô tả `3S-100G` khớp IN-list 014 (§1.3).
- [ ] Controlled mapping file tồn tại, permission `600`, checksum đã lưu kiểm soát (§8).
- [ ] Initial active admin + role toàn bộ active staff đã PO chốt.  - [ ] Maintenance đang bật (§2A).
- [ ] **Dashboard CSP preflight pass trên `a3s-dash.robanme.com`** (§1.4 — errata §6.1).

## 9. Sau cutover — Cutover Result Report (DUY NHẤT, CA §9)
Dev gửi **một** report, không mở thêm chuỗi review, gồm: release SHA/tag thực tế; start/end + maintenance
on/off; migration/baseline exit codes; backup/restore evidence reference; **RBAC assignment verdict KHÔNG
chứa PII**; CSP (dashboard host)/health/dashboard/bot/audit smoke results; anomaly/rollback/forward-fix (nếu
có). Mọi check pass → CA ghi nhận M0 production complete → chuyển M1.

## Ký
```text
PROD MIGRATION RUNBOOK v1.0.3 — CA FINAL DECISION (A3S-PHASE1B-CA-M0-RELEASE-DECISION-001): controlled cutover
APPROVED cho 8a702d6/ib-m0-rc1, subject to PO session + go-no-go. Va 2 errata bat buoc: (§6.1) CSP verify tai
dashboard host a3s-dash.robanme.com (§1.4/§4); (§6.2) quiesce staff traffic triet de - 2 staff xac nhan +
operator kiem in-flight + fallback temporary staff-API/route block (§2A). Them §8B go/no-go + §9 Cutover
Result Report. CHUA duoc chay tu dong - cho PO session approval + preflight. Author role: Dev. Ngay: 2026-07-25 15:41 GMT+7.

--- v1.0.2 (superseded) — amendment CA-REVIEW-M0-DEV-004 §4/§8/§9:
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
