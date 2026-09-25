"""CA Directive 393 §2.2/§7 — Dashboard Staff entry point tao van don GHN (quyen rieng `shipment.ghn.create`).

Review (preview) -> staff xac nhan TUONG MINH (nhap lai ma don + fingerprint preview) -> `prepare` (1 transaction,
idempotent command_key). KHONG goi provider tu request: dispatch CHI o worker sau gate
`ghn_shipment_create_dashboard_enabled` (mac dinh OFF). Khong hien token; SDT mask; correlation mask.
"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import require_active_session, require_permission
from app.api.m6_fulfillment import guard_order_active
from app.config import settings
from app.services.fulfillment import ghn_shipment_create as gsc

router = APIRouter(prefix="/dashboard/fulfillment", tags=["ghn-shipment-create"],
                   dependencies=[Depends(require_active_session)])
PERM = "shipment.ghn.create"


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _actor(staff: dict) -> str:
    return staff.get("username") or f"staff:{staff.get('id')}"


def _err(e: gsc.ShipmentCreateError) -> HTTPException:
    return HTTPException(status_code=e.http_status, detail={"error_code": e.code, "message": e.message,
                                                            "blockers": e.blockers})


def _gates() -> dict:
    return {"dashboard": bool(settings.ghn_shipment_create_dashboard_enabled),
            "bot": bool(settings.ghn_shipment_create_bot_enabled), "mode": settings.ghn_active_mode}


@router.get("/orders/{order_id}/ghn-create/preview")
async def preview(order_id: int, staff: dict = Depends(require_permission(PERM))) -> dict:
    """Man hinh review: order/recipient, pickup, district/ward map, khoi luong/kich thuoc, quote/ETA, service, phi,
    payment/method + blockers/warnings + gate. KHONG ghi, KHONG goi provider."""
    conn = await asyncpg.connect(_db_url())
    try:
        ev = await gsc.evaluate(conn, order_id, source="dashboard")
        return {"order_id": order_id, "gates": _gates(), **gsc.redacted_preview(ev),
                "operations": await gsc.list_for_order(conn, order_id)}
    finally:
        await conn.close()


@router.post("/orders/{order_id}/ghn-create")
async def create_request(order_id: int, body: dict, staff: dict = Depends(require_permission(PERM))) -> dict:
    """Staff xac nhan tao yeu cau van don. Bat buoc: command_key, confirm_order_id == order_id (nhap lai),
    preview_fingerprint == fingerprint hien hanh. note tuy chon (<=500)."""
    body = body or {}
    if str(body.get("confirm_order_id", "")).strip().lstrip("#") != str(order_id):
        raise HTTPException(422, detail={"error_code": "confirmation_required",
                                         "message": "Nhap lai dung ma don de xac nhan tao van don"})
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            await guard_order_active(conn, order_id, staff)
            rc = await gsc.prepare(conn, order_id, source="dashboard", command_key=str(body.get("command_key") or ""),
                                   actor=_actor(staff), staff_id=int(staff["id"]),
                                   confirm_fingerprint=body.get("preview_fingerprint"), note=body.get("note"))
        return {**rc, "gates": _gates()}
    except gsc.ShipmentCreateError as e:
        raise _err(e) from e
    finally:
        await conn.close()


@router.get("/orders/{order_id}/ghn-create/operations")
async def operations(order_id: int, staff: dict = Depends(require_permission(PERM))) -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        return {"order_id": order_id, "gates": _gates(), "operations": await gsc.list_for_order(conn, order_id)}
    finally:
        await conn.close()


@router.post("/ghn-create/operations/{op_id}/reconcile")
async def reconcile(op_id: int, staff: dict = Depends(require_permission(PERM))) -> dict:
    """Doi soat theo client_order_code (read-only provider). Gate dashboard OFF -> 409 truoc HTTP."""
    conn = await asyncpg.connect(_db_url())
    try:
        return await gsc.reconcile(conn, op_id, staff_id=int(staff["id"]), actor=_actor(staff))
    except gsc.ShipmentCreateError as e:
        raise _err(e) from e
    finally:
        await conn.close()


@router.post("/ghn-create/operations/{op_id}/abandon")
async def abandon(op_id: int, body: dict, staff: dict = Depends(require_permission(PERM))) -> dict:
    """Dung yeu cau: truoc dispatch -> cancelled_before_dispatch; unknown -> failed_terminal (staff da kiem tra GHN).
    Ghi chu bat buoc. KHONG goi provider."""
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await gsc.abandon(conn, op_id, staff_id=int(staff["id"]), actor=_actor(staff),
                                     note=str((body or {}).get("note") or ""))
    except gsc.ShipmentCreateError as e:
        raise _err(e) from e
    finally:
        await conn.close()
