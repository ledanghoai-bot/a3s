---
id: A3S-PHASE1B-M0-EVIDENCE-PACKAGE-001
title: Alpha3S I-B M0 — Immutable Evidence Package (rehearsal pinned SHA)
document_type: evidence_package
parent: A3S-PHASE1B-M0-DEV-REPORT-001
owner: Alpha3S
author_role: Dev
version: 1.0.0
status: submitted_to_ca
generated_at: "2026-07-25 12:2x (GMT+7)"
branch: phase1b-m0
commit_sha: 29ce7a4319117d40751e57a3c0e8079d0f42c204
language: vi-VN
---

# M0 — Immutable Evidence Package (CA-REVIEW-M0-DEV-002 §6)

> Trả lời đúng yêu cầu immutable evidence của CA. Toàn bộ rehearsal dưới đây **chạy lại tại đúng revision
> bất biến** ghi ở §1, log lưu access-controlled (scratchpad phiên). Không PII/secret production; các
> credential trong lệnh là DB throwaway local (`alpha3s:alpha3s`), không phải bí mật production.

## 1. Revision & xác nhận code-đã-test (§6.1-6.3, §6.7)
- **Branch:** `phase1b-m0`
- **Full commit SHA:** `29ce7a4319117d40751e57a3c0e8079d0f42c204`
- **Git status tại revision test:** *clean* (không có uncommitted change) → **code đã test CHÍNH LÀ code
  tại SHA**. Runner chạy trong container `api` bind-mount working tree ở đúng SHA này.
- **Checksum artifact chính (sha256, 16 ký tự đầu):**
  | Artifact | sha256[:16] |
  |---|---|
  | `scripts/migrate.py` | `8ba02897b0eccea3` |
  | `migrations/014_correct_product_seed.sql` | `87dc259b2cda15a4` |
  | `scripts/baseline_manifest_13.json` | `022e3e79b1fa9bd8` |
- **Artifact trong commit (git ls-files):** `scripts/migrate.py`, `scripts/baseline_manifest.json`,
  `scripts/baseline_manifest_13.json`, `scripts/fresh_db_seed_validation.sql`,
  `scripts/app_integration_validation.py`, `scripts/m0_foundation_validation.py`,
  `scripts/rbac_seed_proposed.sql`, `migrations/014_correct_product_seed.sql` … `017_auth_hardening.sql`,
  `app/services/audit_service.py`, `app/services/permission_service.py`, `app/security/{__init__,headers,throttle}.py`.

## 2. Môi trường test
Container Postgres tạm (`pgvector/pgvector:pg16`) trên network dev, **tách hoàn toàn dev/production, xóa
sau mỗi kịch bản** (xác nhận `docker ps -a --filter name=reh` = 0 sau khi chạy). Runner/services chạy
trong container `api` (asyncpg 0.31) với `DATABASE_URL` trỏ throwaway. **Guard branch = `phase1b-m0`
trước+sau mỗi batch** (chống session `stage-c` song song switch working tree).

## 3. Kịch bản, lệnh exact, exit code, kết quả (§6.4-6.5)

| # | Kịch bản | Lệnh (rút gọn) | Exit | Kết quả (log) |
|---|---|---|---|---|
| E1 | **Fresh** up 001-017 + post-validation | `migrate.py up` | **0** | `Post-migration validations pass (1 file)` |
| E2 | **App-integration** (lớp 2) | `app_integration_validation.py` | **0** | `APP PASS: search_products KHONG tra serving_info/servings_per_unit/price_per_serving` |
| E3 | **Foundation** (M0.3/4) | seed `rbac_seed_proposed.sql` → `m0_foundation_validation.py` | **0** | `M0 FOUNDATION PASS: admin⊇staff.manage; sales KHONG staff.manage/inventory.adjust; audit fail-closed rollback OK; secret redaction OK` |
| E4 | **Existing** baseline-12 + up | `migrate.py baseline` → `up` | **0 / 0** | baseline: `KHONG baseline (phai chay): 013,014,015,016,017`; up: validations pass |
| E5 | **Negative** (unknown-bad variant) | inject → `migrate.py up` | **1** | `RaiseError: 014 postcondition FAIL: … "100% Robusta" (unknown-bad variant?)`; `v014_recorded=0` (rollback) |
| E6 | **Manifest-13 positive** (mô phỏng production) | load 001-013 → `baseline --manifest baseline_manifest_13.json` → `up` | **0 / 0** | baseline: `Baselined 13 … KHONG baseline (phai chay): 014,015,016,017`; up: validations pass |

Lệnh đầy đủ (mẫu, thay `<DB>`):
```bash
docker exec -e DATABASE_URL=<DB> -e MIGRATE_ACTOR=ev api python /srv/scripts/migrate.py up
docker exec -e DATABASE_URL=<DB> api python /srv/scripts/migrate.py baseline --manifest scripts/baseline_manifest_13.json
docker exec -e DATABASE_URL=<DB> -e PYTHONPATH=/srv -w /srv api python scripts/m0_foundation_validation.py
```
Log đầy đủ: `scratchpad/ev_{fresh,app,foundation,exist_baseline,exist_up,negative,m13_baseline,m13_up}.log`
(access-controlled, không commit).

## 4. Mapping assertion (report) → test/log (§6.6)

| Assertion trong M0 Dev Report | Test | Evidence |
|---|---|---|
| **P0§4** baseline không vượt threshold; corrective luôn chạy | E4, E6 | `KHONG baseline (phai chay): …014…` ở cả manifest-12 và manifest-13 → `never_baseline:014` + threshold enforce |
| **P0§5** manifest verify đủ (constraints/indexes/data-assertions), fail-closed | E4/E6 (positive verify pass) + `migrate.py:verify_manifest` (code) | baseline chỉ chạy sau verify pass; path STOP-on-missing đã demo (manifest-13 trên DB-012 → STOP, batch trước) |
| **P0§6** corrective executable pre/postcondition, fail-closed | E5 | `RaiseError 014 postcondition FAIL` + `v014_recorded=0` (rollback, không ghi) |
| **P0§7** validation nối vào `up`, fail→exit≠0 | E1, E5 | E1 `validations pass` exit 0; E5 fail → exit 1 |
| **M0.2** DB pool (8 service) | E2, E3 | tool `search_products` + audit/permission service chạy qua pool OK |
| **M0.3** audit fail-closed + redaction | E3 | `audit fail-closed rollback OK; secret redaction OK` |
| **M0.4** RBAC no-cache + least-privilege | E3 | `admin⊇staff.manage; sales KHONG staff.manage/inventory.adjust` |
| **§4.1** baseline_through=13 cho production | E6 | manifest-13 verify `data_deletion_requests` → baseline 001-013, up 014-017 |

## 5. Ghi chú
- Đây là evidence cho **development rehearsal**, KHÔNG phải production execution. Production baseline/migration
  vẫn NOT APPROVED.
- Redaction test hiện phủ password/token/secret (E3). CA §8 yêu cầu mở rộng redaction (phone/email/address/
  nested) + integration test audit-rollback nhiều case → **sẽ bổ sung ở batch tiếp** (audit release-gate).

## Ký
```text
EVIDENCE PACKAGE — A3S-PHASE1B-M0-EVIDENCE-PACKAGE-001 v1.0.0
Commit SHA 29ce7a4319117d40751e57a3c0e8079d0f42c204 (branch phase1b-m0, git clean).
6 kich ban rehearsal PASS pinned SHA (E1-E6), log access-controlled, guard branch OK, container tam da xoa.
Author role: Dev (Alpha3S). Xuat: 2026-07-25 (GMT+7).
```
