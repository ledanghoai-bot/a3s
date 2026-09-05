"""M5 Phase 3 — Customer confirmation service (CA Directive 112).

Phat hanh confirmation request cho resolution 'needs_customer_confirmation' -> khach phan hoi (binding) ->
sinh resolution moi 'customer_confirmed'. Bat bien candidate_snapshot; fail-closed; idempotency; replay/stale/
binding/expiry check; immutable audit. KHONG gui thong bao that (dormant). KHONG order/quote wiring.
"""
from __future__ import annotations

import json

from app.services import audit_service


class ConfirmationError(Exception):
    """Fail-closed. Khong leak secret."""


def _codes(snapshot: list[dict]) -> set[str]:
    return {c.get("code") for c in (snapshot or []) if c.get("code")}


async def _assert_audit(conn):
    if not await audit_service.audit_exists(conn):
        raise ConfirmationError("audit_log chua provision — fail-closed")


async def _resolution(conn, rid):
    r = await conn.fetchrow("SELECT * FROM address_resolution WHERE id=$1::uuid", str(rid))
    return dict(r) if r else None


async def _append_resolution(conn, orig: dict, *, status: str, actor: str, note: dict) -> str:
    """INSERT resolution MOI (append-only) phan anh ket qua confirm. Copy codes tu resolution goc."""
    row = await conn.fetchrow(
        "INSERT INTO address_resolution (subject_type,subject_id,raw_province,raw_district,raw_ward,"
        "street_text,province_code,district_code,ward_code,dataset_version,as_of,status,method,confidence,"
        "candidates,rules_applied,resolved_by,reason) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'manual',$13,$14::jsonb,$15::jsonb,$16,$17) RETURNING id",
        orig["subject_type"], orig["subject_id"], orig["raw_province"], orig["raw_district"], orig["raw_ward"],
        orig["street_text"], orig["province_code"], orig["district_code"], orig["ward_code"],
        orig["dataset_version"], orig["as_of"], status, orig["confidence"],
        json.dumps([note], ensure_ascii=False), json.dumps(["from_confirmation"], ensure_ascii=False),
        actor, "confirmation result")
    return str(row["id"])


async def issue(conn, *, resolution_id: str, channel: str, bound_ref: str, expiry_minutes: int,
                actor: str, reason: str, ticket: str, idempotency_key: str | None = None) -> dict:
    if not (actor and actor.strip()):
        raise ConfirmationError("thieu actor (session)")
    if not (bound_ref and bound_ref.strip()):
        raise ConfirmationError("thieu bound_ref (channel/session binding)")
    if not (1 <= int(expiry_minutes) <= 10080):
        raise ConfirmationError("expiry_minutes ngoai [1,10080]")
    await _assert_audit(conn)
    if idempotency_key:
        ex = await conn.fetchrow("SELECT * FROM address_confirmation_request WHERE idempotency_key=$1",
                                 idempotency_key)
        if ex:
            return _row(ex)
    res = await _resolution(conn, resolution_id)
    if not res:
        raise ConfirmationError("resolution khong ton tai")
    if res["status"] != "needs_customer_confirmation":
        raise ConfirmationError(f"chi phat hanh cho needs_customer_confirmation (dang {res['status']})")
    snapshot = res["candidates"]
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot or "[]")
    row = await conn.fetchrow(
        "INSERT INTO address_confirmation_request (resolution_id,subject_type,subject_id,candidate_snapshot,"
        "channel,bound_ref,expiry,idempotency_key,issued_by,reason,ticket) "
        "VALUES ($1::uuid,$2,$3,$4::jsonb,$5,$6,now()+($7||' minutes')::interval,$8,$9,$10,$11) RETURNING *",
        str(resolution_id), res["subject_type"], res["subject_id"], json.dumps(snapshot, ensure_ascii=False),
        channel, bound_ref, str(int(expiry_minutes)), idempotency_key, actor, reason, ticket)
    await audit_service.record(
        conn, actor_type="cli", action="address.confirm.issue", actor_ref=actor,
        entity_type="address_confirmation_request", entity_id=str(row["id"]), before=None,
        after={"resolution_id": str(resolution_id), "channel": channel, "state": "issued",
               "ticket": ticket}, reason=reason)
    return _row(row)


