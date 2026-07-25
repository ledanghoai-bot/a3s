---
id: A3S-PHASE1B-M0-DEV-RESPONSE-004
title: Alpha3S I-B M0 — Dev Response gửi CA (đóng 4 P0 CA-REVIEW-M0-DEV-004)
document_type: dev_response
responds_to: A3S-PHASE1B-CA-REVIEW-M0-DEV-004 v1.0.0
owner: Alpha3S
author_role: Dev
version: 1.0.0
status: submitted_to_ca
created_at: 2026-07-25 15:07 GMT+7
branch: phase1b-m0
tested_code_sha: 8a702d616eab54d5def9292a40593ff1b1540b04
submission_head: 3b45376523c05334da52429b269131315c65f568
proposed_release_sha: 8a702d616eab54d5def9292a40593ff1b1540b04
proposed_release_tag: ib-m0-rc1
language: vi-VN
---

# Dev Response — CA-REVIEW-M0-DEV-004 (đóng 4 P0 cuối)

## 1. Kết luận (Dev đề nghị)

```text
CA-004 §4  Runbook RBAC_STRICT=false claim sai .............. ĐÃ SỬA (Runbook v1.0.2, Phương án A)
CA-004 §5  localStorage exception / CSP unsafe-inline ....... ĐÃ SỬA (nonce CSP + browser/header smoke)
CA-004 §6  Audit endpoint rollback chưa đủ ................. ĐÃ SỬA (E7 + staff.update + session revocation)
CA-004 §7  E9/E10 chưa executable ......................... ĐÃ SỬA (E9/E10 exit code 0)
CA-004 §8  Controlled-file operational checks ............. ĐÃ THÊM (Runbook §8 — operator thực thi lúc cutover)
CA-004 §9  Runbook amendments (tag/maintenance/rollback/CSP/backup/ledger) ... ĐÃ THÊM
CA-004 §2  Phân biệt 3 SHA .............................. ĐÃ LÀM (tested_code / submission_head / release)
Evidence Package v1.0.2 @ release-candidate SHA .......... ĐÃ GHIM (8a702d6, log manifest sha256)
```

**Đề nghị CA:** verify Evidence Package v1.0.2 (SHA `8a702d6`) → xác nhận 4 P0 CA-004 đóng → **đóng release
gate** + cấp **activation approval** cho auth/session exception (điều kiện nonce CSP đã đạt) + cấp
**production release approval**. Production **CHƯA thay đổi** — M0 migration chỉ chạy sau approval + PO gates
+ maintenance window (Runbook v1.0.2 §0).

**Ba SHA (CA §2):** `tested_code_sha = 8a702d6` (code+test git clean) · `submission_head = 3b45376` (artifact
tài liệu v1.0.2) · `proposed release = 8a702d6` / tag `ib-m0-rc1`. **Không** dùng `931943d` (evidence v1.0.1
cũ) làm release SHA.

---

## 2. §4 — Runbook hiểu sai `RBAC_STRICT=false` (P0)

**Dev xác nhận phân tích của CA đúng.** Code thực tế: `rbac_provisioned()` trả `true` ngay khi 016 tạo
table/column; staff chưa gán role có `permissions = ∅`; `require_permission()` chỉ degrade khi
`rbac_provisioned=false`. ⇒ **Sau 016, staff chưa role bị 403 bất kể `RBAC_STRICT`.** Vì vậy 2 tuyên bố cũ
trong runbook v1.0.1 là SAI và đã bị **gỡ bỏ hoàn toàn**.

**Đã chọn Phương án A (maintenance/quiesce cutover — CA ưu tiên).** Runbook **v1.0.2**:
- **§2A MAINTENANCE ON (trước 016):** stop container `dashboard` chặn staff UI; thông báo 2 staff không
  đăng nhập; customer channel (Messenger webhook + telegram_customer_bot) giữ chạy (không đụng staff RBAC path).
- **§3 migrate 014-018** trong maintenance.
- **§3A gán role** (`assign_staff_roles.py`, fail-closed) + verify mọi active staff có role + ≥1 active admin
  → **chỉ khi đó** `RBAC_STRICT=true` → recreate → startup readiness pass → permission smoke.
- **§3B MAINTENANCE OFF:** mở staff traffic (start dashboard) **chỉ sau khi §3A pass**.
- **Exact rollback khi assignment fail (§3A.6, §5):** GIỮ maintenance; **(a)** sửa mapping + chạy lại
  assignment (idempotent), hoặc **(b) ABORT:** redeploy code cũ `c210a84` (RBAC-unaware, không truy vấn
  `role_permissions`) → staff đăng nhập lại trên schema đã expand (expand-only, DB giữ nguyên). **KHÔNG**
  dùng `RBAC_STRICT=false` làm recovery.

