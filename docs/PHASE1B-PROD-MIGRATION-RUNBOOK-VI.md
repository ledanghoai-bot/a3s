---
id: A3S-PHASE1B-PROD-MIGRATION-RUNBOOK-001
title: Alpha3S I-B M0 — Production Migration Runbook
document_type: production_migration_runbook
parent: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
depends_on: A3S-PHASE1B-PROD-AUDIT-001
gate_reference: A3S-PHASE1B-CA-REVIEW-M0-DEV-003
owner: Alpha3S
author_role: Dev
version: 1.0.1
status: draft_pending_ca_release_approval
created_at: 2026-07-25
last_updated: 2026-07-25
language: vi-VN
---

# Production Migration Runbook — I-B M0 (v1.0.1)

> Đưa **production (host alias `alpha3s-vps`)** từ schema **012+013** lên M0 (014 corrective + 015 audit +
> 016 rbac + 017 auth + 018 rbac_seed). **CHƯA được phép chạy** — chỉ khi §0 gates PASS. Gate reference:
> CA-REVIEW-M0-DEV-003 + M0 Dev Report v1.0.5 + Evidence Package v1.0.1 (SHA `931943d…`).
> Nguyên tắc: expand-only, forward-only, **immutable release SHA/tag** (không checkout branch/commit ad hoc
> trên VPS), backup + restore-check BẮT BUỘC, mỗi bước verify, rollback rõ. Mọi thao tác production PO
> approve từng phiên. **Dùng host alias, không lặp IP.**

## 0. Gate tiên quyết (đủ TẤT CẢ)
- [ ] **CA release approval** (Evidence v1.0.1 verified-closed + review 003 amendments đóng).
- [ ] **PO khóa policy** (TRƯỚC maintenance window): duyệt ma trận role→permission; **điền staff worksheet**
      (gán role cho từng staff hiện hữu, chỉ định initial active admin); xác nhận PII masking/export;
      **xác nhận `payment.cod_record` cho support/delivery** (quyền ghi nhận tài chính); ký **ADR
      localStorage** (nếu chọn temporary session exception — kèm CSP + TTL≤48h đã implement).
- [ ] **Cleanup**: `.env.bak.pre-llmfix` (untracked, benign) chuyển `/srv/backups/`; **thêm cron pg_dump
      ngày**; kiểm mô tả `3S-100G` production khớp IN-list 014.
- [ ] Maintenance window + **người thực thi / người quan sát / go-no-go owner / evidence location** ghi rõ.

## 1. Pre-flight
**1.1. Backup DB + RESTORE-CHECK BẮT BUỘC** (không phải tùy chọn — CA §10.3):
```bash
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U alpha3s -d alpha3s \
  | gzip > /srv/backups/alpha3s_pre_m0_$(date -u +%Y%m%dT%H%M%SZ).sql.gz
# RESTORE-CHECK: khoi phuc vao container throwaway, verify row counts khop, roi xoa throwaway.
```
**1.2.** Chạy `scripts/prod_audit.sql` (read-only) → xác nhận 012+013, anomaly còn.
**1.3. Verify IN-list 014:** so mô tả `3S-100G` với 2 chuỗi known-bad trong `014`. **Nếu khác → DỪNG**,
tạo **migration forward mới** sửa IN-list, **rehearsal lại**, **xin approval lại** — **KHÔNG sửa 014 đã
rehearsal ngay trong phiên cutover** (CA §10.4).

## 2. Deploy code (backward-compat, immutable SHA)
Code M0 feature-detect → chạy được trên 012+013 (RBAC unprovisioned + `RBAC_STRICT=false` → degrade;
startup readiness skip hợp lệ). Deploy TRƯỚC, migrate SAU.
- **Dùng immutable release SHA/tag** (`931943d…` hoặc tag release) qua CI/CD (merge→main→deploy) HOẶC
  checkout đúng tag trên VPS — **không checkout branch/commit ad hoc**.
- `docker compose -f docker-compose.prod.yml up -d --force-recreate api worker telegram_bot telegram_customer_bot dashboard`.
- **Verify:** health 200; login OK (degrade vì chưa provision, `RBAC_STRICT=false`); bot trả lời; log sạch.
- **Rollback bước này:** redeploy SHA cũ (`c210a84`) + recreate. DB nguyên (chưa migrate).

