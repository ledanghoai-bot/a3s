"""M2 order-transition + inventory API (I-B M2 Slice 6). Spec §13.2.

Mutation đi QUA command service (Idempotency-Key bắt buộc, effective-once) — KHÔNG sửa status/tồn bằng
CRUD generic (§7.3). RBAC per-action (require_permission). Reads: timeline/balance/ledger/reconciliation.
Gated sau flag M2_ORDER_TRANSITIONS (mutation) — tắt -> 409 feature_disabled.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.auth import require_permission, require_staff_session
from app.config import settings
from app.db_pool import acquire, release
from app.services.command import errors, lifecycle, registry
from app.services.command.envelope import Actor
from app.services.inventory.reconcile import reconcile_inventory

router = APIRouter(prefix="/dashboard", tags=["m2-inventory"])

# action -> (command_type, permission). cancel: exception perm khi order đang processing.
_ACTIONS: dict[str, tuple[str, str]] = {
    "confirm": (registry.ORDER_CONFIRM, "order.confirm"),
    "start_processing": (registry.ORDER_START_PROCESSING, "order.process"),
    "ready_for_fulfillment": (registry.ORDER_READY, "order.fulfillment.prepare"),
    "fulfill": (registry.ORDER_FULFILL, "order.fulfill"),
    "cancel": (registry.ORDER_CANCEL, "order.cancel"),
    # CA M2-S1-F03: quyền WRITE riêng cho từng mutation (KHÔNG dùng order.transition.view).
    "complete": (registry.ORDER_COMPLETE, "order.complete"),
    "mark_delivery_failed": (registry.ORDER_MARK_DELIVERY_FAILED, "order.delivery.manage"),
    "request_return": (registry.ORDER_REQUEST_RETURN, "order.return.manage"),
    "return_inspect": (registry.INVENTORY_RETURN_INSPECT, "order.return.manage"),
}


def _check_perm(staff: dict, perm: str) -> None:
    """Enforce quyền cụ thể (giữ degrade như require_permission khi RBAC chưa provisioned)."""
    if not staff.get("rbac_provisioned"):
        if settings.rbac_strict:
            raise HTTPException(403, "RBAC strict: chua provision/gan role")
        return
    if perm not in staff.get("permissions", set()):
        raise HTTPException(403, f"Thieu quyen: {perm}")


def _require_flag() -> None:
    if not settings.m2_order_transitions:
        raise HTTPException(409, "M2 order transitions chua bat (feature_disabled)")


def _staff_actor(staff: dict) -> Actor:
    return Actor("staff", str(staff["id"]))


def _receipt_or_raise(receipt) -> dict:
    if receipt.outcome == "rejected":
        # business reject -> map error_code sang http (illegal 409, SoD/perm 403, else 422)
        code = receipt.error_code or "rejected"
        status = 409 if code == "illegal_order_transition" else (
            403 if code in ("separation_of_duties", "not_unit_head", "staff_required") else (
                404 if code in ("adjustment_not_found",) else 422))
        raise HTTPException(status, detail={"error_code": code, "receipt": receipt.to_dict()})
    return receipt.to_dict()


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------
@router.post("/orders/{order_id}/transitions")
async def order_transition(
    order_id: int, body: dict,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    staff: dict = Depends(require_staff_session),
) -> dict:
    _require_flag()
    if not idempotency_key:
        raise HTTPException(400, "Thieu Idempotency-Key.")
    action = (body or {}).get("action")
    if action not in _ACTIONS:
        raise HTTPException(422, f"action khong hop le: {action}")
    command_type, perm = _ACTIONS[action]
    # cancel khi processing -> can quyen ngoai le
    if action == "cancel":
        conn = await acquire()
        try:
            st = await conn.fetchval("SELECT status FROM orders WHERE id=$1", order_id)
        finally:
            await release(conn)
        if st == "processing":
            perm = "order.cancel.exception"
    _check_perm(staff, perm)
    env = lifecycle.build_lifecycle_envelope(
        command_type=command_type, payload={"order_id": order_id, "reason": (body or {}).get("reason")},
        actor=_staff_actor(staff), channel="dashboard", idempotency_key=idempotency_key)
    try:
        receipt = await lifecycle.execute_lifecycle(env)
    except errors.CommandError as e:
        raise HTTPException(e.http_status, detail={"error_code": e.code, "message": e.message}) from e
    return _receipt_or_raise(receipt)


@router.get("/orders/{order_id}/timeline")
async def order_timeline(order_id: int, staff: dict = Depends(require_permission("order.transition.view"))) -> list[dict]:
    conn = await acquire()
    try:
        rows = await conn.fetch(
            "SELECT event_type, from_status, to_status, inventory_status_before, inventory_status_after, "
            "actor_type, actor_id, reason, occurred_at FROM order_events WHERE order_id=$1 "
            "ORDER BY occurred_at", order_id)
    finally:
        await release(conn)
    return [dict(r) | {"occurred_at": r["occurred_at"].isoformat()} for r in rows]


# ---------------------------------------------------------------------------
# Inventory reads
# ---------------------------------------------------------------------------
@router.get("/inventory/balances")
async def inventory_balances(staff: dict = Depends(require_permission("inventory.view"))) -> list[dict]:
    conn = await acquire()
    try:
        rows = await conn.fetch(
            "SELECT l.code AS location, p.sku, b.on_hand, b.reserved, b.on_hand-b.reserved AS available "
            "FROM inventory_balances b JOIN inventory_locations l ON l.id=b.location_id "
            "JOIN products p ON p.id=b.product_id ORDER BY l.code, p.sku")
    finally:
        await release(conn)
    return [dict(r) for r in rows]


@router.get("/inventory/movements")
async def inventory_movements(
    product_id: int | None = None, limit: int = 200,
    staff: dict = Depends(require_permission("inventory.movement.view")),
) -> list[dict]:
    conn = await acquire()
    try:
        rows = await conn.fetch(
            "SELECT movement_type, on_hand_delta, reserved_delta, before_on_hand, after_on_hand, "
            "before_reserved, after_reserved, reference_type, reference_id, actor_type, actor_id, created_at "
            "FROM inventory_movements WHERE ($1::bigint IS NULL OR product_id=$1) "
            "ORDER BY created_at DESC LIMIT $2", product_id, min(limit, 500))
    finally:
        await release(conn)
    return [dict(r) | {"created_at": r["created_at"].isoformat()} for r in rows]


@router.get("/inventory/reconciliation")
async def inventory_reconciliation(staff: dict = Depends(require_permission("inventory.reconcile"))) -> dict:
    conn = await acquire()
    try:
        rep = await reconcile_inventory(conn, check_stock_compat=True)
    finally:
        await release(conn)
    return rep.as_dict()


# ---------------------------------------------------------------------------
# Adjustments
# ---------------------------------------------------------------------------
@router.get("/inventory/adjustments")
async def list_adjustments(status: str = "pending", staff: dict = Depends(require_permission("inventory.adjust"))) -> list[dict]:
    conn = await acquire()
    try:
        rows = await conn.fetch(
            "SELECT id, location_id, product_id, quantity_delta, is_large, status, reason, "
            "requested_by_staff_id, approved_by_staff_id, requested_at "
            "FROM inventory_adjustment_requests WHERE status=$1 ORDER BY requested_at DESC LIMIT 200", status)
    finally:
        await release(conn)
    return [dict(r) | {"id": str(r["id"]), "requested_at": r["requested_at"].isoformat()} for r in rows]


async def _run_adjust(command_type: str, payload: dict, idempotency_key: str | None, staff: dict) -> dict:
    _require_flag()
    if not idempotency_key:
        raise HTTPException(400, "Thieu Idempotency-Key.")
    env = lifecycle.build_lifecycle_envelope(
        command_type=command_type, payload=payload, actor=_staff_actor(staff),
        channel="dashboard", idempotency_key=idempotency_key)
    try:
        receipt = await lifecycle.execute_lifecycle(env)
    except errors.CommandError as e:
        raise HTTPException(e.http_status, detail={"error_code": e.code, "message": e.message}) from e
    return _receipt_or_raise(receipt)


@router.post("/inventory/adjustments")
async def request_adjustment(
    body: dict, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    staff: dict = Depends(require_permission("inventory.adjust")),
) -> dict:
    return await _run_adjust(registry.ADJUST_REQUEST, {
        "location_id": (body or {}).get("location_id"), "product_id": (body or {}).get("product_id"),
        "quantity_delta": (body or {}).get("quantity_delta"), "reason": (body or {}).get("reason"),
        "evidence_ref": (body or {}).get("evidence_ref"),
    }, idempotency_key, staff)


@router.post("/inventory/adjustments/{request_id}/approve")
async def approve_adjustment(
    request_id: str, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    staff: dict = Depends(require_permission("inventory.adjust.approve")),
) -> dict:
    return await _run_adjust(registry.ADJUST_APPROVE, {"request_id": request_id}, idempotency_key, staff)


@router.post("/inventory/adjustments/{request_id}/reject")
async def reject_adjustment(
    request_id: str, body: dict,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    staff: dict = Depends(require_permission("inventory.adjust.approve")),
) -> dict:
    return await _run_adjust(registry.ADJUST_REJECT, {"request_id": request_id, "reason": (body or {}).get("reason")},
                             idempotency_key, staff)
