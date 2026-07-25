---
id: A3S-PHASE1B-M0-EVIDENCE-PACKAGE-001
title: Alpha3S I-B M0 — Immutable Evidence Package (rehearsal pinned SHA)
document_type: evidence_package
parent: A3S-PHASE1B-M0-DEV-REPORT-001
owner: Alpha3S
author_role: Dev
version: 1.0.1
status: submitted_to_ca
branch: phase1b-m0
commit_sha: 931943d5c1a413771fa6c6ff4c96bf890ad9389a
supersedes: "v1.0.0 (SHA 29ce7a4 — không cover batch strict-RBAC/readiness/redaction)"
language: vi-VN
---

# M0 — Immutable Evidence Package v1.0.1 (CA-REVIEW-M0-DEV-003 §4)

> **Ghim đúng HEAD MỚI** sau khi sửa blocker CA-REVIEW-M0-DEV-003 (startup readiness fail-closed, TTL,
> CSP, migration 018, endpoint audit tests). Bản v1.0.0 ghim `29ce7a4` (trước batch gate) đã bị thay thế.
> Rehearsal chạy container tạm (đã xóa, 0 sót), guard branch `phase1b-m0` trước+sau. Không PII/secret
> production; credential trong lệnh là DB throwaway local.

## 1. Revision (§4.1-4.2, §4.7)
- **Branch:** `phase1b-m0` · **Full SHA:** `931943d5c1a413771fa6c6ff4c96bf890ad9389a`
- **Git status tại revision test:** *clean* (0 uncommitted) → **code đã test = code tại SHA**.
- **Checksum (sha256[:16]):** `migrate.py`=`8ba02897b0eccea3` · `014_correct_product_seed.sql`=`87dc259b2cda15a4`
  · `018_rbac_seed.sql`=`3461c6500c8658a0` · `permission_service.py`=`b68ab531fb171b6e` · `main.py`=`2e52bb1de722d515`.

## 2. Kịch bản E1-E10 (§4.3-4.6)

| # | Kịch bản | Lệnh (rút gọn) | Exit | Kết quả (log) |
|---|---|---|---|---|
| **E1** | Fresh up 001-018 + validation | `migrate.py up` | **0** | `Post-migration validations pass (1 file)` |
| **E4** | Existing baseline-12 + up | `baseline` → `up` | **0/0** | `KHONG baseline (phai chay): 013,014,015,016,017,018`; up validations pass |
| **E5** | Negative (unknown-bad variant) | inject → `up` | **1** | `014 postcondition FAIL: … "100% Robusta" (unknown-bad variant)`; migration không ghi |
| **E6** | Manifest-13 positive (mô phỏng prod) | `baseline --manifest _13` → `up` | **0/0** | `Baselined 13 … KHONG baseline (phai chay): 014,015,016,017,018`; up validations pass |
| **E3** | Foundation (M0.3/4 + redaction nested) | `m0_foundation_validation.py` | **0** | `admin⊇staff.manage; sales KHONG staff.manage/inventory.adjust; audit fail-closed rollback OK; redaction secret+PII nested OK; rbac_ready OK` |
| **E7** | **Endpoint audit rollback** (§9) | `audit_rollback_endpoint_test.py` | **0** | `staff.create + password_change ROLLBACK mutation khi audit insert fail; audit-ok path ghi audit_log` |
| **E8** | **Startup readiness** verdict (§6) | `startup_readiness_test.py` | **0** | `STARTUP_VERDICT PASS (8 cases): error+strict->FAIL (no false readiness); half-provisioned->FAIL; pre-016 skip chỉ khi non-strict` |
| **E9** | **Strict RBAC** positive+negative | require_permission (rbac_strict=True) | — | unprovisioned+strict → **403**; có quyền → pass; thiếu quyền → **403** |
| **E10** | **Half-provisioned** (001-016, no 018) | `rbac_ready(conn)` | — | `(False, "role_permissions mapping RỖNG (half-provisioned)")` |
| **Boot** | Dev api reload (schema 012, strict off) | lifespan startup | — | `[startup] readiness: pre-016 (chưa provisioned), strict off — skip hợp lệ` + health 200 |

Log đầy đủ: `scratchpad/e{1,3,4b,4u,5,6b,6u,7,8}.log` (access-controlled, không commit).

## 3. Mapping assertion → test (§4, §6, §9)
| Assertion | Test | Evidence |
|---|---|---|
| P0 baseline threshold + never_baseline (013-018 skip) | E4, E6 | skip list gồm 014-018; corrective luôn chạy |
| P0 corrective executable pre/postcondition fail-closed | E5 | postcondition FAIL → migration không ghi |
| P0 validation nối `up`, fail→exit≠0 | E1/E4/E6 (0), E5 (1) | |
| **§6 startup readiness fail-closed** — DB/query error KHÔNG tạo readiness giả | **E8** | error+strict→FAIL; error+non-strict→tolerate (chỉ dev); half-provisioned→FAIL |
| §6 half-provisioned detect | E10, E8 | `rbac_ready`=False khi 016 mà chưa seed |
| §7 strict RBAC no-degrade sau cutover | E9 | unprovisioned+strict→403 |
| **§9 endpoint audit rollback** | **E7** | staff.create + password_change rollback khi audit insert fail (force CHECK(false)) |
| §8 redaction credential+PII+nested | E3 | phone/email/address/token/sdt redact mọi cấp; field thường giữ |
| §4.1 manifest-13 cho production | E6 | verify data_deletion → baseline 001-013, up 014-018 |

## 4. Ghi chú
- Evidence cho **development rehearsal**; production baseline/migration/RBAC vẫn NOT APPROVED.
- `migration 018_rbac_seed` = versioned seed (thay psql trực tiếp — CA §5); nội dung = đề xuất chờ PO duyệt.

## Ký
```text
EVIDENCE PACKAGE v1.0.1 — commit SHA 931943d5c1a413771fa6c6ff4c96bf890ad9389a (branch phase1b-m0, git clean).
E1-E10 PASS pinned SHA (cover startup readiness fail-closed + endpoint audit rollback + strict RBAC +
redaction nested — cac blocker CA-REVIEW-M0-DEV-003). Log access-controlled, container tam da xoa.
Author role: Dev (Alpha3S). Ngay: 2026-07-25 (GMT+7).
```
