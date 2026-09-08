"""CA Review 253-01 R2 harness — chay SAU nhom case qua PATH THAT (assertion tren output/query that,
khong hard-code). Throwaway m5lab DB (schema>=062). KHONG PII/secret. Re-runnable (RUN).

Nhom (253 §3):
  G1 truthful guard reply cho MOI state (NEEDS_CLARIFICATION/ESCALATED/REJECTED/CANCELLED/EXPIRED/COMMITTED)
     qua handle_message thuc; CHI COMMITTED duoc noi "da ghi nhan".
  G2 khach sua dia chi dung o luot 1/2/3 -> READY/confirm/commit, moi case DUNG 1 order.
  G3 outbox worker: transient delivery fail -> retry -> success, KHONG duplicate logical notification.
  G4 cross-intent: cung conversation 1 COMMITTED + 1 ESCALATED -> payload/status phan biet, khong stale.
  G5 bounded context + PII treatment tren payload THAT.
  G6 unknown reason tren FRESH no-intent conversation -> KHONG pause, KHONG outbox.
"""
import asyncio
import json
import sys
import time
import types

from app.config import Settings, settings
from app.db_pool import acquire, close_pool, release
from app.services import handoff, tools
from app.services import orchestrator
from app.services.command import order_intent_service as svc
from app.services.command import outbox_worker

RUN = str(int(time.time()))
FAILS = []


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


# ---- Mock LLM: main-loop (tools=) lay tu _S; extraction (khong tools) lay tu _EX ----
_S, _EX = [], []


def _mk(content=None, tools_=None):
    tcs = [types.SimpleNamespace(id=f"c{i}", function=types.SimpleNamespace(
        name=t["name"], arguments=json.dumps(t["args"], ensure_ascii=False)))
        for i, t in enumerate(tools_ or [])] or None
    return types.SimpleNamespace(content=content, tool_calls=tcs)


async def _fake(client, **kw):
    if "tools" in kw:
        it = _S.pop(0) if _S else {"text": "..."}
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=_mk(it.get("text"), it.get("tools")),
            finish_reason="tool_calls" if it.get("tools") else "stop")],
            usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=1))
    return types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=_mk(json.dumps(_EX.pop(0) if _EX else {}, ensure_ascii=False)), finish_reason="stop")],
        usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=1))


orchestrator._llm_create = _fake

_C = [0]


def mid(pfx="tg"):
    _C[0] += 1
    return f"{pfx}:{RUN}{_C[0]}"


def base_flags():
    settings.m1_reliable_order_command = False
    settings.enable_gate_e_order_wiring = True
    settings.enable_address_resolver = True
    settings.enable_nlu_router = False
    settings.gate_e_canary_customer_ids = ""
    settings.address_resolver_pilot_customer_ids = ""
    settings.gate_e_kill_switch = False
    settings.gate_e_fullscope_telegram_customer = True   # full-scope -> enroll moi khach TG
    settings.address_resolver_fullscope_telegram_customer = True
    settings.gate_e_fullscope_messenger = False
    settings.address_resolver_fullscope_messenger = False


async def q(s, *a):
    c = await acquire()
    try:
        return await c.fetchval(s, *a)
    finally:
        await release(c)


async def seed_products():
    c = await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPR2','Ca phe hu',500,90000) "
                        "ON CONFLICT(sku) DO UPDATE SET stock=500,price_vnd=90000")
    finally:
        await release(c)


