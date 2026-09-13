"""M6 shipment service — tao/quote/status/attempt (CA Directive 265 §4.1). Domain SONG SONG orders.status.

Mutation: optimistic `version` compare-and-set (concurrency an toan) + audit; state machine fail-closed;
attempts append-only max 3 (retry cung attempt_no khong tang). KHONG tu cong ton kho khi giao that bai/hoan.
Notify (outbox) o notify.py rieng — service nay chi lo state + audit.
"""
from __future__ import annotations

from app.services import audit_service
from app.services.fulfillment import quote as _q

POLICY_VERSION = "robanme-giao-nhan-2026-09"

# State machine shipment (fail-closed). (from -> {to,...})
ALLOWED = {
    "pending_prep": {"ready_to_ship"},
    "ready_to_ship": {"in_transit", "pending_prep"},          # co the lui neu chua ban giao
    "in_transit": {"delivered", "delivery_failed"},
    "delivery_failed": {"in_transit", "return_pending"},      # retry (neu con luot) hoac chuyen cho hoan
    "delivered": set(),                                       # terminal thanh cong
    "return_pending": set(),                                  # terminal (staff xu ly hoan thu cong)
}
MAX_ATTEMPTS = 3


class ShipmentError(Exception):
    """Fail-closed. Khong leak secret."""


async def ensure_shipment(conn, order_id: int, *, actor: str) -> dict:
    """Get-or-create 1 shipment cho order (UNIQUE order_id -> idempotent)."""
    row = await conn.fetchrow("SELECT * FROM shipments WHERE order_id=$1", order_id)
    if row:
        return dict(row)
    if not await conn.fetchval("SELECT 1 FROM orders WHERE id=$1", order_id):
        raise ShipmentError(f"order {order_id} khong ton tai")
    row = await conn.fetchrow(
        "INSERT INTO shipments (order_id, status, zone, fee_status) VALUES ($1,'pending_prep','unknown','unknown') "
        "ON CONFLICT (order_id) DO UPDATE SET updated_at=now() RETURNING *", order_id)
    await audit_service.record(conn, actor_type="cli", action="shipment.create", actor_ref=actor,
                               entity_type="shipments", entity_id=str(row["id"]), after={"order_id": order_id})
    return dict(row)


async def _load_zone_rows(conn):
    return [dict(r) for r in await conn.fetch(
        "SELECT province_code, ward_code, zone, active FROM delivery_zones WHERE active")]


async def _load_fee_rules(conn):
    return [dict(r) for r in await conn.fetch(
        "SELECT zone, weight_min_g, weight_max_g, fee_vnd, quote_required, active FROM shipping_fee_rules WHERE active")]


async def _order_weight(conn, order_id: int) -> int | None:
    items = [dict(r) for r in await conn.fetch(
        "SELECT oi.quantity, p.shipping_weight_g FROM order_items oi JOIN products p ON p.id=oi.product_id "
        "WHERE oi.order_id=$1", order_id)]
    if not items:
        return None
    return _q.order_shipping_weight_g(items)


async def auto_quote(conn, order_id: int, *, actor: str) -> dict:
    """Resolve zone (tu order_address_snapshot) + weight (order_items x shipping_weight_g) + fee (rules).
    Thieu snapshot/weight/rule -> quote_required/unknown (KHONG bao gio 0 gia). Cap nhat shipment."""
    sh = await ensure_shipment(conn, order_id, actor=actor)
    snap = await conn.fetchrow(
        "SELECT province_code, ward_code FROM order_address_snapshot WHERE order_id=$1", order_id)
    zone = _q.resolve_zone(snap["province_code"] if snap else None,
                           snap["ward_code"] if snap else None, await _load_zone_rows(conn))
    weight = await _order_weight(conn, order_id)
    fee, fee_status = _q.quote_fee(zone, weight, await _load_fee_rules(conn))
    eta = _q.eta_text(zone)
    return await _apply_quote(conn, sh, zone=zone, weight_g=weight, fee_vnd=fee, fee_status=fee_status,
                              eta=eta, quote_source="auto_rule", actor=actor)


async def set_manual_quote(conn, order_id: int, *, actor: str, zone: str | None = None,
                           weight_g: int | None = None, fee_vnd: int | None = None,
                           eta_text: str | None = None) -> dict:
    """Staff chot tay (vd tinh khac 5500-10000g range, hoac zone unknown). fee_vnd cu the -> 'quoted'."""
    sh = await ensure_shipment(conn, order_id, actor=actor)
    z = zone or sh["zone"]
    if fee_vnd is not None:
        if fee_vnd < 0:
            raise ShipmentError("fee_vnd khong hop le")
        fee, fee_status = int(fee_vnd), "quoted"
    else:
        fee, fee_status = None, "quote_required"
    return await _apply_quote(conn, sh, zone=z, weight_g=weight_g if weight_g is not None else sh["weight_g"],
                              fee_vnd=fee, fee_status=fee_status,
                              eta=eta_text or sh["eta_text"] or _q.eta_text(z),
                              quote_source="staff_manual", actor=actor)


