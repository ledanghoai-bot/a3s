---
id: A3S-PHASE1B-M0-EVIDENCE-PACKAGE-001
title: Alpha3S I-B M0 — Immutable Evidence Package (rehearsal pinned SHA)
document_type: evidence_package
parent: A3S-PHASE1B-M0-DEV-REPORT-001
owner: Alpha3S
author_role: Dev
version: 1.0.2
status: submitted_to_ca
branch: phase1b-m0
commit_sha: 8a702d616eab54d5def9292a40593ff1b1540b04
supersedes: "v1.0.1 (SHA 931943d — E9/E10 exit code '—', thiếu CSP smoke + audit endpoint update/session)"
language: vi-VN
---

# M0 — Immutable Evidence Package v1.0.2 (CA-REVIEW-M0-DEV-004 §7, §10)

> **Ghim đúng release-candidate SHA mới** `8a702d6…` sau khi đóng P0 CA-REVIEW-M0-DEV-004: E9/E10 thành
> **test command thực thi có exit code**; audit endpoint rollback bổ sung **staff.update(deactivate/role) +
> session revocation**; **nonce-based CSP** (bỏ `unsafe-inline` script-src) có header + browser smoke.
> Rehearsal chạy container tạm (đã xóa, 0 sót); guard branch `phase1b-m0` trước+sau; không PII/secret
> production — credential trong lệnh là DB throwaway local (`m0reh-pg`).

## 1. Revision (§4.1-4.2, §4.7)
- **Branch:** `phase1b-m0` · **Full SHA:** `8a702d616eab54d5def9292a40593ff1b1540b04` · đề xuất tag `ib-m0-rc1`.
- **Git status tại revision test:** *clean* (code+tests đã commit tại SHA trên; báo cáo/evidence commit sau).
- **Phân biệt SHA (CA §2):** `tested_code_sha = submission_head = proposed_release_sha = 8a702d6…`.
  KHÔNG dùng `931943d…` (evidence v1.0.1) làm release SHA.
- **Checksum code (sha256[:16]) @ 8a702d6:**

  | File | sha256[:16] | So với v1.0.1 |
  |---|---|---|
  | `scripts/migrate.py` | `8ba02897b0eccea3` | **identical** (engine không đổi) |
  | `migrations/014_correct_product_seed.sql` | `87dc259b2cda15a4` | **identical** |
  | `app/services/permission_service.py` | `b68ab531fb171b6e` | **identical** |
  | `app/main.py` | `2e52bb1de722d515` | **identical** |
  | `migrations/018_rbac_seed.sql` | `2ccbaa64d110c84f` | đổi **comment/sign-off** (CA §2 xác nhận; SQL exec không đổi — E1/E4/E6 áp 018 pass) |
  | `dashboard/middleware.js` | `d77813a945753736` | **mới** (nonce CSP) |
  | `dashboard/next.config.mjs` | `61e2429ef681171b` | bỏ CSP tĩnh |
  | `scripts/rbac_strict_test.py` | `37b174675ca0b900` | **mới** (E9 executable) |
  | `scripts/rbac_half_provisioned_test.py` | `f786af6cc145ccc1` | **mới** (E10 executable) |
  | `scripts/audit_rollback_endpoint_test.py` | `e907a5844d2198fb` | mở rộng (E7) |

  > Engine migration + corrective 014 + permission_service + startup = **byte-identical** với SHA đã test ở
  > v1.0.1 → E4/E5/E6 (chỉ chạm các file này + manifest) **không hồi quy**; vẫn re-run đầy đủ dưới đây tại SHA mới.

## 2. Kịch bản E1-E10 + CSP (§4.3-4.6, §7) — re-run tại `8a702d6`

