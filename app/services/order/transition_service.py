"""Shared order transition service (I-B M2 Slice 4). Spec §7, §10.2-10.4, §11.3, §13.1.

MỘT engine duy nhất cho mọi lifecycle transition (dashboard/API/command đều gọi đây — không CRUD
status trực tiếp). Atomic trong transaction của caller:
  guard matrix -> lock order + reservations (§10.4) -> apply inventory effect -> update order
  (status + inventory_status) -> append order_event. Idempotency effective-once do command layer
  (Slice 5) đảm bảo; primitive ledger/event đều idempotent theo key.
"""
from __future__ import annotations

from dataclasses import dataclass

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
        "SELECT id, status, inventory_status, inventory_location_id "
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
                # Compatibility dual-write (§15.6): release trả available -> legacy products.stock cũng
                # phải +qty để giữ products.stock==available. Cũng SỬA bug legacy cancel-no-restore
                # (Slice0 finding): dưới flag M2, cancel/release KHÔI PHỤC tồn.
                await conn.execute(
                    "UPDATE products SET stock = stock + $1 WHERE id = $2", qty, r["product_id"])
            else:  # EFFECT_CONSUME (fulfillment): on_hand-=qty & reserved-=qty -> available giữ nguyên;
                # legacy stock đã trừ lúc create nên KHÔNG đổi -> vẫn khớp available.
                await inv_service.fulfill_reservation(
                    conn, r, idem_prefix=prefix, actor_type=actor_type, actor_id=actor_id,
                    correlation_id=correlation_id, command_id=command_id)

    # confirm: giữ reservation nhưng bỏ expiry (§11.3) — new -> confirmed set expires_at=NULL
    if action == "confirm":
        await conn.execute(
            "UPDATE inventory_reservations SET expires_at=NULL "
            "WHERE order_id=$1 AND status='active'",
            order_id,
        )

    # --- update order (business + inventory summary cùng transaction §7.4) ---
    inv_after = spec.inventory_status_after or inv_before
    await conn.execute(
        "UPDATE orders SET status=$2, inventory_status=$3, status_updated_at=now() WHERE id=$1",
        order_id, spec.to_status, inv_after,
    )

    # --- append event (idempotent) ---
    await append_order_event(
        conn, order_id=order_id, event_type=f"order.{action}", to_status=spec.to_status,
        from_status=from_status, inventory_status_before=inv_before, inventory_status_after=inv_after,
        actor_type=actor_type, actor_id=actor_id, correlation_id=correlation_id, command_id=command_id,
        reason=reason, idempotency_key=f"{prefix}:event:{order_id}:{action}",
    )
    return TransitionResult(order_id, from_status, spec.to_status, spec.inventory_effect, affected)


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
