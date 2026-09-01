"""M5 Phase 2 — API router: address resolution (verify/mapping). CA Directive 108.

Gate 2 tang: HTTP require_permission (address.resolve de tao, address.view de doc) + actor tu session (khong
tin body). Idempotency qua Idempotency-Key header. KHONG nhan secret/decision tu body. KHONG order/quote wiring.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from app.api.auth import require_active_session, require_permission
from app.db_pool import get_pool
from app.services.address import resolver

router = APIRouter(
    prefix="/dashboard/address-resolution",
    tags=["m5-address-resolution"],
    dependencies=[Depends(require_active_session)],
)


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, resolver.ResolveError):
        msg = str(exc)
        if "secret" in msg:
            return HTTPException(status_code=400, detail="Payload chua chuoi giong secret — tu choi")
        return HTTPException(status_code=400, detail=msg)
    return HTTPException(status_code=400, detail="Yeu cau khong hop le")


@router.post("/resolve", dependencies=[Depends(require_permission("address.resolve"))])
async def resolve(staff: dict = Depends(require_active_session),
                  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                  body: dict = Body(...)) -> dict:
    try:
        async with (await get_pool()).acquire() as conn:
            return await resolver.resolve(
                conn, subject_type=body.get("subject_type", "adhoc"), subject_id=body.get("subject_id"),
                province=body.get("province"), district=body.get("district"), ward=body.get("ward"),
                street_text=body.get("street_text"), as_of=body.get("as_of"),
                actor=staff["username"], reason=body.get("reason"), ticket=body.get("ticket"),
                idempotency_key=idempotency_key)
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.get("/{resolution_id}", dependencies=[Depends(require_permission("address.view"))])
async def get_resolution(resolution_id: str) -> dict:
    async with (await get_pool()).acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM address_resolution WHERE id=$1::uuid", resolution_id)
        if not row:
            raise HTTPException(status_code=404, detail="resolution khong ton tai")
    return resolver._row(row)
