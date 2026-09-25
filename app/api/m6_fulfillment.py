"""M6 Delivery & Payment dashboard API (CA Directive 265 §4.1). JSON cho dashboard Next.js.

Board/filter theo shipment+payment status; detail (address snapshot, carrier, tracking, fee, ETA, attempts,
timeline, payment events); actions co RBAC per-action. Mutation goi service (audit + version CAS + idempotency).
Bot doc committed state qua path rieng (orchestrator), KHONG qua router nay.
"""
from __future__ import annotations

from datetime import datetime

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import require_active_session, require_permission
from app.config import settings
from app.services.fulfillment import cancel_cascade
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


def _has_perm(staff: dict, perm: str) -> bool:
    if not staff.get("rbac_provisioned"):
        return not settings.rbac_strict
    return perm in staff.get("permissions", set())


async def guard_order_active(conn, order_id: int, staff: dict, *, exception_ok: bool = False) -> None:
    """CA Directive 387 §4.2/§6: don DA HUY khong con la workflow hanh dong duoc (chuan bi/thu tien/bao phi/QR).
    FOR SHARE (trong tx cua action) -> tuan tu hoa voi lenh huy (FOR UPDATE orders). Ngoai le: nguoi co
    order.cancel.exception van thao tac shipment/evidence (xu ly hang da ban giao / hoan tien) khi exception_ok."""
    st = await conn.fetchval("SELECT status FROM orders WHERE id=$1 FOR SHARE", order_id)
    if st in cancel_cascade.CANCELLED_ORDER_STATUSES:
        if exception_ok and _has_perm(staff, "order.cancel.exception"):
            return
        raise HTTPException(status_code=409, detail={"error_code": "order_cancelled",
                                                     "message": f"Don #{order_id} da huy — khong con thao tac duoc"})


def _map_err(e: Exception) -> HTTPException:
    msg = str(e)
    code = 409 if "version conflict" in msg else 400
    return HTTPException(status_code=code, detail=msg)


def _money(body: dict, field: str, *, required: bool = False) -> int | None:
    """CA 266-01: tien = so nguyen VND >= 0. Sai kieu/am -> 422 (khong de raise 500)."""
    v = body.get(field)
    if v is None:
        if required:
            raise HTTPException(status_code=422, detail=f"thieu {field}")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not v.is_integer()):
        raise HTTPException(status_code=422, detail=f"{field} phai so nguyen VND")
    iv = int(v)
    if iv < 0:
        raise HTTPException(status_code=422, detail=f"{field} phai >= 0")
    return iv


def _dt(body: dict, field: str):
    """Parse ISO-8601 datetime tu body; sai dinh dang -> 422."""
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"{field} sai dinh dang thoi gian (ISO-8601)")


def _command_key(body: dict) -> str:
    """CA 266-03: client phai gui command_key on-dinh cho mutation idempotent."""
    ck = body.get("command_key")
    if not ck or not isinstance(ck, str):
        raise HTTPException(status_code=422, detail="thieu command_key (idempotency key tu client)")
    return ck


# ============================ Board / detail (read) ============================
@router.get("/board")
async def board(shipment_status: str | None = None, payment_status: str | None = None,
                limit: int = 200) -> list[dict]:
    """Danh sach don kem shipment + payment status (loc tuy chon)."""
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            # CA Directive 387 §5: nguoi nhan THEO DON; ho so khach (chu tai khoan) chi fallback khi don legacy rong.
            "SELECT o.id AS order_id, o.status AS order_status, o.total_vnd, "
            "COALESCE(NULLIF(o.shipping_name,''), cu.name) AS customer_name, "
            "COALESCE(NULLIF(o.shipping_phone,''), cu.phone) AS recipient_phone, "
            "cu.name AS account_name, cu.channel AS account_channel, "
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
            "SELECT o.id, o.status, o.total_vnd, o.created_at, "
            "COALESCE(NULLIF(o.shipping_name,''), cu.name) AS customer_name, "
            "COALESCE(NULLIF(o.shipping_phone,''), cu.phone) AS phone, o.shipping_address, "
            "cu.name AS account_name, cu.channel AS account_channel, o.origin_channel "
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
        instruction = None
        if p:
            # CA 267-05: tra id + corrects_event_id de UI cho chon event goc khi correction (khong bat PO doan id)
            events = [dict(r) for r in await conn.fetch(
                "SELECT id, kind, amount_vnd, occurred_at, recorded_by, reference, note, corrects_event_id "
                "FROM payment_events WHERE payment_id=$1 ORDER BY occurred_at, id", p["id"])]
            # instruction moi nhat (neu co) — UI hien lai snapshot + copy sau reload
            instruction = await conn.fetchrow(
                "SELECT pi.bank_snapshot, pi.account_number_snapshot, pi.holder_snapshot, pi.transfer_content, "
                "pi.amount_vnd, pi.is_test, pi.created_at, v.voided_at FROM payment_instructions pi "
                "LEFT JOIN payment_instruction_voids v ON v.instruction_id=pi.id "
                "WHERE pi.payment_id=$1 ORDER BY pi.id DESC LIMIT 1", p["id"])
        return {"order": dict(order), "address_snapshot": dict(snap) if snap else None,
                "shipment": dict(sh) if sh else None, "attempts": attempts,
                "payment": dict(p) if p else None, "payment_events": events,
                "payment_instruction": dict(instruction) if instruction else None}
    finally:
        await conn.close()