| # | Kịch bản | Lệnh (rút gọn) | Exit | Kết quả (log) |
|---|---|---|---|---|
| **E1** | Fresh up 001-018 + validation | `migrate.py up` | **0** | `Applied 18 migration(s)`; `Post-migration validations pass (1 file)` |
| **E3** | Foundation M0.3/4 + redaction nested | `m0_foundation_validation.py` | **0** | `RBAC provisioned; admin⊇staff.manage; sales KHONG staff.manage/inventory.adjust; audit fail-closed rollback OK; redaction secret+PII nested OK; rbac_ready OK` |
| **E4** | Existing baseline-12 → up 013-018 | `baseline` → `up` | **0/0** | `Baselined 12 … KHONG baseline (phai chay): 013,014,015,016,017,018`; `Applied 6`; validations pass |
| **E5** | Negative — unknown-bad "100% Robusta" variant | inject variant → `up` | **1** | `RaiseError: 014 postcondition FAIL … van chua "100% Robusta" (unknown-bad variant?)`; `schema_migrations 014 = 0 row` (rollback) |
| **E6** | Manifest-13 (prod sim) → up 014-018 | `baseline --manifest _13` → `up` | **0/0** | `Baselined 13 … KHONG baseline (phai chay): 014,015,016,017,018`; `Applied 5`; validations pass |
| **E7** | **Endpoint audit rollback (mở rộng §6)** | `audit_rollback_endpoint_test.py` | **0** | `staff.create + password_change(+session revocation) + staff.update(deactivate) + staff.update(role) ROLLBACK khi audit insert fail; audit-ok ghi audit_log` |
| **E8** | Startup readiness verdict (pure, 8 cases) | `startup_readiness_test.py` | **0** | `STARTUP_VERDICT PASS (8 cases): error+strict->FAIL (no false readiness); half-provisioned->FAIL; pre-016 skip chỉ khi non-strict` |
| **E9** | **Strict RBAC pos+neg (EXECUTABLE)** | `rbac_strict_test.py` | **0** | `RBAC-STRICT PASS: unprovisioned+strict->403; có quyền->pass; thiếu quyền->403` |
| **E10** | **Half-provisioned (EXECUTABLE)** | `rbac_half_provisioned_test.py` (DB 016, truncate role_permissions) | **0** | `HALF-PROVISIONED PASS: provisioned=True nhưng rbac_ready=False (role_permissions mapping RỖNG) -> readiness fail-closed` |
| **E-CSP** | **Nonce CSP header + browser smoke (§5)** | header assert + in-app browser | **0** | header `script-src 'self' 'nonce-…' 'strict-dynamic'`, **không** unsafe-inline; nonce **đổi mỗi request**; browser render+hydrate OK, **0 CSP violation / 0 console error** |
| **Boot** | Dev api reload (schema 012, strict off) | lifespan startup | — | `[startup] RBAC chưa provision (dev/pre-016) — readiness bỏ qua` + health 200 |

> **v1.0.2 vá gap CA §7:** E9 và E10 nay là **command thực thi có exit code (0)** — không còn `—`. E10 tạo
> trạng thái half-provisioned bằng cách áp 001-018 rồi `TRUNCATE role_permissions` (016 provisioned nhưng
> mapping rỗng), đúng ngữ nghĩa half-provisioned.

Log đầy đủ: `scratchpad/e{1,3,4b,4u,5,6b,6u,7,8,9,10}.log` + `csp_smoke.log` (access-controlled, không commit).

