"""M5 Gate C — confirmation delivery outbox (durable LOCAL/test transport; CA Directive 179 §5).

Enqueue-after-commit + dedupe + bounded retry + terminal/dead-letter. Transport la callable LOCAL/FAKE (khong provider
that, khong external message). Provider fail KHONG mark 'sent' va KHONG mat durable request. State machine:
  pending --deliver ok--> sent (terminal)
  pending --deliver fail--> failed (retry toi max_attempts) --> dead_letter (terminal)
Bang address_confirmation_outbox (migration 057): DELETE bi chan, request_id/payload/dedupe_key bat bien.
"""
from __future__ import annotations

import json


class OutboxError(Exception):
    """Fail-closed."""


def _row(r) -> dict:
    d = dict(r)
    for k in ("id", "request_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if isinstance(d.get("payload"), str):
        d["payload"] = json.loads(d["payload"] or "{}")
    return d


async def enqueue(conn, *, request_id: str, channel: str, payload: dict, dedupe_key: str) -> dict:
    """Enqueue MOT delivery cho confirmation request DA COMMIT (FK -> address_confirmation_request dam bao
    enqueue-after-commit: request phai ton tai). Dedupe qua dedupe_key UNIQUE: goi lai -> tra ban ghi cu, khong nhan doi."""
    if not (dedupe_key and dedupe_key.strip()):
        raise OutboxError("thieu dedupe_key")
    row = await conn.fetchrow(
        "INSERT INTO address_confirmation_outbox (request_id,channel,payload,dedupe_key) "
        "VALUES ($1::uuid,$2,$3::jsonb,$4) ON CONFLICT (dedupe_key) DO NOTHING RETURNING *",
        str(request_id), channel, json.dumps(payload, ensure_ascii=False), dedupe_key)
    if row is None:  # dedupe hit
        row = await conn.fetchrow("SELECT * FROM address_confirmation_outbox WHERE dedupe_key=$1", dedupe_key)
        return {**_row(row), "deduped": True}
    return {**_row(row), "deduped": False}


async def deliver_once(conn, *, outbox_id: str, transport, backoff_seconds: int = 60) -> dict:
    """Thu gui MOT lan qua transport LOCAL, AN TOAN concurrent (G-A-180-03).

    ATOMIC CLAIM: `SELECT ... FOR UPDATE SKIP LOCKED` chi lay row eligible (pending/failed, toi han) va KHOA no
    trong transaction; worker khac se SKIP -> KHONG goi transport lan hai. Terminal (sent/dead_letter) va row chua
    toi `next_attempt_at` KHONG duoc claim. transport goi TRONG claim; success->'sent', fail->attempts++ (dead_letter
    neu >= max_attempts, nguoc lai 'failed'+backoff). attempts don dieu (serialized boi row lock). Claim bo do (worker
    chet) -> tx abort -> lock nha -> row co the claim lai (khong ket 'claimed' vinh vien). Provider fail KHONG mark 'sent'."""
    async with conn.transaction():
        o = await conn.fetchrow(
            "SELECT * FROM address_confirmation_outbox WHERE id=$1::uuid "
            "AND state IN ('pending','failed') AND next_attempt_at <= now() "
            "FOR UPDATE SKIP LOCKED", str(outbox_id))
        if o is None:
            cur = await conn.fetchrow("SELECT * FROM address_confirmation_outbox WHERE id=$1::uuid", str(outbox_id))
            if cur is None:
                raise OutboxError("outbox item khong ton tai")
            return {**_row(cur), "claimed": False}  # bi worker khac claim / terminal / chua toi han
        o = dict(o)
        payload = o["payload"] if not isinstance(o["payload"], str) else json.loads(o["payload"] or "{}")
        try:
            transport(payload)  # LOCAL/fake — no external send
            ok, err = True, None
        except Exception as e:  # noqa: BLE001  (fake transport failure — durable request khong mat)
            ok, err = False, repr(e)[:200]
        if ok:
            await conn.execute("UPDATE address_confirmation_outbox SET state='sent', sent_at=now(), "
                               "attempts=attempts+1 WHERE id=$1::uuid", str(outbox_id))
        else:
            attempts = o["attempts"] + 1
            if attempts >= o["max_attempts"]:
                await conn.execute("UPDATE address_confirmation_outbox SET state='dead_letter', attempts=$2, "
                                   "last_error=$3 WHERE id=$1::uuid", str(outbox_id), attempts, err)
            else:
                await conn.execute(
                    "UPDATE address_confirmation_outbox SET state='failed', attempts=$2, last_error=$3, "
                    "next_attempt_at=now()+($4||' seconds')::interval WHERE id=$1::uuid",
                    str(outbox_id), attempts, err, str(int(backoff_seconds)))
    return {**_row(await conn.fetchrow("SELECT * FROM address_confirmation_outbox WHERE id=$1::uuid",
                                       str(outbox_id))), "claimed": True}


async def due(conn):
    """Cac item con gui duoc (pending/failed, toi han)."""
    rows = await conn.fetch("SELECT * FROM address_confirmation_outbox WHERE state IN ('pending','failed') "
                            "AND next_attempt_at <= now() ORDER BY created_at")
    return [_row(r) for r in rows]