Bằng chứng behavior: **E9** chứng minh `unprovisioned + strict → 403` (no-degrade sau cutover); **E10**
chứng minh half-provisioned → `rbac_ready=False` → startup fail-closed (không boot trạng thái nửa vời).

---

## 3. §5 — Auth/session exception & CSP `unsafe-inline` (P0)

Dev chọn **phương án (1)** CA nêu: nonce-based CSP loại `unsafe-inline`.

- **`dashboard/middleware.js`** (Next 14 App Router): `Content-Security-Policy` với
  `script-src 'self' 'nonce-<random>' 'strict-dynamic'` — **đã bỏ `'unsafe-inline'` cho `script-src`**.
  `next.config.mjs` bỏ header CSP tĩnh (middleware sở hữu CSP, tránh 2 nguồn xung đột).
- **Threat model đóng:** inline-script do XSS chèn **không có nonce → không chạy → không đọc/exfil token**
  trong `localStorage`.
- **Verify production-ready (Evidence E-CSP):**
  - Header: `script-src` có `nonce-…` + `strict-dynamic`, **không** `unsafe-inline`; đủ `object-src 'none'`,
    `frame-ancestors 'none'`, `base-uri 'self'`.
  - **Nonce đổi mỗi request** (2 request → 2 nonce khác nhau).
  - **Browser smoke** (in-app browser, `http://localhost:3000/`): dashboard render + hydrate đầy đủ (nav
    Hội thoại/Đơn hàng/Sản phẩm/FAQ/Metrics/Nhân viên), **0 CSP violation, 0 console error** → chứng minh
    Next script nhận nonce, hoạt động **không cần** unsafe-inline.
- `style-src` giữ `'unsafe-inline'` (inline style không execute → không exfil token; style-nonce là follow-up
  UX, không thuộc gate).

**ADR → v1.0.1:** ghi điều kiện kích hoạt exception (nonce CSP) **đã đạt**; PO risk-acceptance vẫn giữ; TTL
48h không đổi; deadline HttpOnly cookie+CSRF trước M6 không đổi. **Chờ CA activation approval** (Dev không tự
coi đã mở).

---

## 4. §6 — Audit endpoint rollback (P0)

`scripts/audit_rollback_endpoint_test.py` (**E7**) mở rộng, force audit fail bằng
`ALTER TABLE audit_log ADD CONSTRAINT _forcefail CHECK(false) NOT VALID` (chặn INSERT mới, bảng vẫn tồn tại
→ code không skip audit → chứng minh fail-closed thật). Bao phủ:

| Nhánh | Kỳ vọng khi audit insert fail | Kết quả |
|---|---|---|
| `staff.create` | không tạo staff (rollback) | PASS |
| `password_change` | mật khẩu **không** đổi + **session revocation rollback** (session cũ còn) | PASS |
| **`staff.update` (deactivate)** | `is_active` **không** đổi | PASS |
| **`staff.update` (role change)** | `role_key` **không** đổi | PASS |
| audit-ok path | mutation thành công **+ ghi `audit_log`** | PASS |

Đáp ứng CA §6 (thêm `staff.update` activate/deactivate/role + session revocation path). Single-role audit
exception vẫn trong điều kiện CA chấp nhận (không có audit UPDATE/DELETE endpoint; test pass).

---

## 5. §7 — E9/E10 executable + Evidence Package v1.0.2 (P0)

- **E9** `scripts/rbac_strict_test.py` (không cần DB): `unprovisioned+strict → 403`; `có quyền → pass`;
  `thiếu quyền → 403`. **exit 0**.
- **E10** `scripts/rbac_half_provisioned_test.py` (DB 016 provisioned, `role_permissions` rỗng):
  `rbac_provisioned=True` nhưng `rbac_ready=False` → readiness fail-closed. **exit 0**.
- **Evidence Package v1.0.2** ghim `8a702d6`: bảng E1-E10 + E-CSP với **exit code thật + assertion**;
  **immutable log manifest** (sha256 từng log + checksum của manifest, CA §7); bảng checksum code chứng minh
  engine `migrate.py/014/permission_service/main.py` **byte-identical** v1.0.1, `018` chỉ đổi comment.

### Rehearsal đầy đủ tại `8a702d6` (throwaway `m0reh-pg`, đã xóa — không đụng dev/prod)

