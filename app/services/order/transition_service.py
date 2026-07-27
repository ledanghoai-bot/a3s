"""Shared order transition service (I-B M2 Slice 4). Spec §7, §10.2-10.4, §11.3, §13.1.

MỘT engine duy nhất cho mọi lifecycle transition (dashboard/API/command đều gọi đây — không CRUD
status trực tiếp). Atomic trong transaction của caller:
  guard matrix -> lock order + reservations (§10.4) -> apply inventory effect -> update order
  (status + inventory_status) -> append order_event. Idempotency effective-once do command layer
  (Slice 5) đảm bảo; primitive ledger/event đều idempotent theo key.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.services.command import repository as cmd_repo
from app.services.command.retry import MAX_ATTEMPTS
from app.services.inventory import repository as inv_repo
from app.services.inventory import service as inv_service
from app.services.order import transitions
from app.services.order.events import append_order_event


@dataclass(frozen=True)
class TransitionResult:
    order_id: int
    from_status: str
    to_status: str
    inventory_effect: str
    affected_quantity: int  # released/consumed qty (0 nếu không đổi tồn)


async def _lock_order(conn, order_id: int):
    return await conn.fetchrow(
        "SELECT id, status, inventory_status, inventory_location_id, customer_id, origin_channel "
        "FROM orders WHERE id=$1 FOR UPDATE",
        order_id,
    )


async def apply_transition(
    conn,
    *,
    order_id: int,
    action: str,
    actor_type: str,
    actor_id: str,
    correlation_id,
    command_id=None,
    reason: str | None = None,
    idem_prefix: str | None = None,
) -> TransitionResult:
    order = await _lock_order(conn, order_id)
    if order is None:
        raise transitions.IllegalTransition("<missing>", action)
    from_status = order["status"]
    # M3-S1 gate: transition delivered-lifecycle chỉ mở khi flag bật; OFF = hành vi M2 nguyên trạng.
    if (from_status, action) in transitions.M3_PAIRS and not settings.m3_delivered_lifecycle:
        raise transitions.IllegalTransition(from_status, action)
    spec = transitions.resolve(from_status, action)  # raise IllegalTransition nếu không hợp lệ
    prefix = idem_prefix or f"cmd:{command_id}"
    inv_before = order["inventory_status"]

    # --- inventory effect (§7.2) trên active reservations, lock ordering §10.4 ---
    affected = 0
    if spec.inventory_effect in (transitions.EFFECT_RELEASE, transitions.EFFECT_CONSUME):
        reservations = await inv_repo.lock_reservations_for_order(conn, order_id)
        for r in reservations:
            qty = r["quantity_remaining"]
            affected += qty
            if spec.inventory_effect == transitions.EFFECT_RELEASE:
                await inv_service.release_reservation(
                    conn, r, terminal_status="released", idem_prefix=prefix,
                    actor_type=actor_type, actor_id=actor_id, correlation_id=correlation_id,
                    command_id=command_id)
                # Mirror contract (CA M2-S2-F01): release trả available -> materialize stock := available
                # (KHÔNG delta stale). Cũng sửa bug legacy cancel-no-restore (Slice0 finding).
                await inv_repo.materialize_stock_mirror(conn, r["location_id"], r["product_id"])
            else:  # EFFECT_CONSUME (fulfillment): on_hand-=qty & reserved-=qty -> available giữ nguyên.
                await inv_service.fulfill_reservation(
                    conn, r, idem_prefix=prefix, actor_type=actor_type, actor_id=actor_id,
                    correlation_id=correlation_id, command_id=command_id)
                # Mirror contract: materialize (available không đổi -> no-op nhưng giữ nhất quán mọi path).
                await inv_repo.materialize_stock_mirror(conn, r["location_id"], r["product_id"])

    # confirm: giữ reservation nhưng bỏ expiry (§11.3) — new -> confirmed set expires_at=NULL
    if action == "confirm":
        await conn.execute(
            "UPDATE inventory_reservations SET expires_at=NULL "
            "WHERE order_id=$1 AND status='active'",
            order_id,
        )

    # --- update order (business + inventory summary cùng transaction §7.4) ---
    # M3-S1: delivered_at chỉ set khi commit sang delivered; COALESCE -> retry/correction không overwrite.
    inv_after = spec.inventory_status_after or inv_before
    await conn.execute(
        "UPDATE orders SET status=$2, inventory_status=$3, status_updated_at=now(), "
        "delivered_at = CASE WHEN $2='delivered' THEN COALESCE(delivered_at, now()) "
        "ELSE delivered_at END WHERE id=$1",
        order_id, spec.to_status, inv_after,
    )

    # --- append event (idempotent) ---
    await append_order_event(
        conn, order_id=order_id, event_type=f"order.{action}", to_status=spec.to_status,
        from_status=from_status, inventory_status_before=inv_before, inventory_status_after=inv_after,
        actor_type=actor_type, actor_id=actor_id, correlation_id=correlation_id, command_id=command_id,
        reason=reason, idempotency_key=f"{prefix}:event:{order_id}:{action}",
    )
    # --- customer notification deterministic (AC-M2-15, CA M2-S1-F06) ---
    await _notify_customer(conn, order, spec.to_status, command_id)
    return TransitionResult(order_id, from_status, spec.to_status, spec.inventory_effect, affected)


# Template deterministic từ committed status (KHÔNG LLM, không bịa quantity/tiền).
_CUSTOMER_NOTIFY = {
    "confirmed": "Đơn #{id} của bạn đã được xác nhận.",
    "fulfilled": "Đơn #{id} của bạn đã được giao.",
    # M3-S1: transactional notify khi giao thành công (P03; sensor COMM-04). Chỉ phát khi flag
    # m3_delivered_lifecycle bật (transition không xảy ra khi OFF). Text 'fulfilled' giữ nguyên M2.
    "delivered": "Đơn #{id} của bạn đã giao thành công. Cảm ơn bạn!",
    "cancelled": "Đơn #{id} của bạn đã được huỷ.",
    "cancelled_by_exception": "Đơn #{id} của bạn đã được huỷ.",
    "completed": "Đơn #{id} của bạn đã hoàn tất. Cảm ơn bạn!",
}


async def _notify_customer(conn, order, to_status: str, command_id) -> None:
    """Emit customer outbox notification (durable: retry/dead-letter/dedupe M1) cho kênh khách.
    Dedupe theo (order, to_status) -> giao đúng-một-lần. Chỉ khi có command_id (đi từ command)."""
    if command_id is None:
        return
    ch = order["origin_channel"]
    if ch not in ("messenger", "telegram_customer"):
        return
    tmpl = _CUSTOMER_NOTIFY.get(to_status)
    if tmpl is None or order["customer_id"] is None:
        return
    psid = await conn.fetchval("SELECT psid FROM customers WHERE id=$1", order["customer_id"])
    if not psid:
        return
    if settings.m3_outbound_dispatcher:
        # M3-S5: qua dispatcher — consent check + approved template lúc GỬI. Cùng dedupe_key ->
        # dedupe/at-least-once M1 giữ nguyên (AC-M3-06); template seed 032 = đúng text M2.
        from app.services.command import dispatcher
        await dispatcher.enqueue_outbound(
            conn, command_id=command_id, customer_id=order["customer_id"], customer_ref=psid,
            destination=ch, purpose_code="P03_TRANSACTIONAL",
            template_key=f"order_status_{to_status}", template_version=1,
            params={"id": order["id"]},
            dedupe_key=f"order_status:{order['id']}:{to_status}", max_attempts=MAX_ATTEMPTS)
        return
    await cmd_repo.insert_outbox(
        conn, command_id=command_id, event_type="order.status.customer", event_version=1,
        destination=ch, dedupe_key=f"order_status:{order['id']}:{to_status}",
        payload={"customer_ref": psid, "order_id": order["id"], "text": tmpl.format(id=order["id"])},
        max_attempts=MAX_ATTEMPTS)


async def reserve_on_create(
    conn,
    *,
    order_id: int,
    order_item_id: int,
    product_id: int,
    quantity: int,
    actor_type: str,
    actor_id: str,
    correlation_id,
    command_id=None,
    ttl_hours: int = 24,
) -> int:
    """Reserve atomic khi order.create (§7.2 create->new Reserve TTL 24h). Set order inventory_status=
    reserved + location; append order.created event. Trả location_id đã reserve. Raise InventoryError
    (insufficient/invariant) -> command rollback (không tạo đơn)."""
    location_id = await inv_repo.resolve_default_location(conn)
    expires_at = await conn.fetchval(
        "SELECT now() + ($1 || ' hours')::interval", str(ttl_hours)
    )
    prefix = f"cmd:{command_id}"
    await inv_service.reserve_item(
        conn, order_id=order_id, order_item_id=order_item_id, location_id=location_id,
        product_id=product_id, quantity=quantity, idem_prefix=prefix, actor_type=actor_type,
        actor_id=actor_id, correlation_id=correlation_id, expires_at=expires_at, command_id=command_id,
    )
    await conn.execute(
        "UPDATE orders SET inventory_status='reserved', inventory_location_id=$2, status_updated_at=now() "
        "WHERE id=$1",
        order_id, location_id,
    )
    await append_order_event(
        conn, order_id=order_id, event_type="order.created", to_status="new",
        from_status=None, inventory_status_before="unreserved", inventory_status_after="reserved",
        actor_type=actor_type, actor_id=actor_id, correlation_id=correlation_id, command_id=command_id,
        idempotency_key=f"{prefix}:event:{order_id}:created",
    )
    return location_id
