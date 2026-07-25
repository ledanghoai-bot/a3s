---
id: A3S-PHASE1B-M0-DEV-REPORT-001
title: Alpha3S I-B — Dev Report gửi CA: M0 development + rehearsal (v1.0.1)
document_type: dev_report_to_ca
responds_to: A3S-PHASE1B-CA-REVIEW-M0-DEV-001
reports_on: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
plan_version: 0.1.3
owner: Alpha3S
author_role: Dev
version: 1.0.1
status: submitted_to_ca
created_at: 2026-07-25
language: vi-VN
---

# Dev Report gửi CA — M0 development + rehearsal (v1.0.1)

Gửi CA. v1.0.1 xử lý **toàn bộ 4 P0 + P1** của CA-REVIEW-M0-DEV-001 (đóng các blocker của rehearsal gate).
Mọi fix đều **chứng minh bằng chạy thật** trong container tạm cô lập. **Production không đụng.**

## 1. Xử lý P0/P1 (CA-REVIEW-M0-DEV-001)

| CA | Vấn đề | Fix | Bằng chứng |
|---|---|---|---|
| **P0 §4** | `baseline <through>` tùy ý → có thể đánh dấu 014 applied mà không chạy | Bỏ tham số `through` tùy ý: `baseline` chỉ tới `manifest.baseline_through`; `never_baseline:["014_..."]`; drift-check trước; insert atomic (1 transaction). Env có 013 → `baseline_manifest_13.json` (verify `data_deletion_requests`) | Kịch bản B2: `KHONG baseline (phai chay): 013, 014`; B1: manifest-13 trên DB-012 → STOP |
| **P0 §5** | Manifest verify chỉ đọc tables/columns | `verify_manifest()` enforce đủ: `expected_tables`, `expected_columns`, `expected_constraints`, `expected_indexes`, `prebaseline_data_assertions` — fail-closed | B1: STOP đúng vì thiếu constraint + index + data_assertion |
| **P0 §6** | Pre/postcondition 014 chỉ là comment | 014 dùng **DO block executable**: precondition (SKU=1) → apply exact-match IN → correct serving → postcondition (không "100% Robusta", serving NULL, net_weight=100) → RAISE EXCEPTION → rollback | Kịch bản C: unknown-bad variant → `RaiseError: 014 postcondition FAIL`, `v014_recorded=0`, rollback |
| **P0 §7** | Validation chưa nối vào runner/startup | `migrate.py up` **luôn** chạy `post_migration_validations` (từ manifest) sau apply; lỗi → exit≠0. One-shot service dựa exit code này | Fresh: `Post-migration validations pass`; C: validation/postcondition fail → `up_exit=1` |
| P1 §8 | Seed validation chưa đủ | Tách **3 lớp** (SQL / application / KB) — §3; SQL nay kiểm **exact** approved description + **exact** tier values | §3 |
| P1 §9 | Advisory lock contract | Chốt **fail-fast** (`pg_try_advisory_lock`), sửa doc plan §5.3 | migrate.py docstring + plan §5.3 |
| P1 §10 | Non-transactional recovery | Chưa có migration loại này; ghi điều kiện bắt buộc trước cái đầu tiên (plan §5.4) | plan §5.4 |

## 2. Evidence — kịch bản rehearsal (exit codes)

Chạy trong Postgres container tạm (`pgvector:pg16`) trên network dev; runner trong container `api`
(asyncpg 0.31). **Container tạm tách hoàn toàn dev/production, xóa sau khi xong.**

| Kịch bản | Kết quả |
|---|---|
| **A. Fresh DB** | `up` áp 001-014 + post-migration validation → `up_exit=0`; app-integration → `app_exit=0` |
| **B. Existing DB (012)** | B1 `baseline --manifest _13` (DB chưa có 013) → **STOP** (`b1_exit=1`, thiếu constraint/index/data_assertion); B2 `baseline` (manifest-12) → baseline 001-012, **skip 013+014**; B3 `up` → áp 013+014 + validation → `b3_exit=0` |
| **C. Negative (unknown-bad variant)** | inject description lạ chứa "100% Robusta" → `up`: 013 OK, **014 RAISE** `postcondition FAIL` → `c_up_exit=1`; `v014_recorded=0` (rollback), `v013_recorded=1` |

