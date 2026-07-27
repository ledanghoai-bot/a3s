"""Inventory domain operations (I-B M2 Slice 3). Spec §10.1-10.3, §12.1.

Primitives thuần tồn kho (KHÔNG wrap order transition/command — đó là Slice 4/5). Mỗi op ATOMIC
trong transaction của caller; đi qua repository.apply_movement (ledger + balance + invariant + idempotent).
Idempotency key do caller (command) cấp để effective-once dưới retry.
"""
from __future__ import annotations

import math

from app.services.inventory import repository as repo
from app.services.inventory.repository import MovementEffect


# ---------------------------------------------------------------------------
# §10.1 reserve — reserved += qty (available phải đủ)
# ---------------------------------------------------------------------------
async def reserve_item(
    conn, *, order_id: int, order_item_id: int, location_id: int, product_id: int,
    quantity: int, idem_prefix: str, actor_type: str, actor_id: str, correlation_id,
    expires_at=None, command_id=None,
) -> tuple[str, MovementEffect]:
    reservation_id = await repo.create_reservation(
        conn, order_id=order_id, order_item_id=order_item_id, location_id=location_id,
        product_id=product_id, quantity=quantity, idempotency_key=f"{idem_prefix}:resv:{order_item_id}",
        expires_at=expires_at, command_id=command_id,
    )
    effect = await repo.apply_movement(
        conn, location_id=location_id, product_id=product_id, movement_type="reserve",
        on_hand_delta=0, reserved_delta=quantity,
        idempotency_key=f"{idem_prefix}:reserve:{order_item_id}",
        actor_type=actor_type, actor_id=actor_id, correlation_id=correlation_id,
        reference_type="order_item", reference_id=str(order_item_id),
        reservation_id=reservation_id, order_id=order_id, order_item_id=order_item_id,
        command_id=command_id,
    )
    return reservation_id, effect


# ---------------------------------------------------------------------------
# §10.3 release/expire — reserved -= remaining (trước fulfillment)
# ---------------------------------------------------------------------------
async def release_reservation(
    conn, reservation, *, terminal_status: str, idem_prefix: str,
    actor_type: str, actor_id: str, correlation_id, command_id=None,
) -> MovementEffect:
    assert terminal_status in ("released", "expired")
    remaining = reservation["quantity_remaining"]
    mtype = "reservation_expire" if terminal_status == "expired" else "reservation_release"
    effect = await repo.apply_movement(
        conn, location_id=reservation["location_id"], product_id=reservation["product_id"],
        movement_type=mtype, on_hand_delta=0, reserved_delta=-remaining,
        idempotency_key=f"{idem_prefix}:{mtype}:{reservation['id']}",
        actor_type=actor_type, actor_id=actor_id, correlation_id=correlation_id,
        reference_type="reservation", reference_id=str(reservation["id"]),
        reservation_id=reservation["id"], order_id=reservation["order_id"],
        order_item_id=reservation["order_item_id"], command_id=command_id,
    )
    await repo.terminate_reservation(conn, reservation["id"], status=terminal_status, command_id=command_id)
    return effect


# ---------------------------------------------------------------------------
# §10.2 fulfillment — on_hand -= remaining, reserved -= remaining
# ---------------------------------------------------------------------------
async def fulfill_reservation(
    conn, reservation, *, idem_prefix: str, actor_type: str, actor_id: str,
    correlation_id, command_id=None,
) -> MovementEffect:
    remaining = reservation["quantity_remaining"]
    effect = await repo.apply_movement(
        conn, location_id=reservation["location_id"], product_id=reservation["product_id"],
        movement_type="fulfillment_consume", on_hand_delta=-remaining, reserved_delta=-remaining,
        idempotency_key=f"{idem_prefix}:fulfill:{reservation['id']}",
        actor_type=actor_type, actor_id=actor_id, correlation_id=correlation_id,
        reference_type="reservation", reference_id=str(reservation["id"]),
        reservation_id=reservation["id"], order_id=reservation["order_id"],
        order_item_id=reservation["order_item_id"], command_id=command_id,
    )
    await repo.terminate_reservation(conn, reservation["id"], status="fulfilled", command_id=command_id)
    return effect


# ---------------------------------------------------------------------------
# §12.1 adjustment threshold + apply
# ---------------------------------------------------------------------------
def compute_threshold(on_hand: int) -> int:
    """threshold = max(10, ceil(on_hand * 0.02)); on_hand=0 -> 10."""
    return max(10, math.ceil(on_hand * 0.02))


def is_large_adjustment(on_hand: int, quantity_delta: int) -> bool:
    return abs(quantity_delta) >= compute_threshold(on_hand)


async def apply_adjustment(
    conn, *, location_id: int, product_id: int, quantity_delta: int, idem_prefix: str,
    actor_type: str, actor_id: str, correlation_id, reason: str, reference_id: str, command_id=None,
) -> MovementEffect:
    """Điều chỉnh on_hand (±). reserved không đổi. Invariant reserved<=on_hand vẫn được apply_movement enforce."""
    mtype = "adjustment_increase" if quantity_delta > 0 else "adjustment_decrease"
    return await repo.apply_movement(
        conn, location_id=location_id, product_id=product_id, movement_type=mtype,
        on_hand_delta=quantity_delta, reserved_delta=0,
        idempotency_key=f"{idem_prefix}:adjust:{reference_id}",
        actor_type=actor_type, actor_id=actor_id, correlation_id=correlation_id,
        reference_type="adjustment", reference_id=reference_id, reason=reason, command_id=command_id,
    )
