---
id: A3S-PHASE1B-PROD-MIGRATION-RUNBOOK-001
title: Alpha3S I-B M0 — Production Migration Runbook
document_type: production_migration_runbook
parent: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
depends_on: A3S-PHASE1B-PROD-AUDIT-001
owner: Alpha3S
author_role: Dev
version: 1.0.0
status: draft_pending_ca_release_approval
created_at: 2026-07-25
language: vi-VN
---

# Production Migration Runbook — I-B M0

> Quy trình cầm-tay-chỉ-việc để đưa **production (VPS 160.30.157.235)** từ schema **012+013** lên **M0**
> (014 corrective + 015 audit + 016 rbac + 017 auth). Soạn sẵn, **CHƯA được phép chạy** — chỉ thực hiện
> khi **§0 tất cả gate = PASS**. Căn cứ hiện trạng: `PHASE1B-PROD-AUDIT-VI.md`.
>
> Nguyên tắc xuyên suốt: **expand-only, forward-only, có backup, mỗi bước verify, rollback rõ**. Mọi thao
> tác production đều cần PO approve từng phiên (không tự động).

## 0. Gate tiên quyết (PHẢI đủ TẤT CẢ trước khi bắt đầu)
- [ ] **CA release approval** cho M0 production migration (đã trình v1.0.4 + prod audit).
- [ ] **PO khóa policy gates:** duyệt `scripts/rbac_seed_proposed.sql` (Phụ lục A ma trận role→permission);
      chốt initial admin; export policy; **localStorage risk-acceptance** (auth decision record §9.1).
- [ ] **Cleanup production (từ prod audit §4):** dọn **1 tracked file dirty** trên `main` VPS; **verify
      backup/cron pg_dump ngày** hoạt động; **kiểm mô tả `3S-100G` production khớp IN-list known-bad của
      014** (nếu là biến thể khác → bổ sung vào IN-list 014 + re-rehearsal trước).
- [ ] **Maintenance window** thông báo (bot có thể chớp gián đoạn khi recreate container).

> Thiếu bất kỳ gate nào → **DỪNG**, không chạy.

## 1. Pre-flight (ngay trước khi migrate)

**1.1. Backup DB BẮT BUỘC** (không có backup → không migrate):
```bash
# trên VPS
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U alpha3s -d alpha3s \
  | gzip > /srv/backups/alpha3s_pre_m0_$(date -u +%Y%m%dT%H%M%SZ).sql.gz
ls -lh /srv/backups/alpha3s_pre_m0_*.sql.gz   # xác nhận file có kích thước hợp lý
```
Kiểm restore-able (thử restore vào 1 DB throwaway nếu cẩn trọng).

**1.2. Chụp lại hiện trạng (read-only):** chạy `scripts/prod_audit.sql` → xác nhận vẫn 012+013,
`schema_migrations`=false, anomaly còn (baseline chưa chạy). Lưu output.

**1.3. Verify IN-list 014:** query mô tả thật (không PII — mô tả marketing):
```sql
SELECT sku, description FROM products WHERE sku='3S-100G';
```
So với 2 chuỗi known-bad trong `migrations/014_correct_product_seed.sql`. **Nếu khớp** → OK. **Nếu khác** →
bổ sung biến thể vào `IN(...)` của 014, chạy lại rehearsal (fresh+existing) trước khi tiếp.

## 2. Deploy M0 code lên production (backward-compat — an toàn trên 012+013)

Code M0 **feature-detect**: chạy được trên schema 012+013 (RBAC unprovisioned → degrade về hành vi cũ;
audit_log chưa có → bỏ qua). Đã verify trên dev 012. → **Deploy code TRƯỚC, migrate SAU** (expand→migrate).

**2.1.** Đưa branch `phase1b-m0` vào luồng deploy production. 2 cách:
- **CI/CD (khuyến nghị, CLAUDE §8):** merge `phase1b-m0` → `main`, push → GitHub Actions tự deploy VPS.
- **Thủ công trên VPS:** `git -C /srv/alpha3s fetch && git -C /srv/alpha3s checkout <commit phase1b-m0>`.

**2.2.** Recreate service để nạp code mới (env_file/code):
```bash
cd /srv/alpha3s
docker compose -f docker-compose.prod.yml up -d --force-recreate api worker telegram_bot telegram_customer_bot dashboard
```
**2.3. Verify backward-compat (schema vẫn 012+013):**
- `curl -s https://a3s.robanme.com/health` (hoặc qua container) = 200.
- Đăng nhập dashboard OK (require_permission degrade vì RBAC chưa provisioned → không chặn).
- Bot trả lời thật (LLM đã là `deepseek-v4-flash`).
- Log không lỗi import/500.

> **Rollback ở bước này:** redeploy commit cũ (`c210a84`) + recreate. Chưa migrate nên DB nguyên vẹn.

## 3. Chạy migration qua runner (baseline-13 → up)

Runner = `scripts/migrate.py` (đã có trên VPS sau bước 2). DB production `schema_migrations` chưa tồn tại +
`data_deletion_requests` đã có (013 áp tay) → **baseline_through = 13** (dùng `baseline_manifest_13.json`).

