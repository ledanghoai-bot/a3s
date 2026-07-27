"""Backorder + escalation (I-B M2 PO-change: never-drop-order on out-of-stock).

PO-directed (deviates CA spec §10.1). Gated flag `M2_BACKORDER_ESCALATION`. Khi thiếu hàng: giữ đơn
(inventory_status='unreserved') + backorder row + escalate inventory topup (outbox telegram_admin +
dashboard queue). Topup (adjustment_increase) -> drain_backorders auto-reserve FIFO + notify sales.
Notification deterministic (admin_text dựng tại emit, KHÔNG qua LLM). Đi qua outbox durable M1.
"""
from __future__ import annotations

import uuid

from app.services.command import repository as repo
from app.services.command.retry import MAX_ATTEMPTS
from app.services.inventory import repository as inv_repo
from app.services.inventory import service as inv_service
from app.services.order.events import append_order_event

_DEST_ADMIN = "telegram_admin"


async def _emit_admin(conn, *, command_id, event_type: str, dedupe_key: str, admin_text: str,
                      extra: dict | None = None) -> None:
    payload = {"admin_text": admin_text, "kind": event_type}
    if extra:
        payload.update(extra)
    await repo.insert_outbox(
        conn, command_id=command_id, event_type=event_type, event_version=1,
        destination=_DEST_ADMIN, dedupe_key=dedupe_key, payload=payload, max_attempts=MAX_ATTEMPTS)


async def capture_backorder(
    conn, *, order_id: int, order_item_id: int, product_id: int, location_id: int, quantity: int,
    sku: str, actor_type: str, actor_id: str, command_id, correlation_id,
) -> str:
    """Giữ đơn thiếu hàng: backorder row (idempotent) + order.backordered event + escalate inventory.
    KHÔNG trừ stock, KHÔNG reserve (chưa có hàng). inventory_status giữ 'unreserved'."""
    idem = f"backorder:{order_item_id}"
    bid = uuid.uuid5(uuid.NAMESPACE_OID, idem)
    await conn.execute(
        "INSERT INTO inventory_backorders "
        "(id,order_id,order_item_id,location_id,product_id,quantity,status,idempotency_key,created_command_id) "
        "VALUES ($1,$2,$3,$4,$5,$6,'active',$7,$8) ON CONFLICT (idempotency_key) DO NOTHING",
        bid, order_id, order_item_id, location_id, product_id, quantity, idem, command_id)
    await append_order_event(
        conn, order_id=order_id, event_type="order.backordered", to_status="new",
        from_status=None, inventory_status_before="unreserved", inventory_status_after="unreserved",
        idempotency_key=f"cmd:{command_id}:event:{order_id}:backordered", correlation_id=correlation_id,
        actor_type=actor_type, actor_id=actor_id, command_id=command_id,
        reason=f"out_of_stock sku={sku} qty={quantity}")
    await _emit_admin(
        conn, command_id=command_id, event_type="inventory.shortage_topup_request",
        dedupe_key=f"backorder_escalation:{order_item_id}",
        admin_text=(
            "⚠️ 3S Coffee — THIEU HANG (khong bo don)\n"
            f"Don #{order_id}: {sku} x {quantity} — KHONG du ton de reserve.\n"
            "Don da duoc GIU (backorder). Can INVENTORY topup de tu dong reserve (FIFO).\n"
            "Xem: dashboard -> Kho -> Backorder/Escalation."),
        extra={"order_id": order_id, "product_id": product_id, "sku": sku, "quantity": quantity})
    return str(bid)


async def drain_backorders(
    conn, *, location_id: int, product_id: int, actor_type: str, actor_id: str, command_id, correlation_id,
) -> list[dict]:
    """Sau topup: reserve backorder active theo FIFO trong khi available đủ. Trả list đã reserve.
    Mỗi cái: reservation + reserve movement + order inventory_status=reserved + order.backorder_reserved
    event + notify sales. Idempotent qua idempotency key domain."""
    reserved = []
    # lock candidate backorders FIFO
    rows = await conn.fetch(
        "SELECT id, order_id, order_item_id, quantity FROM inventory_backorders "
        "WHERE location_id=$1 AND product_id=$2 AND status='active' "
        "ORDER BY created_at FOR UPDATE SKIP LOCKED",
        location_id, product_id)
    for bo in rows:
        bal = await inv_repo.get_balance(conn, location_id, product_id)
        available = (bal["on_hand"] - bal["reserved"]) if bal else 0
        if available < bo["quantity"]:
            continue  # chưa đủ cho cái này (FIFO: dừng phần lớn hơn, nhưng vẫn thử cái nhỏ sau — ở đây tiếp)
        # reserve
        prefix = f"cmd:{command_id}:bo:{bo['id']}"
        await inv_service.reserve_item(
            conn, order_id=bo["order_id"], order_item_id=bo["order_item_id"], location_id=location_id,
            product_id=product_id, quantity=bo["quantity"], idem_prefix=prefix, actor_type=actor_type,
            actor_id=actor_id, correlation_id=correlation_id, command_id=command_id)
        await conn.execute(
            "UPDATE inventory_backorders SET status='reserved', reserved_command_id=$2, resolved_at=now() "
            "WHERE id=$1", bo["id"], command_id)
        await conn.execute(
            "UPDATE orders SET inventory_status='reserved', inventory_location_id=$2, status_updated_at=now() "
            "WHERE id=$1", bo["order_id"], location_id)
        await append_order_event(
            conn, order_id=bo["order_id"], event_type="order.backorder_reserved", to_status="new",
            from_status="new", inventory_status_before="unreserved", inventory_status_after="reserved",
            idempotency_key=f"{prefix}:event", correlation_id=correlation_id,
            actor_type=actor_type, actor_id=actor_id, command_id=command_id, reason="topup auto-reserve")
        await _emit_admin(
            conn, command_id=command_id, event_type="order.backorder_reserved_notify",
            dedupe_key=f"backorder_reserved:{bo['order_item_id']}",
            admin_text=(
                "✅ 3S Coffee — BACKORDER DA CO HANG\n"
                f"Don #{bo['order_id']} da tu dong reserve {bo['quantity']} sau topup.\n"
                "SALES tiep tuc xu ly (confirm/fulfill)."),
            extra={"order_id": bo["order_id"], "quantity": bo["quantity"]})
        reserved.append({"backorder_id": str(bo["id"]), "order_id": bo["order_id"], "quantity": bo["quantity"]})
    return reserved