async def _apply_quote(conn, sh, *, zone, weight_g, fee_vnd, fee_status, eta, quote_source, actor) -> dict:
    row = await conn.fetchrow(
        "UPDATE shipments SET zone=$2, weight_g=$3, delivery_fee_vnd=$4, fee_status=$5, eta_text=$6, "
        "policy_version=$7, quote_source=$8, version=version+1, updated_at=now() WHERE id=$1 RETURNING *",
        sh["id"], zone, weight_g, fee_vnd, fee_status, eta, POLICY_VERSION, quote_source)
    await audit_service.record(conn, actor_type="cli", action="shipment.quote", actor_ref=actor,
                               entity_type="shipments", entity_id=str(sh["id"]),
                               after={"zone": zone, "weight_g": weight_g, "fee_vnd": fee_vnd,
                                      "fee_status": fee_status, "source": quote_source})
    return dict(row)


async def set_carrier(conn, order_id: int, *, actor: str, carrier: str | None, tracking_text: str | None) -> dict:
    sh = await ensure_shipment(conn, order_id, actor=actor)
    row = await conn.fetchrow(
        "UPDATE shipments SET carrier=$2, tracking_text=$3, version=version+1, updated_at=now() "
        "WHERE id=$1 RETURNING *", sh["id"], carrier, tracking_text)
    await audit_service.record(conn, actor_type="cli", action="shipment.carrier", actor_ref=actor,
                               entity_type="shipments", entity_id=str(sh["id"]),
                               after={"carrier": carrier, "tracking": bool(tracking_text)})
    return dict(row)


async def change_status(conn, order_id: int, to_status: str, *, actor: str,
                        expected_version: int | None = None) -> dict:
    """Optimistic CAS. Transition ngoai ALLOWED -> reject. Ban giao (in_transit) set handover_at."""
    sh = await conn.fetchrow("SELECT * FROM shipments WHERE order_id=$1", order_id)
    if not sh:
        raise ShipmentError(f"shipment cho order {order_id} chua ton tai")
    frm = sh["status"]
    if to_status not in ALLOWED.get(frm, set()):
        raise ShipmentError(f"transition khong hop le: {frm} -> {to_status}")
    if expected_version is not None and expected_version != sh["version"]:
        raise ShipmentError("version conflict (co cap nhat dong thoi) — tai lai roi thu lai")
    set_handover = ", handover_at=now()" if to_status == "in_transit" and sh["handover_at"] is None else ""
    row = await conn.fetchrow(
        f"UPDATE shipments SET status=$2, version=version+1, updated_at=now(){set_handover} "
        "WHERE id=$1 AND version=$3 RETURNING *", sh["id"], to_status, sh["version"])
    if row is None:
        raise ShipmentError("version conflict (concurrent) — huy cap nhat")
    await audit_service.record(conn, actor_type="cli", action="shipment.status", actor_ref=actor,
                               entity_type="shipments", entity_id=str(sh["id"]),
                               before={"status": frm}, after={"status": to_status})
    from app.services.fulfillment import (
        notify as _n,  # CA 265 §4.4: notify khach (atomic voi state)
    )
    await _n.notify_shipment(conn, order_id, to_status=to_status, sh=dict(row))
    return dict(row)


async def record_attempt(conn, order_id: int, *, actor: str, result: str, reason: str | None = None,
                         note: str | None = None, next_contact_at=None) -> dict:
    """Append 1 lan giao (max 3). result='success' -> delivered; 'failed' o lan 3 -> return_pending;
    'failed'/'no_contact' truoc lan 3 -> delivery_failed (staff hen lai/retry). Attempt append-only."""
    sh = await conn.fetchrow("SELECT * FROM shipments WHERE order_id=$1", order_id)
    if not sh:
        raise ShipmentError(f"shipment cho order {order_id} chua ton tai")
    used = await conn.fetchval("SELECT count(*) FROM shipment_delivery_attempts WHERE shipment_id=$1", sh["id"])
    if used >= MAX_ATTEMPTS:
        raise ShipmentError(f"da du {MAX_ATTEMPTS} lan giao — case ngoai le chuyen staff review, khong tao lan thu 4")
    if result not in ("success", "failed", "no_contact", "rescheduled"):
        raise ShipmentError("result khong hop le")
    attempt_no = used + 1
    att = await conn.fetchrow(
        "INSERT INTO shipment_delivery_attempts (shipment_id, attempt_no, result, reason, note, "
        "next_contact_at, recorded_by) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *",
        sh["id"], attempt_no, result, reason, note, next_contact_at, actor)
    # cap nhat shipment status theo ket qua (chi khi con transition hop le)
    new_status = None
    if result == "success" and "delivered" in ALLOWED.get(sh["status"], set()):
        new_status = "delivered"
    elif result in ("failed", "no_contact"):
        if attempt_no >= MAX_ATTEMPTS and "return_pending" in ALLOWED.get("delivery_failed", set()):
            new_status = "delivery_failed"  # se chuyen return_pending o buoc rieng (staff), khong tu suy hoan
        elif "delivery_failed" in ALLOWED.get(sh["status"], set()):
            new_status = "delivery_failed"
    if new_status and new_status != sh["status"]:
        await conn.execute("UPDATE shipments SET status=$2, version=version+1, updated_at=now() WHERE id=$1",
                           sh["id"], new_status)
        from app.services.fulfillment import (
            notify as _n,  # CA 265 §4.4: notify delivered/failed
        )
        await _n.notify_shipment(conn, order_id, to_status=new_status, sh=dict(sh))
    await audit_service.record(conn, actor_type="cli", action="shipment.attempt", actor_ref=actor,
                               entity_type="shipments", entity_id=str(sh["id"]),
                               after={"attempt_no": attempt_no, "result": result, "status": new_status or sh["status"]})
    return {"attempt": dict(att), "shipment_status": new_status or sh["status"], "attempts_used": attempt_no}
