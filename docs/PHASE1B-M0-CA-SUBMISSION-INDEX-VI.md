---
id: A3S-PHASE1B-M0-CA-SUBMISSION-INDEX-001
title: Alpha3S I-B M0 — Văn bản tổng hợp gửi CA (index + việc đã làm + vị trí file)
document_type: submission_index
responds_to: A3S-PHASE1B-CA-REVIEW-M0-DEV-004
owner: Alpha3S
author_role: Dev
version: 1.0.1
status: submitted_to_ca
created_at: 2026-07-25
last_updated: 2026-07-25 15:07 GMT+7
branch: phase1b-m0
tested_code_sha: 8a702d616eab54d5def9292a40593ff1b1540b04
submission_head: 3b45376523c05334da52429b269131315c65f568
proposed_release_sha: 8a702d616eab54d5def9292a40593ff1b1540b04
proposed_release_tag: ib-m0-rc1
language: vi-VN
---

# I-B M0 — Văn bản tổng hợp gửi CA (v1.0.1)

> Bản index để CA **truy cập & kiểm tra read-only**. Cập nhật cho vòng CA-REVIEW-M0-DEV-004: phân biệt rõ
> **3 SHA** (CA §2), đóng 4 P0 còn lại. Liệt kê: (A) việc cycle này, (B) vị trí file, (C) mapping CA-004,
> (D) commit manifest, (E) cách verify.

## 0. Truy cập & phân biệt SHA (CA-REVIEW-M0-DEV-004 §2)
- **Repo:** `D:\alpha3s` (Windows dev). Branch `phase1b-m0` **CHƯA push / CHƯA merge** (giữ local tới khi CA
  duyệt). **main = `c210a84`** (không đổi) → **production KHÔNG có code M0**.
- **`tested_code_sha` = `8a702d6…`** — SHA chứa toàn bộ code+test đã rehearsal (git clean tại thời điểm test).
- **`submission_head` = `3b45376…`** — HEAD chứa các artifact tài liệu v1.0.2 (runbook/evidence/ADR).
  Index này nằm 1 commit trên đó.
- **`proposed_release_sha/tag` = `8a702d6…` / `ib-m0-rc1`** — điểm freeze phát hành. Các commit tài liệu
  sau `8a702d6` **không đổi runtime code** → release vẫn ghim `8a702d6`. **KHÔNG dùng `931943d…`** (evidence
  v1.0.1 cũ) làm release SHA.

## A. Việc đã làm (cycle CA-REVIEW-M0-DEV-004 — 4 P0)
1. **P0 Runbook §4 — bỏ claim sai `RBAC_STRICT=false`:** runbook lên **v1.0.2**, **Phương án A maintenance
   cutover** (CA ưu tiên): chặn staff traffic (stop dashboard) TRƯỚC 016 → migrate → gán role trong
   maintenance → verify → `RBAC_STRICT=true` → recreate → smoke → **mới mở traffic**. Ghi rõ: sau 016
   `rbac_provisioned=true` nên staff chưa role **403 bất kể strict** → `RBAC_STRICT=false` **KHÔNG** phải
   recovery. Exact rollback = giữ maintenance + sửa/chạy lại assignment **hoặc** redeploy code cũ `c210a84`
   (RBAC-unaware).
2. **P0 §5 — nonce CSP loại `unsafe-inline`:** `dashboard/middleware.js` (Next 14) đặt
   `script-src 'self' 'nonce-<random>' 'strict-dynamic'`; `next.config.mjs` bỏ CSP tĩnh. **Verified:** header
   no-unsafe-inline + nonce **đổi mỗi request** + **browser smoke 0 CSP violation / 0 console error**, dashboard
   render+hydrate OK. ADR → **v1.0.1** (điều kiện activation đã đạt).
3. **P0 §6 — audit endpoint rollback đủ:** `audit_rollback_endpoint_test.py` mở rộng — thêm
   **`staff.update(deactivate)` + `staff.update(role change)` + session revocation** (ngoài staff.create,
   password_change). Tất cả rollback mutation/session khi audit insert fail.
4. **P0 §7 — E9/E10 executable có exit code:** `scripts/rbac_strict_test.py` (E9, exit 0) +
   `scripts/rbac_half_provisioned_test.py` (E10, exit 0). Không còn exit code `—`.
