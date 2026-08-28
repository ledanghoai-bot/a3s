"""M4 — Production Signing Activation (Tier B) service.

Flow: request → preflight → approve (SoD) → activate (in window, TTL) → revoke/expire.
Xem docs/M4-SIGNING-ACTIVATION-DESIGN-VI.md. KHONG cham KMS/WIF/customer-data — preflight la
read-only stub (hook cho infra that sau); rehearsal chay tren digest gia.

Bat bien: capability rieng `m4.signing.activate.production`; SoD approver≠requester, activator≠
approver; artifact_digest anti-substitution (trigger DB); TTL/expiry auto-dormant; audit bat bien;
no-secret. Assignment/approval != tu dong ky — day chi cap capability co scope+TTL.
"""
from __future__ import annotations

import datetime as _dt
import json
import os

from app.db_pool import get_pool
from app.services import audit_service
from app.services.m4_signing import preflight_checks

ACTIVATE_CAP = "m4.signing.activate.production"
PREFLIGHT_FRESH_SECONDS = 15 * 60
POLICY_VERSION = "m4-activation-v1"

TRANSITIONS = {
    "REQUESTED": {"preflight_pass": "PREFLIGHT_PASSED", "preflight_fail": "REVOKED", "revoke": "REVOKED"},
    "PREFLIGHT_PASSED": {"approve": "APPROVED", "revoke": "REVOKED"},
    "APPROVED": {"activate": "ACTIVE", "expire": "EXPIRED", "revoke": "REVOKED"},
    "ACTIVE": {"close": "CLOSED", "expire": "EXPIRED", "revoke": "REVOKED"},
    "EXPIRED": {}, "REVOKED": {}, "CLOSED": {},
}
TERMINAL = frozenset({"EXPIRED", "REVOKED", "CLOSED"})


class ActivationError(Exception):
    """Loi nghiep vu activation (fail-closed, khong leak secret)."""


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _hydrate(row) -> dict:
    d = dict(row)
    if isinstance(d.get("scope"), str):
        try:
            d["scope"] = json.loads(d["scope"])
        except (ValueError, TypeError):
            d["scope"] = {}
    return d


async def _audit(conn, action, actid, actor, staff_id, before, after, reason):
    await audit_service.record(
        conn, actor_type="cli", action=f"signing.activation.{action}",
        actor_ref=actor, actor_staff_id=staff_id, entity_type="m4_signing_activation",
        entity_id=str(actid), before=before, after=after, reason=reason)


async def create_request(
    *, request_id: str, scope: dict, artifact_digest: str, manifest_ref: str | None,
    max_sign_count: int, reason: str, ticket: str, requester_staff_id: int,
    delegated_by: str | None, rollback_owner: str, actor: str,
) -> dict:
    """Signer tao request. Fail-closed neu thieu digest/ticket/reason/rollback_owner/scope."""
    if not (artifact_digest and artifact_digest.strip()):
        raise ActivationError("thieu artifact_digest (khoa boundary)")
    if not (ticket and reason and rollback_owner and request_id):
        raise ActivationError("thieu request_id/ticket/reason/rollback_owner")
    if not scope:
        raise ActivationError("thieu scope (data/tenant boundary)")
    if "pin_secret" in json.dumps(scope) or "-----BEGIN" in json.dumps(scope):
        raise ActivationError("scope chua chuoi giong secret")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            dup = await conn.fetchval(
                "SELECT activation_id FROM m4_signing_activation WHERE request_id=$1 "
                "AND state NOT IN ('EXPIRED','REVOKED','CLOSED')", request_id)
            if dup is not None:
                raise ActivationError(f"request_id '{request_id}' da co activation dang mo (idempotency)")
            row = await conn.fetchrow(
                "INSERT INTO m4_signing_activation "
                "(request_id,scope,artifact_digest,manifest_ref,max_sign_count,reason,ticket,"
                " requester_staff_id,delegated_by,rollback_owner,state) "
                "VALUES ($1,$2::jsonb,$3,$4,$5,$6,$7,$8,$9,$10,'REQUESTED') RETURNING *",
                request_id, json.dumps(scope), artifact_digest, manifest_ref, max_sign_count,
                reason, ticket, requester_staff_id, delegated_by, rollback_owner)
            await _audit(conn, "request", row["activation_id"], actor, requester_staff_id, None,
                         {"state": "REQUESTED", "digest": artifact_digest, "ticket": ticket,
                          "scope": scope, "delegated_by": delegated_by}, reason)
    return _hydrate(row)


async def get(activation_id: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM m4_signing_activation WHERE activation_id=$1",
                                  activation_id)
    return _hydrate(row) if row else None


