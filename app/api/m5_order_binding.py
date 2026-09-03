"""M5 Phase 4 — API: order snapshot binding + quote_shipping contract (CA Directive 116).

Server-side RBAC (address.bind de bind; address.view de quote/xem). actor tu session. Shadow-mode: quote
enforcement production tat mac dinh. KHONG mutate order production tu dong; chi thao tac tuong minh khi test/bat.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from app.api.auth import require_active_session, require_permission
from app.db_pool import get_pool
from app.services.address import order_binding as ob

router = APIRouter(prefix="/dashboard/address-binding", tags=["m5-address-binding"],
                   dependencies=[Depends(require_active_session)])


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, ob.BindingError):
        msg = str(exc)
        if "da bind" in msg:
            return HTTPException(status_code=409, detail=msg)
        if "wrong-owner" in msg:
            return HTTPException(status_code=403, detail=msg)
        return HTTPException(status_code=400, detail=msg)
    return HTTPException(status_code=400, detail="Yeu cau khong hop le")


@router.post("/bind", dependencies=[Depends(require_permission("address.bind"))])
async def bind(staff: dict = Depends(require_active_session), body: dict = Body(...)) -> dict:
    try:
        async with (await get_pool()).acquire() as conn:
            return await ob.bind_order(conn, order_id=int(body["order_id"]), resolution_id=body["resolution_id"],
                                       actor=staff["username"], reason=body.get("reason"), ticket=body.get("ticket"),
                                       expected_customer_ref=body.get("expected_customer_ref"),
                                       apply=bool(body.get("apply")))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"thieu truong {e}") from e
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.post("/quote", dependencies=[Depends(require_permission("address.view"))])
async def quote(body: dict = Body(...)) -> dict:
    try:
        async with (await get_pool()).acquire() as conn:
            return await ob.quote_shipping(conn, verified_address_id=body.get("verified_address_id"),
                                           order_id=body.get("order_id"),
                                           expected_customer_ref=body.get("expected_customer_ref"))
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.get("/order-snapshot/{order_id}", dependencies=[Depends(require_permission("address.view"))])
async def get_snapshot(order_id: int) -> dict:
    async with (await get_pool()).acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM order_address_snapshot WHERE order_id=$1", order_id)
        if not r:
            raise HTTPException(status_code=404, detail="order chua co snapshot")
    return ob._snap(r)
