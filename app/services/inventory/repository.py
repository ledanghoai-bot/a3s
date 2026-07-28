"""Inventory repositories + core movement primitive (I-B M2 Slice 3). Spec §9, §10.4, §9.8.

Nguyên tắc:
- MỌI thay đổi balance đi qua `apply_movement` — ghi ledger (append-only) + cập nhật balance ATOMIC
  trong transaction của caller (command boundary). Ledger là nguồn chân lý; balance là materialized.
- Idempotent theo `idempotency_key` (UNIQUE trên inventory_movements): replay KHÔNG áp lại delta.
- Deterministic lock ordering (§10.4) qua lock_reservations/lock_balances để tránh deadlock.
- Invariant (on_hand>=0, reserved>=0, reserved<=on_hand) kiểm ở code (lỗi rõ ràng) + DB CHECK (phòng thủ).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.services.inventory import errors


@dataclass(frozen=True)
class MovementEffect:
    movement_id: str
    location_id: int
    product_id: int
    before_on_hand: int
    after_on_hand: int
    before_reserved: int
    after_reserved: int
    already_applied: bool  # True nếu idempotent replay (không áp lại delta)

    @property
    def available(self) -> int:
        return self.after_on_hand - self.after_reserved


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
async def resolve_default_location(conn) -> int:
    loc = await conn.fetchval(
        "SELECT id FROM inventory_locations WHERE is_default AND is_active"
    )
    if loc is None:
        raise errors.no_default_location()
    return loc


# ---------------------------------------------------------------------------
# Deterministic locking (§10.4)
# ---------------------------------------------------------------------------
async def lock_balances(conn, location_id: int, product_ids: list[int]) -> None:
    """Lock balance rows theo (location_id, product_id) tăng dần — ensure row tồn tại trước."""
    ordered = sorted(set(product_ids))
    for pid in ordered:
        await conn.execute(
            "INSERT INTO inventory_balances (location_id,product_id,on_hand,reserved) "
            "VALUES ($1,$2,0,0) ON CONFLICT (location_id,product_id) DO NOTHING",
            location_id, pid,
        )
    if ordered:
        await conn.execute(
            "SELECT 1 FROM inventory_balances WHERE location_id=$1 AND product_id = ANY($2::bigint[]) "
            "ORDER BY product_id FOR UPDATE",
            location_id, ordered,
        )


async def lock_reservations_for_order(conn, order_id: int) -> list:
    """Lock active reservations của order theo (location_id, product_id, id) — §10.4 step 2."""
    return await conn.fetch(
        "SELECT * FROM inventory_reservations WHERE order_id=$1 AND status='active' "
        "ORDER BY location_id, product_id, id FOR UPDATE",
        order_id,
    )


async def materialize_stock_mirror(conn, location_id: int, product_id: int) -> None:
    """Phase mirror contract (CA M2-S2-F01): `products.stock := balance.available` cho DEFAULT location.
    MATERIALIZE từ giá trị authoritative (không delta trên giá trị stale) -> stock LUÔN == available,
    KHÔNG bao giờ âm (available = on_hand - reserved >= 0 do invariant). Áp dụng nhất quán cho MỌI
    inventory write path (create/cancel/expire/fulfill/adjustment). Non-default location: no-op
    (compat assertion §17.1 chỉ cho default location)."""
    await conn.execute(
        "UPDATE products p SET stock = b.on_hand - b.reserved "
        "FROM inventory_balances b, inventory_locations l "
        "WHERE b.location_id = $1 AND b.product_id = $2 AND p.id = $2 "
        "  AND l.id = b.location_id AND l.is_default AND l.is_active",
        location_id, product_id)


async def get_balance(conn, location_id: int, product_id: int):
    return await conn.fetchrow(
        "SELECT on_hand, reserved, on_hand-reserved AS available, version "
        "FROM inventory_balances WHERE location_id=$1 AND product_id=$2",
        location_id, product_id,
    )


# ---------------------------------------------------------------------------
# Core primitive: apply_movement (append ledger + update balance, idempotent)
# ---------------------------------------------------------------------------
async def apply_movement(
    conn,
    *,
    location_id: int,
    product_id: int,
    movement_type: str,
    on_hand_delta: int,
    reserved_delta: int,
    idempotency_key: str,
    actor_type: str,
    actor_id: str,
    correlation_id,
    reference_type: str,
    reference_id: str,
    reservation_id=None,
    order_id: int | None = None,
    order_item_id: int | None = None,
    command_id=None,
    reason: str | None = None,
) -> MovementEffect:
    # 0) idempotent short-circuit: nếu movement key đã tồn tại -> trả effect cũ, KHÔNG áp lại
    existing = await conn.fetchrow(
        "SELECT id, before_on_hand, after_on_hand, before_reserved, after_reserved "
        "FROM inventory_movements WHERE idempotency_key=$1",
        idempotency_key,
    )
    if existing is not None:
        return MovementEffect(
            str(existing["id"]), location_id, product_id,
            existing["before_on_hand"], existing["after_on_hand"],
            existing["before_reserved"], existing["after_reserved"],
            already_applied=True,
        )

    # 1) ensure + lock balance row
    await conn.execute(
        "INSERT INTO inventory_balances (location_id,product_id,on_hand,reserved) "
        "VALUES ($1,$2,0,0) ON CONFLICT (location_id,product_id) DO NOTHING",
        location_id, product_id,
    )
    bal = await conn.fetchrow(
        "SELECT on_hand, reserved FROM inventory_balances "
        "WHERE location_id=$1 AND product_id=$2 FOR UPDATE",
        location_id, product_id,
    )
    before_on_hand, before_reserved = bal["on_hand"], bal["reserved"]
    after_on_hand = before_on_hand + on_hand_delta
    after_reserved = before_reserved + reserved_delta

    # 2) invariant (code-level, lỗi rõ ràng trước khi chạm DB CHECK)
    if after_on_hand < 0:
        raise errors.invariant(f"on_hand<0 (prod {product_id}: {before_on_hand}{on_hand_delta:+})")
    if after_reserved < 0:
        raise errors.invariant(f"reserved<0 (prod {product_id}: {before_reserved}{reserved_delta:+})")
    if after_reserved > after_on_hand:
        # reserve vượt tồn -> insufficient; các trường hợp khác -> invariant
        if movement_type == "reserve":
            raise errors.insufficient(product_id, reserved_delta, after_on_hand - before_reserved)
        raise errors.invariant(
            f"reserved>on_hand (prod {product_id}: reserved {after_reserved} > on_hand {after_on_hand})"
        )

    # 3) append movement (ledger nguồn chân lý). UNIQUE(idempotency_key) chặn double dưới race.
    mid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO inventory_movements "
        "(id,location_id,product_id,reservation_id,order_id,order_item_id,movement_type,"
        " on_hand_delta,reserved_delta,before_on_hand,after_on_hand,before_reserved,after_reserved,"
        " reference_type,reference_id,idempotency_key,actor_type,actor_id,reason,correlation_id,command_id) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)",
        mid, location_id, product_id, reservation_id, order_id, order_item_id, movement_type,
        on_hand_delta, reserved_delta, before_on_hand, after_on_hand, before_reserved, after_reserved,
        reference_type, reference_id, idempotency_key, actor_type, actor_id, reason, correlation_id, command_id,
    )
    # 4) materialize balance
    await conn.execute(
        "UPDATE inventory_balances SET on_hand=$3, reserved=$4, version=version+1 "
        "WHERE location_id=$1 AND product_id=$2",
        location_id, product_id, after_on_hand, after_reserved,
    )
    return MovementEffect(
        str(mid), location_id, product_id,
        before_on_hand, after_on_hand, before_reserved, after_reserved,
        already_applied=False,
    )


# ---------------------------------------------------------------------------
# Reservation lifecycle helpers
# ---------------------------------------------------------------------------
async def create_reservation(
    conn, *, order_id: int, order_item_id: int, location_id: int, product_id: int,
    quantity: int, idempotency_key: str, expires_at=None, command_id=None,
) -> str:
    """Tạo reservation active (idempotent qua idempotency_key). Trả reservation id (str)."""
    rid = uuid.uuid5(uuid.NAMESPACE_OID, idempotency_key)
    await conn.execute(
        "INSERT INTO inventory_reservations "
        "(id,order_id,order_item_id,location_id,product_id,quantity_initial,quantity_remaining,"
        " status,expires_at,idempotency_key,created_command_id) "
        "VALUES ($1,$2,$3,$4,$5,$6,$6,'active',$7,$8,$9) ON CONFLICT (idempotency_key) DO NOTHING",
        rid, order_id, order_item_id, location_id, product_id, quantity, expires_at,
        idempotency_key, command_id,
    )
    got = await conn.fetchval(
        "SELECT id FROM inventory_reservations WHERE idempotency_key=$1", idempotency_key
    )
    return str(got)


async def terminate_reservation(conn, reservation_id, *, status: str, command_id=None) -> None:
    """Chuyển reservation active -> terminal (fulfilled/released/expired); set remaining=0. Idempotent."""
    await conn.execute(
        "UPDATE inventory_reservations "
        "SET status=$2, quantity_remaining=0, terminal_command_id=coalesce(terminal_command_id,$3), "
        "    terminal_at=now() "
        "WHERE id=$1 AND status='active'",
        reservation_id, status, command_id,
    )
