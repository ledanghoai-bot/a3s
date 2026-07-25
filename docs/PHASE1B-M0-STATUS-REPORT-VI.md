---
id: A3S-PHASE1B-M0-STATUS-REPORT-001
title: Alpha3S I-B M0 — Báo cáo trạng thái tổng hợp (gửi CA/PO)
document_type: status_report
parent: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
owner: Alpha3S
author_role: Dev
version: 1.0.0
status: submitted_to_ca_po
generated_at: "2026-07-25 12:18 (GMT+7) · 05:18 UTC"
branch: phase1b-m0
language: vi-VN
---

# Alpha3S I-B M0 — Báo cáo trạng thái tổng hợp

> **Thời điểm xuất báo cáo: 2026-07-25 12:18 (GMT+7) · 05:18 UTC.**
> Branch `phase1b-m0` (chưa push/merge; `main` = `c210a84` nguyên vẹn). Đây là bản tổng hợp một-nguồn của
> toàn bộ tiến độ M0 (thay cho các bản v1.0.1→v1.0.5 rời trong M0 Dev Report).

## 1. Trạng thái tổng quan
M0 (Foundation) đã **hoàn tất phần development + rehearsal + production audit**, mọi thứ **chứng minh bằng
chạy thật**. **Chưa đụng production** ngoài 2 việc đã được PO approve riêng (LLM model fix + audit
read-only). Đang **chờ CA release approval + PO policy gates** để thực thi production migration theo runbook.

## 2. Đã hoàn tất (development, đã commit branch phase1b-m0)

| Hạng mục | Nội dung | Bằng chứng |
|---|---|---|
| **Migration runner** | `scripts/migrate.py` hardened: baseline threshold + `never_baseline` + manifest enforcement (tables/columns/constraints/indexes/data-assertions) + executable pre/postcondition + validation wiring; advisory lock fail-fast | Rehearsal fresh/existing/negative PASS (exit codes) |
| **Corrective 014** | `014_correct_product_seed.sql`: sửa "100% Robusta" + `serving_size_g=2→NULL`, DO-block fail-closed | Kịch bản C: RAISE→rollback→không ghi |
| **M0.2 DB pool** | 8 service → `acquire/release`; sizing min1/max5 + command_timeout; lifespan close_pool | Smoke dev PASS, api không vỡ |
| **M0.3 Audit** | `audit_log` (015) + `audit_service`: nhóm A fail-closed cùng transaction + redaction secret/PII | foundation validation PASS |
| **M0.4 RBAC** | `roles/permissions/role_permissions` (016) + `require_permission` (no-cache) + staff CRUD hardened (last-admin guard, no-escalation); seed mapping chờ PO (`rbac_seed_proposed.sql`) | admin⊇staff.manage; sales KHÔNG có staff.manage/inventory.adjust |
| **M0.5 Security** | auth hardening (017): login throttling (fail-open), password change/revoke, must_change_password restricted session, security headers | backward-compat dev 012 không vỡ |
| **Auth decision record** | Temporary exception (localStorage + CSP) + deadline HttpOnly cookie trước M6 — **chờ PO/CA accept** | plan §9.1 |
| **3 lớp validation** | SQL seed (exact desc+tiers) · application (search_products không serving_info) · KB layer-3 (brand-truth PASS; serving post-014 confirmed) | đã chạy, tách bạch |

## 3. M0.0 Production audit (read-only, PO approve — `docs/PHASE1B-PROD-AUDIT-VI.md`)
- Production = **schema 012+013** (data_deletion áp tay, M0 chưa áp, `schema_migrations`=false) → **baseline_through=13**.
- **Volume nhỏ**: 2 đơn, 1 SP, 2 customers, 48 msg, **2 staff thật**, kb_units 364 → **migration window low-risk XÁC NHẬN trên production** (không cần backfill nặng).
- **Anomaly CONFIRMED live**: `3S-100G` còn "100% Robusta" + `serving_size_g=2` → 014 cần chạy production.
- Deployment: main `c210a84`, 8/8 container, `LLM_MODEL=deepseek-v4-flash` (đã fix), `@Ben3s_bot` active.
- Cần dọn trước migration: **1 tracked file dirty** trên main + **backup/cron pg_dump chưa verify**.

## 4. Production migration runbook (`docs/PHASE1B-PROD-MIGRATION-RUNBOOK-VI.md`) — DRAFT
§0 gates → §1 backup + verify IN-list 014 → §2 deploy code backward-compat → §3 baseline-13 + up(014-017) →
§4 RBAC gán role 2 staff (không default viewer) → §5 verify → §6 rollback (ranh giới an toàn sau §2). **Chưa
được phép chạy** (chờ §0).

## 5. Đang chờ (blocker — ngoài tầm Dev)
- **CA**: đóng rehearsal gate + **release approval** cho production migration (đã trình M0 Dev Report v1.0.5 + Prod Audit).
- **PO**: khóa policy gates — duyệt `rbac_seed_proposed.sql` (ma trận role→permission), initial admin, export policy, **localStorage risk-acceptance**.
- **Trước migration prod**: dọn 1 file dirty + verify backup/cron + kiểm mô tả prod khớp IN-list 014.

## 6. An toàn / production
- **Production KHÔNG bị đụng** bởi M0 dev (rehearsal chạy container tạm, đã xóa; dev DB net-zero).
- 2 thay đổi production đã làm (PO approve riêng): **LLM model fix** (deepseek-v4-flash, bot chạy lại) + **audit read-only** (không ghi).
- Production migration (014-017 + RBAC) **chưa chạy** — chờ §5 gates.

## 7. Commit manifest (branch `phase1b-m0`, chưa push)
```text
128de40  production migration runbook (draft)
5553a1f  M0.0 production audit (read-only)
2f53e05  report v1.0.5 (production LLM fixed)
db94d2c  auth decision record + layer-3 post-014
f1ac797  fix LLM model default -> deepseek-v4-flash
d1bc484  report v1.0.3 (pool + KB layer-3 + model finding)
ef04d61  M0.2 DB pool 8 service
e0ab09a  M0.3/4/5 audit/RBAC/security
6f9ed88  M0 scaffold (runner + 014 + prod_audit + docs feasibility/plan)
```
*(main `c210a84` không đổi; branch chưa push/merge.)*

## Ký
```text
M0 STATUS REPORT — A3S-PHASE1B-M0-STATUS-REPORT-001 v1.0.0
Xuat luc: 2026-07-25 12:18 (GMT+7) / 05:18 UTC.
M0 development + rehearsal + production audit + runbook HOAN TAT (chung minh bang chay that).
Production KHONG thay doi (ngoai LLM fix + audit read-only da PO approve). Cho CA release approval + PO
policy gates de chay production migration theo runbook. Author role: Dev (Alpha3S).
```
