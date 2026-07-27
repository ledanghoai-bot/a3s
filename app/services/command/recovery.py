"""Operator recovery + read cho command/outbox (I-B M1 Slice 8). Spec §9.3, §11.

Mutation (retry/replay/cancel) audit fail-closed CUNG transaction (§11.2): loi audit -> rollback.
Payload da redact luc luu (Slice 3/5) nen read tra thang. Guard trang thai theo §9.3.
"""
from __future__ import annotations

import json
import uuid

from app.db_pool import acquire, release
from app.services import audit_service
from app.services.command import errors
from app.services.command.retry import MAX_ATTEMPTS as _RETRY_BUDGET


def _audit_actor(actor: dict) -> tuple[str, str, int | None]:
    sid = actor.get("id")
    return "staff", str(actor.get("username") or sid), sid if isinstance(sid, int) else None


def _require_reason(reason: str | None) -> str:
    if not reason or not reason.strip():
        raise errors.CommandError("reason_required", "Bat buoc nhap ly do.", http_status=422)
    return reason.strip()


# ------------------------------- read -------------------------------

async def list_commands(limit: int = 100, status: str | None = None,
                        command_type: str | None = None) -> list[dict]:
    conn = await acquire()
    try:
        rows = await conn.fetch(
            "SELECT id, command_type, command_version, status, channel, resource_type, resource_id, "
            "correlation_id, error_code, created_at, completed_at FROM command_executions "
            "WHERE ($1::text IS NULL OR status=$1) AND ($2::text IS NULL OR command_type=$2) "
            "ORDER BY created_at DESC LIMIT $3", status, command_type, limit)
        return [dict(r) for r in rows]
    finally:
        await release(conn)


async def list_outbox(limit: int = 100, status: str | None = None,
                     destination: str | None = None) -> list[dict]:
    conn = await acquire()
    try:
        rows = await conn.fetch(
            "SELECT id, command_id, event_type, destination, dedupe_key, status, attempt_count, "
            "max_attempts, available_at, last_error_code, created_at, updated_at FROM outbox_events "
            "WHERE ($1::text IS NULL OR status=$1) AND ($2::text IS NULL OR destination=$2) "
            "ORDER BY updated_at DESC LIMIT $3", status, destination, limit)
        return [dict(r) for r in rows]
    finally:
        await release(conn)


async def outbox_detail(outbox_id: str) -> dict:
    conn = await acquire()
    try:
        ev = await conn.fetchrow("SELECT * FROM outbox_events WHERE id=$1", outbox_id)
        if ev is None:
            raise errors.CommandError("outbox_not_found", "Khong tim thay outbox event.", http_status=404)
        attempts = await conn.fetch(
            "SELECT attempt_no, worker_id, outcome, http_status, provider_message_id, error_class, "
            "duration_ms, started_at, finished_at FROM delivery_attempts WHERE outbox_event_id=$1 "
            "ORDER BY attempt_no", outbox_id)
        d = dict(ev)
        if isinstance(d.get("payload"), str):
            d["payload"] = json.loads(d["payload"])  # da redact luc luu
        d["attempts"] = [dict(a) for a in attempts]
        return d
    finally:
        await release(conn)


# ------------------------------- recovery mutations -------------------------------

async def retry_outbox(outbox_id: str, actor: dict, reason: str | None) -> dict:
    """Dead-letter -> retry_scheduled, giu dedupe key, reset attempt budget. Audit fail-closed."""
    reason = _require_reason(reason)
    conn = await acquire()
    try:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT status FROM outbox_events WHERE id=$1 FOR UPDATE", outbox_id)
            if row is None:
                raise errors.CommandError("outbox_not_found", "Khong tim thay.", http_status=404)
            if row["status"] != "dead_lettered":
                raise errors.CommandError("outbox_not_retryable",
                                          f"Chi retry dead_lettered (dang {row['status']}).", http_status=409)
            # CR-01: KHÔNG reset attempt_count (attempt_no phải đơn điệu — tránh trùng
            # UNIQUE(outbox_event_id,attempt_no)). Cấp thêm budget bằng cách nâng max_attempts.
            await conn.execute(
                "UPDATE outbox_events SET status='retry_scheduled', available_at=now(), "
                "max_attempts=attempt_count+$2, dead_lettered_at=NULL, last_error_code=NULL, "
                "lease_owner=NULL, lease_expires_at=NULL WHERE id=$1", outbox_id, _RETRY_BUDGET)
            atype, aref, asid = _audit_actor(actor)
            await audit_service.record(conn, atype, "outbox.retry", actor_ref=aref, actor_staff_id=asid,
                                       entity_type="outbox_event", entity_id=str(outbox_id), reason=reason)
        return {"outbox_id": str(outbox_id), "status": "retry_scheduled"}
    finally:
        await release(conn)


