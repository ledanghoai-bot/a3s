"""CA Review 236 — two regressions (236-01 inbox effective-once recovery, 236-02 conversation-safe staff
receipt reconciler). Extraction-primary flow, sanitized synthetic."""
import asyncio
import json
import sys
import time
import types

from app.config import settings
from app.db_pool import acquire, close_pool, release
from app.services import orchestrator
from app.services.command import order_intent_flow as oiflow
from app.services.command import order_intent_service as oisvc
from app.services.command import staff_receipt_reconcile

RUN = str(int(time.time()))
FAILS = []


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


_S = []
_EX = []


def _mk(content=None, tools=None):
    tcs = [types.SimpleNamespace(id=f"c{i}", function=types.SimpleNamespace(
        name=t["name"], arguments=json.dumps(t["args"], ensure_ascii=False)))
        for i, t in enumerate(tools or [])] or None
    return types.SimpleNamespace(content=content, tool_calls=tcs)


def _resp(m, f):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=m, finish_reason=f)],
                                 usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=1))


async def _fake(client, **kw):
    if "tools" in kw:
        it = _S.pop(0) if _S else {"text": "..."}
        return _resp(_mk(it.get("text"), it.get("tools")), "tool_calls" if it.get("tools") else "stop")
    return _resp(_mk(json.dumps(_EX.pop(0) if _EX else {}, ensure_ascii=False)), "stop")


orchestrator._llm_create = _fake


async def q1(s, *a):
    c = await acquire()
    try:
        return await c.fetchval(s, *a)
    finally:
        await release(c)


async def ex(s, *a):
    c = await acquire()
    try:
        return await c.execute(s, *a)
    finally:
        await release(c)


async def setup(psid, sku="SPV2H"):
    c = await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES($1,'Cà phê hũ',500,90000) "
                        "ON CONFLICT(sku) DO UPDATE SET stock=500,name='Cà phê hũ',price_vnd=90000", sku)
        return await c.fetchval("SELECT id FROM customers WHERE psid=$1", psid) or await c.fetchval(
            "INSERT INTO customers(psid,name,phone) VALUES($1,'H','0900001234') RETURNING id", psid)
    finally:
        await release(c)


ADDR = "12 Le Loi, P. Ea Kao, Dak Lak"


def FULL(sku="SPV2H", qty=1):
    return {"sku": sku, "quantity": qty, "customer_name": "Hoa", "phone": "0900001234", "address": ADDR,
            "province": "Tỉnh Đắk Lắk", "ward": "Phường Ea Kao"}


_C = [0]


def mid():
    _C[0] += 1
    return f"tg:{RUN}{_C[0]}"


async def enroll(cid):
    settings.m1_reliable_order_command = False
    settings.enable_gate_e_order_wiring = True
    settings.enable_address_resolver = True
    settings.enable_nlu_router = False
    settings.gate_e_canary_customer_ids = str(cid)
    settings.address_resolver_pilot_customer_ids = str(cid)


async def nintents(cid):
    return await q1("SELECT count(*) FROM order_intents WHERE customer_id=$1", cid)


