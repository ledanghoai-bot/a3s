"""M4 — Signer Access Request orchestrator (Directive 91 + Addendum 90).

UI request hop nhat: signer-role TAM THOI + activation window. Backend tach 2 event khi approve:
  (1) provision temp signer role (m4_temp_signer_role_grant, valid_until=window_end, auto-revoke);
  (2) issue activation window (m4_signing_activation row lien ket).
Flow: submit -> preflight (that) -> approve (SoD: approver!=requester) -> ACTIVE -> close/expire/revoke
      -> auto-revoke temp role + terminal activation.

Bat bien (KHONG noi): SoD server-side; capability activate.production dormant; role temp allowlist
m4_signing_operator; rehearsal grant KHONG cap quyen that; digest lock; fail-closed; audit bat bien
no-secret. UI khong bao gio la lop enforce duy nhat.
"""
from __future__ import annotations

import datetime as _dt
import json
import uuid as _uuid

from app.db_pool import get_pool
from app.services import audit_service
from app.services.m4_signing import activation, preflight_checks, rbac_provisioning

ROLE_KEY = "m4_signing_operator"
PREFLIGHT_FRESH_SECONDS = 15 * 60
POLICY_VERSION = "m4-signer-access-v1"

TRANSITIONS = {
    "SUBMITTED": {"preflight_pass": "PREFLIGHT_PASSED", "preflight_fail": "REVOKED", "revoke": "REVOKED"},
    "PREFLIGHT_PASSED": {"approve": "ACTIVE", "revoke": "REVOKED"},
    "ACTIVE": {"close": "CLOSED", "expire": "EXPIRED", "revoke": "REVOKED"},
    "CLOSED": {}, "EXPIRED": {}, "REVOKED": {},
}
TERMINAL = frozenset({"CLOSED", "EXPIRED", "REVOKED"})


class SignerAccessError(Exception):
    """Loi nghiep vu (fail-closed, khong leak secret)."""


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


async def _audit(conn, action, rid, actor, staff_id, before, after, reason):
    await audit_service.record(
        conn, actor_type="cli", action=f"signer_access.{action}", actor_ref=actor,
        actor_staff_id=staff_id, entity_type="m4_signer_access_request", entity_id=str(rid),
        before=before, after=after, reason=reason)


async def submit(*, request_id: str, scope: dict, artifact_digest: str, ticket: str, reason: str,
                 rollback_owner: str, requester_staff_id: int, window_minutes: int,
                 is_rehearsal: bool = False, actor: str) -> dict:
    """Signer gui request. Fail-closed thieu field. Idempotency theo request_id."""
    if not (artifact_digest and artifact_digest.strip()):
        raise SignerAccessError("thieu artifact_digest")
    if not (request_id and ticket and reason and rollback_owner):
        raise SignerAccessError("thieu request_id/ticket/reason/rollback_owner")
    if not scope:
        raise SignerAccessError("thieu scope")
    if not (1 <= int(window_minutes) <= 240):
        raise SignerAccessError("window_minutes phai 1..240 (TTL ngan)")
    if "pin_secret" in json.dumps(scope) or "-----BEGIN" in json.dumps(scope):
        raise SignerAccessError("scope chua chuoi giong secret")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            dup = await conn.fetchval(
                "SELECT request_id FROM m4_signer_access_request WHERE request_id=$1 "
                "AND state NOT IN ('CLOSED','EXPIRED','REVOKED')", request_id)
            if dup is not None:
                raise SignerAccessError(f"request_id '{request_id}' dang mo (idempotency)")
            row = await conn.fetchrow(
                "INSERT INTO m4_signer_access_request "
                "(request_id,scope,artifact_digest,ticket,reason,rollback_owner,requester_staff_id,"
                " window_minutes,is_rehearsal,state) "
                "VALUES ($1,$2::jsonb,$3,$4,$5,$6,$7,$8,$9,'SUBMITTED') RETURNING *",
                request_id, json.dumps(scope), artifact_digest, ticket, reason, rollback_owner,
                requester_staff_id, window_minutes, is_rehearsal)
            await _audit(conn, "submit", request_id, actor, requester_staff_id, None,
                         {"state": "SUBMITTED", "digest": artifact_digest, "ticket": ticket,
                          "is_rehearsal": is_rehearsal, "window_minutes": window_minutes}, reason)
    return _hydrate(row)


