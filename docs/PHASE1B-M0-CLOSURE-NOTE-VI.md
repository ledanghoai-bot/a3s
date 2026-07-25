---
id: A3S-PHASE1B-M0-CLOSURE-NOTE-001
title: Alpha3S I-B M0 — Operational Closure Note
document_type: operational_closure_note
responds_to: A3S-PHASE1B-CA-REVIEW-M0-CUTOVER-001
owner: Alpha3S
author_role: Dev
version: 1.0.0
status: m0_operational_closure_submitted
production_sha: 3845f446a0297262f5bef093db337688eefc3986
production_tag: ib-m0-rc6
created_at: 2026-07-25 16:55 GMT+7
language: vi-VN
---

# M0 — Operational Closure Note (CA-REVIEW-M0-CUTOVER §5)

> Ghi chú đóng vận hành **ngắn** — KHÔNG phải submission/review cycle mới (đúng CA §5.3). Đóng 3 việc §5.
> Không PII/credential (staff theo `staff_id` + role).

## 1. Trạng thái production cuối
- **SHA:** `3845f446a0297262f5bef093db337688eefc3986` · branch **`main`** · tag **`ib-m0-rc6`**.
- **Health:** `200`. **Readiness:** `RBAC ready (permissions=21, mappings=35)`. **`RBAC_STRICT=true`.**
- **Dashboard:** HTTP 200, nonce CSP (`script-src 'self' 'nonce-…' 'strict-dynamic'`, no unsafe-inline), login render OK.
- **DB:** `schema_migrations=18`, anomaly 3S-100G đã sửa (robusta=0), 2 active staff = admin.

## 2. §5.1 — Authenticated admin + audit smoke ✅
- PO đăng nhập dashboard bằng tài khoản admin (`staff_id=2`) — **login thành công**.
- Thao tác gated: **sửa bậc giá** (thêm 1 bậc) — **mutation thành công** (quyền admin hoạt động).
- `audit_log` row (id=3): `action=product.price_tiers.replace` · `actor_type=staff` · `actor_staff_id=2` (role admin) ·
  `entity_type=product` · `entity_id=1` · `before`/`after` = danh sách bậc giá (cũ→mới).
- **Redaction:** spot-check 0 row chứa key nhạy cảm raw (password/token/secret/phone/email/address).
- Unauthenticated `401` (đã kiểm ở cutover) KHÔNG dùng thay — đây là authenticated permission + audit thật.

## 3. §5.2 — Telegram dual-poller ✅
- Đã dừng container bot development (`alpha3s-telegram_bot-1`) dùng chung production token.
- Production 2 bot: **0 × `409 Conflict`** suốt 5 phút quan sát. Một poller duy nhất sở hữu token.

## 4. Price-mutation audit — PO-approved change package (governance)
- **Bối cảnh:** §5.1 ban đầu PO sửa giá nhưng price mutation NGOÀI M0 audit scope (group A = auth/staff) → không sinh audit.
- **Quyết định PO (scope-change, CA §7 exception "PO thay đổi scope"):** audit cho mutation giá (tài chính nhạy cảm).
- **Thực hiện (change package RIÊNG):** wire `audit_service.record` fail-closed vào `products.replace_price_tiers`
  (`audit_service.audit_exists()` shared; endpoint inject actor). **Rehearsal `price_audit_test.py` PASS**:
  positive (actor/entity/before-after) + **fail-closed rollback giá khi audit fail** + backward-compat (actor=None → không audit).
  `app` ruff clean + pytest 42 passed.
- **SHA delta (release governance CA §3):** `fb2a46b` (rc5) → **`3845f44` (rc6)**. Delta = 4 file
  (`audit_service.py`, `products.py`, `dashboard.py`, `scripts/price_audit_test.py`); **migration/RBAC/auth runtime không đổi**.
- **Incident/approval record:** KHÔNG phải emergency — đây là **PO scope-decision có kiểm soát** (PO duyệt trong phiên trước khi deploy).
  Deploy tay (CI SSH vẫn lỗi firewall — đã ghi backlog M1).

## 5. Thời điểm kiểm tra
`2026-07-25 16:55 GMT+7` (VPS wall-clock ~cùng). Verify read-only qua `alpha3s-vps`, không PII trong note.

## Ký
```text
M0 OPERATIONAL CLOSURE NOTE — 3 viec §5 DONG:
(5.1) authenticated admin + audit smoke: login admin OK, price mutation success, audit_log product.price_tiers.replace
      actor_staff_id=2/entity product:1/before-after, redaction 0 PII raw.
(5.2) Telegram 409 het (dung bot dev, 0x409/5min).
(5.3) closure note nay.
Production: main @ 3845f44 (tag ib-m0-rc6), health 200, RBAC ready+strict, dashboard nonce CSP login OK, schema=18.
Price-audit = PO-approved change package (delta rc5->rc6, 4 file, migration/RBAC runtime khong doi).
De nghi CA danh dau M0 production_complete. Author role: Dev (Alpha3S). Ngay: 2026-07-25 16:55 GMT+7.
```
