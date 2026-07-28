---
id: A3S-PHASE1B-M2-SLICE0-BASELINE-AUDIT
milestone: M2
governing_directive: A3S-PHASE1B-M2-DEV-DIRECTIVE-001 v1.0.0
language: vi-VN
---

# M2 Slice 0 — Baseline audit + legacy status/backfill report

## 1. Base SHA & branch (Directive §2) — VERIFIED

```text
Locked base SHA   : d7ccc4f930ad4ef579b7befc12f24048dc4fbcc8
M1 accepted code  : 46e1169f9f6fae70eca06ef21eec62ae3ebfe70f
Descendant check  : 46e1169 is ancestor of d7ccc4f (exit 0)
Delta 46e1169->d7ccc4f : docs/PHASE1B-M1-DEV-DELIVERY-PACKAGE-VI.md ONLY (docs-only, no code/migration)
Migration manifest: 001-020 (20 files) tại base
M2 branch         : feat/phase1b-m2-order-inventory-correctness (off d7ccc4f, KHÔNG off main)
```

## 2. Current-state inventory model (code audit)

- Tồn hiện tại = **một cột `products.stock`** (vừa physical vừa sellable). KHÔNG reservation, KHÔNG
  ledger, KHÔNG location.
- **Stock bị TRỪ khi order create** tại 3 nơi (đều `UPDATE products SET stock = stock - qty`):
  - `app/services/command/order_service.py` (`_run_winner`, đường M1 command).
  - `app/services/orders.py` (`create_order_manual`, manual dashboard).
  - `app/services/tools.py` (`create_order`, AI legacy khi flag M1 off).
- `app/api/dashboard.py` cho staff set `stock` trực tiếp khi tạo/sửa product.

## 3. Legacy order status → M2 mapping

Legacy `orders.status` (từ `orders.py _STAGES` + `cancelled`): **{new, confirmed, shipped, done, cancelled}**.

| Legacy status | Ý nghĩa | M2 order_status | Inventory tại backfill |
|---|---|---|---|
| `new` | active, chưa fulfill | `new` | active-unfulfilled → tạo reservation (opening_reserved) |
| `confirmed` | active, đã xác nhận | `confirmed` | active-unfulfilled → tạo reservation |
| `shipped` | đã giao | `fulfilled` | đã tiêu thụ (stock đã trừ, KHÔNG cộng lại) |
| `done` | hoàn tất | `completed` | đã tiêu thụ |
| `cancelled` | đã huỷ | `cancelled` | released — xem §4 (anomaly) |

## 4. ⚠️ Finding quan trọng — legacy cancel KHÔNG restore stock

Xác minh code: KHÔNG có `stock = stock + …` ở đâu; `orders.validate_transition` chỉ đổi cột status.
→ Đơn `cancelled` đã bị **trừ stock lúc create và KHÔNG được cộng lại**.

**Hệ quả cho backfill (§15.4):** `products.stock` có thể **thấp hơn tồn vật lý thật** một lượng =
Σ(quantity của đơn cancelled). Backfill theo §15.4 dựng:

```text
opening_reserved  = Σ quantity active-unfulfilled (new/confirmed)
opening_on_hand   = products.stock + opening_reserved
opening_available = products.stock
```

Công thức này tái dựng **đúng trạng thái vận hành** (available == products.stock) — KHÔNG tự cộng lại
lượng cancelled (không đoán mù). Chênh lệch physical-vs-operational do cancelled-not-restored là **vấn đề
legacy có sẵn**, phải sửa bằng **physical count + adjustment sau cutover**, KHÔNG auto-correct trong backfill
(§15.4 "không copy mù", §18 "unknown → abort, không force"). Cần ghi vào backfill report + báo ops.

## 5. Data-anomaly audit SQL (đã chạy trên dev DB; DÙNG NGUYÊN cho production snapshot)

```sql
SELECT status, count(*), sum(oi.quantity) FROM orders o LEFT JOIN order_items oi ON oi.order_id=o.id GROUP BY status;
SELECT count(*) FROM products WHERE stock < 0;                                   -- negative stock
SELECT count(*) FROM order_items oi LEFT JOIN products p ON p.id=oi.product_id WHERE p.id IS NULL;  -- orphan
SELECT DISTINCT status FROM orders WHERE status NOT IN ('new','confirmed','shipped','done','cancelled'); -- unknown -> abort
SELECT sum(oi.quantity) FROM orders o JOIN order_items oi ON oi.order_id=o.id WHERE o.status IN ('new','confirmed'); -- opening_reserved
```

Kết quả **dev DB** (mẫu nhỏ, không đại diện production): statuses={new}; unknown=none; negative stock=0;
orphan items=0; active-unfulfilled qty=5; cancelled=0. → dev sạch nhưng **không đủ để kết luận**.

## 6. Dependency / Stop condition

**Full data audit (§15.4 items 1–5) yêu cầu PRODUCTION-like snapshot** (distinct statuses/counts thật,
verify cancel-restore trên data thật, phát hiện negative/orphan/ambiguous, duplicate semantics). Dev DB chỉ
có 1 đơn → không đại diện. Đây là **open release input (§23)** + có thể chạm Stop condition §10 ("cần
production access"). 

**Ảnh hưởng scope:** Slice 1 (schema), Slice 3 (domain), Slice 4 (transitions) **KHÔNG cần** production
data → tiến hành được. **Slice 2 (backfill execution)** cần snapshot production (read-only) để chạy audit
+ reconstruct thật; tạo tooling trước, chạy trên snapshot khi có. Báo PO để cấp snapshot read-only.

## 7. Kết luận Slice 0

- Base/SHA/migrations verified; M2 branch tạo đúng.
- Legacy status mapping + cancel/stock behavior đã lập.
- Anomaly audit method + SQL sẵn sàng; dev sạch, production audit chờ snapshot.
- Không phát hiện data không map được trên dev → chưa cần Stop; nhưng backfill EXECUTION gate ở production snapshot.

## 8. Production snapshot audit (§15.4) — thực hiện read-only, PO-approved

Snapshot production xuất **read-only** (PO approve 27/7): 3 lệnh `COPY (SELECT...) TO STDOUT` stream về
`E:\Alpha3s\prod-snapshot\*.csv` (KHÔNG PII, KHÔNG ghi file trên VPS, KHÔNG đụng production). Directive §10
production-access resolved bằng PO approval; đã log minh bạch tại đây.

**Kết quả (production thật):**
- 2 orders, cả 2 `status='new'`; 2 items × `3S-100G` qty 1; 1 product `3S-100G` stock=998.
- Distinct statuses = {new}; **KHÔNG** unknown status; **KHÔNG** negative stock; **KHÔNG** orphan; **KHÔNG** cancelled (→ vấn đề legacy-cancel-no-restore MOOT trên production).
- Reconstruction: `opening_reserved=2`, `opening_on_hand=998+2=1000`, `opening_available=998==products.stock` ✓.
- → Backfill an toàn/trivial, không Stop condition. Data thật nhỏ (chưa có khách thật).
