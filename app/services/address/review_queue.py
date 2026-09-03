"""M5 Phase 3 — Durable staff review queue service (CA Directive 112).

Enqueue resolution 'needs_staff_review' -> assign -> staff resolve (permission address.review). Override dung
address.override + approver DOC LAP (no-self-approval) khi anh huong fulfillment. Stale candidate check, immutable
audit, fail-closed. Ket qua = resolution moi 'staff_confirmed'. KHONG order/quote wiring.
"""
from __future__ import annotations

import json

from app.services import audit_service
from app.services.address.confirmation import _append_resolution


class ReviewQueueError(Exception):
    """Fail-closed."""


async def _assert_audit(conn):
    if not await audit_service.audit_exists(conn):
        raise ReviewQueueError("audit_log chua provision — fail-closed")


def _codes(snapshot):
    return {c.get("code") for c in (snapshot or []) if c.get("code")}


async def enqueue(conn, *, resolution_id: str, reason: str, actor: str, ticket: str,
                  idempotency_key: str | None = None) -> dict:
    if not (actor and actor.strip()):
        raise ReviewQueueError("thieu actor")
    await _assert_audit(conn)
    if idempotency_key:
        ex = await conn.fetchrow("SELECT * FROM address_review_queue WHERE idempotency_key=$1", idempotency_key)
        if ex:
            return _row(ex)
    res = await conn.fetchrow("SELECT * FROM address_resolution WHERE id=$1::uuid", str(resolution_id))
    if not res:
        raise ReviewQueueError("resolution khong ton tai")
    if res["status"] != "needs_staff_review":
        raise ReviewQueueError(f"chi enqueue cho needs_staff_review (dang {res['status']})")
    snap = res["candidates"]
    if isinstance(snap, str):
        snap = json.loads(snap or "[]")
    row = await conn.fetchrow(
        "INSERT INTO address_review_queue (resolution_id,subject_type,subject_id,candidate_snapshot,reason,"
        "ticket,idempotency_key) VALUES ($1::uuid,$2,$3,$4::jsonb,$5,$6,$7) RETURNING *",
        str(resolution_id), res["subject_type"], res["subject_id"], json.dumps(snap, ensure_ascii=False),
        reason, ticket, idempotency_key)
    await audit_service.record(conn, actor_type="cli", action="address.review.enqueue", actor_ref=actor,
                               entity_type="address_review_queue", entity_id=str(row["id"]), before=None,
                               after={"state": "open", "resolution_id": str(resolution_id), "ticket": ticket},
                               reason=reason)
    return _row(row)


async def assign(conn, *, queue_id: str, assignee: str, actor: str) -> dict:
    if not (actor and actor.strip() and assignee and assignee.strip()):
        raise ReviewQueueError("thieu actor/assignee")
    await _assert_audit(conn)
    q = await conn.fetchrow("SELECT state FROM address_review_queue WHERE id=$1::uuid", str(queue_id))
    if not q:
        raise ReviewQueueError("queue item khong ton tai")
    if q["state"] not in ("open", "assigned"):
        raise ReviewQueueError(f"chi assign khi open/assigned (dang {q['state']})")
    async with conn.transaction():
        await conn.execute("UPDATE address_review_queue SET state='assigned', assignee=$2, assigned_at=now() "
                           "WHERE id=$1::uuid", str(queue_id), assignee)
        await audit_service.record(conn, actor_type="cli", action="address.review.assign", actor_ref=actor,
                                   entity_type="address_review_queue", entity_id=str(queue_id),
                                   before={"state": q["state"]}, after={"state": "assigned", "assignee": assignee},
                                   reason="assign")
    return _row(await conn.fetchrow("SELECT * FROM address_review_queue WHERE id=$1::uuid", str(queue_id)))


async def resolve(conn, *, queue_id: str, chosen_code: str, actor: str, reason: str, ticket: str,
                  is_override: bool = False, approver: str | None = None,
                  affects_fulfillment: bool = False, accept: bool = True) -> dict:
    """Staff quyet (permission address.review enforce o API). Override (address.override enforce o API) can
    approver doc lap; no-self-approval; anh huong fulfillment BAT BUOC approver."""
    if not (actor and actor.strip() and reason and reason.strip() and ticket and ticket.strip()):
        raise ReviewQueueError("thieu actor/reason/ticket")
    await _assert_audit(conn)
    q = await conn.fetchrow("SELECT * FROM address_review_queue WHERE id=$1::uuid", str(queue_id))
    if not q:
        raise ReviewQueueError("queue item khong ton tai")
    q = dict(q)
    if q["state"] not in ("open", "assigned"):
        raise ReviewQueueError(f"khong resolve duoc o trang thai {q['state']} (replay/duplicate)")
    snap = q["candidate_snapshot"]
    if isinstance(snap, str):
        snap = json.loads(snap or "[]")
    if accept and chosen_code not in _codes(snap):
        raise ReviewQueueError("chosen_code khong nam trong candidate_snapshot (stale)")
    if is_override or affects_fulfillment:
        if not (approver and approver.strip()):
            raise ReviewQueueError("override/anh huong fulfillment can approver doc lap")
        if approver.strip() == actor.strip():
            raise ReviewQueueError("SoD: approver phai KHAC nguoi resolve (no self-approval)")

    orig = await conn.fetchrow("SELECT * FROM address_resolution WHERE id=$1::uuid", str(q["resolution_id"]))
    async with conn.transaction():
        if accept:
            new_rid = await _append_resolution(conn, dict(orig), status="staff_confirmed", actor=actor,
                                                note={"confirmed_code": chosen_code, "via": "staff",
                                                      "override": is_override, "approver": approver})
            await conn.execute(
                "UPDATE address_review_queue SET state='resolved', chosen_code=$2, is_override=$3, approver=$4,"
                "result_resolution_id=$5::uuid, resolved_by=$6, resolved_at=now() WHERE id=$1::uuid",
                str(queue_id), chosen_code, is_override, approver, new_rid, actor)
            action, new_state = "address.review.resolve", "resolved"
        else:
            new_rid = None
            await conn.execute("UPDATE address_review_queue SET state='rejected', resolved_by=$2, "
                               "resolved_at=now() WHERE id=$1::uuid", str(queue_id), actor)
            action, new_state = "address.review.reject", "rejected"
        await audit_service.record(
            conn, actor_type="cli", action=action, actor_ref=actor, entity_type="address_review_queue",
            entity_id=str(queue_id), before={"state": q["state"]},
            after={"state": new_state, "chosen_code": chosen_code if accept else None, "is_override": is_override,
                   "approver": approver, "result_resolution_id": new_rid, "ticket": ticket}, reason=reason)
    return _row(await conn.fetchrow("SELECT * FROM address_review_queue WHERE id=$1::uuid", str(queue_id)))


def _row(r) -> dict:
    d = dict(r)
    for k in ("id", "resolution_id", "result_resolution_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if isinstance(d.get("candidate_snapshot"), str):
        d["candidate_snapshot"] = json.loads(d["candidate_snapshot"] or "[]")
    return d
