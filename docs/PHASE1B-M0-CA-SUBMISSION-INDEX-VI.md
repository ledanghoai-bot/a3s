---
id: A3S-PHASE1B-M0-CA-SUBMISSION-INDEX-001
title: Alpha3S I-B M0 — Văn bản tổng hợp gửi CA (index + việc đã làm + vị trí file)
document_type: submission_index
responds_to: A3S-PHASE1B-CA-REVIEW-M0-DEV-003
owner: Alpha3S
author_role: Dev
version: 1.0.0
status: submitted_to_ca
created_at: 2026-07-25
branch: phase1b-m0
head_commit: b1a1da1b1be7bc4d3aafac202778734cbf74daa2
evidence_commit: 931943d5c1a413771fa6c6ff4c96bf890ad9389a
language: vi-VN
---

# I-B M0 — Văn bản tổng hợp gửi CA

> Bản index để CA **truy cập & kiểm tra read-only**. Liệt kê: (A) việc đã làm cycle này, (B) vị trí mọi
> file, (C) mapping CA §11, (D) commit manifest, (E) cách verify.

## 0. Truy cập
- **Repo:** `D:\alpha3s` (Windows dev). Remote `gitlab` (`gitlab.com/alpha3s-dev/alpha3s`) — **branch
  `phase1b-m0` CHƯA push** (theo yêu cầu giữ local tới khi CA duyệt). CA đọc bản local/relayed.
- **Branch:** `phase1b-m0` · **HEAD:** `b1a1da1b1be7bc4d3aafac202778734cbf74daa2`.
- **Evidence pinned SHA (code đã rehearsal):** `931943d5c1a413771fa6c6ff4c96bf890ad9389a` (git clean).
- **main** = `c210a84` (không đổi; branch chưa merge). **Production KHÔNG có code M0** (main).

## A. Việc đã làm (cycle CA-REVIEW-M0-DEV-003)
1. **4 P0 runner** (review 001) — CLOSED bởi CA; evidence E1-E6→E10.
2. **Startup readiness FAIL-CLOSED** (§6): `startup_verdict` (pure, testable) — DB/query error KHÔNG tạo
   readiness giả; half-provisioned→fail; pre-016 skip chỉ khi non-strict. Bỏ catch-all.
3. **Endpoint-level audit rollback** (§9): `staff.create` + `password_change` rollback mutation khi audit
   insert fail (force `CHECK(false)`), audit-ok path ghi `audit_log`.
4. **Versioned RBAC seed** (§5): `migration 018_rbac_seed.sql` thay chạy proposal bằng psql.
5. **Staff assignment procedure** (§5): `assign_staff_roles.py` idempotent/transactional/cardinality
   fail-closed, mapping từ file kiểm soát truy cập (không PII repo).
6. **Session TTL≤48h** + **dashboard CSP baseline** (§8) (ghi rõ hạn chế Next inline-script → nonce follow-up).
7. **Evidence Package v1.0.1** ghim SHA mới `931943d` — **E1-E10** (command+exit code+log+checksum+mapping).
8. **Runbook v1.0.1** (§5+§10): RBAC cutover unit (RBAC_STRICT bật sau cùng), immutable SHA, backup
   restore-check bắt buộc, không test-order/không throttle tài khoản thật, host alias.
9. **PO đã ký 4 văn bản** (matrix/018, staff worksheet, auth ADR localStorage, audit DB-role exception→M2).
10. **Ops:** cron `pg_dump` ngày trên VPS (PO duyệt) — deploy `/srv/pg_backup_daily.sh` + crontab
    `30 3 * * *` (+07) + retention 14; test run OK 840K. (Gap CA §4.3 đóng.)

## B. Vị trí file (repo-relative)

### Báo cáo / quyết định (`docs/`)
| File | Nội dung | Version/Status |
|---|---|---|
| `docs/PHASE1B-M0-DEV-REPORT-VI.md` | Dev report tổng M0 | v1.0.5 (single version) |
| `docs/PHASE1B-M0-EVIDENCE-PACKAGE-VI.md` | **Immutable evidence E1-E10** | **v1.0.1 @ SHA 931943d** |
| `docs/PHASE1B-PROD-AUDIT-VI.md` | M0.0 production audit + pre-release actions | v1.0.1 |
| `docs/PHASE1B-PROD-MIGRATION-RUNBOOK-VI.md` | Runbook production migration | v1.0.1 (chưa chạy) |
| `docs/PHASE1B-RBAC-STAFF-WORKSHEET-VI.md` | Gán role staff | v1.0.1 **PO approved** |
| `docs/PHASE1B-AUTH-SESSION-DECISION-RECORD-VI.md` | ADR localStorage | **PO accepted**, chờ CA kiến trúc |
| `docs/PHASE1B-AUDIT-RELEASE-GATE-VI.md` | Audit gate + DB-role exception | **PO accepted** (deadline M2) |
| `docs/PHASE1B-IMPLEMENTATION-PLAN-VI.md` | Plan M0-M6 | v0.1.3 |
| `docs/PHASE1B-FEASIBILITY-REPORT-VI/-EN.md`, `...-DEV-RESPONSE-VI.md` | Feasibility | v0.1.1 |
| `docs/PHASE1B-M0-STATUS-REPORT-VI.md` | Snapshot tổng hợp | v1.0.0 |