async def cancel_outbox(outbox_id: str, actor: dict, reason: str | None) -> dict:
    """Cancel event CHUA delivered (§9.3). Audit fail-closed."""
    reason = _require_reason(reason)
    conn = await acquire()
    try:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT status FROM outbox_events WHERE id=$1 FOR UPDATE", outbox_id)
            if row is None:
                raise errors.CommandError("outbox_not_found", "Khong tim thay.", http_status=404)
            # CR-02: KHÔNG cho cancel khi đang 'delivering' (worker đang gửi — tránh đè trạng thái
            # + provider có thể đã nhận). Chỉ cancel pending/retry_scheduled/dead_lettered.
            if row["status"] in ("delivered", "cancelled", "delivering"):
                raise errors.CommandError("outbox_not_cancellable",
                                          f"Khong the cancel (dang {row['status']}).", http_status=409)
            await conn.execute(
                "UPDATE outbox_events SET status='cancelled', cancelled_at=now(), "
                "lease_owner=NULL, lease_expires_at=NULL WHERE id=$1", outbox_id)
            atype, aref, asid = _audit_actor(actor)
            await audit_service.record(conn, atype, "outbox.cancel", actor_ref=aref, actor_staff_id=asid,
                                       entity_type="outbox_event", entity_id=str(outbox_id), reason=reason)
        return {"outbox_id": str(outbox_id), "status": "cancelled"}
    finally:
        await release(conn)


async def replay_outbox(outbox_id: str, actor: dict, reason: str | None,
                        confirm_business_effect: bool = False) -> dict:
    """Tao outbox event MOI tu event cu (admin, §9.3). CR-06: chi replay tu trang thai da ket thuc
    khong-giao (dead_lettered/cancelled) + operator PHAI xac nhan da doi soat business effect. Audit."""
    reason = _require_reason(reason)
    if not confirm_business_effect:
        raise errors.CommandError(
            "reconcile_confirmation_required",
            "Replay yeu cau xac nhan da doi soat business effect (confirm_business_effect=true).",
            http_status=422)
    conn = await acquire()
    try:
        async with conn.transaction():
            src = await conn.fetchrow(
                "SELECT status, command_id, event_type, event_version, destination, dedupe_key, "
                "payload, max_attempts FROM outbox_events WHERE id=$1 FOR UPDATE", outbox_id)
            if src is None:
                raise errors.CommandError("outbox_not_found", "Khong tim thay.", http_status=404)
            if src["status"] not in ("dead_lettered", "cancelled"):
                raise errors.CommandError(
                    "outbox_not_replayable",
                    f"Chi replay tu dead_lettered/cancelled (dang {src['status']}).", http_status=409)
            new_dedupe = f"{src['dedupe_key']}:replay:{uuid.uuid4().hex[:8]}"
            payload = src["payload"] if isinstance(src["payload"], str) else json.dumps(src["payload"])
            new_id = await conn.fetchval(
                "INSERT INTO outbox_events (id, command_id, event_type, event_version, destination, "
                "dedupe_key, payload, status, available_at, max_attempts) "
                "VALUES (gen_random_uuid(), $1,$2,$3,$4,$5,$6::jsonb,'pending', now(), $7) RETURNING id",
                src["command_id"], src["event_type"], src["event_version"], src["destination"],
                new_dedupe, payload, src["max_attempts"])
            atype, aref, asid = _audit_actor(actor)
            await audit_service.record(
                conn, atype, "outbox.replay", actor_ref=aref, actor_staff_id=asid,
                entity_type="outbox_event", entity_id=str(outbox_id), reason=reason,
                after={"new_outbox_id": str(new_id), "dedupe_key": new_dedupe,
                       "source_status": src["status"], "business_effect_reconciled": True})
        return {"replayed_from": str(outbox_id), "new_outbox_id": str(new_id)}
    finally:
        await release(conn)
