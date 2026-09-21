"""CA Directive 305 (+ Review 307 V02) — Shop Settings integrations API. RBAC granular per-action; readback REDACTED
(khong ciphertext/plaintext). Secret write-only + purge PO-only. Mutation qua service (audit + version CAS + durable
command_key idempotency + fail-closed). Module gate (307-01): flag OFF -> toan bo surface 404 (zero DB/provider effect)."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import require_active_session, require_permission
from app.config import settings
from app.services.settings import crypto as _crypto
from app.services.settings import integrations as svc


def require_settings_module():
    """307-01: khi settings_integrations_enabled=OFF, toan bo Settings surface tro thanh inert (404 deterministic).
    Khong read/mutation nao chay -> zero DB/provider effect. UI chi bat sau Apply rieng (Directive 305 §7)."""
    async def _dep():
        if not settings.settings_integrations_enabled:
            raise HTTPException(status_code=404, detail="Settings module chua bat")
        return True
    return _dep


router = APIRouter(prefix="/dashboard/settings", tags=["settings-integrations"],
                   dependencies=[Depends(require_active_session), Depends(require_settings_module())])

_P_VIEW = "settings.integration.view"
_P_PUBLIC = "settings.integration.manage_public"
_P_SECRET = "settings.integration.secret_write"
_P_PURGE = "settings.integration.secret_purge"
_P_TEST = "settings.integration.test"
_P_ACTIVATE = "settings.integration.activate"


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _actor(staff: dict) -> str:
    return staff.get("username") or f"staff:{staff.get('id')}"


def _map_err(e: Exception) -> HTTPException:
    if isinstance(e, svc.SettingsNotFound):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, svc.SettingsConflict):
        return HTTPException(status_code=409, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


def _int(body: dict, field: str, *, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise HTTPException(status_code=422, detail=f"thieu {field}")
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise HTTPException(status_code=422, detail=f"{field} phai so nguyen")
    return v


def _cmd_key(body: dict) -> str:
    v = body.get("command_key")
    if not isinstance(v, str) or not v.strip():
        raise HTTPException(status_code=422, detail="thieu command_key (idempotency)")
    return v.strip()


# ---------------------------------------------------------------- read
@router.get("/integrations", dependencies=[Depends(require_permission(_P_VIEW))])
async def list_integrations(kind: str | None = None) -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        items = await svc.list_integrations(conn, kind=kind)
        return {"items": items, "crypto_configured": _crypto.crypto_configured(),
                "module_enabled": settings.settings_integrations_enabled}
    finally:
        await conn.close()


@router.get("/integrations/{integration_id}", dependencies=[Depends(require_permission(_P_VIEW))])
async def get_integration(integration_id: int) -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        d = await svc.get_integration(conn, integration_id)
        if not d:
            raise HTTPException(status_code=404, detail="integration khong ton tai")
        return d
    finally:
        await conn.close()


# ---------------------------------------------------------------- create / update public
@router.post("/integrations", dependencies=[Depends(require_permission(_P_PUBLIC))])
async def create_integration(body: dict, staff: dict = Depends(require_active_session)) -> dict:
    for f in ("kind", "provider", "label", "mode"):
        if not isinstance(body.get(f), str) or not body[f]:
            raise HTTPException(status_code=422, detail=f"thieu {f}")
    ck = _cmd_key(body)
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await svc.create_integration(conn, kind=body["kind"], provider=body["provider"],
                                                label=body["label"], mode=body["mode"],
                                                config_public=body.get("config_public") or {}, actor=_actor(staff),
                                                command_key=ck)
    except svc.SettingsError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.patch("/integrations/{integration_id}", dependencies=[Depends(require_permission(_P_PUBLIC))])
async def update_public(integration_id: int, body: dict, staff: dict = Depends(require_active_session)) -> dict:
    ev = _int(body, "expected_version")
    ck = _cmd_key(body)
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await svc.update_public(conn, integration_id, label=body.get("label"),
                                           config_public=body.get("config_public"), expected_version=ev,
                                           actor=_actor(staff), command_key=ck)
    except svc.SettingsError as e:
        raise _map_err(e)
    finally:
        await conn.close()


# ---------------------------------------------------------------- secret (write-only)
@router.post("/integrations/{integration_id}/secret", dependencies=[Depends(require_permission(_P_SECRET))])
async def write_secret(integration_id: int, body: dict, staff: dict = Depends(require_active_session)) -> dict:
    key_name = body.get("key_name")
    value = body.get("value")
    if not isinstance(key_name, str) or not key_name:
        raise HTTPException(status_code=422, detail="thieu key_name")
    # value rong/omitted = GIU NGUYEN (CA 304-07 blank-keeps) -> no-op, khong loi, khong bump version,
    # khong doi hoi expected_version/command_key (khong mutation nao xay ra).
    if value is None or (isinstance(value, str) and value == ""):
        return {"key_name": key_name, "kept": True}
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="value phai chuoi")
    ev = _int(body, "expected_version")
    ck = _cmd_key(body)
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await svc.write_secret(conn, integration_id, key_name=key_name, plaintext=value,
                                          expected_version=ev, actor=_actor(staff), command_key=ck)
    except svc.SettingsError as e:
        raise _map_err(e)
    except _crypto.ConfigCryptoError:
        raise HTTPException(status_code=503, detail="crypto chua san sang (config key)")
    finally:
        await conn.close()


@router.post("/integrations/{integration_id}/secret/{key_name}/purge",
             dependencies=[Depends(require_permission(_P_PURGE))])
async def purge_secret(integration_id: int, key_name: str, body: dict,
                       staff: dict = Depends(require_active_session)) -> dict:
    """PO/owner-only (secret_purge). Tach khoi secret_write (307-06): nguoi chi co secret_write KHONG purge duoc."""
    ev = _int(body, "expected_version")
    ck = _cmd_key(body)
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await svc.purge_secret(conn, integration_id, key_name=key_name, expected_version=ev,
                                          actor=_actor(staff), command_key=ck)
    except svc.SettingsError as e:
        raise _map_err(e)
    finally:
        await conn.close()


# ---------------------------------------------------------------- test / enable / disable / archive
@router.post("/integrations/{integration_id}/test-connection", dependencies=[Depends(require_permission(_P_TEST))])
async def test_connection(integration_id: int, staff: dict = Depends(require_active_session)) -> dict:
    # KHONG bao transaction o API: service tu quan ly (GHN HAI PHA probe ngoai txn — 307-04; SePay readiness LOCAL).
    conn = await asyncpg.connect(_db_url())
    try:
        prov = await conn.fetchval("SELECT provider FROM integrations WHERE id=$1", integration_id)
        if prov is None:
            raise HTTPException(status_code=404, detail="integration khong ton tai")
        if prov == "sepay":
            return await svc.sepay_readiness(conn, integration_id, actor=_actor(staff))   # D306 §8 (308-02)
        return await svc.test_connection(conn, integration_id, actor=_actor(staff))
    except svc.SettingsError as e:
        raise _map_err(e)
    except _crypto.ConfigCryptoError:
        raise HTTPException(status_code=503, detail="crypto chua san sang (config key)")
    finally:
        await conn.close()


@router.post("/integrations/{integration_id}/enable", dependencies=[Depends(require_permission(_P_ACTIVATE))])
async def enable(integration_id: int, body: dict, staff: dict = Depends(require_active_session)) -> dict:
    ev = _int(body, "expected_version")
    ck = _cmd_key(body)
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await svc.enable(conn, integration_id, expected_version=ev, actor=_actor(staff), command_key=ck)
    except svc.SettingsError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/integrations/{integration_id}/disable", dependencies=[Depends(require_permission(_P_ACTIVATE))])
async def disable(integration_id: int, body: dict, staff: dict = Depends(require_active_session)) -> dict:
    ev = _int(body, "expected_version")
    ck = _cmd_key(body)
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await svc.disable(conn, integration_id, expected_version=ev, actor=_actor(staff), command_key=ck)
    except svc.SettingsError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/integrations/{integration_id}/archive", dependencies=[Depends(require_permission(_P_ACTIVATE))])
async def archive(integration_id: int, body: dict, staff: dict = Depends(require_active_session)) -> dict:
    ev = _int(body, "expected_version")
    ck = _cmd_key(body)
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await svc.archive(conn, integration_id, expected_version=ev, actor=_actor(staff), command_key=ck)
    except svc.SettingsError as e:
        raise _map_err(e)
    finally:
        await conn.close()