# ============================ Shipment actions ============================
class _DashboardGateOffProvider:
    """CA 396 §3.2: gate dashboard_route_quote_enabled OFF -> KHONG goi GHN HTTP. Tra quote_required tat dinh (cung
    contract QuoteResult nhu provider that) -> route_and_quote xu ly nhu GHN tat (manual/fallback theo policy)."""

    async def quote(self, conn, req):
        from app.services.providers.base import QuoteResult
        return QuoteResult(status="quote_required", provider="ghn", reason=ship.DASHBOARD_GATE_OFF_REASON,
                           request_fingerprint=req.fingerprint())


@router.post("/orders/{order_id}/shipment/quote")
async def shipment_quote(order_id: int, body: dict | None = None,
                         staff: dict = Depends(require_permission("shipment.manage"))) -> dict:
    """"Tinh phi theo dia chi" (CA Directive 396 §3.2 — thay auto_rule M6):
    - Don CHUA co order_address_snapshot -> 409 address_not_verified (UI huong dan "Xac minh dia chi"). KHONG con tra
      200 thanh cong voi zone=unknown.
    - Co snapshot -> CHUNG pipeline dinh tuyen/bao phi voi Bot (route_operation: idempotent theo command_key,
      2 pha, ambiguous -> staff). Gate dashboard_route_quote_enabled OFF (mac dinh) -> KHONG GHN HTTP."""
    ck = _command_key(body or {})
    from app.services.fulfillment import route_operation as rops
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            await guard_order_active(conn, order_id, staff)
            has_snap = await conn.fetchval("SELECT 1 FROM order_address_snapshot WHERE order_id=$1", order_id)
        if not has_snap:
            raise HTTPException(status_code=409, detail={
                "error_code": "address_not_verified",
                "message": "Dia chi don chua xac minh — bam 'Xac minh dia chi' (chon Tinh/Phuong-Xa) truoc khi tinh phi"})
        provider = None if settings.dashboard_route_quote_enabled else _DashboardGateOffProvider()
        out = await rops.execute(conn, order_id, actor=_actor(staff), command_key=f"dash:{ck.strip()}",
                                 provider=provider)
        row = dict(out["shipment"]) if out.get("shipment") else {}
        row.pop("quote_snapshot", None)
        row["duplicate"] = out["duplicate"]
        row["provider_gate"] = "on" if settings.dashboard_route_quote_enabled else "off"
        return row
    except (rops.RouteOpConflict, rops.RouteOpInFlight, rops.RouteOpAmbiguous) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ship.ShipmentError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/orders/{order_id}/address/verify")
async def verify_order_address(order_id: int, body: dict,
                               staff: dict = Depends(require_permission("address.bind"))) -> dict:
    """CA 396 §3.1: "Xac minh dia chi" cho don CU chua snapshot — staff chon Tinh/Phuong-Xa + so nha (KHONG suy tu
    text cu). Resolve + bind snapshot + cap nhat chuoi hien thi trong MOT transaction. Da co snapshot -> 409."""
    from app.api import dashboard_address as _dah
    from app.services import audit_service
    from app.services.address import dashboard_address as da
    from app.services.address import order_binding as ob
    from app.services.address import resolver as res
    addr = await _dah.prepare(body, staff)
    display = addr.pop("display_text")
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            await guard_order_active(conn, order_id, staff)
            if await conn.fetchval("SELECT 1 FROM order_address_snapshot WHERE order_id=$1", order_id):
                raise HTTPException(status_code=409, detail={"error_code": "address_already_verified",
                                                             "message": "Don da co dia chi xac minh (snapshot bat bien)"})
            bound = await da.resolve_and_bind_in_tx(conn, order_id=order_id, addr=addr, actor=_actor(staff),
                                                    ticket=f"DASHADDR:verify:{order_id}")
            old = await conn.fetchval("SELECT shipping_address FROM orders WHERE id=$1", order_id)
            if old != display:
                await conn.execute("UPDATE orders SET shipping_address=$2 WHERE id=$1", order_id, display)
            await audit_service.record(conn, actor_type="cli", action="order.address_verified", actor_ref=_actor(staff),
                                       entity_type="orders", entity_id=str(order_id), before=None,
                                       after={"resolution_id": bound["resolution_id"],
                                              "verification": bound["verification"],
                                              "shipping_address_updated": old != display},
                                       reason=(addr.get("staff_confirm") or {}).get("reason") or "dashboard verify")
        return {"order_id": order_id, "verification": bound["verification"], "resolution_id": bound["resolution_id"],
                "shipping_address": display}
    except da.DashboardAddressError as e:
        raise _dah.http_error(e) from e
    except (ob.BindingError, res.ResolveError) as e:
        raise HTTPException(status_code=409, detail={"error_code": "address_bind_failed", "message": str(e)}) from e
    finally:
        await conn.close()