async def get(request_id: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM m4_signer_access_request WHERE request_id=$1", request_id)
    return _hydrate(row) if row else None


async def list_requests(limit: int = 50) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM m4_signer_access_request ORDER BY created_at DESC LIMIT $1", limit)
    return [_hydrate(r) for r in rows]


async def run_preflight(request_id: str, *, actor: str) -> dict:
    """Preflight THAT (read-only, fail-closed) — dung preflight_checks nhu activation. Fail -> REVOKED."""
    req = await get(request_id)
    if req is None:
        raise SignerAccessError("request khong ton tai")
    if req["state"] != "SUBMITTED":
        raise SignerAccessError(f"preflight chi tu SUBMITTED (dang {req['state']})")
    checks = [{"name": "digest_locked", "passed": bool(req["artifact_digest"]), "detail": "khoa"},
              {"name": "scope_bounded", "passed": bool(req["scope"]), "detail": "scope"},
              {"name": "policy_version", "passed": True, "detail": POLICY_VERSION}]
    backend_factory, token_provider, redis_ping, localdev_ok = activation._preflight_deps()
    pool = await get_pool()
    async with pool.acquire() as conn:
        # no_conflicting_incident so voi m4_signing_activation.activation_id (UUID) — truyen UUID
        # throwaway (request_id la TEXT, khong phai activation row). Check van dem cac activation
        # APPROVED/ACTIVE khac (single-active production window).
        real = await preflight_checks.run_all(
            conn, activation_id=str(_uuid.uuid4()), backend_factory=backend_factory,
            token_provider=token_provider, redis_ping=redis_ping, localdev_ok=localdev_ok)
        checks.extend(real)
        ok = all(c["passed"] for c in checks)
        async with conn.transaction():
            to = "PREFLIGHT_PASSED" if ok else "REVOKED"
            await conn.execute(
                "UPDATE m4_signer_access_request SET state=$2, preflight_at=now(), updated_at=now(), "
                "terminal_at=CASE WHEN $2='REVOKED' THEN now() ELSE terminal_at END, "
                "terminal_reason=CASE WHEN $2='REVOKED' THEN 'preflight_fail' ELSE terminal_reason END "
                "WHERE request_id=$1", request_id, to)
            await _audit(conn, "preflight", request_id, actor, None, {"state": req["state"]},
                         {"state": to, "ok": ok,
                          "checks": [{"name": c["name"], "passed": c["passed"]} for c in checks]}, None)
    return {"ok": ok, "checks": checks, "state": to}


async def _staff_has_static_role(conn, staff_id: int) -> bool:
    return bool(await conn.fetchval("SELECT 1 FROM staff_users WHERE id=$1 AND role_key=$2",
                                    staff_id, ROLE_KEY))


async def approve(request_id: str, *, approver_staff_id: int, actor: str) -> dict:
    """PO/approver duyet (SoD: approver != requester). Tach 2 event: provision temp role + issue window.
    Preflight phai tuoi. Neu requester da co role signer -> KHONG cap temp role (chi issue window)."""
    req = await get(request_id)
    if req is None:
        raise SignerAccessError("request khong ton tai")
    if req["state"] != "PREFLIGHT_PASSED":
        raise SignerAccessError(f"approve chi tu PREFLIGHT_PASSED (dang {req['state']})")
    if req["requester_staff_id"] == approver_staff_id:
        raise SignerAccessError("SoD: approver phai khac requester (Addendum 90)")
    if req["preflight_at"] is None or (_now() - req["preflight_at"]).total_seconds() > PREFLIGHT_FRESH_SECONDS:
        raise SignerAccessError("preflight stale — chay lai preflight")
    requester = req["requester_staff_id"]
    is_reh = req["is_rehearsal"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            win_end = await conn.fetchval("SELECT now() + ($1||' minutes')::interval",
                                          str(req["window_minutes"]))
            # EVENT 1: provision temp signer role (tru khi da co static role)
            already = await _staff_has_static_role(conn, requester)
            grant_id = None
            if not already:
                # CONTROL chuan Addendum 70A (Directive 91): cap temp role QUA rbac_provisioning
                # (allowlist role + _require_auth + audit-ready + immutable audit fail-closed) —
                # KHONG INSERT truc tiep o day. Day la duong duy nhat provisioning temp role.
                grant_id = await rbac_provisioning.grant_temp_signer_role(
                    conn, staff_id=requester, request_id=request_id, valid_until=win_end,
                    granted_by=approver_staff_id, actor=actor,
                    reason=req["reason"] or "signer access", ticket=req["ticket"] or request_id,
                    is_rehearsal=is_reh)
            # EVENT 2: issue activation window (m4_signing_activation row lien ket)
            act = await conn.fetchrow(
                "INSERT INTO m4_signing_activation "
                "(request_id,scope,artifact_digest,max_sign_count,reason,ticket,requester_staff_id,"
                " approver_staff_id,rollback_owner,state,approved_at,window_start,window_end,preflight_at) "
                "VALUES ($1,$2::jsonb,$3,1,$4,$5,$6,$7,$8,'APPROVED',now(),now(),$9,now()) RETURNING activation_id",
                "sa-" + request_id, json.dumps(req["scope"]), req["artifact_digest"], req["reason"],
                req["ticket"], requester, approver_staff_id, req["rollback_owner"], win_end)
            activation_id = act["activation_id"]
            row = await conn.fetchrow(
                "UPDATE m4_signer_access_request SET state='ACTIVE', approver_staff_id=$2, "
                "approved_at=now(), activated_at=now(), window_start=now(), window_end=$3, "
                "activation_id=$4, updated_at=now() WHERE request_id=$1 RETURNING *",
                request_id, approver_staff_id, win_end, activation_id)
            await _audit(conn, "approve", request_id, actor, approver_staff_id,
                         {"state": "PREFLIGHT_PASSED"},
                         {"state": "ACTIVE", "activation_id": str(activation_id),
                          "temp_role_granted": (grant_id is not None), "already_had_role": already,
                          "window_end": str(win_end)}, None)
    return _hydrate(row)


async def _terminate(request_id: str, to_state: str, reason: str, *, actor: str,
                     staff_id: int | None) -> dict:
    """close/expire/revoke: terminal request + auto-revoke temp grant + terminal activation."""
    req = await get(request_id)
    if req is None:
        raise SignerAccessError("request khong ton tai")
    if req["state"] in TERMINAL:
        raise SignerAccessError(f"da terminal ({req['state']})")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # auto-revoke temp role grant(s) QUA control chuan rbac_provisioning (immutable audit)
            await rbac_provisioning.revoke_temp_signer_role(
                conn, request_id=request_id, actor=actor, reason=reason)
            # terminal activation lien ket (neu con active)
            if req["activation_id"]:
                act_to = "CLOSED" if to_state == "CLOSED" else ("EXPIRED" if to_state == "EXPIRED" else "REVOKED")
                await conn.execute(
                    "UPDATE m4_signing_activation SET state=$2, terminal_at=now(), terminal_reason=$3, "
                    "updated_at=now() WHERE activation_id=$1 AND state NOT IN ('EXPIRED','REVOKED','CLOSED')",
                    req["activation_id"], act_to, reason)
            row = await conn.fetchrow(
                "UPDATE m4_signer_access_request SET state=$2, terminal_at=now(), terminal_reason=$3, "
                "updated_at=now() WHERE request_id=$1 RETURNING *", request_id, to_state, reason)
            verb = {"CLOSED": "close", "EXPIRED": "expire", "REVOKED": "revoke"}[to_state]
            await _audit(conn, verb, request_id, actor, staff_id,
                         {"state": req["state"]},
                         {"state": to_state, "reason": reason, "temp_role_revoked": True}, reason)
    return _hydrate(row)


async def close(request_id: str, *, actor: str, staff_id: int | None = None) -> dict:
    return await _terminate(request_id, "CLOSED", "completed", actor=actor, staff_id=staff_id)


async def revoke(request_id: str, *, actor: str, reason: str, staff_id: int | None = None) -> dict:
    if not reason:
        raise SignerAccessError("revoke can reason")
    return await _terminate(request_id, "REVOKED", reason, actor=actor, staff_id=staff_id)


async def expire_due(*, actor: str = "system") -> int:
    """Auto-revoke worker: request ACTIVE qua window_end -> EXPIRED + revoke role + expire activation."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT request_id FROM m4_signer_access_request "
            "WHERE state='ACTIVE' AND window_end IS NOT NULL AND window_end < now()")
    n = 0
    for r in rows:
        try:
            await _terminate(r["request_id"], "EXPIRED", "ttl_expired", actor=actor, staff_id=None)
            n += 1
        except SignerAccessError:
            pass
    # Ghi chu: grant het valid_until TU DONG khong con cap quyen (permission resolution kiem
    # valid_until>now); revoke (audit) di qua _terminate -> rbac_provisioning.revoke_temp_signer_role.
    # KHONG sweep UPDATE truc tiep o day (tranh duong provisioning ngoai control).
    return n