| E1 | E3 | E4 | E5 | E6 | E7 | E8 | E9 | E10 | E-CSP |
|---|---|---|---|---|---|---|---|---|---|
| up 001-018 · **0** | foundation · **0** | baseline-12→up · **0/0** | negative variant · **1** (014 không ghi) | manifest-13→up · **0/0** | audit endpoint · **0** | startup verdict · **0** | strict RBAC · **0** | half-provisioned · **0** | header+browser · **0 violation** |

---

## 6. §8 — Controlled mapping file (operational checks)

Runbook **§8** (operator thực thi tại cutover, không đưa nội dung mapping vào repo/CA doc):
- File tồn tại trên target (`test -f`); permission hạn chế (`chmod 600` + verify `stat`).
- Dry-run/validation `assign_staff_roles.py` **không in username/PII** ra report phát hành rộng (chỉ count/verdict).
- Ghi `sha256sum` mapping file vào **evidence access-controlled**.
- **Xóa/archive** file theo retention sau cutover.
- **§7 Cutover ledger:** điền executor / observer / go-no-go owner / evidence location / backup file /
  mapping sha256 / maintenance_on-off **trước khi bắt đầu**.

---

## 7. §9 — Runbook amendments (đã đưa vào v1.0.2)

| CA §9 | Đã làm |
|---|---|
| 1. Release tag/SHA cuối, không mặc định `931943d` | §0 dùng `8a702d6` / tag `ib-m0-rc1`; §2 deploy đúng SHA |
| 2. Maintenance mode/quiesce staff traffic | §2A MAINTENANCE ON (stop dashboard) + §3B OFF |
| 3. Exact rollback khi assignment fail | §3A.6 + bảng §5 (giữ maintenance + sửa/redeploy code cũ) |
| 4. CSP verification pre + post release | §1.4 (pre) + §4 (post: header + browser console) |
| 5. Cron backup verify + backup riêng trước cutover | §0.1 (crontab/log/timestamp) + §1.1 (backup mới + restore-check) |
| 6. Executor/observer/go-no-go/evidence trước khi bắt đầu | §7 cutover ledger |

---

## 8. Artifact gửi kèm (CA §10)

| Artifact | Version | Vị trí |
|---|---|---|
| Evidence Package | **v1.0.2** @ `8a702d6` | `docs/PHASE1B-M0-EVIDENCE-PACKAGE-VI.md` |
| Production Migration Runbook | **v1.0.2** | `docs/PHASE1B-PROD-MIGRATION-RUNBOOK-VI.md` |
| Auth/Session ADR | **v1.0.1** | `docs/PHASE1B-AUTH-SESSION-DECISION-RECORD-VI.md` |
| Submission Index | **v1.0.1** | `docs/PHASE1B-M0-CA-SUBMISSION-INDEX-VI.md` |
| CSP nonce middleware | mới | `dashboard/middleware.js` (+ `next.config.mjs`) |
| Audit endpoint test (mở rộng) | E7 | `scripts/audit_rollback_endpoint_test.py` |
| Strict-RBAC / half-provisioned test | E9 / E10 | `scripts/rbac_strict_test.py` · `scripts/rbac_half_provisioned_test.py` |

Sign-off lịch sử đã được CA chấp nhận (startup readiness, 018 versioned seed, backup cron, PO 4 văn bản)
**không gửi lại** — dẫn chiếu Submission Index v1.0.1 §A/§C.

---

## 9. Xác nhận ràng buộc

- Production **KHÔNG thay đổi**; main = `c210a84` (không có code M0). Branch `phase1b-m0` chưa push/merge.
- Rehearsal chạy container throwaway `m0reh-pg` (đã xóa, 0 sót); guard branch trước+sau; không PII/secret
  production trong evidence.
- Vòng này là **remediation kỹ thuật của Dev — không phát sinh chữ ký PO mới**; 4 văn bản chính sách PO đã
  ký (vòng CA-003) giữ hiệu lực.

## Ký
```text
DEV RESPONSE — CA-REVIEW-M0-DEV-004: 4 P0 dong (runbook Phuong an A + bo claim RBAC_STRICT=false sai;
nonce CSP bo unsafe-inline + browser/header smoke; audit endpoint staff.update+session revocation; E9/E10
executable exit 0) + §8 controlled-file + §9 runbook amendments + §2 phan biet 3 SHA.
Release-candidate SHA 8a702d6 (tag ib-m0-rc1), Evidence v1.0.2 + log manifest sha256. Production CHUA chay.
De nghi CA verify Evidence v1.0.2 -> dong release gate + activation approval + production release approval.
Author role: Dev (Alpha3S). Ngay: 2026-07-25 15:07 GMT+7.
```