5. **Evidence Package → v1.0.2** ghim `8a702d6`: E1-E10 + **E-CSP**, exit codes thật, **log manifest sha256
   immutable** (CA §7), bảng checksum code (engine byte-identical v1.0.1).
6. **Controlled-file operational checks (CA §8):** thêm Runbook **§8** (file tồn tại/permission 600/dry-run
   no-PII/checksum vào evidence/archive sau cutover) + **§7 cutover ledger** (executor/observer/go-no-go/evidence).

## B. Vị trí file (repo-relative)

### Báo cáo / quyết định (`docs/`)
| File | Nội dung | Version/Status |
|---|---|---|
| `docs/PHASE1B-M0-EVIDENCE-PACKAGE-VI.md` | **Immutable evidence E1-E10 + E-CSP** | **v1.0.2 @ SHA 8a702d6** |
| `docs/PHASE1B-PROD-MIGRATION-RUNBOOK-VI.md` | Runbook (Phương án A maintenance cutover) | **v1.0.2** (chưa chạy) |
| `docs/PHASE1B-AUTH-SESSION-DECISION-RECORD-VI.md` | ADR localStorage (nonce CSP condition met) | **v1.0.1** PO accepted, chờ CA activation |
| `docs/PHASE1B-M0-DEV-REPORT-VI.md` | Dev report tổng M0 | v1.0.5 |
| `docs/PHASE1B-PROD-AUDIT-VI.md` | M0.0 production audit + pre-release actions | v1.0.1 |
| `docs/PHASE1B-RBAC-STAFF-WORKSHEET-VI.md` | Gán role staff | v1.0.1 **PO approved** |
| `docs/PHASE1B-AUDIT-RELEASE-GATE-VI.md` | Audit gate + DB-role exception | **PO accepted** (deadline M2) |
| `docs/PHASE1B-IMPLEMENTATION-PLAN-VI.md` | Plan M0-M6 | v0.1.3 |
| `docs/PHASE1B-FEASIBILITY-REPORT-VI/-EN.md`, `...-DEV-RESPONSE-VI.md` | Feasibility | v0.1.1 |
| `docs/PHASE1B-M0-STATUS-REPORT-VI.md` | Snapshot tổng hợp | v1.0.0 |

### Code / scripts / migrations (đối tượng kiểm tra chính)
| File | Vai trò |
|---|---|
| `scripts/migrate.py` | Runner (baseline threshold, manifest verify, validation wiring, advisory lock) — **identical v1.0.1** |
| `scripts/baseline_manifest.json` / `baseline_manifest_13.json` | Manifest (prod = manifest-13) |
| `migrations/014_correct_product_seed.sql` | Corrective 014 (DO-block pre/postcondition) — **identical v1.0.1** |
| `migrations/015…018` | M0 migrations (018 = versioned RBAC seed; đổi comment/sign-off vs v1.0.1, SQL exec không đổi) |
| `app/services/audit_service.py` | Audit fail-closed + redaction đệ quy |
| `app/services/permission_service.py` | RBAC no-cache + `rbac_ready` + `startup_verdict` — **identical v1.0.1** |
| `app/api/auth.py` | `require_permission` (strict mode) |
| `app/main.py` | Lifespan startup readiness (fail-closed) — **identical v1.0.1** |
| `app/security/{headers,throttle}.py` | Security headers + login throttling |
| **`dashboard/middleware.js`** | **MỚI — nonce-based CSP (bỏ unsafe-inline script-src)** |
| `dashboard/next.config.mjs` | Bỏ CSP tĩnh (middleware sở hữu CSP) |
| `scripts/m0_foundation_validation.py` | E3 |
| `scripts/audit_rollback_endpoint_test.py` | E7 (mở rộng: staff.update + session revocation) |
| `scripts/startup_readiness_test.py` | E8 |
| **`scripts/rbac_strict_test.py`** | **MỚI — E9 executable (exit code)** |
| **`scripts/rbac_half_provisioned_test.py`** | **MỚI — E10 executable (exit code)** |
| `scripts/fresh_db_seed_validation.sql` | Post-migration seed assertions |
| `scripts/assign_staff_roles.py` | Gán role fail-closed |
| `scripts/prod_audit.sql` | Production audit read-only |
| `scripts/pg_backup_daily.sh` | Cron backup (bản VPS `/srv/pg_backup_daily.sh`) |