async def issue_with_delivery(conn, *, resolution_id: str, channel: str, bound_ref: str, expiry_minutes: int,
                              actor: str, reason: str, ticket: str, idempotency_key: str | None = None) -> dict:
    """ATOMIC (G-A-180-02): tao confirmation request + DUNG MOT outbox delivery item TRONG CUNG transaction
    (+audit). Transport dispatch chi sau commit (worker goi outbox.deliver_once). Idempotency: cung idempotency_key
    -> tra ve request+outbox cu, khong tao delivery trung. Route /issue dung ham nay -> khong the tao issued request
    ma thieu outbox row. tx fail -> rollback CA HAI."""
    if not (actor and actor.strip()):
        raise ConfirmationError("thieu actor (session)")
    if not (bound_ref and bound_ref.strip()):
        raise ConfirmationError("thieu bound_ref (channel/session binding)")
    if not (1 <= int(expiry_minutes) <= 10080):
        raise ConfirmationError("expiry_minutes ngoai [1,10080]")
    await _assert_audit(conn)
    if idempotency_key:
        ex = await conn.fetchrow("SELECT * FROM address_confirmation_request WHERE idempotency_key=$1",
                                 idempotency_key)
        if ex:
            ob = await conn.fetchrow("SELECT id FROM address_confirmation_outbox WHERE request_id=$1", ex["id"])
            return {**_row(ex), "outbox_id": str(ob["id"]) if ob else None, "idempotent": True}
    res = await _resolution(conn, resolution_id)
    if not res:
        raise ConfirmationError("resolution khong ton tai")
    if res["status"] != "needs_customer_confirmation":
        raise ConfirmationError(f"chi phat hanh cho needs_customer_confirmation (dang {res['status']})")
    snapshot = res["candidates"]
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot or "[]")
    async with conn.transaction():  # ATOMIC: request + outbox + audit
        row = await conn.fetchrow(
            "INSERT INTO address_confirmation_request (resolution_id,subject_type,subject_id,candidate_snapshot,"
            "channel,bound_ref,expiry,idempotency_key,issued_by,reason,ticket) "
            "VALUES ($1::uuid,$2,$3,$4::jsonb,$5,$6,now()+($7||' minutes')::interval,$8,$9,$10,$11) RETURNING *",
            str(resolution_id), res["subject_type"], res["subject_id"], json.dumps(snapshot, ensure_ascii=False),
            channel, bound_ref, str(int(expiry_minutes)), idempotency_key, actor, reason, ticket)
        rid = str(row["id"])
        payload = {"request_id": rid, "channel": channel, "action": "confirm_address",
                   "candidate_codes": sorted(_codes(snapshot))}
        ob = await conn.fetchrow(
            "INSERT INTO address_confirmation_outbox (request_id,channel,payload,dedupe_key) "
            "VALUES ($1::uuid,$2,$3::jsonb,$4) RETURNING id", rid, channel,
            json.dumps(payload, ensure_ascii=False), f"confirm:{rid}")
        await audit_service.record(
            conn, actor_type="cli", action="address.confirm.issue", actor_ref=actor,
            entity_type="address_confirmation_request", entity_id=rid, before=None,
            after={"resolution_id": str(resolution_id), "channel": channel, "state": "issued",
                   "outbox_id": str(ob["id"]), "ticket": ticket}, reason=reason)
    return {**_row(row), "outbox_id": str(ob["id"]), "idempotent": False}


