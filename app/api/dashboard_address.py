"""CA Directive 396 §3.1 (F2) — danh muc dia chi (chi doc, theo dataset ACTIVE) cho form Dashboard + helper HTTP dung
chung cho tao don / xac minh don cu. Quyen: address.view (doc danh muc); staff_confirm can address.bind.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import check_permission, require_active_session, require_permission
from app.db_pool import get_pool
from app.services.address import dashboard_address as da

router = APIRouter(prefix="/dashboard/address-catalog", tags=["dashboard-address"],
                   dependencies=[Depends(require_active_session)])


def http_error(e: da.DashboardAddressError) -> HTTPException:
    status = 409 if e.code in ("needs_staff_confirmation", "dataset_unavailable") else 422
    detail = {"error_code": f"address_{e.code}", "message": str(e)}
    if e.candidates:
        detail["candidates"] = e.candidates
    return HTTPException(status_code=status, detail=detail)


@router.get("/provinces", dependencies=[Depends(require_permission("address.view"))])
async def provinces() -> dict:
    try:
        async with (await get_pool()).acquire() as conn:
            return await da.catalog_provinces(conn)
    except da.DashboardAddressError as e:
        raise http_error(e) from e


@router.get("/wards", dependencies=[Depends(require_permission("address.view"))])
async def wards(province_code: str = Query(..., min_length=1, max_length=10)) -> dict:
    try:
        async with (await get_pool()).acquire() as conn:
            return await da.catalog_wards(conn, province_code)
    except da.DashboardAddressError as e:
        raise http_error(e) from e


async def prepare(raw, staff: dict) -> dict:
    """Validate + precheck (KHONG ghi DB). Chua tu xac minh duoc va chua co staff_confirm -> 409 kem candidates
    (UI cho staff chon + nhap ly do). Tra addr (kem display_text) de truyen vao duong tao don/xac minh."""
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail={
            "error_code": "address_invalid_address",
            "message": "Dia chi phai chon Tinh + Phuong/Xa tu danh muc (khong nhan dia chi tu do)"})
    try:
        addr = da.parse_input(raw)
        if addr["staff_confirm"]:
            check_permission(staff, "address.bind")
        async with (await get_pool()).acquire() as conn:
            pc = await da.precheck(conn, addr)
            if not pc["auto"] and not addr["staff_confirm"]:
                raise da.DashboardAddressError(
                    "needs_staff_confirmation",
                    "Dia chi chua tu xac minh duoc — chon dung Phuong/Xa va nhap ly do xac nhan",
                    candidates=pc["candidates"])
            addr["display_text"] = await da.display_text(conn, addr)
        return addr
    except da.DashboardAddressError as e:
        raise http_error(e) from e
