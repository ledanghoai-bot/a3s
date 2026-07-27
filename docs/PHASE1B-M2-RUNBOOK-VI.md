---
id: A3S-PHASE1B-M2-RUNBOOK
milestone: M2
language: vi-VN
---

# M2 Runbook — Order and Inventory Correctness

Vận hành lớp tồn kho/đơn hàng M2. Mọi mutation đi qua **command service** (effective-once, Idempotency-Key);
tồn kho là **ledger append-only** (`inventory_movements`) + `inventory_balances` materialized; đơn có
**two-axis** `status` (business) + `inventory_status`. Flags mặc định **TẮT**.

## 1. Feature flags & thứ tự bật (§15.6, §16)

| Flag | Ý nghĩa | Bật khi |
|---|---|---|
| `M2_INVENTORY_LEDGER` | dual-write ledger/reservation/balance; order.create reserve atomic; expiry worker chạy | sau khi **backfill xong** + reconciliation OK |
| `M2_ORDER_TRANSITIONS` | API transition + lifecycle command (confirm/fulfill/cancel/adjust…) | sau ledger ổn định, đã canary |
| `M2_BALANCE_AUTHORITY` | availability/reserve đọc từ balance (Phase C) | **cuối cùng**, sau dual-write assertion xanh |

Rollout phases (§15.6): **A** schema+backfill (legacy authority) → **B** dual-write + assert `products.stock == available` → **C** balance authority. KHÔNG nhảy phase khi còn mismatch P1.

## 2. Cutover checklist (§15, §18)

1. Migrations 021–025 applied (schema expand + DB-role + order status). Postcondition mỗi migration fail-closed.
2. **Backfill**: `python scripts/m2_backfill.py audit` (exit 0) → `plan` (review checksum) → `apply --report R.json`.
   - Abort nếu unknown status / negative stock / orphan (§15.4). KHÔNG copy mù stock.
3. `python scripts/m2_backfill.py reconcile` → `ok: true` (§17.1: ledger=balance=reservation, stock=available).
4. Bật `M2_INVENTORY_LEDGER` (canary owner = Unit Head). Theo dõi reserve tại order.create + expiry sweep.
5. Bật `M2_ORDER_TRANSITIONS`. Smoke: confirm → fulfill 1 đơn test; adjustment nhỏ; approve lớn.
6. DB-role cutover (AC-M2-14): ops set `ALTER ROLE alpha3s_app LOGIN PASSWORD '<secret>'` + đổi `DATABASE_URL`
   sang `alpha3s_app`. Readiness: KHÔNG start runtime bằng migration-owner credential.

## 3. Expiry worker (§11)

- Cron `expire_reservations_job` mỗi 60s (arq). Claim reservation `active` + `expires_at<=now` + order `new`,
  batch 100, gọi command `inventory.reservation.expire` (idempotency key `reservation.expire:<id>:<expires_at>`).
- Flag TẮT → no-op. Nhiều worker / poll lặp KHÔNG nhân đôi (idempotent). Redis TTL KHÔNG phải nguồn chân lý.
- **Kill switch**: tắt `M2_INVENTORY_LEDGER` → sweep no-op; reservation KHÔNG bị bỏ quên (poll lại khi bật lại).

## 4. Adjustment approval (§12)

- `threshold = max(10, ceil(on_hand*0.02))`; `is_large = |Δ| >= threshold`.
- Nhỏ: actor có `inventory.adjust`, apply ngay. Lớn: `pending` → **Unit Head** của location (`inventory.adjust.approve`
  + mapping `inventory_unit_members`) duyệt; **requester ≠ approver** (SoD, DB CHECK); approve revalidate threshold →
  `409 adjustment_stale` nếu balance đổi. UI: trang **Kho → Điều chỉnh chờ duyệt**.

## 5. Metrics/alerts (§17.2) — structured log events (`log_event`)

| Event | Ý nghĩa | Alert |
|---|---|---|
| `reservation.expiry.sweep` `{claimed,expired,noop,failed}` | mỗi vòng sweep có việc | `failed>0` lặp lại → P2 |
| `reservation.expire.error` | 1 reservation expire lỗi | rate cao → điều tra |
| `<command>.rejected` `{error_code}` | business reject | `illegal_order_transition`/`adjustment_stale` tăng đột biến → xem UI/ops |
| reconciliation `mismatches` | `GET /dashboard/inventory/reconciliation` != ok | **P1** — dừng rollout (Phase B assert) |
| order.create reserve `insufficient_stock` sau khi legacy pass | bất nhất ledger↔legacy | **P1** — kiểm backfill/balance |

Kiểm tra nhanh: `GET /dashboard/inventory/reconciliation` (cần `inventory.reconcile`). `ok:false` → P1.

## 6. Rollback (§16)

- **Trước balance authority**: tắt flags, GIỮ schema expand, điều tra mismatch. Legacy stock vẫn chạy.
- **Sau dual-write**: KHÔNG xóa ledger/reservation; forward-fix data (movement bù), KHÔNG sửa balance mù.
- **Sau balance authority có business writes**: KHÔNG quay lại legacy stock mù; cần reconciliation + CA rollback decision.
- Ledger/`order_events` **append-only** (trigger + DB-role revoke) — correction = movement/event MỚI, không UPDATE/DELETE.

## 7. Sự cố thường gặp

| Triệu chứng | Xử lý |
|---|---|
| reconciliation mismatch `reserved != active_resv` | có reservation active mồ côi hoặc balance drift → điều tra, tạo movement bù, KHÔNG sửa balance tay |
| `products.stock != available` | Phase B: dừng rollout (P1). Kiểm cancel/expire có restore stock (dual-write) không |
| expire không chạy | check flag `M2_INVENTORY_LEDGER` bật + worker container up + cron log |
| adjustment lớn không duyệt được | approver phải là Unit Head của location (`inventory_unit_members`) + khác requester |
| order.create báo hết hàng dù stock đủ | balance chưa backfill / available<qty → chạy backfill + reconcile |

## 8. Lệnh nhanh

```bash
# Backfill (production, sau maintenance window)
python scripts/m2_backfill.py audit
python scripts/m2_backfill.py apply --report /root/m2_backfill_report.json
python scripts/m2_backfill.py reconcile

# Evidence (throwaway DB)
docker exec alpha3s-api-1 python scripts/m2_db_role_test.py
docker exec alpha3s-api-1 python scripts/m2_backfill_test.py
docker exec alpha3s-api-1 python scripts/m2_inventory_domain_test.py
docker exec -e DATABASE_URL=...m2s4_itest -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/m2_transitions_test.py
docker exec -e DATABASE_URL=...m2s5_itest -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/m2_lifecycle_test.py
docker exec -e DATABASE_URL=...m2s6_itest -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/m2_worker_api_test.py
```
