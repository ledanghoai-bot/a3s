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

1. Migrations **021–028** applied (021 inventory core · 022 order events · 023 adjustment RBAC · 024 DB-role
   · 025 order status · 026 mutation RBAC · 027 origin_channel · 028 stock>=0). Postcondition mỗi migration fail-closed.
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
| `products.stock < 0` (CHECK 028 chặn; nếu thấy attempt) | drift/stale write | **P1** — mirror contract §9 phải giữ stock=available>=0 |
| reconciliation `products.stock != available` | mirror không chạy ở một write path | **P1** — dừng rollout, kiểm §9 mirror |

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

## 9. Contract quan trọng (remediation CA Submission 1 + 2)

### 9.1 Phase C stock MIRROR contract (S2-F01) — nguồn tồn hợp nhất
`products.stock` là **MIRROR** của `balance.available` (default location). MỌI inventory write
(create/cancel/expire/fulfill/adjustment) gọi `inv_repo.materialize_stock_mirror()` để **materialize**
`stock := on_hand - reserved` — **KHÔNG** delta trên giá trị stale. Hệ quả:
- `products.stock == available` LUÔN đúng (default location) ở mọi phase.
- `stock` không bao giờ âm (available ≥ 0 do invariant + CHECK 028 `products_stock_nonneg`).
- Split-brain (legacy writer sửa stock lệch) tự **heal** ở op kế tiếp.
- Reconciliation sau MỖI op phải `ok`; `stock != available` → **P1**, kiểm write path bỏ mirror.

### 9.2 Authority read (S1-F05): `m2_balance_authority` ON → `order.create` đọc availability TỪ balance
(Phase C); OFF → legacy `products.stock`. Reserve `FOR UPDATE` là guard cuối (no oversell). Bật CUỐI CÙNG.

### 9.3 RBAC tại SHARED command boundary (S2-F02): `execute_lifecycle()` enforce quyền fail-closed
(`_enforce`, permission từ transition matrix/registry; `system` actor bypass). HTTP `_check_perm` giữ làm
defense-in-depth. Caller nội bộ gọi thẳng command service KHÔNG bypass được authorization.

### 9.4 Mutation permission (S1-F03): quyền write riêng `order.complete`/`order.delivery.manage`/
`order.return.manage` (migration 026) — KHÔNG cấp `viewer`. Không dùng `order.transition.view` cho mutation.

### 9.5 Customer notify (S1-F06): `orders.origin_channel` (migration 027); transition confirmed/fulfilled/
cancelled/completed phát customer outbox deterministic đúng kênh, dedupe `order_status:{id}:{status}`,
retry/dead-letter M1. Đơn `dashboard` không phát.

### 9.6 Backorder: đã TÁCH khỏi M2 (S1-F01) — change/milestone riêng.

Evidence remediation (thêm vào §8): `m2_rbac_test.py` (F03+F02 direct-call), `m2_adjustment_compat_test.py`
(F02), `m2_balance_authority_test.py` (F05+F01 mirror), `m2_customer_notify_test.py` (F06),
`m2_existing_apply_rehearsal.py` (F07/S2-F05).
