"""M4-9 — API router cho Dashboard-triggered Production Signing Run.

Dashboard la control/approval surface: router chi tao/di chuyen state machine + thu approval +
kich background job. Execution that su do arq worker (m4_signing_execute) goi CLI adapter.

Gate 2 tang: (1) HTTP require_permission(...) o day; (2) tang RBAC Postgres cua stage0p (pinned
actor) trong chinh CLI runner. SoD approve!=operator kiem o service (run_store.transition).

KHONG nhan secret/PIN/private key/token/customer data trong request body.
"""
from __future__ import annotations

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Body, Depends, HTTPException

from app.api.auth import require_active_session, require_permission
from app.config import settings
from app.services.m4_signing import policy, run_store

router = APIRouter(
    prefix="/dashboard/signing",
    tags=["m4-signing"],
    dependencies=[Depends(require_active_session)],
)

_redis_pool = None


async def _get_redis():
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _redis_pool


def _err(exc: Exception) -> HTTPException:
    """Map loi service -> HTTP, KHONG leak chi tiet nhay cam."""
    from app.services.m4_signing.run_store import (
        ActiveRunExists,
        InvalidTransition,
        SecretLeakBlocked,
        SoDViolation,
    )
    if isinstance(exc, InvalidTransition):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, SoDViolation):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, SecretLeakBlocked):
        return HTTPException(status_code=400, detail="Payload chua chuoi giong secret — tu choi")
    if isinstance(exc, ActiveRunExists):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail="Yeu cau khong hop le")


# --- Read -------------------------------------------------------------------
@router.get("/runs", dependencies=[Depends(require_permission("m4.signing.run.view"))])
async def list_runs(limit: int = 50) -> list[dict]:
    return await run_store.list_runs(limit=limit)


@router.get("/runs/{run_id}", dependencies=[Depends(require_permission("m4.signing.run.view"))])
async def get_run(run_id: str) -> dict:
    run = await run_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run khong ton tai")
    events = await run_store.list_events(run_id)
    counts = await run_store.attempt_counts(run_id)
    fresh_ok, fresh_detail = policy.is_preflight_fresh(run, events)
    return {"run": run, "events": events, "attempt_counts": counts,
            "preflight_fresh": {"ok": fresh_ok, "detail": fresh_detail}}


# --- Create / confirm -------------------------------------------------------
@router.post("/runs", dependencies=[Depends(require_permission("m4.signing.run.start"))])
async def create_run(
    staff: dict = Depends(require_permission("m4.signing.run.start")),
    body: dict = Body(...),
) -> dict:
    try:
        return await run_store.create_run(
            created_by=staff["id"],
            run_kind=body.get("run_kind", "synthetic_rehearsal"),
            change_ticket=body.get("change_ticket"),
            scope=body.get("scope") or {},
            window_start=body.get("window_start"),
            window_end=body.get("window_end"),
            quota_sts=int(body.get("quota_sts", 3)),
            quota_sign=int(body.get("quota_sign", 3)),
            data_boundary=body.get("data_boundary") or {},
        )
    except Exception as exc:
        raise _err(exc) from None


@router.post("/runs/{run_id}/confirm",
             dependencies=[Depends(require_permission("m4.signing.run.start"))])
async def confirm(run_id: str, staff: dict = Depends(require_permission("m4.signing.run.start")),
                  body: dict = Body(default={})) -> dict:
    try:
        return await run_store.transition(run_id, "confirm", actor_staff_id=staff["id"],
                                          reason=body.get("reason"))
    except Exception as exc:
        raise _err(exc) from None


# --- Preflight (server chay read-only) --------------------------------------
@router.post("/runs/{run_id}/preflight",
             dependencies=[Depends(require_permission("m4.signing.run.operate"))])
async def preflight(run_id: str,
                    staff: dict = Depends(require_permission("m4.signing.run.operate"))) -> dict:
    result = await policy.run_preflight(run_id)
    event = "preflight_pass" if result["ok"] else "preflight_fail"
    try:
        run = await run_store.transition(run_id, event, actor_staff_id=staff["id"],
                                         reason=None, detail={"ok": result["ok"]})
    except Exception as exc:
        raise _err(exc) from None
    return {"preflight": result, "run": run}