def _preflight_deps():
    """Wire dependency THAT tu settings/env cho preflight_checks. KHONG goi backend/token o day
    (chi dung factory/closure) — moi loi thuc thi do check tu bat va fail-closed. KHONG nhan secret."""
    from app.config import settings
    from app.services.pii.kms_transport import get_kms_transport
    from app.services.pii.signing_backend import get_signing_backend

    app_env = settings.app_env
    env_backend = os.environ.get("M4_SIGNING_BACKEND", "").strip().lower()
    allow_localdev = os.environ.get("M4_ALLOW_LOCALDEV_SIGNING", "").strip() == "1"
    localdev_ok = (allow_localdev and env_backend == "localdev"
                   and app_env.strip().lower() not in ("production", "prod", "staging"))

    def backend_factory():
        if env_backend == "kms":
            transport, key_id, key_version = get_kms_transport(app_env)
            return get_signing_backend(app_env=app_env, transport=transport,
                                       key_id=key_id, key_version=key_version)
        return get_signing_backend(app_env=app_env)

    token_provider = None
    cfg = os.environ.get("M4_GOOGLE_CREDENTIAL_CONFIG")
    if cfg:
        from app.services.pii.google_credentials import GoogleWifTokenProvider
        try:
            token_provider = GoogleWifTokenProvider(cfg)
        except Exception as exc:  # noqa: BLE001 — construct loi -> cert_chain fail-closed
            _err = exc

            def token_provider():  # type: ignore[misc]
                raise _err

    async def redis_ping():
        import redis.asyncio as aioredis
        r = await aioredis.from_url(settings.redis_url, socket_timeout=3, socket_connect_timeout=3)
        try:
            return bool(await r.ping())
        finally:
            await r.aclose()

    return backend_factory, token_provider, redis_ping, localdev_ok


async def run_preflight(activation_id: str, *, actor: str) -> dict:
    """Preflight THAT (read-only, fail-closed). 3 check re noi bo + 4 check ha tang qua
    preflight_checks (kms_wif_health / cert_chain / clock_nonce_replay / no_conflicting_incident).
    Truoc khi KMS/WIF provision (Buoc 2/3) cac check ngoai fail-closed -> preflight khong pass (dung
    thiet ke dormant). Preflight fail -> REVOKED (phai request lai)."""
    act = await get(activation_id)
    if act is None:
        raise ActivationError("activation khong ton tai")
    if act["state"] != "REQUESTED":
        raise ActivationError(f"preflight chi tu REQUESTED (dang {act['state']})")
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "passed": ok, "detail": detail})

    add("digest_locked", bool(act["artifact_digest"]), "artifact_digest da khoa")
    add("scope_bounded", bool(act["scope"]), "scope khai bao")
    add("policy_version", True, POLICY_VERSION)

    backend_factory, token_provider, redis_ping, localdev_ok = _preflight_deps()

    pool = await get_pool()
    async with pool.acquire() as conn:
        real = await preflight_checks.run_all(
            conn, activation_id=activation_id, backend_factory=backend_factory,
            token_provider=token_provider, redis_ping=redis_ping, localdev_ok=localdev_ok)
        checks.extend(real)
        ok = all(c["passed"] for c in checks)
        async with conn.transaction():
            to = "PREFLIGHT_PASSED" if ok else "REVOKED"
            await conn.execute(
                "UPDATE m4_signing_activation SET state=$2, preflight_at=now(), updated_at=now(), "
                "terminal_at=CASE WHEN $2='REVOKED' THEN now() ELSE terminal_at END, "
                "terminal_reason=CASE WHEN $2='REVOKED' THEN 'preflight_fail' ELSE terminal_reason END "
                "WHERE activation_id=$1", activation_id, to)
            await _audit(conn, "preflight", activation_id, actor, None, {"state": act["state"]},
                         {"state": to, "ok": ok,
                          "checks": [{"name": c["name"], "passed": c["passed"],
                                      "detail": c["detail"]} for c in checks]},
                         None)
    return {"ok": ok, "checks": checks, "state": to}