**3.1. Status (trước):**
```bash
docker compose -f docker-compose.prod.yml exec -T -e MIGRATE_ACTOR="prod-m0" api \
  python /srv/scripts/migrate.py status     # 001-017 PENDING (schema_migrations vua tao)
```
**3.2. Baseline 001-013 (manifest-13, KHÔNG chạy, verify data_deletion tồn tại):**
```bash
docker compose -f docker-compose.prod.yml exec -T api \
  python /srv/scripts/migrate.py baseline --manifest scripts/baseline_manifest_13.json
# Ky vong: baseline 001-013; "KHONG baseline (phai chay): 014_correct_product_seed, 015..., 016..., 017..."
```
> Nếu manifest verify FAIL (thiếu object) → **STOP**, điều tra drift (không baseline mù).

**3.3. Up (áp 014→017 + post-migration validation):**
```bash
docker compose -f docker-compose.prod.yml exec -T -e MIGRATE_ACTOR="prod-m0" api \
  python /srv/scripts/migrate.py up
# Ky vong: apply 014,015,016,017; "Post-migration validations pass"; exit 0.
# 014 DO-block postcondition: neu mo ta la unknown-bad variant -> RAISE -> rollback 014 -> exit!=0
#   -> quay lai §1.3 bo sung IN-list, KHONG ep chay.
```
**3.4. Verify sau migrate (read-only):** chạy lại `prod_audit.sql`:
- `3S-100G`: description approved, **serving_size_g NULL**, net_weight 100, **không "100% Robusta"**.
- `schema_migrations` có 001-017; `audit_log`, `roles`, `staff_users.role_key` tồn tại.

## 4. Provision RBAC (quy trình existing-staff — CA §11.2)

Production có **2 staff thật** → **KHÔNG** default `viewer`.
**4.1.** Audit 2 staff hiện có (username, ai nên role gì — **PO quyết**):
```sql
SELECT id, username, name, is_active, role_key FROM staff_users ORDER BY id;
```
**4.2.** Áp mapping role→permission **đã PO duyệt** (`rbac_seed_proposed.sql` → thành migration `018_rbac_seed.sql`, hoặc chạy qua psql một lần có kiểm soát).
**4.3.** Gán role cho từng staff theo PO:
```sql
UPDATE staff_users SET role_key='admin' WHERE username='<admin_user_PO_chot>';
-- ... cac staff khac theo PO
```
**4.4.** (Sau khi mọi staff có role) migration siết `role_key` NOT NULL (bước sau, không bắt buộc ngay).
**4.5. Verify enforcement:** đăng nhập bằng 1 tài khoản non-admin → gọi endpoint gated `staff.manage` → **403**;
đăng nhập admin → OK; thử disable admin cuối → **bị chặn (409)**.

## 5. Post-migration verification (toàn diện)
- [ ] `prod_audit.sql` khớp target state (§3.4).
- [ ] Bot smoke: "100% Robusta?" → Robusta+Arabica; "bao nhiêu ly?" → không "50 ly"; tạo đơn test (rồi xóa).
- [ ] Dashboard: login + 1 thao tác gated → audit_log ghi đúng (actor/action/before-after); PII không lộ.
- [ ] Login throttling (N lần sai → 429); password change → revoke session.
- [ ] Log production không lỗi trong 30-60 phút đầu.

## 6. Rollback plan

| Thời điểm hỏng | Rollback |
|---|---|
| Sau deploy code (§2), trước migrate | Redeploy `c210a84` + recreate. DB nguyên vẹn (chưa migrate). |
| Migration lỗi giữa chừng (§3.3) | Mỗi migration 1 transaction → cái lỗi tự rollback; `schema_migrations` phản ánh cái đã áp. **Forward-fix** (sửa migration mới) rồi `up` lại. 014 fail-closed → không ghi, an toàn. |
| Phát hiện sai sau migrate | Expand-only → revert code deploy; bảng/cột mới không đọc = vô hại. **014 (data) KHÔNG rollback ngược** (không muốn khôi phục "100% Robusta") — nếu cần sửa, dùng migration forward mới. |
| Hỏng nặng / nghi mất dữ liệu | **Restore từ backup §1.1** (`gunzip | psql`), điều tra offline. |

**Rollback boundary rõ:** ranh giới an toàn là **sau §2 / trước §3** (chỉ code, redeploy được). Sau §3, ưu
tiên forward-fix; backup là lưới cuối.

## 7. Ràng buộc / KHÔNG được làm
- **KHÔNG** gỡ initdb path production (CA §8.4 — chỉ sau khi runner chứng minh trên production, bước sau).
- **KHÔNG** bỏ backup §1.1.
- **KHÔNG** default staff = viewer; phải PO gán role.
- **KHÔNG** chạy §2-§5 khi §0 chưa đủ gate.
- Production audit ≠ migration approval; migration cần CA release approval (§0).

## 8. Thứ tự tóm tắt (checklist 1 dòng)
```text
§0 gates PASS → §1 backup + audit + verify IN-list → §2 deploy code + verify backward-compat
→ §3 baseline-13 + up(014-017) + verify → §4 provision RBAC (PO gán role 2 staff)
→ §5 verify toàn diện → (giám sát). Hỏng: §6 rollback.
```

## Ký
```text
PROD MIGRATION RUNBOOK — A3S-PHASE1B-PROD-MIGRATION-RUNBOOK-001 v1.0.0 (DRAFT)
Soan san theo prod audit (012+013, baseline_through=13, 2 staff, anomaly confirmed). CHUA duoc chay -
cho CA release approval + PO gates + cleanup (§0). Expand-only, backup bat buoc, rollback boundary sau §2.
Author role: Dev (Alpha3S). Ngay: 2026-07-25
```