async def respond(conn, *, request_id: str, chosen_code: str, responder_ref: str,
                  accept: bool = True, idempotency_key: str | None = None) -> dict:
    """Khach phan hoi. Binding: responder_ref phai == bound_ref. Stale: chosen_code in snapshot. Replay:
    state phai 'issued'. Expiry: qua han -> expired + tu choi."""
    if not (responder_ref and responder_ref.strip()):
        raise ConfirmationError("thieu responder_ref (binding)")
    await _assert_audit(conn)
    req = await conn.fetchrow("SELECT * FROM address_confirmation_request WHERE id=$1::uuid", str(request_id))
    if not req:
        raise ConfirmationError("confirmation request khong ton tai")
    req = dict(req)
    if req["responded_at"] is not None or req["state"] != "issued":
        raise ConfirmationError(f"request khong o trang thai 'issued' (dang {req['state']}) — replay/duplicate")
    expired = await conn.fetchval("SELECT now() > $1", req["expiry"])
    if expired:
        async with conn.transaction():
            await conn.execute("UPDATE address_confirmation_request SET state='expired' WHERE id=$1::uuid",
                               str(request_id))
            await audit_service.record(conn, actor_type="cli", action="address.confirm.expire",
                                       actor_ref="system", entity_type="address_confirmation_request",
                                       entity_id=str(request_id), before={"state": "issued"},
                                       after={"state": "expired"}, reason="expiry passed")
        raise ConfirmationError("request het han (expired)")
    if responder_ref.strip() != (req["bound_ref"] or "").strip():
        raise ConfirmationError("binding mismatch — responder khong khop bound_ref")
    snap = req["candidate_snapshot"]
    if isinstance(snap, str):
        snap = json.loads(snap or "[]")
    if accept and chosen_code not in _codes(snap):
        raise ConfirmationError("chosen_code khong nam trong candidate_snapshot (stale/invalid)")

    orig = await _resolution(conn, req["resolution_id"])
    async with conn.transaction():
        if accept:
            new_rid = await _append_resolution(
                conn, orig, status="customer_confirmed", actor=responder_ref,
                note={"confirmed_code": chosen_code, "via": "customer"})
            await conn.execute(
                "UPDATE address_confirmation_request SET state='confirmed', chosen_code=$2, responded_by=$3,"
                "responded_at=now(), result_resolution_id=$4::uuid WHERE id=$1::uuid",
                str(request_id), chosen_code, responder_ref, new_rid)
            action, new_state = "address.confirm.respond", "confirmed"
        else:
            new_rid = None
            await conn.execute(
                "UPDATE address_confirmation_request SET state='rejected', responded_by=$2, responded_at=now() "
                "WHERE id=$1::uuid", str(request_id), responder_ref)
            action, new_state = "address.confirm.reject", "rejected"
        await audit_service.record(
            conn, actor_type="cli", action=action, actor_ref=responder_ref,
            entity_type="address_confirmation_request", entity_id=str(request_id),
            before={"state": "issued"}, after={"state": new_state, "chosen_code": chosen_code if accept else None,
                                               "result_resolution_id": new_rid}, reason="customer response")
    return _row(await conn.fetchrow("SELECT * FROM address_confirmation_request WHERE id=$1::uuid",
                                    str(request_id)))


async def cancel(conn, *, request_id: str, actor: str, reason: str) -> dict:
    if not (actor and actor.strip() and reason and reason.strip()):
        raise ConfirmationError("thieu actor/reason")
    await _assert_audit(conn)
    req = await conn.fetchrow("SELECT state FROM address_confirmation_request WHERE id=$1::uuid", str(request_id))
    if not req:
        raise ConfirmationError("request khong ton tai")
    if req["state"] != "issued":
        raise ConfirmationError(f"chi cancel khi 'issued' (dang {req['state']})")
    async with conn.transaction():
        await conn.execute("UPDATE address_confirmation_request SET state='cancelled' WHERE id=$1::uuid",
                           str(request_id))
        await audit_service.record(conn, actor_type="cli", action="address.confirm.cancel", actor_ref=actor,
                                   entity_type="address_confirmation_request", entity_id=str(request_id),
                                   before={"state": "issued"}, after={"state": "cancelled"}, reason=reason)
    return _row(await conn.fetchrow("SELECT * FROM address_confirmation_request WHERE id=$1::uuid",
                                    str(request_id)))


def _row(r) -> dict:
    d = dict(r)
    for k in ("id", "resolution_id", "result_resolution_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if isinstance(d.get("candidate_snapshot"), str):
        d["candidate_snapshot"] = json.loads(d["candidate_snapshot"] or "[]")
    return d
