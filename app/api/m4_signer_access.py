"""M4 — API router cho Signer Access Request (Directive 91 + Addendum 90).

Dashboard control/approval surface cho luong hop nhat: signer-role tam + activation window. Router
chi tao/di chuyen state machine; provision temp role + issue window do service lam (2 event, audit).

Gate 2 tang: (1) HTTP require_permission o day; (2) SoD (approver!=requester) enforce o service.
requester_staff_id/approver_staff_id LAY TU SESSION (khong tin body) — chong mao danh.
KHONG nhan secret/PIN/private key/token/customer data trong request body.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from app.api.auth import require_active_session, require_permission
from app.services.m4_signing import signer_access

router = APIRouter(
    prefix="/dashboard/signer-access",
    tags=["m4-signer-access"],
    dependencies=[Depends(require_active_session)],
)


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, signer_access.SignerAccessError):
        msg = str(exc)
        if "SoD" in msg:
            return HTTPException(status_code=403, detail=msg)
        if "idempotency" in msg or "dang mo" in msg or "terminal" in msg:
            return HTTPException(status_code=409, detail=msg)
        if "secret" in msg:
            return HTTPException(status_code=400, detail="Payload chua chuoi giong secret — tu choi")
        return HTTPException(status_code=400, detail=msg)
    return HTTPException(status_code=400, detail="Yeu cau khong hop le")


@router.get("/requests", dependencies=[Depends(require_permission("m4.signer_access.view"))])
async def list_requests(limit: int = 50) -> list[dict]:
    return await signer_access.list_requests(limit=limit)


@router.get("/requests/{request_id}",
            dependencies=[Depends(require_permission("m4.signer_access.view"))])
async def get_request(request_id: str) -> dict:
    req = await signer_access.get(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="request khong ton tai")
    return req


@router.post("/requests", dependencies=[Depends(require_permission("m4.signer_access.request"))])
async def submit(staff: dict = Depends(require_permission("m4.signer_access.request")),
                 body: dict = Body(...)) -> dict:
    try:
        return await signer_access.submit(
            request_id=body.get("request_id"), scope=body.get("scope") or {},
            artifact_digest=body.get("artifact_digest", ""), ticket=body.get("ticket", ""),
            reason=body.get("reason", ""), rollback_owner=body.get("rollback_owner", ""),
            requester_staff_id=staff["id"], window_minutes=int(body.get("window_minutes", 30)),
            is_rehearsal=bool(body.get("is_rehearsal", False)), actor=staff["username"])
    except Exception as exc:
        raise _err(exc) from None


@router.post("/requests/{request_id}/preflight",
             dependencies=[Depends(require_permission("m4.signer_access.request"))])
async def preflight(request_id: str,
                    staff: dict = Depends(require_permission("m4.signer_access.request"))) -> dict:
    try:
        return await signer_access.run_preflight(request_id, actor=staff["username"])
    except Exception as exc:
        raise _err(exc) from None


@router.post("/requests/{request_id}/approve",
             dependencies=[Depends(require_permission("m4.signer_access.approve"))])
async def approve(request_id: str,
                  staff: dict = Depends(require_permission("m4.signer_access.approve"))) -> dict:
    try:
        return await signer_access.approve(request_id, approver_staff_id=staff["id"],
                                           actor=staff["username"])
    except Exception as exc:
        raise _err(exc) from None


@router.post("/requests/{request_id}/close",
             dependencies=[Depends(require_permission("m4.signer_access.approve"))])
async def close(request_id: str,
                staff: dict = Depends(require_permission("m4.signer_access.approve"))) -> dict:
    try:
        return await signer_access.close(request_id, actor=staff["username"], staff_id=staff["id"])
    except Exception as exc:
        raise _err(exc) from None


@router.post("/requests/{request_id}/revoke",
             dependencies=[Depends(require_permission("m4.signer_access.approve"))])
async def revoke(request_id: str,
                 staff: dict = Depends(require_permission("m4.signer_access.approve")),
                 body: dict = Body(default={})) -> dict:
    try:
        return await signer_access.revoke(request_id, actor=staff["username"],
                                          reason=body.get("reason") or "revoke", staff_id=staff["id"])
    except Exception as exc:
        raise _err(exc) from None
