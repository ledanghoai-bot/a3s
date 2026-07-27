---
id: A3S-PHASE1B-M2-PO-CHANGE-BACKORDER
milestone: M2
title: PO Change Package — Backorder / never-drop-order + escalation
type: po-directed-behavior-change
governing_directive: A3S-PHASE1B-M2-DEV-DIRECTIVE-001 v1.0.0
flag: M2_BACKORDER_ESCALATION (default OFF)
language: vi-VN
---

# PO Change Package — Backorder & Escalation

> **Bản chất:** PO (anh Hoài) chỉ đạo một thay đổi hành vi có chủ đích, **lệch khỏi CA spec §10.1**.
> Ghi lại minh bạch để CA review đúng quy trình (giống M0 đổi audit sang fail-closed theo PO). **Không
> tự ý chệch spec đã duyệt** — thay đổi gated sau flag `M2_BACKORDER_ESCALATION` **mặc định TẮT**, nên
> hành vi M2 đã được CA chấp nhận (thiếu hàng → reject) **giữ nguyên** khi flag tắt.

## 1. Chỉ đạo của PO
> "Gửi message cho inventory để báo cáo và request topup. **Ưu tiên tối thượng không bỏ đơn vì
> out-stock.** Gửi message nhắc staff thực hiện hoặc xin phép thực hiện."

Quyết định thiết kế PO đã chốt: (a) thiếu hàng → **giữ đơn (backorder)** + escalate inventory topup;
(b) topup xong → **auto-reserve FIFO**; (c) kênh: **Telegram admin + hàng đợi dashboard**.

## 2. Điểm lệch spec (khai báo thẳng)
- **CA spec §10.1** quy định: order create thiếu hàng → `422 insufficient_inventory`, **KHÔNG order,
  không reservation, không movement**.
- **Hành vi mới (flag ON):** thiếu hàng → **VẪN tạo order** ở `status='new'` / `inventory_status='unreserved'`
  + `inventory_backorders` row (active) + `order.backordered` event + escalation outbox tới inventory.
  **KHÔNG trừ stock, KHÔNG reserve** (đúng bản chất: chưa có hàng). → **không mất đơn**.
- Đây là lệch **có chủ đích, PO-directed**, phù hợp nguyên tắc automation-first (không mất doanh thu;
  con người/inventory chỉ ở exception path = topup).

## 3. Cách giữ inventory correctness KHÔNG bị phá
- Backorder **không tạo reservation giả** → invariant tồn kho (`reserved<=on_hand`, ledger=balance) **vẫn
  đúng tuyệt đối**. Đơn backorder chỉ là "đơn đã ghi nhận, chờ hàng", không chiếm tồn ảo.
- Backorder **không thể fulfill** khi chưa reserve (matrix guard + không có reservation active).
- Topup = `adjustment_increase` (qua đúng command adjustment, có audit/approval SoD/Unit Head) → sau khi
  apply, `drain_backorders` reserve FIFO theo `created_at`, chỉ khi `available >= quantity`. Mỗi lần
  reserve đi qua `apply_movement` (idempotent, invariant). Retry KHÔNG reserve 2 lần.
- Reconciliation §17.1 **không đổi** (backorder không nằm trong balance/ledger tới khi được reserve thật).

## 4. Escalation / notification (deterministic, không LLM)
Đi qua **outbox durable M1** (retry/dead-letter/dedupe), text dựng tại emit:
| Event | Khi nào | Tới |
|---|---|---|
| `inventory.shortage_topup_request` | tạo backorder | inventory (Telegram admin) + dashboard queue |
| `order.backorder_reserved_notify` | topup auto-reserve xong | sales (Telegram admin) |
| `inventory.adjust.approval_request` | điều chỉnh lớn pending | Unit Head (Telegram admin) — "xin phép" |
Dashboard: `GET /dashboard/inventory/escalations` + trang **Kho → Cần xử lý**.

## 5. Thay đổi kỹ thuật
- Migration **026** `inventory_backorders` (one active per order_item, FIFO index).
- Flag `M2_BACKORDER_ESCALATION` (config, default False).
- `app/services/inventory/backorder.py` (capture / drain FIFO / emit escalation+ping).
- `order_service._run_winner`: thiếu hàng + flag → backorder path (không reject/không trừ stock).
- `lifecycle`: adjustment apply Δ>0 → `_maybe_drain_backorders`; large pending → approval ping.
- `outbox_worker._telegram_admin_text`: honor `admin_text` (render escalation deterministic).
- `receipt.build_order_create_receipt`: thêm `backordered`.
- API `GET /dashboard/inventory/escalations`; dashboard Kho tab "Cần xử lý".

## 6. Evidence
`scripts/m2_backorder_test.py` (throwaway DB, migrate 001..026) — **PASS**:
- flag **OFF** → reject `insufficient_stock` (CA spec §10.1 giữ nguyên).
- flag **ON** → đơn GIỮ (`backordered=true`), unreserved, backorder active, **stock không trừ**,
  `order.backordered` event, escalation outbox tới inventory.
- topup (adjustment_increase approve) → auto-reserve **2 backorder FIFO**, balance on_hand=22/reserved=8,
  approval-ping outbox cho Unit Head.
`scripts/m2_worker_api_test.py` — escalations endpoint 200. Regression: pytest 81 + M1 fresh + M2 S1-6 PASS.

## 7. Rollback / an toàn
- Flag OFF → hành vi CA-accepted (reject) tức thì, không cần migrate lùi. `inventory_backorders` để nguyên
  (expand-only). Không đụng ledger/balance semantics.
- Backorder tồn đọng khi tắt flag: vẫn hiển thị ở dashboard queue để ops xử lý tay; không mất dữ liệu.

## 8. Cần CA quyết
1. **Chấp nhận** thay đổi hành vi §10.1 này như **PO change** (flag-gated) trong M2, hay tách milestone riêng?
2. Nếu chấp nhận: bật `M2_BACKORDER_ESCALATION` ở phase nào của rollout (đề xuất: cùng/sau `M2_ORDER_TRANSITIONS`,
   khi đã có Unit Head + inventory account thật để nhận escalation).
3. Customer-facing: hiện khách nhận reply trung lập (CR-08). Có cần thông báo khách "đơn đang chờ hàng"?
   (Đề xuất: có, template deterministic — P2 nếu chưa gấp.)