### Code / scripts / migrations (đối tượng kiểm tra chính)
| File | Vai trò |
|---|---|
| `scripts/migrate.py` | Runner (baseline threshold, manifest verify, validation wiring, advisory lock) |
| `scripts/baseline_manifest.json` / `baseline_manifest_13.json` | Manifest (prod = manifest-13) |
| `migrations/014_correct_product_seed.sql` | Corrective 014 (DO-block pre/postcondition) |
| `migrations/015_audit_log.sql` / `016_rbac.sql` / `017_auth_hardening.sql` / `018_rbac_seed.sql` | M0 migrations |
| `app/services/audit_service.py` | Audit fail-closed + redaction đệ quy (secret/PII/nested) |
| `app/services/permission_service.py` | RBAC no-cache + `rbac_ready` + `startup_verdict` |
| `app/api/auth.py` | `require_permission` (strict mode) |
| `app/main.py` | Lifespan startup readiness (fail-closed) |
| `app/security/{headers,throttle}.py` | Security headers + login throttling |
| `scripts/m0_foundation_validation.py` | E3 (audit/permission/redaction) |
| `scripts/app_integration_validation.py` | E2 (search_products no serving_info) |
| `scripts/audit_rollback_endpoint_test.py` | E7 (endpoint audit rollback) |
| `scripts/startup_readiness_test.py` | E8 (startup_verdict 8 cases) |
| `scripts/fresh_db_seed_validation.sql` | Post-migration seed assertions |
| `scripts/assign_staff_roles.py` | Gán role fail-closed |
| `scripts/rbac_seed_proposed.sql` | Đề xuất matrix (→ migration 018) |
| `scripts/prod_audit.sql` | Production audit read-only |
| `scripts/pg_backup_daily.sh` | Cron backup (canonical; bản VPS ở `/srv/pg_backup_daily.sh`) |

## C. Mapping CA §11 (review 003) → vị trí
| # | Yêu cầu | Vị trí / trạng thái |
|---|---|---|
| 1 | Evidence Package v1.0.1 pinned SHA mới | `docs/…EVIDENCE-PACKAGE` v1.0.1 @ `931943d` |
| 2 | Runbook v1.0.1 | `docs/…RUNBOOK` v1.0.1 |
| 3 | Fix startup readiness fail-closed | `permission_service.startup_verdict` + `main.py`; test `startup_readiness_test.py` (E8) |
| 4 | Versioned RBAC seed | `migrations/018_rbac_seed.sql` |
| 5 | Staff assignment procedure | `scripts/assign_staff_roles.py` |
| 6 | Endpoint audit rollback tests | `scripts/audit_rollback_endpoint_test.py` (E7) |
| 7 | CSP + TTL≤48h | `dashboard/next.config.mjs` + `config.session_ttl_hours=48`; ADR ghi hạn chế nonce |
| 8 | Audit exception deadline M2 + PO | `docs/…AUDIT-RELEASE-GATE` (PO ký, M2) |
| 9 | PO-completed RBAC worksheet | `docs/…RBAC-STAFF-WORKSHEET` v1.0.1 (PO ký; mapping ở controlled file) |

## D. Commit manifest (branch `phase1b-m0`, chưa push)
```text
b1a1da1  PO sign-off 4 van ban + cron pg_dump (HEAD)
8f5315b  docs CA-003: Evidence v1.0.1 + runbook v1.0.1 + gate updates
931943d  code CA-003: startup readiness fail-closed + TTL/CSP + 018 + assign + endpoint/verdict tests  <-- EVIDENCE SHA
02abe1e  code CA-002: strict-RBAC + startup readiness + redaction
edb9d84  docs CA-002: evidence v1.0.0 + report v1.0.5
5553a1f  M0.0 production audit    | 2f53e05 prod LLM fix    | 128de40 runbook draft
6f9ed88 / e0ab09a / ef04d61 / d1bc484 / f1ac797 / db94d2c / 29ce7a4  (M0 scaffold + pool + M0.3/4/5 + fixes)
main = c210a84 (khong doi)
```

## E. Cách CA verify (read-only)
1. `git checkout 931943d5c1a413771fa6c6ff4c96bf890ad9389a` → `git status` = clean → **code = code đã test**.
2. Đối chiếu checksum artifact (Evidence §1) + đọc E1-E10 (command + exit code + assertion mapping).
3. (Tùy chọn) chạy lại rehearsal theo lệnh trong Evidence §2 (container tạm, không đụng prod).
4. Raw log rehearsal: scratchpad phiên Dev (access-controlled, không commit) — cung cấp khi CA yêu cầu.
5. Production audit read-only: `scripts/prod_audit.sql` (đã chạy, kết quả `docs/…PROD-AUDIT`).

## F. Chờ CA (blocker duy nhất còn lại)
- Verify Evidence v1.0.1 → chuyển 4 P0 runner sang `CA verified closed` (đã CLOSED) + **đóng release gate**.
- **Phê duyệt kiến trúc** Auth/session ADR (PO đã ký risk nghiệp vụ).
- Cấp **production release approval** → Dev chạy runbook v1.0.1.
- *(Không còn mục chờ PO hay ops — 4 văn bản PO đã ký, cron đã cài.)*

## Ký
```text
CA SUBMISSION INDEX — tong hop response CA-REVIEW-M0-DEV-003 + PO sign-off + ops cron.
Branch phase1b-m0, HEAD b1a1da1, evidence SHA 931943d (git clean). Production KHONG thay doi (M0 migration
chua chay). Cho CA release approval. Author role: Dev (Alpha3S). Ngay: 2026-07-25.
```