## 3. 3 lớp validation tách riêng (CA §8 — không gom 1 chữ PASS)

**Lớp 1 — SQL seed assertions** (`scripts/fresh_db_seed_validation.sql`, chạy qua runner `up`/`validate`):
- Exact approved description · SKU count=1 · `serving_size_g IS NULL` · `net_weight_g=100` · **exact tier
  values** (1/170k, 5/160k, 20/140k, đúng 3 tier). → Fresh/B3: **SEED PASS**.

**Lớp 2 — Application integration** (`scripts/app_integration_validation.py`, gọi tool thật):
- `tools.search_products()` **không** trả `serving_info` / `servings_per_unit_approx` /
  `price_per_serving_vnd_approx` cho `3S-100G`. → Kịch bản A: **APP PASS** (`app_exit=0`).
- Lệnh: `DATABASE_URL=… PYTHONPATH=/srv python scripts/app_integration_validation.py`.

**Lớp 3 — Knowledge/UAT regression** (KB harness, phụ thuộc LLM — CHƯA chạy trong rehearsal xác định này):
- Định nghĩa: UAT-011 / UAT-027 / UAT-079 ("Khẳng định 100% Robusta" = FAIL), + serving smoke; chạy qua
  `scripts/kb_*` với DeepSeek. **Sẽ báo cáo riêng** (non-deterministic, cần API key) — **không** gộp vào
  PASS của lớp 1-2. Ghi rõ đây là lớp còn phải chạy.

## 4. Artifact + commit (CA §12, §14)

Commit trên branch **`phase1b-m0`** (không lên `main`, không push). **Commit SHA gửi kèm trong transmittal
message của Dev** (branch/commit bất biến — CA §12).

Artifact: `scripts/migrate.py` (hardened v2), `scripts/baseline_manifest.json` + `baseline_manifest_13.json`,
`scripts/fresh_db_seed_validation.sql`, `scripts/app_integration_validation.py`, `scripts/prod_audit.sql`,
`migrations/014_correct_product_seed.sql`, + cụm doc I-B.

## 5. Cô lập môi trường (CA §12.6)
Mọi rehearsal chạy trên container `pgvector:pg16` tạm (tên `reh*`), tạo trên network dev, **xóa ngay sau
khi xong**. Đã xác nhận: DB dev thật vẫn ở migration 012, vẫn còn "100% Robusta" + `serving_size_g=2`,
**không có** `schema_migrations` (rehearsal không chạm dev DB). Production VPS: không truy cập.

## 6. Ràng buộc production (không đổi)
Chưa chạy production migration / chưa baseline production / chưa bật RBAC / chưa đổi session / chưa gỡ
initdb. M0.0 production audit chỉ chạy sau khi **PO cấp quyền VPS read-only**. Production migration cần **CA
release approval** + PO policy gates + backup/restore readiness + dry-run.

## 7. Đề nghị CA
Xin đóng **rehearsal release gate** trên cơ sở: 4 P0 đã fix + chứng minh bằng chạy thật (exit codes §2),
3 lớp validation tách bạch (§3), commit SHA + logs (§4). Tiếp tục: migrations 015/016/017 + audit/permission
services + DB pool + auth/security spike.

## Ký
```text
DEV REPORT — A3S-PHASE1B-M0-DEV-REPORT-001 v1.0.1
Da xu ly 4 P0 (baseline threshold, manifest enforcement, executable pre/postcondition, validation wiring)
+ P1 (3-layer validation, advisory-lock fail-fast doc, non-transactional recovery note). Chung minh bang
chay that: fresh/existing/negative scenarios (exit codes). Container tam cô lap, da xoa. Production KHONG
thay doi. Commit branch phase1b-m0 (SHA gui kem). Author role: Dev (Alpha3S). Ngay: 2026-07-25
```