# --- Ceremony checkpoint (public metadata only) -----------------------------
@router.post("/runs/{run_id}/ceremony",
             dependencies=[Depends(require_permission("m4.signing.run.operate"))])
async def ceremony(run_id: str, staff: dict = Depends(require_permission("m4.signing.run.operate")),
                   body: dict = Body(...)) -> dict:
    # Chi nhan public metadata (fingerprint/serial/hash). Store se chan neu giong secret.
    meta = body.get("public_metadata") or {}
    run = await run_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run khong ton tai")
    events = await run_store.list_events(run_id)
    fresh_ok, fresh_detail = policy.is_preflight_fresh(run, events)
    if not fresh_ok:
        raise HTTPException(status_code=409, detail=f"Preflight khong tuoi: {fresh_detail}")
    try:
        return await run_store.transition(
            run_id, "ceremony_record", actor_staff_id=staff["id"],
            reason=body.get("reason"), set_operator=True, public_metadata=meta,
        )
    except Exception as exc:
        raise _err(exc) from None


# --- Canary request + approve (SoD) -----------------------------------------
@router.post("/runs/{run_id}/canary-request",
             dependencies=[Depends(require_permission("m4.signing.run.operate"))])
async def canary_request(run_id: str,
                         staff: dict = Depends(require_permission("m4.signing.run.operate"))) -> dict:
    try:
        return await run_store.transition(run_id, "canary_request", actor_staff_id=staff["id"])
    except Exception as exc:
        raise _err(exc) from None


@router.post("/runs/{run_id}/canary-approve",
             dependencies=[Depends(require_permission("m4.signing.run.approve"))])
async def canary_approve(run_id: str,
                         staff: dict = Depends(require_permission("m4.signing.run.approve")),
                         body: dict = Body(default={})) -> dict:
    try:
        return await run_store.transition(
            run_id, "canary_approve", actor_staff_id=staff["id"],
            reason=body.get("reason"), set_approver=True,
        )
    except Exception as exc:
        raise _err(exc) from None


# --- Execute (async qua arq worker) -----------------------------------------
@router.post("/runs/{run_id}/execute",
             dependencies=[Depends(require_permission("m4.signing.run.operate"))])
async def execute(run_id: str,
                  staff: dict = Depends(require_permission("m4.signing.run.operate")),
                  body: dict = Body(...)) -> dict:
    run = await run_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run khong ton tai")
    events = await run_store.list_events(run_id)
    fresh_ok, fresh_detail = policy.is_preflight_fresh(run, events)
    if not fresh_ok:
        raise HTTPException(status_code=409, detail=f"Preflight khong tuoi: {fresh_detail}")
    # Manifest/approval_ref la tham chieu KHONG nhay cam (path + ref); PIN lay server-side o worker.
    manifest = body.get("manifest")
    approval_ref = body.get("approval_ref")
    reviewer_staff_id = body.get("reviewer_staff_id")
    if not manifest or not approval_ref or not reviewer_staff_id:
        raise HTTPException(status_code=400, detail="Thieu manifest/approval_ref/reviewer_staff_id")
    try:
        run = await run_store.transition(run_id, "execute_start", actor_staff_id=staff["id"],
                                         reason=body.get("reason"))
    except Exception as exc:
        raise _err(exc) from None
    redis = await _get_redis()
    await redis.enqueue_job(
        "m4_signing_execute",
        {"run_id": run_id, "manifest": manifest, "approval_ref": approval_ref,
         "operator_staff_id": run["operator_staff_id"], "reviewer_staff_id": int(reviewer_staff_id)},
    )
    return {"run": run, "enqueued": True}


# --- Abort / break-glass ----------------------------------------------------
@router.post("/runs/{run_id}/abort",
             dependencies=[Depends(require_permission("m4.signing.run.abort"))])
async def abort(run_id: str, staff: dict = Depends(require_permission("m4.signing.run.abort")),
                body: dict = Body(...)) -> dict:
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Abort bat buoc co reason")
    try:
        return await run_store.transition(run_id, "abort", actor_staff_id=staff["id"],
                                          reason=reason, detail={"break_glass": bool(body.get("break_glass"))})
    except Exception as exc:
        raise _err(exc) from None