async def mkcust(psid):
    c = await acquire()
    try:
        cid = await c.fetchval("SELECT id FROM customers WHERE psid=$1", psid) or await c.fetchval(
            "INSERT INTO customers(psid,name,phone) VALUES($1,'Hoa','0900001234') RETURNING id", psid)
        conv = await c.fetchval("SELECT id FROM conversations WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid) \
            or await c.fetchval("INSERT INTO conversations(customer_id,bot_paused) VALUES($1,FALSE) RETURNING id", cid)
        return cid, conv
    finally:
        await release(c)


async def set_intent_state(cid, conv, state, *, committed_order_id=None, channel="telegram_customer"):
    """Tao/dat mot intent o state cho truoc (test G1). Dung transition hop le tu COLLECTING."""
    c = await acquire()
    try:
        async with c.transaction():
            row = await svc.create_intent(c, customer_id=cid, conversation_id=conv, channel=channel)
            iid = row["id"]
            await c.execute("UPDATE order_intents SET draft_sku='SPR2',draft_quantity=1,draft_customer_name='Hoa',"
                            "draft_phone='0900001234',draft_address='12 Le Loi, P. Ea Kao, Dak Lak' WHERE id=$1", iid)
            # dat truc tiep state (test fixture) — bypass transition-guard chi de dung san state cho G1.
            if committed_order_id is not None:
                await c.execute("UPDATE order_intents SET state=$2, committed_order_id=$3 WHERE id=$1",
                                iid, state, committed_order_id)
            else:
                await c.execute("UPDATE order_intents SET state=$2 WHERE id=$1", iid, state)
        return iid
    finally:
        await release(c)


CLAIM = "Dạ đơn của anh/chị đã được ghi nhận rồi ạ, cảm ơn anh/chị."


async def main():
    base_flags()
    await seed_products()

    # ================= G1: truthful guard reply per state =================
    print("== G1 truthful guard reply per state ==")
    states = ["NEEDS_CLARIFICATION", "ESCALATED", "REJECTED", "CANCELLED", "EXPIRED", "COMMITTED"]
    for st in states:
        psid = f"tg:g1-{st}-{RUN}"
        cid, conv = await mkcust(psid)
        coid = None
        if st == "COMMITTED":
            # tao 1 order that de committed_order_id tro toi
            coid = await q("INSERT INTO orders(customer_id,status,total_vnd) VALUES($1,'new',90000) RETURNING id", cid)
        await set_intent_state(cid, conv, st, committed_order_id=coid)
        _S.clear(); _EX.clear()
        _S.append({"text": CLAIM})  # model BIA "da ghi nhan"
        _EX.append({})              # extraction rong (khong tao don)
        reply = await orchestrator.handle_message(psid, "cảm ơn em nhé", channel="telegram_customer",
                                                  provider_message_id=mid())
        claims = "đã được ghi nhận" in (reply or "").lower() or "đã ghi nhận" in (reply or "").lower()
        if st == "COMMITTED":
            ck(f"G1 {st}: reply DUOC noi da ghi nhan (truthful)", claims, (reply or "")[:60])
        else:
            ck(f"G1 {st}: reply KHONG noi da ghi nhan (server-truth override bia)", not claims, (reply or "")[:70])

    # ================= G6: unknown reason tren FRESH no-intent conversation =================
    print("== G6 unknown reason fresh no-intent ==")
    psid6 = f"tg:g6-{RUN}"
    _cid6, conv6 = await mkcust(psid6)
    res = await tools.escalate_to_human(psid=psid6, reason="x", reason_code="totally_bogus",
                                        channel="telegram_customer")
    paused = await q("SELECT bot_paused FROM conversations WHERE id=$1", conv6)
    n_ob = await q("SELECT count(*) FROM outbox_events WHERE dedupe_key LIKE $1", f"handoff_escalated:{conv6}:%")
    ck("G6: unknown reason -> refused", res.get("refused") == "unknown_reason")
    ck("G6: FRESH conversation KHONG bi pause", paused is False, f"paused={paused}")
    ck("G6: KHONG tao outbox", n_ob == 0, f"n={n_ob}")

    # ================= G4/G5: cross-intent (committed + escalated) + PII/bounded =================
    print("== G4 cross-intent committed+escalated + G5 PII/bounded ==")
    psid4 = f"tg:g4-{RUN}"
    cid4, conv4 = await mkcust(psid4)
    o4 = await q("INSERT INTO orders(customer_id,status,total_vnd) VALUES($1,'new',90000) RETURNING id", cid4)
    # intent 1: COMMITTED (order-created.notify se do command flow — o day chi mo phong committed intent)
    await set_intent_state(cid4, conv4, "COMMITTED", committed_order_id=o4)
    # intent 2 (moi, cung conversation): open -> ESCALATED (durable notify)
    from app.services.command import order_intent_flow as oif
    i2 = await set_intent_state(cid4, conv4, "COLLECTING")  # unique index 1 open/conv: intent1 da COMMITTED (terminal)
    await oif.terminalize(customer_id=cid4, conversation_id=conv4, to_state="ESCALATED",
                          reason="clarification_exhausted")
    pj = await q("SELECT payload FROM outbox_events WHERE dedupe_key LIKE $1", f"order_escalated:{i2}:%")
    pjd = pj if isinstance(pj, dict) else json.loads(pj)
    ck("G4: escalated notify gan intent2 (khong nham intent1 committed)", pjd.get("intent_id") == str(i2)
       and pjd.get("has_intent") is True)
    # CA Review 254-01: latest intent (ESCALATED moi) PHAI thang committed CU — assert CHINH XAC "escalated",
    # KHONG chap nhan "committed" stale nua.
    st_srv = await orchestrator._conversation_order_state(psid4, conv4)
    ck("G4: server-state = escalated (latest intent, KHONG stale committed cu)",
       st_srv.get("state") == "escalated", st_srv.get("state"))
    # CA 254 §4.3: chay actual handle_message case nay -> reply KHONG duoc claim don MOI da ghi nhan.
    _S.clear(); _EX.clear()
    _S.append({"text": CLAIM})  # model BIA "da ghi nhan"
    _EX.append({})              # extraction rong (khong tao don moi)
    reply4 = await orchestrator.handle_message(psid4, "em chốt đơn giúp anh nhé", channel="telegram_customer",
                                               provider_message_id=mid())
    _low4 = (reply4 or "").lower()
    ck("G4: reply KHONG claim don MOI da ghi nhan (escalated override bia)",
       ("đã được ghi nhận" not in _low4 and "đã ghi nhận" not in _low4), (reply4 or "")[:80])
    # CA 254 §4.4: regression — conversation CHI co committed intent van tra "committed".
    psid4b = f"tg:g4b-{RUN}"
    cid4b, conv4b = await mkcust(psid4b)
    o4b = await q("INSERT INTO orders(customer_id,status,total_vnd) VALUES($1,'new',90000) RETURNING id", cid4b)
    await set_intent_state(cid4b, conv4b, "COMMITTED", committed_order_id=o4b)
    st_srv_b = await orchestrator._conversation_order_state(psid4b, conv4b)
    ck("G4: regression committed-only conversation van tra committed",
       st_srv_b.get("state") == "committed", st_srv_b.get("state"))
    # G5 PII/bounded
    ck("G5: SDT masked (khong lo so day du)", pjd.get("phone_masked", "").startswith("***")
       and "0900001234" not in json.dumps(pjd), pjd.get("phone_masked"))
    ck("G5: address bounded (<=80 char)", len(pjd.get("address") or "") <= 80)

    # ================= G3: outbox worker transient fail -> retry -> success, no duplicate =================
    print("== G3 outbox worker transient retry ==")
    # tao 1 escalation outbox (qua conversation-scoped cho gon)
    psid3 = f"tg:g3-{RUN}"
    _c3, conv3 = await mkcust(psid3)
    await handoff.enqueue_conversation_escalation_notify(conv3, channel="telegram_customer",
                                                         reason_code="customer_wants_human",
                                                         reason_detail="test", last_message="cho gap nguoi")
    dk = f"handoff_escalated:{conv3}:customer_wants_human"
    _attempts = {"n": 0}
    _orig_send = outbox_worker.telegram_send

    async def _flaky(dest, payload):
        # CHI flaky cho ROW cua minh (m5lab co the con pending rows khac) — fail 1 lan roi success.
        mine = (payload.get("conversation_id") == conv3 and payload.get("reason_code") == "customer_wants_human")
        if mine:
            _attempts["n"] += 1
            if _attempts["n"] == 1:
                return outbox_worker.SendResult(ok=False, is_timeout=True, error_class="timeout")  # transient
        return outbox_worker.SendResult(ok=True, http_status=200, provider_message_id="m1")

    outbox_worker.telegram_send = _flaky
    try:
        await outbox_worker.run_once()   # lan 1: transient fail -> retry_scheduled
        st1 = await q("SELECT status FROM outbox_events WHERE dedupe_key=$1", dk)
        # ep available_at ve qua khu de retry ngay
        c = await acquire()
        try:
            await c.execute("UPDATE outbox_events SET available_at=now()-interval '1 minute' WHERE dedupe_key=$1", dk)
        finally:
            await release(c)
        await outbox_worker.run_once()   # lan 2: success
        st2 = await q("SELECT status FROM outbox_events WHERE dedupe_key=$1", dk)
        n_rows = await q("SELECT count(*) FROM outbox_events WHERE dedupe_key=$1", dk)
        ck("G3: transient fail lan 1 -> khong delivered", st1 != "delivered", f"st1={st1}")
        ck("G3: retry lan 2 -> delivered", st2 == "delivered", f"st2={st2}")
        ck("G3: KHONG duplicate logical notification (van 1 outbox row)", n_rows == 1, f"rows={n_rows}")
        ck("G3: gui THAT su chi thanh cong 1 lan (attempts=2: 1 fail +1 success)", _attempts["n"] == 2, _attempts["n"])
    finally:
        outbox_worker.telegram_send = _orig_send

    # ================= G2: correction turn 1/2/3 -> commit exactly one =================
    print("== G2 correction turn 1/2/3 -> commit 1 order ==")
    FULL = {"sku": "SPR2", "quantity": 1, "customer_name": "Hoa", "phone": "0900001234",
            "address": "12 Le Loi, Phuong Ea Kao, Dak Lak", "province": "Tỉnh Đắk Lắk", "ward": "Phường Ea Kao"}
    for turn in (1, 2, 3):
        psid = f"tg:g2-t{turn}-{RUN}"
        cid, conv = await mkcust(psid)
        # (turn-1) luot dia chi CHUA DU (thieu ward/province) -> need_more, giu intent OPEN (khong escalate,
        # khong clarify-exhaust) — mo phong khach dua thong tin dan; luot cuoi moi day du -> READY.
        for _ in range(turn - 1):
            _S.clear(); _EX.clear()
            _S.append({"tools": [{"name": "create_order", "args": {
                "sku": "SPR2", "quantity": 1, "customer_name": "Hoa", "phone": "0900001234"}}]})  # THIEU address
            _EX.append({"sku": "SPR2", "quantity": 1, "customer_name": "Hoa", "phone": "0900001234"})
            await orchestrator.handle_message(psid, "dat 1 hu ca phe", channel="telegram_customer",
                                              provider_message_id=mid())
        # luot SUA dung -> READY (verified)
        _S.clear(); _EX.clear()
        _S.append({"tools": [{"name": "create_order", "args": {k: FULL[k] for k in
                   ("sku", "quantity", "customer_name", "phone", "address")}}]})
        _EX.append({"sku": "SPR2", "quantity": 1, "customer_name": "Hoa", "phone": "0900001234",
                    "address": FULL["address"], "province": FULL["province"], "ward": FULL["ward"]})
        r_ready = await orchestrator.handle_message(psid, "dat 1 hu giao Phuong Ea Kao, Dak Lak",
                                                    channel="telegram_customer", provider_message_id=mid())
        # confirm -> commit
        _S.clear(); _EX.clear()
        _S.append({"text": "Dạ vâng"})
        _EX.append({})
        await orchestrator.handle_message(psid, "xác nhận", channel="telegram_customer",
                                          provider_message_id=mid())
        n_orders = await q("SELECT count(*) FROM order_intents WHERE customer_id=$1 AND state='COMMITTED'", cid)
        n_committed_orders = await q("SELECT count(*) FROM orders WHERE customer_id=$1", cid)
        ck(f"G2 correction@turn{turn}: DUNG 1 committed intent", n_orders == 1, f"committed_intents={n_orders}")
        ck(f"G2 correction@turn{turn}: DUNG 1 order (khong trung)", n_committed_orders == 1, f"orders={n_committed_orders}")

    await close_pool()
    print("\nRESULT:", "ALL PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main())