## 3. Immutable log manifest (CA §7 — evidence không đổi sau sign-off)
`EVIDENCE-LOG-MANIFEST-v1.0.2.sha256` (access-controlled) — sha256 từng log:
```text
89d3fa7a3ccf1e6df8dcd3aa7829573960c03d2161bbac9e798ee4b55090225d  e1.log
e84af3201d17044bdef7a016a4ff4cd4e53446ab1bf009ab392c93b222d298ee  e3.log
c4ea77111fe57df763cf46d8893fadaa04f7171efe1f74d53c03fc0eb575815b  e4b.log
5d2688ec048d81d972701e59d8ae3b60803ca85959417d957ee2f1303d0c1ff0  e4u.log
25f270647d275c2b091e7d25d1dc019859708370028ca2bf999111313e0fc3ff  e5.log
4de4aab51521cd6789d39caa2814e4d729b47729a839fd4fac5f5849a9c8f76e  e6b.log
0e01229bb7d0d2484c34336a4a304761706066a78f802cc64010d1fb7ad711ae  e6u.log
a007f9c18b9b85d951250fd05336eebafab6fa370c6f00537ea5e79f87d54e36  e7.log
8092aa10b4615309ae966e42f89ae666d8e8185e0048d98adf0e2a9d094aaf66  e8.log
7b0cd4b1f849b0a6ac62aa9bf6183ed13ad7d035811292981aceb6d3719ba19b  e9.log
9cb6f4d228810c3528a703ee27f5ab4c0aeb25ebdf35b53ab50b27b2fc132d74  e10.log
016fe55a70536060cf9ed3779201c7f1afec6674a26c436e5ecbe13c4e5e0277  csp_smoke.log
```
Checksum của chính manifest (sha256): `15686bd228349954906e713de5fa7b5683efd81a1518516b94fc0502c22d23ba`.

## 4. Mapping assertion → test (§4, §6, §7, §9)
| Assertion | Test | Evidence |
|---|---|---|
| P0 baseline threshold + never_baseline (013-018 skip) | E4, E6 | skip list gồm 014-018; corrective luôn chạy |
| P0 corrective executable pre/postcondition fail-closed | E5 | postcondition FAIL → 014 không ghi (rollback) |
| P0 validation nối `up`, fail→exit≠0 | E1/E4/E6 (0), E5 (1) | |
| §6 startup readiness fail-closed | E8 | error+strict→FAIL; half-provisioned→FAIL |
| §6 half-provisioned detect **(executable)** | **E10**, E8 | `rbac_ready`=False khi 016 mà mapping rỗng, exit 0 |
| §7 strict RBAC no-degrade sau cutover **(executable)** | **E9** | unprovisioned+strict→403, exit 0 |
| **§6 endpoint audit rollback — staff.update + session revocation** | **E7** | staff.create + password_change(+session revoke) + staff.update(deactivate) + staff.update(role) rollback khi audit fail |
| **§5 nonce CSP loại unsafe-inline + browser smoke** | **E-CSP** | header no-unsafe-inline script-src + nonce/request + 0 violation |
| §8 redaction credential+PII+nested | E3 | phone/email/address/token/sdt redact mọi cấp |
| §4.1 manifest-13 cho production | E6 | verify data_deletion → baseline 001-013, up 014-018 |

## 5. Ghi chú
- Evidence cho **development rehearsal**; production baseline/migration/RBAC/CSP-activation vẫn **NOT APPROVED**
  — chờ CA release approval + PO gates (Runbook v1.0.2 §0).
- `migration 018_rbac_seed` = versioned seed (thay psql trực tiếp — CA §5); nội dung mapping thật = controlled
  file (Runbook §8), KHÔNG trong repo.
- E7 force audit fail bằng `ALTER TABLE audit_log ADD CONSTRAINT _forcefail CHECK(false) NOT VALID` (chặn INSERT
  mới, `audit_log` vẫn tồn tại → code không skip audit → chứng minh fail-closed rollback thật).

## Ký
```text
EVIDENCE PACKAGE v1.0.2 — release-candidate SHA 8a702d616eab54d5def9292a40593ff1b1540b04 (branch phase1b-m0).
E1-E10 + E-CSP PASS pinned SHA (E9/E10 executable co exit code; E7 mo rong staff.update+session revocation;
nonce CSP bo unsafe-inline + browser/header smoke). Log manifest sha256 ghim immutable. Engine migrate/014/
permission_service/main.py byte-identical v1.0.1. Container tam da xoa; khong PII/secret production.
Author role: Dev (Alpha3S). Ngay: 2026-07-25 15:07 GMT+7.
```
