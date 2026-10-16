"""CA Review 414 §2 — outbox Messenger chi gui trong khung 24h tu tin khach gan nhat (nguon durable: messages).

DB (skipif not M6_TEST_DB): trong khung -> gui; bien 24h - margin (trong/ngoai); ngoai khung / chua tung nhan -> KHONG
goi Send API, event 'cancelled'/messaging_window_closed (khong bao gio 'delivered'), 0 delivery_attempts, mo staff
attention + bao admin 1 lan/don; dispatcher outbound cung bi chan; Telegram khong bi anh huong; retry (retry_scheduled)
va replay dead-letter -> van chan; restart (lease het han -> reclaim) -> danh gia lai dung 1 lan; worker khac giu lease
cu -> no-op; khach nhan lai -> tin moi gui duoc, tin da chan khong song lai.
"""
import json
import os
import random
import uuid

import pytest

from app.services import messenger_window as mw
from app.services.command import outbox_worker as ow

DB = os.environ.get("M6_TEST_DB") == "1"
dbonly = pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")


def test_window_constants():
    assert mw.WINDOW_HOURS == 24 and 0 < mw.SAFETY_MARGIN_MINUTES <= 60


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


async def _customer(conn, *, channel="messenger", inbound_ago_min: int | None = 60):
    """Khach + conversation + (tuy chon) 1 tin khach cach day `inbound_ago_min` phut + 1 don. -> (ref, cid, oid)."""
    raw = "9" + "".join(random.choice("0123456789") for _ in range(15))
    ref = raw if channel == "messenger" else f"tg:{raw[:10]}"
    chat = raw if channel == "messenger" else raw[:10]
    cid = await conn.fetchval("INSERT INTO customers(psid,channel,external_chat_id) VALUES($1,$2,$3) RETURNING id",
                              ref, channel, chat)
    conv = await conn.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id", cid)
    if inbound_ago_min is not None:
        await conn.execute("INSERT INTO messages(conversation_id,role,content,created_at) "
                           "VALUES($1,'customer','x',now() - make_interval(mins => $2))", conv, inbound_ago_min)
    # tin BOT moi hon khong duoc tinh la mo khung
    await conn.execute("INSERT INTO messages(conversation_id,role,content) VALUES($1,'bot','y')", conv)
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                              "VALUES($1,'confirmed',100000,$2) RETURNING id", cid, channel)
    return ref, cid, oid, conv


async def _event(conn, ref, oid, *, dest="messenger", event_type="payment.confirmed.notify", payload=None,
                 lease=True, status="delivering", attempt_count=1):
    cmd = uuid.uuid4()
    await conn.execute(
        "INSERT INTO command_executions(id,command_type,command_version,idempotency_scope,idempotency_key,request_hash,"
        "status,actor_type,actor_id,channel,correlation_id,request_payload) "
        "VALUES($1,'order.create',1,'s414',$2,$3,'accepted','system','t','messenger',$4,'{}'::jsonb)",
        cmd, uuid.uuid4().hex, "0" * 64, uuid.uuid4())
    eid = uuid.uuid4()
    p = payload or {"customer_ref": ref, "order_id": oid, "text": "Shop đã nhận tiền ạ"}
    await conn.execute(
        "INSERT INTO outbox_events(id,command_id,event_type,event_version,destination,dedupe_key,payload,status,"
        "max_attempts,attempt_count,lease_owner,lease_expires_at) VALUES($1,$2,$3,1,$4,$5,$6::jsonb,$7,5,$8,$9,"
        "now() + interval '60 seconds')",
        eid, cmd, event_type, dest, f"t414:{eid}", json.dumps(p), status, attempt_count,
        ow.WORKER_ID if lease else "other-worker")
    return eid


class _Send:
    def __init__(self):
        self.calls = []

    async def __call__(self, dest, payload):
        self.calls.append(dest)
        return ow.SendResult(ok=True, http_status=200, provider_message_id="m1")


async def _process(conn, eid, send):
    ev = await conn.fetchrow("SELECT * FROM outbox_events WHERE id=$1", eid)
    return await ow._send_and_record(conn, dict(ev), send)


async def _state(conn, eid):
    row = await conn.fetchrow("SELECT status, last_error_code FROM outbox_events WHERE id=$1", eid)
    attempts = await conn.fetchval("SELECT count(*) FROM delivery_attempts WHERE outbox_event_id=$1", eid)
    return row["status"], row["last_error_code"], attempts


async def _attention(conn, oid):
    return await conn.fetch("SELECT * FROM staff_attention WHERE order_id=$1 AND reason='messaging_window_closed'",
                            oid)


