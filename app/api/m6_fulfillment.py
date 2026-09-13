"""M6 Delivery & Payment dashboard API (CA Directive 265 §4.1). JSON cho dashboard Next.js.

Board/filter theo shipment+payment status; detail (address snapshot, carrier, tracking, fee, ETA, attempts,
timeline, payment events); actions co RBAC per-action. Mutation goi service (audit + version CAS + idempotency).
Bot doc committed state qua path rieng (orchestrator), KHONG qua router nay.
"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import require_active_session, require_permission
from app.config import settings
from app.services.fulfillment import shipment_service as ship
from app.services.payment import payment_service as pay

router = APIRouter(prefix="/dashboard/fulfillment", tags=["m6-fulfillment"],
                   dependencies=[Depends(require_active_session)])

# RBAC evidence theo kind (Directive §4.2: tach quyen ghi evidence / xac nhan / reconcile).
_EVIDENCE_PERM = {
    "customer_reported": None,                 # ghi lai loi khach bao — bat ky staff active
    "cod_collected": "payment.cod_record",
    "shop_confirmed_received": "payment.transfer_confirm",
    "reconciled": "payment.reconcile",
    "correction": "payment.reconcile",
}


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _actor(staff: dict) -> str:
    return staff.get("username") or f"staff:{staff.get('id')}"


def _require(staff: dict, perm: str | None) -> None:
    """Enforce quyen theo body-driven kind (Depends khong lam duoc). Degrade khi RBAC chua provisioned + khong
    strict (giong require_permission)."""
    if perm is None:
        return
    if not staff.get("rbac_provisioned"):
        if settings.rbac_strict:
            raise HTTPException(status_code=403, detail="RBAC strict: chua provision/gan role")
        return
    if perm not in staff.get("permissions", set()):
        raise HTTPException(status_code=403, detail=f"Thieu quyen: {perm}")


def _map_err(e: Exception) -> HTTPException:
    msg = str(e)
    code = 409 if "version conflict" in msg else 400
    return HTTPException(status_code=code, detail=msg)


# ============================ Board / detail (read) ============================
@router.get("/board")
async def board(shipment_status: str | None = None, payment_status: str | None = None,
                limit: int = 200) -> list[dict]:
    """Danh sach don kem shipment + payment status (loc tuy chon)."""
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            "SELECT o.id AS order_id, o.status AS order_status, o.total_vnd, cu.name AS customer_name, "
            "s.status AS shipment_status, s.carrier, s.zone, s.delivery_fee_vnd, s.fee_status, s.eta_text, "
            "p.method AS payment_method, p.status AS payment_status, p.amount_due_vnd, o.created_at "
            "FROM orders o JOIN customers cu ON cu.id=o.customer_id "
            "LEFT JOIN shipments s ON s.order_id=o.id LEFT JOIN payments p ON p.order_id=o.id "
            "WHERE ($1::text IS NULL OR s.status=$1) AND ($2::text IS NULL OR p.status=$2) "
            "ORDER BY o.created_at DESC LIMIT $3", shipment_status, payment_status, limit)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


@router.get("/orders/{order_id}")
async def detail(order_id: int) -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        order = await conn.fetchrow(
            "SELECT o.id, o.status, o.total_vnd, o.created_at, cu.name AS customer_name, cu.phone "
            "FROM orders o JOIN customers cu ON cu.id=o.customer_id WHERE o.id=$1", order_id)
        if not order:
            raise HTTPException(status_code=404, detail="order khong ton tai")
        snap = await conn.fetchrow(
            "SELECT province_name, district_name, ward_name, street_text, province_code, ward_code "
            "FROM order_address_snapshot WHERE order_id=$1", order_id)
        sh = await conn.fetchrow("SELECT * FROM shipments WHERE order_id=$1", order_id)
        attempts = []
        if sh:
            attempts = [dict(r) for r in await conn.fetch(
                "SELECT attempt_no, attempted_at, result, reason, note, next_contact_at, recorded_by "
                "FROM shipment_delivery_attempts WHERE shipment_id=$1 ORDER BY attempt_no", sh["id"])]
        p = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", order_id)
        events = []
        if p:
            events = [dict(r) for r in await conn.fetch(
                "SELECT kind, amount_vnd, occurred_at, recorded_by, reference, note FROM payment_events "
                "WHERE payment_id=$1 ORDER BY occurred_at", p["id"])]
        return {"order": dict(order), "address_snapshot": dict(snap) if snap else None,
                "shipment": dict(sh) if sh else None, "attempts": attempts,
                "payment": dict(p) if p else None, "payment_events": events}
    finally:
        await conn.close()


# ============================ Shipment actions ============================
@router.post("/orders/{order_id}/shipment/quote")
async def shipment_quote(order_id: int, staff: dict = Depends(require_permission("shipment.manage"))) -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await ship.auto_quote(conn, order_id, actor=_actor(staff))
    except ship.ShipmentError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/orders/{order_id}/shipment/manual-quote")
async def shipment_manual_quote(order_id: int, body: dict,
                                staff: dict = Depends(require_permission("shipment.manage"))) -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await ship.set_manual_quote(
                conn, order_id, actor=_actor(staff), zone=body.get("zone"),
                weight_g=body.get("weight_g"),
                fee_vnd=int(body["fee_vnd"]) if body.get("fee_vnd") is not None else None,
                eta_text=body.get("eta_text"))
    except ship.ShipmentError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/orders/{order_id}/shipment/carrier")
async def shipment_carrier(order_id: int, body: dict,
                           staff: dict = Depends(require_permission("shipment.manage"))) -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await ship.set_carrier(conn, order_id, actor=_actor(staff),
                                          carrier=body.get("carrier"), tracking_text=body.get("tracking_text"))
    except ship.ShipmentError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/orders/{order_id}/shipment/status")
async def shipment_status(order_id: int, body: dict,
                          staff: dict = Depends(require_permission("fulfillment.status_change"))) -> dict:
    if not body.get("to_status"):
        raise HTTPException(status_code=422, detail="thieu to_status")
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await ship.change_status(conn, order_id, body["to_status"], actor=_actor(staff),
                                            expected_version=body.get("expected_version"))
    except ship.ShipmentError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/orders/{order_id}/shipment/attempt")
async def shipment_attempt(order_id: int, body: dict,
                           staff: dict = Depends(require_permission("fulfillment.status_change"))) -> dict:
    if not body.get("result"):
        raise HTTPException(status_code=422, detail="thieu result")
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await ship.record_attempt(conn, order_id, actor=_actor(staff), result=body["result"],
                                             reason=body.get("reason"), note=body.get("note"),
                                             next_contact_at=body.get("next_contact_at"))
    except ship.ShipmentError as e:
        raise _map_err(e)
    finally:
        await conn.close()


# ============================ Payment actions ============================
@router.post("/orders/{order_id}/payment/ensure")
async def payment_ensure(order_id: int, body: dict, staff: dict = Depends(require_active_session)) -> dict:
    if body.get("method") not in ("COD", "BANK_TRANSFER"):
        raise HTTPException(status_code=422, detail="method phai COD|BANK_TRANSFER")
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            p = await pay.ensure_payment(conn, order_id, method=body["method"], actor=_actor(staff))
            await pay.recompute_amount_due(conn, order_id, actor=_actor(staff))
            return p
    except pay.PaymentError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/orders/{order_id}/payment/evidence")
async def payment_evidence(order_id: int, body: dict, staff: dict = Depends(require_active_session)) -> dict:
    kind = body.get("kind")
    if kind not in _EVIDENCE_PERM:
        raise HTTPException(status_code=422, detail="kind khong hop le")
    _require(staff, _EVIDENCE_PERM[kind])
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await pay.record_evidence(
                conn, order_id, kind=kind,
                amount_vnd=int(body["amount_vnd"]) if body.get("amount_vnd") is not None else None,
                recorded_by=_actor(staff), reference=body.get("reference"), note=body.get("note"),
                attachment_ref=body.get("attachment_ref"))
    except pay.PaymentError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/orders/{order_id}/payment/instruction")
async def payment_instruction(order_id: int, staff: dict = Depends(require_active_session)) -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await pay.generate_instruction(conn, order_id, actor=_actor(staff))
    except pay.PaymentError as e:
        raise _map_err(e)
    finally:
        await conn.close()


# ============================ Bank account config ============================
@router.get("/bank-account")
async def get_bank_account(staff: dict = Depends(require_active_session)) -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        row = await conn.fetchrow("SELECT bank, account_number, holder_name, branch, version, is_test "
                                  "FROM bank_accounts WHERE active")
        return {"account": dict(row) if row else None}
    finally:
        await conn.close()


@router.post("/bank-account")
async def set_bank_account(body: dict, staff: dict = Depends(require_permission("bank.config"))) -> dict:
    for f in ("bank", "account_number", "holder_name"):
        if not body.get(f):
            raise HTTPException(status_code=422, detail=f"thieu {f}")
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            row = await pay.set_bank_account(
                conn, bank=body["bank"], account_number=body["account_number"],
                holder_name=body["holder_name"], branch=body.get("branch"),
                is_test=bool(body.get("is_test", False)), actor=_actor(staff))
            return {k: row[k] for k in ("id", "bank", "account_number", "holder_name", "version", "is_test")}
    except pay.PaymentError as e:
        raise _map_err(e)
    finally:
        await conn.close()