@router.post("/orders/{order_id}/shipment/manual-quote")
async def shipment_manual_quote(order_id: int, body: dict,
                                staff: dict = Depends(require_permission("shipment.manage"))) -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            await guard_order_active(conn, order_id, staff)
            return await ship.set_manual_quote(
                conn, order_id, actor=_actor(staff), zone=body.get("zone"),
                weight_g=_money(body, "weight_g"),
                fee_vnd=_money(body, "fee_vnd"),
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
            await guard_order_active(conn, order_id, staff, exception_ok=True)
            return await ship.set_carrier(conn, order_id, actor=_actor(staff),
                                          carrier=body.get("carrier"), tracking_text=body.get("tracking_text"),
                                          expected_version=body.get("expected_version"))
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
            await guard_order_active(conn, order_id, staff, exception_ok=True)
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
    command_key = _command_key(body)
    next_contact_at = _dt(body, "next_contact_at")
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            await guard_order_active(conn, order_id, staff, exception_ok=True)
            return await ship.record_attempt(conn, order_id, actor=_actor(staff), command_key=command_key,
                                             result=body["result"], reason=body.get("reason"),
                                             note=body.get("note"), next_contact_at=next_contact_at)
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
            await guard_order_active(conn, order_id, staff)
            await pay.ensure_payment(conn, order_id, method=body["method"], actor=_actor(staff))
            await pay.sync_amount_due_if_unsettled(conn, order_id, actor=_actor(staff))
            return dict(await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", order_id))
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
    command_key = _command_key(body)
    if kind == "correction":
        # CA 266-05: correction la delta dieu chinh received, CO THE AM (ghi du -> tru lai).
        raw = body.get("amount_vnd")
        if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)) or \
                (isinstance(raw, float) and not raw.is_integer()):
            raise HTTPException(status_code=422, detail="correction can amount_vnd (so nguyen, co the am)")
        amount_vnd = int(raw)
    elif kind == "reconciled":
        # CA Directive 293 §5: doi soat COD la accounting-only — KHONG yeu cau/khong cong so tien.
        amount_vnd = None
    else:
        amount_vnd = _money(body, "amount_vnd", required=True)
    corrects = body.get("corrects_event_id")
    if corrects is not None and not isinstance(corrects, int):
        raise HTTPException(status_code=422, detail="corrects_event_id phai so nguyen")
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            await guard_order_active(conn, order_id, staff, exception_ok=True)
            return await pay.record_evidence(
                conn, order_id, kind=kind, amount_vnd=amount_vnd, recorded_by=_actor(staff),
                command_key=command_key, reference=body.get("reference"), note=body.get("note"),
                attachment_ref=body.get("attachment_ref"), corrects_event_id=corrects)
    except pay.PaymentError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/orders/{order_id}/payment/instruction")
async def payment_instruction(order_id: int, staff: dict = Depends(require_active_session)) -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            await guard_order_active(conn, order_id, staff)
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
        row = await conn.fetchrow("SELECT bank, account_number, holder_name, branch, version, is_test, bin "
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
                is_test=bool(body.get("is_test", False)), actor=_actor(staff),
                bin_code=(str(body["bin"]).strip() if body.get("bin") else None))  # M7: NAPAS BIN cho VietQR
            return {k: row[k] for k in ("id", "bank", "account_number", "holder_name", "version", "is_test", "bin")}
    except pay.PaymentError as e:
        raise _map_err(e)
    finally:
        await conn.close()