async def approve(activation_id: str, *, approver_staff_id: int, actor: str,
                  window_minutes: int, emergency: bool = False,
                  emergency_reason: str | None = None) -> dict:
    """Approver duyet (SoD: khac requester) + cap window (TTL). Preflight phai tuoi."""
    act = await get(activation_id)
    if act is None:
        raise ActivationError("activation khong ton tai")
    if act["state"] != "PREFLIGHT_PASSED":
        raise ActivationError(f"approve chi tu PREFLIGHT_PASSED (dang {act['state']})")
    if act["requester_staff_id"] == approver_staff_id and not emergency:
        raise ActivationError("SoD: approver phai khac requester (tru emergency co ly do)")
    if emergency and not emergency_reason:
        raise ActivationError("emergency approve can emergency_reason (hau kiem bat buoc)")
    if act["preflight_at"] is None or (_now() - act["preflight_at"]).total_seconds() > PREFLIGHT_FRESH_SECONDS:
        raise ActivationError("preflight stale — chay lai preflight")
    if window_minutes < 1 or window_minutes > 240:
        raise ActivationError("window_minutes phai 1..240 (TTL ngan)")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "UPDATE m4_signing_activation SET state='APPROVED', approver_staff_id=$2, "
                "approved_at=now(), window_start=now(), window_end=now()+($3||' minutes')::interval, "
                "updated_at=now() WHERE activation_id=$1 RETURNING *",
                activation_id, approver_staff_id, str(window_minutes))
            await _audit(conn, "approve", activation_id, actor, approver_staff_id,
                         {"state": "PREFLIGHT_PASSED"},
                         {"state": "APPROVED", "window_minutes": window_minutes,
                          "emergency": emergency, "emergency_reason": emergency_reason,
                          "digest": act["artifact_digest"]}, emergency_reason)
    return _hydrate(row)


async def activate(activation_id: str, *, activator_staff_id: int, actor: str) -> dict:
    """Activator kich hoat (trong window, TTL). SoD: activator != approver. Tra receipt."""
    act = await get(activation_id)
    if act is None:
        raise ActivationError("activation khong ton tai")
    if act["state"] != "APPROVED":
        raise ActivationError(f"activate chi tu APPROVED (dang {act['state']})")
    if act["approver_staff_id"] == activator_staff_id:
        raise ActivationError("SoD: activator phai khac approver")
    if act["window_end"] is None or _now() >= act["window_end"]:
        raise ActivationError("qua TTL/window — activation het han (auto dormant)")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "UPDATE m4_signing_activation SET state='ACTIVE', activator_staff_id=$2, "
                "activated_at=now(), updated_at=now() WHERE activation_id=$1 RETURNING *",
                activation_id, activator_staff_id)
            await _audit(conn, "activate", activation_id, actor, activator_staff_id,
                         {"state": "APPROVED"},
                         {"state": "ACTIVE", "digest": act["artifact_digest"],
                          "window_end": act["window_end"].isoformat()}, None)
    receipt = {"activation_id": str(activation_id), "state": "ACTIVE",
               "digest": act["artifact_digest"], "scope": act["scope"],
               "window_end": act["window_end"].isoformat(),
               "max_sign_count": act["max_sign_count"]}
    return {"receipt": receipt, "activation": _hydrate(row)}


async def revoke(activation_id: str, *, actor: str, reason: str, staff_id: int | None = None) -> dict:
    """Revoke khan (PO) — moi state active -> REVOKED (dormant)."""
    if not reason:
        raise ActivationError("revoke can reason")
    act = await get(activation_id)
    if act is None:
        raise ActivationError("activation khong ton tai")
    if act["state"] in TERMINAL:
        raise ActivationError(f"da terminal ({act['state']}) — khong revoke")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "UPDATE m4_signing_activation SET state='REVOKED', terminal_at=now(), "
                "terminal_reason=$2, updated_at=now() WHERE activation_id=$1 RETURNING *",
                activation_id, reason)
            await _audit(conn, "revoke", activation_id, actor, staff_id,
                         {"state": act["state"]}, {"state": "REVOKED", "reason": reason}, reason)
    return _hydrate(row)


async def expire_due(*, actor: str = "system") -> int:
    """Auto-dormant: APPROVED/ACTIVE qua window_end -> EXPIRED. Tra so row expired."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                "UPDATE m4_signing_activation SET state='EXPIRED', terminal_at=now(), "
                "terminal_reason='ttl_expired', updated_at=now() "
                "WHERE state IN ('APPROVED','ACTIVE') AND window_end IS NOT NULL AND window_end < now() "
                "RETURNING activation_id, request_id")
            for r in rows:
                await _audit(conn, "expire", r["activation_id"], actor, None, None,
                             {"state": "EXPIRED", "reason": "ttl_expired"}, None)
    return len(rows)


async def close(activation_id: str, *, actor: str, staff_id: int | None = None) -> dict:
    """Danh dau hoan tat sau khi ky xong (ACTIVE -> CLOSED)."""
    act = await get(activation_id)
    if act is None:
        raise ActivationError("activation khong ton tai")
    if act["state"] != "ACTIVE":
        raise ActivationError(f"close chi tu ACTIVE (dang {act['state']})")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "UPDATE m4_signing_activation SET state='CLOSED', terminal_at=now(), "
                "terminal_reason='completed', updated_at=now() WHERE activation_id=$1 RETURNING *",
                activation_id)
            await _audit(conn, "close", activation_id, actor, staff_id, {"state": "ACTIVE"},
                         {"state": "CLOSED"}, None)
    return _hydrate(row)