@dbonly
@pytest.mark.asyncio
async def test_inside_window_sends():
    conn = await _conn()
    try:
        ref, _, oid, _ = await _customer(conn, inbound_ago_min=60)
        send = _Send()
        eid = await _event(conn, ref, oid)
        assert await _process(conn, eid, send) == "delivered"
        assert send.calls == ["messenger"] and (await _state(conn, eid))[0] == "delivered"
        assert await _attention(conn, oid) == []
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_boundary_safety_margin():
    conn = await _conn()
    try:
        inside = 24 * 60 - mw.SAFETY_MARGIN_MINUTES - 1
        outside = 24 * 60 - mw.SAFETY_MARGIN_MINUTES + 1
        ref, _, oid, _ = await _customer(conn, inbound_ago_min=inside)
        assert (await mw.window_state(conn, ref))["open"] is True
        send = _Send()
        assert await _process(conn, await _event(conn, ref, oid), send) == "delivered"
        ref2, _, oid2, _ = await _customer(conn, inbound_ago_min=outside)
        ws = await mw.window_state(conn, ref2)
        assert ws["open"] is False and ws["reason"] == "outside_window"
        send2 = _Send()
        assert await _process(conn, await _event(conn, ref2, oid2), send2) == "window_blocked"
        assert send2.calls == []
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_outside_window_blocked_attention_once_per_order():
    conn = await _conn()
    try:
        ref, _, oid, _ = await _customer(conn, inbound_ago_min=25 * 60)
        send = _Send()
        e1 = await _event(conn, ref, oid, event_type="payment.confirmed.notify")
        e2 = await _event(conn, ref, oid, event_type="fulfillment.prompt.notify")
        assert await _process(conn, e1, send) == "window_blocked"
        assert await _process(conn, e2, send) == "window_blocked"
        assert send.calls == []
        for e in (e1, e2):
            assert await _state(conn, e) == ("cancelled", "messaging_window_closed", 0)   # khong 'delivered'
        att = await _attention(conn, oid)
        assert len(att) == 1 and att[0]["status"] == "open" and att[0]["created_by"] == "outbox_worker"
        detail = json.loads(att[0]["detail"])
        assert detail["window"] == "outside_window" and detail["age_minutes"] >= 24 * 60
        assert ref not in att[0]["detail"]                                                   # khong PSID trong detail
        notify = await conn.fetchval(
            "SELECT count(*) FROM outbox_events WHERE dedupe_key=$1", f"staff_attention:{att[0]['id']}")
        assert notify == 1
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_no_inbound_and_dispatcher_payload_blocked():
    conn = await _conn()
    try:
        ref, _, oid, _ = await _customer(conn, inbound_ago_min=None)
        send = _Send()
        eid = await _event(conn, ref, oid, event_type="outbound.message",
                           payload={"dispatch": "outbound.message", "customer_ref": ref, "customer_id": 1,
                                    "purpose_code": "p", "template_key": "t", "template_version": 1,
                                    "params": {"order_id": oid}})
        assert await _process(conn, eid, send) == "window_blocked" and send.calls == []
        att = await _attention(conn, oid)
        assert len(att) == 1 and json.loads(att[0]["detail"])["window"] == "no_inbound"
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_telegram_not_affected():
    conn = await _conn()
    try:
        ref, _, oid, _ = await _customer(conn, channel="telegram_customer", inbound_ago_min=None)
        send = _Send()
        eid = await _event(conn, ref, oid, dest="telegram_customer")
        assert await _process(conn, eid, send) == "delivered" and send.calls == ["telegram_customer"]
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_retry_and_dead_letter_replay_still_blocked():
    from app.services.command import recovery
    conn = await _conn()
    try:
        ref, _, oid, _ = await _customer(conn, inbound_ago_min=30 * 60)
        send = _Send()
        # retry: lan 1 that bai truoc do, toi luot retry thi khung da dong
        eid = await _event(conn, ref, oid, attempt_count=2)
        assert await _process(conn, eid, send) == "window_blocked"
        # replay: event dead_lettered (vd that bai cu) -> staff retry -> worker van chan, khong gui
        e2 = await _event(conn, ref, oid, status="dead_lettered", lease=False)
        await conn.execute("UPDATE outbox_events SET lease_owner=NULL, lease_expires_at=NULL WHERE id=$1", e2)
        assert (await recovery.retry_outbox(e2, {"username": "t414"}, "retry thu nghiem 414"))["status"] == \
            "retry_scheduled"
        await conn.execute("UPDATE outbox_events SET status='delivering', lease_owner=$2, "
                           "lease_expires_at=now()+interval '60 seconds' WHERE id=$1", e2, ow.WORKER_ID)
        assert await _process(conn, e2, send) == "window_blocked"
        assert send.calls == [] and (await _state(conn, e2))[0] == "cancelled"
        assert len(await _attention(conn, oid)) == 1
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_restart_reclaim_reevaluates_and_foreign_lease_noop():
    conn = await _conn()
    try:
        ref, _, oid, _ = await _customer(conn, inbound_ago_min=26 * 60)
        send = _Send()
        # worker khac dang giu lease -> CAS khong khop -> KHONG doi event, KHONG mo attention
        eid = await _event(conn, ref, oid, lease=False)
        await _process(conn, eid, send)
        assert (await _state(conn, eid))[0] == "delivering" and await _attention(conn, oid) == []
        # worker do chet: lease het han -> reclaim -> pending -> worker nay xu ly -> chan dung 1 lan
        await conn.execute("UPDATE outbox_events SET lease_expires_at=now() - interval '1 second' WHERE id=$1", eid)
        await ow.reclaim_stale(conn)
        assert (await _state(conn, eid))[0] in ("pending", "retry_scheduled")
        await conn.execute("UPDATE outbox_events SET status='delivering', lease_owner=$2, "
                           "lease_expires_at=now()+interval '60 seconds' WHERE id=$1", eid, ow.WORKER_ID)
        assert await _process(conn, eid, send) == "window_blocked"
        assert await _process(conn, eid, send) == "window_blocked"      # xu ly lai (replay noi bo) -> no-op
        assert send.calls == [] and len(await _attention(conn, oid)) == 1
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_customer_reopens_window_new_message_sent_old_stays_cancelled():
    conn = await _conn()
    try:
        ref, _, oid, conv = await _customer(conn, inbound_ago_min=40 * 60)
        send = _Send()
        old = await _event(conn, ref, oid)
        assert await _process(conn, old, send) == "window_blocked"
        await conn.execute("INSERT INTO messages(conversation_id,role,content) VALUES($1,'customer','alo')", conv)
        new = await _event(conn, ref, oid)
        assert await _process(conn, new, send) == "delivered" and send.calls == ["messenger"]
        assert (await _state(conn, old))[0] == "cancelled"
    finally:
        await conn.close()