## 3. Migration qua runner (baseline-13 → up)
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

## 3A. RBAC CUTOVER UNIT (kiểm soát — CA §5, tránh half-provisioned)
> Migration 016 làm `rbac_provisioned()`=true NGAY khi table/column có. Nếu để `RBAC_STRICT=true` hoặc
> restart giữa lúc `role_permissions`/`role_key` còn rỗng → **half-provisioned** → dashboard mất quyền /
> startup fail. Vì vậy phần này là MỘT unit liên tục, `RBAC_STRICT` bật SAU CÙNG.

1. **Seed mapping đã PO duyệt = migration `018_rbac_seed.sql`** (đã áp ở §3 up) — KHÔNG chạy file proposal
   trực tiếp bằng psql.
2. **Gán role 2 staff** bằng `scripts/assign_staff_roles.py` (transactional, idempotent, cardinality
   fail-closed), mapping đọc từ **file kiểm soát truy cập (không PII trong repo)**:
   ```bash
   docker compose -f docker-compose.prod.yml exec -T api python scripts/assign_staff_roles.py --mapping /path/staff_roles.txt
   ```
   Script FAIL-CLOSED nếu: role không hợp lệ / staff không tồn tại / **<1 active admin** / **còn active
   staff thiếu role** → ROLLBACK.
3. **Verify**: `SELECT count(*) FROM staff_users WHERE is_active AND role_key IS NULL` = 0; ≥1 active admin.
4. **CHỈ bây giờ** đặt **`RBAC_STRICT=true`** (env) → recreate api/worker → startup readiness pass (nếu
   half → api KHÔNG start, quay lại bước 1-2).
5. **Positive/negative permission smoke**: non-admin gọi `staff.manage` → 403; admin → OK; disable admin
   cuối → 409.
6. **Recovery nếu seed/assignment fail**: giữ `RBAC_STRICT=false` (chưa recreate với strict); sửa mapping;
   chạy lại (idempotent); chỉ bật strict khi pass.

## 4. Post-migration verification
- [ ] `prod_audit.sql` khớp target; bot smoke (không "100% Robusta"/"50 ly").
- [ ] Dashboard: 1 thao tác gated → `audit_log` ghi đúng; **KHÔNG test throttling vào tài khoản thật**
      (dùng tài khoản/cửa sổ test được duyệt — CA §10.6).
- [ ] **KHÔNG "tạo đơn test rồi xóa"** trên production — dùng synthetic marker + cancel/void hợp lệ + giữ
      audit trail (CA §10.5).
- [ ] Log sạch 30-60 phút; ghi start/end time + evidence location.

## 5. Rollback
| Thời điểm | Rollback |
|---|---|
| Sau §2, trước §3 | Redeploy SHA `c210a84` + recreate. DB nguyên. |
| Migration lỗi (§3) | Mỗi migration 1 txn; forward-fix + `up` lại. 014 fail-closed không ghi. |
| RBAC cutover fail (§3A) | Giữ `RBAC_STRICT=false`; sửa mapping/assignment; chạy lại; chưa bật strict. |
| Sau migrate, phát hiện sai | Expand-only → revert code; **`RBAC_STRICT=false`** (env rollback) + recreate → degrade; 014-data KHÔNG rollback ngược (forward-fix). |
| Hỏng nặng | **Restore từ backup §1.1** (đã restore-check). |

## 6. Ràng buộc
KHÔNG gỡ initdb (CA §8.4); KHÔNG bỏ backup+restore-check; KHÔNG default staff role; KHÔNG chạy khi §0
chưa đủ; KHÔNG sửa 014 trong cutover; production audit ≠ migration approval.

## Ký
```text
PROD MIGRATION RUNBOOK v1.0.1 (DRAFT) — amendment CA-REVIEW-M0-DEV-003 §5+§10: RBAC cutover unit
(RBAC_STRICT bat sau cung), immutable SHA/tag, backup+restore-check bat buoc, khong sua 014 trong cutover,
khong tao don test/khong throttle tai khoan that, ghi executor/observer/go-no-go/time/evidence, host alias.
CHUA duoc chay — cho CA release approval + PO gates. Author role: Dev (Alpha3S). Ngay: 2026-07-25.
```
