---
id: A3S-PHASE1B-M0-P0-FIX-NOTE-001
title: Alpha3S I-B M0 — Fix Note (price endpoint RBAC P0)
document_type: p0_fix_note
responds_to: A3S-PHASE1B-CA-REVIEW-M0-CLOSURE-001
owner: Alpha3S
author_role: Dev
version: 1.0.0
status: fix_submitted_pending_production_complete
production_sha: 4ce5f3ab2b95846cbc5a3dd5b21528a891b36314
production_tag: ib-m0-rc7
created_at: 2026-07-25 21:37 GMT+7
language: vi-VN
---

# M0 — P0 Fix Note (CA-REVIEW-M0-CLOSURE §3/§4)

> Fix note **ngắn** (CA §4: chỉ SHA + test verdict + production smoke, KHÔNG viết lại Delivery Package).

## 1. Fix
Endpoint `PUT /dashboard/products/{product_id}/tiers`:
```diff
- staff: dict = Depends(require_active_session)          # chỉ authentication
+ staff: dict = Depends(require_permission("price.manage"))   # RBAC authorization
```
- Actor lấy **từ chính dependency** `require_permission` (không lấy nguồn khác).
- **Giữ audit fail-closed** trong cùng transaction (không đổi).
- `price.manage` đã có trong catalog 018 (admin có) → **không cần migration**.
- **Delta:** `3845f44` (rc6) → **`4ce5f3a` (rc7)**, 2 file (`app/api/dashboard.py`, `scripts/price_audit_test.py`);
  migration/RBAC/audit-service runtime không đổi.

## 2. Test verdict (rehearsal throwaway DB 001-018, `RBAC_STRICT=true`)
`scripts/price_audit_test.py` — **PASS** 4 case CA yêu cầu (§4.3):

| Case | Yêu cầu | Kết quả |
|---|---|---|
| A | Authorized (`price.manage`) → mutation + audit | pass gate; giá đổi; audit row (actor/entity/before-after) |
| B | Active role KHÔNG `price.manage` → 403 | **403**; giá KHÔNG đổi; **KHÔNG audit row mới** |
| C | Unauthenticated → 401 | **401** |
| D | Audit insert fail → rollback | **giá rollback** |

`app` **ruff clean** + **pytest 42 passed**.

## 3. Production smoke (main @ `4ce5f3a`, tag `ib-m0-rc7`)
- Health **200**; readiness `RBAC ready (permissions=21, mappings=35)`; `RBAC_STRICT=true`; dashboard 200.
- Gate live trong code (`require_permission("price.manage")` ở endpoint).
- **Unauthenticated** `PUT /dashboard/products/1/tiers` → **401**.
- **Authorized (admin)**: PO đăng nhập admin (`staff_id=2`) sửa bậc giá → **Lưu thành công** (không 403) →
  audit row (id=5) `product.price_tiers.replace`, `actor_staff_id=2`, `entity_type=product`, `entity_id=1`.
- *(403-no-mutation của role thiếu quyền: bằng chứng ở rehearsal case B — production 2 staff đều admin nên
  không tạo staff hạn chế chỉ để test, tránh thao tác thừa trên tài khoản thật.)*

## 4. Audit-service note (CA §5)
- `replace_price_tiers(..., actor=None)` giữ default cho backward-compat; **caller production DUY NHẤT là
  endpoint này và LUÔN truyền actor** (đã enforce permission) → không có đường sửa giá không-audit trên production.
- Cam kết: KHÔNG thêm caller mới dùng `actor=None` cho mutation giá; trước M1 pricing work sẽ cân nhắc
  bắt buộc actor/audit-context hoặc tách rõ internal migration method.

## Ký
```text
M0 P0 FIX NOTE — price endpoint enforce require_permission("price.manage") (CA-REVIEW-M0-CLOSURE §3 P0).
Production main @ 4ce5f3a (tag ib-m0-rc7), health 200, RBAC ready+strict.
Test 4 case PASS: A authorized+audit / B no-price.manage->403 no-mutation-audit / C unauth->401 / D audit-fail->rollback.
ruff clean + pytest 42. Production smoke: unauth->401; admin sua gia OK + audited (row id=5). Deploy co PO approval.
De nghi CA danh dau M0 production_complete. Author role: Dev (Alpha3S). Ngay: 2026-07-25 21:37 GMT+7.
```