async def main():
    # ============ 236-01 STATE MACHINE (deterministic) ============
    ch = "telegram_customer"
    ev = f"tg:{RUN}sm1"
    c = await acquire()
    try:
        async with c.transaction():
            s1 = await oisvc.claim_inbound_event(c, channel=ch, provider_message_id=ev)
        async with c.transaction():
            s2 = await oisvc.claim_inbound_event(c, channel=ch, provider_message_id=ev)  # processing+leased
        await oisvc.mark_inbound_event(c, channel=ch, provider_message_id=ev, ok=True)
        async with c.transaction():
            s3 = await oisvc.claim_inbound_event(c, channel=ch, provider_message_id=ev)  # succeeded
        ev2 = f"tg:{RUN}sm2"
        async with c.transaction():
            s4 = await oisvc.claim_inbound_event(c, channel=ch, provider_message_id=ev2)
        await oisvc.mark_inbound_event(c, channel=ch, provider_message_id=ev2, ok=False)  # retryable
        async with c.transaction():
            s5 = await oisvc.claim_inbound_event(c, channel=ch, provider_message_id=ev2)  # re-claim
    finally:
        await release(c)
    ck("236-01 state machine: claimed/busy/succeeded/claimed/retry->claimed",
       (s1, s2, s3, s4, s5) == ("claimed", "busy", "succeeded", "claimed", "claimed"), (s1, s2, s3, s4, s5))

    # ============ 236-01b EXTRACTION failure -> event NOT lost, redelivery succeeds once ============
    cid = await setup(f"tg:x1-{RUN}")
    await enroll(cid)
    EV = f"tg:{RUN}8801"
    _orig_ex = orchestrator._server_extract_order_fields
    _calls = {"n": 0}

    async def _flaky_extract(*a, **k):
        _calls["n"] += 1
        if _calls["n"] == 1:
            raise RuntimeError("extraction failure injected")
        return await _orig_ex(*a, **k)

    orchestrator._server_extract_order_fields = _flaky_extract
    try:
        _EX.clear()
        _EX.append(FULL())
        _S.clear()
        _S.append({"text": "..."})
        await orchestrator.handle_message(f"tg:x1-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                          channel=ch, provider_message_id=EV)
        ni_after_fail = await nintents(cid)
        # redeliver SAME event -> claim sees retryable -> re-claim -> extraction now succeeds
        _EX.clear()
        _EX.append(FULL())
        _S.clear()
        _S.append({"text": "..."})
        await orchestrator.handle_message(f"tg:x1-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                          channel=ch, provider_message_id=EV)
    finally:
        orchestrator._server_extract_order_fields = _orig_ex
    st = await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid)
    ck("236-01b extraction fail -> event GIU (retryable), redelivery -> READY (1 mutation, khong mat don)",
       await nintents(cid) == 1 and st == "READY_TO_COMMIT", f"ni_fail={ni_after_fail} ni={await nintents(cid)} st={st}")

    # ============ 236-01c PROPOSAL-persistence failure -> retryable -> redelivery succeeds ============
    cid = await setup(f"tg:x2-{RUN}")
    await enroll(cid)
    EV = f"tg:{RUN}8802"
    _orig_prop = oiflow.propose_draft
    _pc = {"n": 0}

    async def _flaky_prop(*a, **k):
        _pc["n"] += 1
        if _pc["n"] == 1:
            raise RuntimeError("proposal persistence failure injected")
        return await _orig_prop(*a, **k)

    oiflow.propose_draft = _flaky_prop
    try:
        _EX.clear()
        _EX.append(FULL())
        _S.clear()
        _S.append({"text": "..."})
        await orchestrator.handle_message(f"tg:x2-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                          channel=ch, provider_message_id=EV)
        _EX.clear()
        _EX.append(FULL())
        _S.clear()
        _S.append({"text": "..."})
        await orchestrator.handle_message(f"tg:x2-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                          channel=ch, provider_message_id=EV)
    finally:
        oiflow.propose_draft = _orig_prop
    st = await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid)
    ck("236-01c proposal fail -> retryable, redelivery -> READY (khong mat don, khong duplicate)",
       await nintents(cid) == 1 and st == "READY_TO_COMMIT", f"ni={await nintents(cid)} st={st}")

    # ============ 236-01d concurrent SAME event -> one draft mutation ============
    cid = await setup(f"tg:x3-{RUN}")
    await enroll(cid)
    EV = f"tg:{RUN}8803"
    _EX.clear()
    _EX.append(FULL())
    _S.clear()
    _S.extend([{"text": "..."}, {"text": "..."}])
    await asyncio.gather(
        orchestrator.handle_message(f"tg:x3-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                    channel=ch, provider_message_id=EV),
        orchestrator.handle_message(f"tg:x3-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                    channel=ch, provider_message_id=EV))
    ck("236-01d concurrent same-event -> 1 intent (1 draft mutation)", await nintents(cid) == 1,
       await nintents(cid))

    # ============ 236-02 conversation-safe reconciler ============
    cid = await setup(f"tg:cv-{RUN}")
    await enroll(cid)
    _EX.clear()
    _EX.append(FULL())
    _S.clear()
    _S.append({"text": "ok"})
    await orchestrator.handle_message(f"tg:cv-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                      channel=ch, provider_message_id=f"tg:{RUN}7701")
    src_conv = await q1("SELECT conversation_id FROM order_intents WHERE customer_id=$1 "
                        "AND state='READY_TO_COMMIT' ORDER BY created_at DESC LIMIT 1", cid)
    # confirm with staff-log failure injected -> committed, staff row missing
    _orig_log = oisvc.log_message_tx

    async def _boom(conn, conversation_id, role, content, dedupe_key=None):
        if dedupe_key and dedupe_key.startswith("order_receipt:"):
            raise RuntimeError("staff-log failure injected")
        return await _orig_log(conn, conversation_id, role, content, dedupe_key=dedupe_key)

    oisvc.log_message_tx = _boom
    try:
        _S.clear()
        _S.append({"text": "..."})
        await orchestrator.handle_message(f"tg:cv-{RUN}", "xác nhận", channel=ch,
                                          provider_message_id=f"tg:{RUN}7702")
    finally:
        oisvc.log_message_tx = _orig_log
    oid = await q1("SELECT committed_order_id FROM order_intents WHERE customer_id=$1 AND state='COMMITTED' "
                   "ORDER BY updated_at DESC LIMIT 1", cid)
    # create a NEWER conversation for same customer (the wrong target for 'latest')
    new_conv = await q1("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id", cid)
    ck("236-02 setup: src_conv < new_conv (2 conversations 1 khach)", src_conv is not None
       and new_conv > src_conv, f"src={src_conv} new={new_conv}")
    obx_before = await q1("SELECT count(*) FROM outbox_events WHERE dedupe_key=$1", f"order_receipt:{oid}")
    n1 = await staff_receipt_reconcile.reconcile_staff_receipts()
    in_src = await q1("SELECT count(*) FROM messages WHERE dedupe_key=$1 AND conversation_id=$2",
                      f"order_receipt:{oid}", src_conv)
    in_new = await q1("SELECT count(*) FROM messages WHERE dedupe_key=$1 AND conversation_id=$2",
                      f"order_receipt:{oid}", new_conv)
    await staff_receipt_reconcile.reconcile_staff_receipts()  # repeat -> +0
    in_src2 = await q1("SELECT count(*) FROM messages WHERE dedupe_key=$1", f"order_receipt:{oid}")
    obx_after = await q1("SELECT count(*) FROM outbox_events WHERE dedupe_key=$1", f"order_receipt:{oid}")
    ck("236-02 receipt restored in SOURCE conversation exactly once", in_src == 1, in_src)
    ck("236-02 ZERO receipt in newer/wrong conversation", in_new == 0, in_new)
    ck("236-02 repeat reconcile -> +0 (tong 1)", in_src2 == 1, in_src2)
    ck("236-02 customer outbox unchanged (khong resend)", obx_before == obx_after == 1,
       f"{obx_before}->{obx_after}")

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: ' + ', '.join(FAILS)}")
    await close_pool()
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
