"""M5 Phase 3 — API: customer confirmation + staff review queue (CA Directive 112).

Server-side RBAC (address.confirm / address.review / address.override), actor tu session (khong tin body),
idempotency, immutable audit o service. Dashboard chi trinh bay; backend enforce. KHONG order/quote wiring,
khong gui thong bao that (dormant). Response cua khach o dormant duoc drive qua session staff + binding
(bound_ref) — production se thay bang channel/session binding that.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from app.api.auth import require_active_session, require_permission
from app.db_pool import get_pool
from app.services.address import confirmation as conf
from app.services.address import review_queue as rq

confirmation_router = APIRouter(prefix="/dashboard/address-confirmation", tags=["m5-address-confirmation"],
                                dependencies=[Depends(require_active_session)])
review_router = APIRouter(prefix="/dashboard/address-review", tags=["m5-address-review"],
                          dependencies=[Depends(require_active_session)])


def _err(exc: Exception) -> HTTPException:
    msg = str(exc)
    if isinstance(exc, (conf.ConfirmationError, rq.ReviewQueueError)):
        if "SoD" in msg or "self-approval" in msg:
            return HTTPException(status_code=403, detail=msg)
        if "replay" in msg or "duplicate" in msg or "trang thai" in msg:
            return HTTPException(status_code=409, detail=msg)
        if "secret" in msg:
            return HTTPException(status_code=400, detail="Payload chua chuoi giong secret — tu choi")
        return HTTPException(status_code=400, detail=msg)
    return HTTPException(status_code=400, detail="Yeu cau khong hop le")


# ---- Customer confirmation ----
@confirmation_router.post("/issue", dependencies=[Depends(require_permission("address.confirm"))])
async def issue(staff: dict = Depends(require_active_session),
                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                body: dict = Body(...)) -> dict:
    try:
        async with (await get_pool()).acquire() as conn:
            # G-A-180-02 atomic issue+outbox; Amendment 182 staff-relay: bound customer derive server-side tu
            # resolution.subject; body bound_ref/actor/issued_by BI BO QUA.
            return await conf.issue_with_delivery(
                conn, resolution_id=body["resolution_id"], channel=body.get("channel", "web"),
                expiry_minutes=body.get("expiry_minutes", 60), actor=staff["username"],
                reason=body.get("reason"), ticket=body.get("ticket"), idempotency_key=idempotency_key)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"thieu truong {e}") from e
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@confirmation_router.post("/{request_id}/respond", dependencies=[Depends(require_permission("address.confirm"))])
async def respond(request_id: str, staff: dict = Depends(require_active_session), body: dict = Body(...)) -> dict:
    # Amendment 182 staff-relay: BUSINESS fields only (chosen_code/accept/reason/ticket). responding actor derive tu
    # staff session; body responder_ref/customer_ref/session_ref/actor/responded_by BI BO QUA (khong xac thuc).
    try:
        async with (await get_pool()).acquire() as conn:
            return await conf.respond(conn, request_id=request_id, chosen_code=body.get("chosen_code"),
                                      actor=staff["username"], accept=bool(body.get("accept", True)),
                                      reason=body.get("reason"), ticket=body.get("ticket"),
                                      idempotency_key=body.get("idempotency_key"))
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@confirmation_router.get("/{request_id}", dependencies=[Depends(require_permission("address.view"))])
async def get_confirmation(request_id: str) -> dict:
    async with (await get_pool()).acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM address_confirmation_request WHERE id=$1::uuid", request_id)
        if not r:
            raise HTTPException(status_code=404, detail="request khong ton tai")
    return conf._row(r)


# ---- Staff review queue ----
@review_router.get("/list", dependencies=[Depends(require_permission("address.review"))])
async def list_queue(state: str | None = None, limit: int = 50) -> list[dict]:
    async with (await get_pool()).acquire() as conn:
        if state:
            rows = await conn.fetch("SELECT * FROM address_review_queue WHERE state=$1 ORDER BY created_at DESC "
                                    "LIMIT $2", state, limit)
        else:
            rows = await conn.fetch("SELECT * FROM address_review_queue ORDER BY created_at DESC LIMIT $1", limit)
    return [rq._row(r) for r in rows]


@review_router.post("/enqueue", dependencies=[Depends(require_permission("address.review"))])
async def enqueue(staff: dict = Depends(require_active_session), body: dict = Body(...)) -> dict:
    try:
        async with (await get_pool()).acquire() as conn:
            return await rq.enqueue(conn, resolution_id=body["resolution_id"], reason=body.get("reason"),
                                    actor=staff["username"], ticket=body.get("ticket"),
                                    idempotency_key=body.get("idempotency_key"))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"thieu truong {e}") from e
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@review_router.post("/{queue_id}/assign", dependencies=[Depends(require_permission("address.review"))])
async def assign(queue_id: str, staff: dict = Depends(require_active_session), body: dict = Body(...)) -> dict:
    try:
        async with (await get_pool()).acquire() as conn:
            return await rq.assign(conn, queue_id=queue_id, assignee=body["assignee"], actor=staff["username"])
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"thieu truong {e}") from e
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@review_router.post("/{queue_id}/resolve", dependencies=[Depends(require_permission("address.review"))])
async def resolve(queue_id: str, staff: dict = Depends(require_active_session), body: dict = Body(...)) -> dict:
    is_override = bool(body.get("is_override"))
    if is_override and "address.override" not in staff.get("permissions", set()):
        raise HTTPException(status_code=403, detail="Thieu quyen: address.override")
    try:
        async with (await get_pool()).acquire() as conn:
            return await rq.resolve(conn, queue_id=queue_id, chosen_code=body.get("chosen_code"),
                                    actor=staff["username"], reason=body.get("reason"), ticket=body.get("ticket"),
                                    is_override=is_override, approver=body.get("approver"),
                                    affects_fulfillment=bool(body.get("affects_fulfillment")),
                                    accept=bool(body.get("accept", True)))
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e
