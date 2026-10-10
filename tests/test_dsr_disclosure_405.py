"""CA Directive 405 — DSR tombstone psid + external_chat_id (+ kho van hanh) va khai bao tro ly tu dong tat dinh.

Pure (CI-safe): apply_disclosure (kenh/tin dau/rong/da co cau tuong duong), helper tombstone.
DB+Redis (skipif not M6_TEST_DB): xoa Messenger day du footprint (customer/command/intent/outbox/fulfillment/Redis/
dead-letter) -> khong con PSID goc -> cung PSID nhan lai tao customer moi; Telegram; callback Meta + callback lap;
2 yeu cau xoa dong thoi; xoa dong thoi voi tin moi; outbox ref tombstone khong goi provider; khai bao o THONG DIEP GUI
RA qua worker Messenger (chao / hoi gia / nhanh tra loi som / loi LLM / phien moi sau het han / luot sau / Telegram).
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import random
import uuid
from types import SimpleNamespace

import pytest

from app.services import customer_identity as ci
from app.services import orchestrator as O

D = O.DISCLOSURE_TEXT


# ============================================================ pure
def test_disclosure_text_has_both_ideas():
    f = O._fold_vi(D)
    assert "tro ly tu dong" in f and "3s coffee" in f and "nhan vien" in f


def test_apply_disclosure_rules():
    r = "Dạ em chào anh/chị ạ."
    assert O.apply_disclosure(r, channel="messenger", first_turn=True) == f"{D}\n\n{r}"
    assert O.apply_disclosure(r, channel="messenger", first_turn=False) == r          # luot sau
    assert O.apply_disclosure(r, channel="telegram_customer", first_turn=True) == r   # kenh khong yeu cau
    for empty in (None, "", "   "):                                                     # M7 SILENT / rong
        assert O.apply_disclosure(empty, channel="messenger", first_turn=True) == empty
    for already in ("Dạ em là trợ lý tự động của shop ạ.", "Da em la TRO LY TU DONG a", f"{D}\n\nChào ạ"):
        assert O.apply_disclosure(already, channel="messenger", first_turn=True) == already  # khong lap


def test_tombstone_helpers():
    t = ci.tombstone("ab12")
    assert t == "deleted:ab12" and ci.is_tombstone(t)
    assert not ci.is_tombstone("12345") and not ci.is_tombstone("tg:1") and not ci.is_tombstone(None)


# ============================================================ DB + Redis
DB = os.environ.get("M6_TEST_DB") == "1"
dbonly = pytest.mark.skipif(not DB, reason="can DB+Redis (M6_TEST_DB=1)")


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


async def _redis():
    import redis.asyncio as aioredis

    from app.config import settings
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def _psid() -> str:
    return "9" + "".join(random.choice("0123456789") for _ in range(15))


async def _seed_full(conn, psid: str, channel: str = "messenger") -> dict:
    """Khach co hoi thoai + don + intent dang mo + command bus + outbox (khach/staff/dead-letter) + M7 + Redis."""
    from app.services import conversation_log
    conv = await conversation_log.ensure_conversation(psid, channel=channel)
    cid = await conn.fetchval("SELECT id FROM customers WHERE psid=$1", psid)
    await conn.execute("UPDATE customers SET name='Khách Thử', phone='0900000001', address='1 Đường A' WHERE id=$1", cid)
    await conn.execute("INSERT INTO messages(conversation_id,role,content) VALUES($1,'customer','tin khach'),"
                       "($1,'bot','tin bot')", conv)
    tag = uuid.uuid4().hex[:10]
    oid = await conn.fetchval(
        "INSERT INTO orders(customer_id,status,total_vnd,origin_channel,shipping_name,shipping_phone,shipping_address) "
        "VALUES($1,'confirmed',200000,$2,'Người Nhận','0911222333','12 Lê Lợi') RETURNING id", cid, channel)
    intent = await conn.fetchval(
        "INSERT INTO order_intents(customer_id,conversation_id,channel,state,draft_customer_name,draft_phone,"
        "draft_address) VALUES($1,$2,$3,'COLLECTING','Người Nhận','0911222333','12 Lê Lợi') RETURNING id",
        cid, conv, channel)
    cmd = uuid.uuid4()
    await conn.execute(
        "INSERT INTO command_executions(id,command_type,command_version,idempotency_scope,idempotency_key,request_hash,"
        "status,actor_type,actor_id,channel,customer_id,conversation_id,correlation_id,causation_id,request_payload) "
        "VALUES($1,'order.create',1,$2,$3,$4,'accepted','customer',$5,$6,$7,$8,$9,$5,$10::jsonb)",
        cmd, f"order.create:{channel}:{psid}", f"k405-{tag}", "0" * 64, psid, channel, cid, conv, uuid.uuid4(),
        json.dumps({"customer_name": "Người Nhận", "phone_masked": "***333", "sku": "X", "psid": psid}))

    async def _ob(event_type, dest, payload, status="pending", command_id=cmd):
        await conn.execute(
            "INSERT INTO outbox_events(id,command_id,event_type,event_version,destination,dedupe_key,payload,status,"
            "max_attempts) VALUES($1,$2,$3,1,$4,$5,$6::jsonb,$7,5)",
            uuid.uuid4(), command_id, event_type, dest, f"t405:{tag}:{uuid.uuid4().hex[:6]}", json.dumps(payload),
            status)
    await _ob("order.receipt.customer", channel, {"customer_ref": psid, "order_id": oid, "text": "Đơn của Người Nhận"})
    await _ob("order.receipt.customer", channel, {"customer_ref": psid, "order_id": oid, "text": "x"}, "dead_lettered")
    await _ob("order.receipt.customer", channel, {"customer_ref": psid, "order_id": oid, "text": "y"}, "delivered")
    await _ob("order.created.notify", "telegram_admin", {"order_id": oid, "customer_name": "Người Nhận",
                                                         "phone_masked": "***333"})
    await _ob("handoff.escalated.notify", "telegram_admin",
              {"conversation_id": conv, "customer_name": "Khách Thử", "last_message": "nhà tôi ở 1 Đường A"},
              command_id=None)
    await _ob("order.escalated.notify", "telegram_admin",
              {"intent_id": str(intent), "customer_name": "Người Nhận", "address": "12 Lê Lợi"}, command_id=None)
    await conn.execute("INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,policy_version) "
                       "VALUES($1,$2,$3,'awaiting_method',1)", oid, channel, psid)
    r = await _redis()
    try:
        await r.set(f"chat:{psid}", json.dumps([{"role": "user", "content": "hi"}]), ex=600)
        await r.set(f"profile:{psid}", "{}", ex=600)
        await r.set(f"nlu_state:{psid}", "{}", ex=600)
        await r.set(f"addr_clarify:{psid}:abc", "1", ex=600)
        await r.lpush("dead_letter:messages",
                      json.dumps({"event": {"sender": {"id": psid}, "message": {"text": "x"}}, "job_try": 3}),
                      json.dumps({"event": {"sender": {"id": "other-405"}, "message": {"text": "y"}}, "job_try": 3}))
    finally:
        await r.aclose()
    return {"cid": cid, "conv": conv, "oid": oid, "intent": intent, "cmd": cmd}


async def _residual_count(conn, needle: str) -> dict:
    """Dem moi dong con chua chuoi dinh danh goc o cac kho mutable DSR phu trach (row::text — khong mock SQL)."""
    out = {}
    for t in ("customers", "conversations", "command_executions", "order_intents", "outbox_events",
              "fulfillment_conversations"):
        out[t] = await conn.fetchval(f"SELECT count(*) FROM {t} x WHERE x::text LIKE '%' || $1 || '%'", needle)
    return out


@dbonly
@pytest.mark.asyncio
async def test_messenger_delete_full_footprint_then_recontact():
    from app.services import conversation_log
    from app.services import data_deletion as dd
    psid = _psid()
    conn = await _conn()
    try:
        s = await _seed_full(conn, psid)
        res = await dd.process_deletion(psid)
        code, summ = res["confirmation_code"], res["summary"]
        assert summ is not None and summ["customer_found"], "xoa phai thanh cong (khong rollback vi FK)"
        assert (await dd.get_status(code))["status"] == "completed"
        tomb = ci.tombstone(code)
        row = await conn.fetchrow("SELECT * FROM customers WHERE id=$1", s["cid"])
        assert row["psid"] == tomb and row["external_chat_id"] == tomb and row["channel"] == "messenger"
        assert row["name"] is None and row["phone"] is None and row["address"] is None
        assert await _residual_count(conn, psid) == {t: 0 for t in (
            "customers", "conversations", "command_executions", "order_intents", "outbox_events",
            "fulfillment_conversations")}
        assert code not in psid and psid not in code
        # command bus: tombstone + bo ten + go FK
        ce = await conn.fetchrow("SELECT * FROM command_executions WHERE id=$1", s["cmd"])
        assert ce["actor_id"] == tomb and ce["causation_id"] == tomb and ce["conversation_id"] is None
        assert ce["idempotency_scope"] == f"order.create:messenger:{tomb}"
        assert "customer_name" not in json.loads(ce["request_payload"])
        # intent: draft PII bo, intent mo -> CANCELLED
        oi = await conn.fetchrow("SELECT * FROM order_intents WHERE id=$1", s["intent"])
        assert oi["state"] == "CANCELLED" and oi["terminal_reason"] == "data_deletion"
        assert oi["draft_customer_name"] is None and oi["draft_phone"] is None and oi["draft_address"] is None
        # outbox: tin chua gui toi khach -> cancelled; staff notify giu nhung bo ten/dia chi/tin
        obs = await conn.fetch(
            "SELECT event_type, status, payload FROM outbox_events WHERE command_id=$1 OR payload->>'conversation_id'=$2 "
            "OR payload->>'intent_id'=$3", s["cmd"], str(s["conv"]), str(s["intent"]))
        st = sorted((o["event_type"], o["status"]) for o in obs)
        assert ("order.receipt.customer", "cancelled") in st and ("order.receipt.customer", "delivered") in st
        assert [x for x in st if x[0] == "order.receipt.customer" and x[1] in ("pending", "dead_lettered")] == []
        for o in obs:
            p = json.loads(o["payload"])
            assert not ({"customer_name", "address", "last_message"} & p.keys())
            if o["event_type"] == "order.receipt.customer":
                assert p["customer_ref"] == tomb and "text" not in p
        assert await conn.fetchval("SELECT customer_ref FROM fulfillment_conversations WHERE order_id=$1",
                                   s["oid"]) == tomb
        o = await conn.fetchrow("SELECT shipping_name, shipping_phone, shipping_address FROM orders WHERE id=$1",
                                s["oid"])
        assert tuple(o) == (None, None, None)
        assert await conn.fetchval("SELECT count(*) FROM conversations WHERE customer_id=$1", s["cid"]) == 0
        # Redis
        r = await _redis()
        try:
            for k in (f"chat:{psid}", f"profile:{psid}", f"nlu_state:{psid}", f"addr_clarify:{psid}:abc"):
                assert not await r.exists(k), k
            dl = await r.lrange("dead_letter:messages", 0, -1)
            assert not [x for x in dl if psid in x] and [x for x in dl if "other-405" in x]
        finally:
            await r.aclose()
        # cung PSID nhan lai -> customer MOI (khong vuong uq_customers_channel_chat), du lieu cu khong quay lai
        conv2 = await conversation_log.ensure_conversation(psid, channel="messenger")
        new = await conn.fetchrow("SELECT c.* FROM customers c JOIN conversations v ON v.customer_id=c.id "
                                  "WHERE v.id=$1", conv2)
        assert new["id"] != s["cid"] and new["external_chat_id"] == psid and new["name"] is None
        # lap lai yeu cau (khach moi) -> xoa khach moi, khong dung lai khach cu
        res2 = await dd.process_deletion(psid)
        assert res2["summary"]["customer_found"] and res2["confirmation_code"] != code
        assert await conn.fetchval("SELECT psid FROM customers WHERE id=$1", s["cid"]) == tomb
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_telegram_delete_then_recontact():
    from app.services import conversation_log
    from app.services import data_deletion as dd
    chat = str(random.randint(10**9, 10**10))
    psid = f"tg:{chat}"
    conn = await _conn()
    try:
        s = await _seed_full(conn, psid, channel="telegram_customer")
        assert await conn.fetchval("SELECT external_chat_id FROM customers WHERE id=$1", s["cid"]) == chat
        res = await dd.process_deletion(psid)
        assert res["summary"]["customer_found"]
        tomb = ci.tombstone(res["confirmation_code"])
        row = await conn.fetchrow("SELECT psid, external_chat_id FROM customers WHERE id=$1", s["cid"])
        assert tuple(row) == (tomb, tomb)
        assert await conn.fetchval("SELECT count(*) FROM customers WHERE external_chat_id=$1 OR psid=$2",
                                   chat, psid) == 0
        assert sum((await _residual_count(conn, chat)).values()) == 0
        conv2 = await conversation_log.ensure_conversation(psid, channel="telegram_customer")
        new = await conn.fetchrow("SELECT c.* FROM customers c JOIN conversations v ON v.customer_id=c.id "
                                  "WHERE v.id=$1", conv2)
        assert new["id"] != s["cid"] and new["external_chat_id"] == chat and new["channel"] == "telegram_customer"
    finally:
        await conn.close()


def _signed_request(user_id: str, secret: str) -> str:
    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    payload = b64(json.dumps({"algorithm": "HMAC-SHA256", "user_id": user_id}).encode())
    sig = b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{sig}.{payload}"


@dbonly
@pytest.mark.asyncio
async def test_meta_callback_and_repeated_callback(monkeypatch):
    import httpx
    from fastapi import FastAPI

    from app.api import legal
    from app.config import settings
    from app.services import data_deletion as dd
    monkeypatch.setattr(settings, "meta_app_secret", "t405-secret")
    app = FastAPI()
    app.include_router(legal.router)
    psid = _psid()
    conn = await _conn()
    try:
        s = await _seed_full(conn, psid)
        body = {"signed_request": _signed_request(psid, "t405-secret")}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as cl:
            bad = await cl.post("/datadeletion/callback", data={"signed_request": _signed_request(psid, "wrong")})
            assert bad.status_code == 400
            assert await conn.fetchval("SELECT psid FROM customers WHERE id=$1", s["cid"]) == psid  # khong xoa gi
            r1 = await cl.post("/datadeletion/callback", data=body)
            r2 = await cl.post("/datadeletion/callback", data=body)
        assert r1.status_code == r2.status_code == 200
        c1, c2 = r1.json()["confirmation_code"], r2.json()["confirmation_code"]
        assert c1 != c2 and psid not in r1.text
        assert await conn.fetchval("SELECT psid FROM customers WHERE id=$1", s["cid"]) == ci.tombstone(c1)
        assert (await dd.get_status(c1))["status"] == (await dd.get_status(c2))["status"] == "completed"
        assert sum((await _residual_count(conn, psid)).values()) == 0
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_concurrent_deletions_single_tombstone():
    from app.services import data_deletion as dd
    psid = _psid()
    conn = await _conn()
    try:
        s = await _seed_full(conn, psid)
        a, b = await asyncio.gather(dd.process_deletion(psid), dd.process_deletion(psid))
        assert sorted([a["summary"]["customer_found"], b["summary"]["customer_found"]]) == [False, True]
        winner = a if a["summary"]["customer_found"] else b
        row = await conn.fetchrow("SELECT psid, external_chat_id FROM customers WHERE id=$1", s["cid"])
        assert tuple(row) == (ci.tombstone(winner["confirmation_code"]),) * 2
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_delete_concurrent_with_new_message_no_unique_violation():
    from app.services import conversation_log
    from app.services import data_deletion as dd
    psid = _psid()
    conn = await _conn()
    try:
        s = await _seed_full(conn, psid)
        res, conv2 = await asyncio.gather(dd.process_deletion(psid),
                                          conversation_log.ensure_conversation(psid, channel="messenger"))
        assert res["summary"] is not None and res["summary"]["customer_found"]
        assert await conn.fetchval("SELECT psid FROM customers WHERE id=$1", s["cid"]) == \
            ci.tombstone(res["confirmation_code"])
        # Tin moi xu ly sau xoa -> customer moi; neu chay truoc -> conversation do cung bi xoa. Khong UniqueViolation.
        assert await conn.fetchval("SELECT count(*) FROM customers WHERE psid=$1", psid) <= 1
        assert await conn.fetchval("SELECT count(*) FROM customers WHERE channel='messenger' AND external_chat_id=$1",
                                   psid) <= 1
        assert isinstance(conv2, int)
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_outbox_tombstoned_recipient_never_sent():
    from app.services.command import outbox_worker as ow
    conn = await _conn()
    try:
        cmd = uuid.uuid4()
        await conn.execute(
            "INSERT INTO command_executions(id,command_type,command_version,idempotency_scope,idempotency_key,"
            "request_hash,status,actor_type,actor_id,channel,correlation_id,request_payload) "
            "VALUES($1,'order.create',1,'s405',$2,$3,'accepted','system','t','messenger',$4,'{}'::jsonb)",
            cmd, uuid.uuid4().hex, "0" * 64, uuid.uuid4())
        eid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO outbox_events(id,command_id,event_type,event_version,destination,dedupe_key,payload,status,"
            "max_attempts,lease_owner,lease_expires_at) VALUES($1,$2,'order.receipt.customer',1,'messenger',$3,$4::jsonb,"
            "'delivering',5,$5,now()+interval '60 seconds')",
            eid, cmd, f"t405g:{eid}", json.dumps({"customer_ref": "deleted:abc", "text": "x"}), ow.WORKER_ID)
        ev = await conn.fetchrow("SELECT * FROM outbox_events WHERE id=$1", eid)
        calls = []

        async def _send(dest, payload):
            calls.append(dest)
            return ow.SendResult(ok=True, http_status=200)
        assert await ow._send_and_record(conn, dict(ev), _send) == "cancelled"
        assert calls == []
        row = await conn.fetchrow("SELECT status, last_error_code FROM outbox_events WHERE id=$1", eid)
        assert tuple(row) == ("cancelled", "recipient_deleted")
    finally:
        await conn.close()


# ---------------------------------------------- disclosure qua THONG DIEP GUI RA (worker Messenger)
class _FakeLLM:
    reply = "Dạ em chào anh/chị ạ."
    fail = False

    def __init__(self, *a, **k):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        if _FakeLLM.fail:
            raise RuntimeError("llm down")
        msg = SimpleNamespace(content=_FakeLLM.reply, tool_calls=None, reasoning_content=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))


@pytest.fixture
def worker(monkeypatch):
    """Worker Messenger that (tasks._process_message_inner) voi LLM gia + chan moi goi provider; tra list tin gui ra."""
    from app.config import settings
    from app.services import kb_retrieval
    from app.workers import tasks
    sent = []

    async def _send_text(psid, text):
        sent.append(text)

    async def _noop(*a, **k):
        return None

    async def _no_kb(*a, **k):
        return []

    async def _no_profile(*a, **k):
        return {}
    monkeypatch.setattr(tasks, "send_text", _send_text)
    monkeypatch.setattr(tasks, "try_take_thread_control", _noop)
    monkeypatch.setattr(O, "AsyncOpenAI", _FakeLLM)
    monkeypatch.setattr(O, "get_user_profile", _no_profile)
    monkeypatch.setattr(O, "_server_propose_turn", _noop)
    monkeypatch.setattr(kb_retrieval, "search_kb", _no_kb)
    monkeypatch.setattr(settings, "enable_nlu_router", False)
    _FakeLLM.reply, _FakeLLM.fail = "Dạ em chào anh/chị ạ.", False

    async def run(psid, text):
        n = len(sent)
        await tasks._process_message_inner({"sender": {"id": psid}, "message": {"mid": uuid.uuid4().hex,
                                                                                 "text": text}})
        return sent[n:]
    return run


async def _last_bot_row(conn, psid):
    return await conn.fetchval(
        "SELECT m.content FROM messages m JOIN conversations c ON c.id=m.conversation_id JOIN customers cu "
        "ON cu.id=c.customer_id WHERE cu.psid=$1 AND m.role='bot' ORDER BY m.id DESC LIMIT 1", psid)


@dbonly
@pytest.mark.asyncio
async def test_disclosure_greeting_then_next_turn_then_new_session(worker):
    psid = _psid()
    conn = await _conn()
    try:
        out = await worker(psid, "Chào shop")
        assert out == [f"{D}\n\nDạ em chào anh/chị ạ."]
        assert await _last_bot_row(conn, psid) == out[0]          # log DB = ban da gui
        r = await _redis()
        try:
            h = json.loads(await r.get(f"chat:{psid}"))
            assert h[-1] == {"role": "assistant", "content": out[0]}
            out2 = await worker(psid, "Cho em hỏi thêm")         # luot sau cung phien -> KHONG lap
            assert out2 == ["Dạ em chào anh/chị ạ."]
            await r.delete(f"chat:{psid}")                         # lich su het han (TTL 24h) -> phien moi
        finally:
            await r.aclose()
        out3 = await worker(psid, "Shop ơi")
        assert out3[0].startswith(D) and out3[0].count("trợ lý tự động") == 1
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_disclosure_product_question_and_llm_already_disclosed(worker):
    _FakeLLM.reply = "Dạ hũ cà phê sấy lạnh 50g giá 189.000đ ạ."
    out = await worker(_psid(), "Cà phê giá bao nhiêu vậy shop?")
    assert out == [f"{D}\n\nDạ hũ cà phê sấy lạnh 50g giá 189.000đ ạ."]
    _FakeLLM.reply = "Dạ em là trợ lý tự động của 3S Coffee ạ. Giá 189.000đ."
    out = await worker(_psid(), "giá?")
    assert out == [_FakeLLM.reply]                                 # da co cau tuong duong -> khong chen them


@dbonly
@pytest.mark.asyncio
async def test_disclosure_on_llm_error_fallback(worker):
    _FakeLLM.fail = True
    out = await worker(_psid(), "alo")
    assert out == [f"{D}\n\nĐội ngũ 3S Coffee sẽ phản hồi bạn ngay."]


@dbonly
@pytest.mark.asyncio
async def test_disclosure_on_early_deterministic_branch(worker):
    psid = _psid()
    conn = await _conn()
    try:
        out = await worker(psid, "cho em xóa dữ liệu")             # nhanh tra loi som (khong qua LLM)
        assert len(out) == 1 and out[0].startswith(f"{D}\n\n") and "XÁC NHẬN XÓA" in out[0]
        assert await _last_bot_row(conn, psid) == out[0]
        out2 = await worker(psid, "XÁC NHẬN XÓA")                  # luot sau: khong lap, xoa xong khong tao lai
        assert not out2[0].startswith(D) and "Mã xác nhận" in out2[0]
        assert await conn.fetchval("SELECT count(*) FROM customers WHERE psid=$1", psid) == 0
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_no_disclosure_on_telegram():
    psid = f"tg:{random.randint(10**9, 10**10)}"
    reply = await O.handle_message(psid, "xóa dữ liệu", channel="telegram_customer")
    assert not reply.startswith(D)