## C. Mapping CA-REVIEW-M0-DEV-004 → vị trí / trạng thái
| CA §  | Yêu cầu | Vị trí / trạng thái |
|---|---|---|
| §4 | Runbook bỏ claim sai `RBAC_STRICT=false`; Phương án A | `docs/…RUNBOOK` **v1.0.2** §2A/§3/§3A/§3B/§5 — **DONE** |
| §5 | Nonce/hash CSP loại unsafe-inline + browser/header smoke | `dashboard/middleware.js`; Evidence **E-CSP**; ADR v1.0.1 — **DONE** |
| §6 | Audit rollback staff.update/deactivate + session revocation | `scripts/audit_rollback_endpoint_test.py` (**E7**) — **DONE** |
| §7 | E9/E10 executable + exit code + log assertion | `rbac_strict_test.py` (E9), `rbac_half_provisioned_test.py` (E10) — **DONE** |
| §7 | Evidence v1.0.2 @ release-candidate SHA + log manifest checksum | `docs/…EVIDENCE-PACKAGE` v1.0.2 @ `8a702d6` §3 — **DONE** |
| §8 | Controlled-file operational checks | Runbook **§8** + §7 ledger — **DONE (operator thực thi lúc cutover)** |
| §2 | Phân biệt tested_code_sha / submission_head / release_sha | frontmatter + §0 — **DONE** |
| §9 | Runbook: release tag, maintenance, exact rollback, CSP pre/post, cron verify, ledger | Runbook §0/§0.1/§1.4/§2A/§3B/§4/§7 — **DONE** |

## D. Commit manifest (branch `phase1b-m0`, chưa push)
```text
<this index commit>  docs: submission index v1.0.1 (CA-004)                    (HEAD, sẽ là submission_head+1)
3b45376  docs CA-004: runbook v1.0.2 + evidence v1.0.2 + ADR v1.0.1            <-- submission_head
8a702d6  code CA-004: nonce CSP middleware + E9/E10 executable + E7 mở rộng    <-- TESTED_CODE_SHA / RELEASE
7eb5691  docs: submission index v1.0.0 (CA-003)
b1a1da1  PO sign-off 4 văn bản + cron pg_dump
931943d  code CA-003 (evidence v1.0.1 SHA cũ — KHÔNG dùng làm release)
02abe1e / edb9d84 / 5553a1f / … / 29ce7a4  (CA-002 + scaffold + audit + fixes)
main = c210a84 (không đổi)
```

## E. Cách CA verify (read-only)
1. `git checkout 8a702d616eab54d5def9292a40593ff1b1540b04` → `git status` = clean → **code = code đã test**.
2. Đối chiếu bảng checksum (Evidence §1) — engine `migrate.py/014/permission_service/main.py` **identical**
   v1.0.1; `018` chỉ đổi comment (SQL exec không đổi, E1/E4/E6 pass).
3. Đọc E1-E10 + **E-CSP** (command + exit code + assertion). Chạy lại (tùy chọn) theo lệnh Evidence §2 —
   container tạm, không đụng prod. Log manifest sha256 (Evidence §3) đảm bảo raw log không đổi sau sign-off.
4. CSP: `curl -sD - http://<dashboard>/ -o /dev/null | grep -i content-security-policy` → script-src có nonce,
   không unsafe-inline (browser smoke đã ghi trong `csp_smoke.log`).
5. Production audit read-only: `scripts/prod_audit.sql` (kết quả `docs/…PROD-AUDIT`).

## F. Chờ CA (blocker còn lại)
- Verify Evidence **v1.0.2** → xác nhận 4 P0 CA-004 đóng.
- **Activation approval** Auth/session exception (điều kiện nonce CSP đã đạt; PO đã ký risk nghiệp vụ).
- Cấp **production release approval** → Dev chạy Runbook **v1.0.2** (Phương án A) dưới PO gates + maintenance window.
- *(PO đã ký 4 văn bản; cron backup đã cài + verified.)*

## Ký
```text
CA SUBMISSION INDEX v1.0.1 — response CA-REVIEW-M0-DEV-004 (4 P0 dong: runbook Phuong an A, nonce CSP,
audit endpoint staff.update+session, E9/E10 executable). 3 SHA: tested_code=8a702d6, submission_head=3b45376,
release=8a702d6/ib-m0-rc1. Production KHONG thay doi (M0 migration chua chay). Cho CA release approval.
Author role: Dev (Alpha3S). Ngay: 2026-07-25 15:07 GMT+7.
```
