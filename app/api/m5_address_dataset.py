"""M5 Phase 1 — API router: dataset hanh chinh versioned + acceptance gate + registry (CA Directive 104).

Gate 2 tang: (1) HTTP require_permission (SoD-capable: ingest/review/manage tach perm); (2) SoD actor-distinct
enforce o control (dataset_registry). actor LAY TU SESSION (username), khong tin body. KHONG nhan secret/PIN/
private key/token/customer data. Dataset dormant: khong co active_version cho toi khi PO activate tuong minh.

Pham vi Phase 1: CHUA verify/mapping/order wiring. Chi quan tri vong doi dataset.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from app.api.auth import require_active_session, require_permission
from app.db_pool import get_pool
from app.services.address import dataset_registry as reg

router = APIRouter(
    prefix="/dashboard/address-dataset",
    tags=["m5-address-dataset"],
    dependencies=[Depends(require_active_session)],
)


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, reg.RegistryError):
        msg = str(exc)
        if "SoD" in msg:
            return HTTPException(status_code=403, detail=msg)
        if "da ton tai" in msg:
            return HTTPException(status_code=409, detail=msg)
        if "secret" in msg:
            return HTTPException(status_code=400, detail="Payload chua chuoi giong secret — tu choi")
        return HTTPException(status_code=400, detail=msg)
    return HTTPException(status_code=400, detail="Yeu cau khong hop le")


@router.get("/list", dependencies=[Depends(require_permission("address.dataset.view"))])
async def list_datasets(limit: int = 50) -> dict:
    async with (await get_pool()).acquire() as conn:
        rows = await conn.fetch(
            "SELECT version,status,source_kind,sha256,ingested_by,reviewed_by,approved_by,"
            "created_at,accepted_at,activated_at FROM admin_unit_dataset "
            "ORDER BY created_at DESC LIMIT $1", limit)
        active = await reg.get_active(conn)
    return {"active_version": active, "datasets": [dict(r) for r in rows]}


@router.get("/{version}", dependencies=[Depends(require_permission("address.dataset.view"))])
async def get_dataset(version: str) -> dict:
    async with (await get_pool()).acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM admin_unit_dataset WHERE version=$1", version)
        if not row:
            raise HTTPException(status_code=404, detail="version khong ton tai")
        n_units = await conn.fetchval("SELECT count(*) FROM admin_unit WHERE dataset_version=$1", version)
        n_alias = await conn.fetchval("SELECT count(*) FROM admin_unit_alias WHERE dataset_version=$1", version)
    d = dict(row)
    d.update({"n_units": n_units, "n_aliases": n_alias})
    return d


@router.post("/ingest", dependencies=[Depends(require_permission("address.dataset.ingest"))])
async def ingest(staff: dict = Depends(require_active_session), body: dict = Body(...)) -> dict:
    try:
        async with (await get_pool()).acquire() as conn:
            return await reg.ingest(
                conn, version=body["version"], source_url=body["source_url"],
                source_kind=body["source_kind"], license=body["license"], sha256=body["sha256"],
                provenance=body.get("provenance") or {}, units=body.get("units") or [],
                aliases=body.get("aliases") or [], release_tag=body.get("release_tag"),
                commit_ref=body.get("commit_ref"), downloaded_at=body.get("downloaded_at"),
                actor=staff["username"], reason=body.get("reason"), ticket=body.get("ticket"),
                apply=bool(body.get("apply")))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"thieu truong {e}") from e
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.post("/{version}/gate", dependencies=[Depends(require_permission("address.dataset.review"))])
async def run_gate(version: str, staff: dict = Depends(require_active_session), body: dict = Body(default={})) -> dict:
    try:
        async with (await get_pool()).acquire() as conn:
            return await reg.run_gate(
                conn, version=version, actor=staff["username"], reason=body.get("reason"),
                ticket=body.get("ticket"), regression=body.get("regression"))
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.post("/{version}/accept", dependencies=[Depends(require_permission("address.dataset.manage"))])
async def accept(version: str, staff: dict = Depends(require_active_session), body: dict = Body(default={})) -> dict:
    try:
        async with (await get_pool()).acquire() as conn:
            return await reg.accept(conn, version=version, actor=staff["username"],
                                    reason=body.get("reason"), ticket=body.get("ticket"),
                                    apply=bool(body.get("apply")))
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.post("/{version}/activate", dependencies=[Depends(require_permission("address.dataset.manage"))])
async def activate(version: str, staff: dict = Depends(require_active_session), body: dict = Body(default={})) -> dict:
    try:
        async with (await get_pool()).acquire() as conn:
            return await reg.activate(conn, version=version, actor=staff["username"],
                                      reason=body.get("reason"), ticket=body.get("ticket"),
                                      apply=bool(body.get("apply")))
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.post("/rollback", dependencies=[Depends(require_permission("address.dataset.manage"))])
async def rollback(staff: dict = Depends(require_active_session), body: dict = Body(...)) -> dict:
    try:
        async with (await get_pool()).acquire() as conn:
            return await reg.rollback(conn, to_version=body["to_version"], actor=staff["username"],
                                      reason=body.get("reason"), ticket=body.get("ticket"),
                                      apply=bool(body.get("apply")))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"thieu truong {e}") from e
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e
