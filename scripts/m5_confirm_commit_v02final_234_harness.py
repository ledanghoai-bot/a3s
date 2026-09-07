"""CA Review 234 — final corrections harness (234-02/03/04). Extraction-primary flow.
Mock _llm_create: MAIN loop (tools=) -> text (assistant refuses tools); EXTRACTION (no tools) -> JSON.
Sanitized synthetic data (no real PII)."""
import asyncio
import json
import sys
import time
import types

from app.config import settings
from app.db_pool import acquire, close_pool, release
from app.services import orchestrator
from app.services.command import order_intent_service as oisvc
from app.services.command import outbox_worker

RUN = str(int(time.time()))
FAILS = []


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


_S = []
_EX = []
_TOOL = {"n": 0}


def _mkmsg(content=None, tools=None):
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
        if it.get("tools"):
            _TOOL["n"] += 1
        return _resp(_mkmsg(it.get("text"), it.get("tools")), "tool_calls" if it.get("tools") else "stop")
    return _resp(_mkmsg(json.dumps(_EX.pop(0) if _EX else {}, ensure_ascii=False)), "stop")


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


async def setup(psid, sku="SPV2F"):
    c = await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES($1,'Cà phê hũ',500,90000) "
                        "ON CONFLICT(sku) DO UPDATE SET stock=500,name='Cà phê hũ',price_vnd=90000", sku)
        return await c.fetchval("SELECT id FROM customers WHERE psid=$1", psid) or await c.fetchval(
            "INSERT INTO customers(psid,name,phone) VALUES($1,'H','0900001234') RETURNING id", psid)
    finally:
        await release(c)


ADDR = "12 Le Loi, P. Ea Kao, Dak Lak"
_C = [0]


def mid():
    _C[0] += 1
    return f"tg:{RUN}{_C[0]}"


def FULL(sku="SPV2F"):
    return {"sku": sku, "quantity": 1, "customer_name": "Hoa", "phone": "0900001234", "address": ADDR,
            "province": "Tỉnh Đắk Lắk", "ward": "Phường Ea Kao"}


async def isolate_receipt(oid):
    """Shared m5lab DB co nhieu outbox pending cu -> mark tat ca receipt KHAC 'delivered' de drain xac dinh
    chi cham event cua don nay (BATCH claim oldest-first)."""
    await ex("UPDATE outbox_events SET status='delivered', delivered_at=now() "
             "WHERE event_type='order.receipt.customer' AND status NOT IN ('delivered','dead_letter') "
             "AND dedupe_key <> $1", f"order_receipt:{oid}")


async def st(cid):
    return await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid)


async def sv(cid):
    return await q1("SELECT state_version FROM order_intents WHERE customer_id=$1 "
                    "ORDER BY created_at DESC LIMIT 1", cid)


async def norders(cid):
    return await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cid)


async def send(psid, msg, ch="telegram_customer"):
    return await orchestrator.handle_message(psid, msg, channel=ch, provider_message_id=mid())


async def enroll_tg(cid):
    # Gate E pilot BAT BUOC co verified resolution (binding fail-closed) -> resolver ON + dia chi resolve.
    settings.m1_reliable_order_command = False
    settings.enable_gate_e_order_wiring = True
    settings.enable_address_resolver = True
    settings.enable_nlu_router = False
    settings.gate_e_canary_customer_ids = str(cid)
    settings.address_resolver_pilot_customer_ids = str(cid)


async def drive_ready_tg(psid, cid, sku="SPV2F"):
    _EX.clear()
    _EX.append(FULL(sku))
    _S.clear()
    _S.append({"text": "ok"})
    return await send(psid, "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234")


async def main():
    # ================= 234-02.1 NO-OP identical proposal =================
    cid = await setup(f"tg:n1-{RUN}")
    await enroll_tg(cid)
    await drive_ready_tg(f"tg:n1-{RUN}", cid)
    v1 = await sv(cid)
    iid = await q1("SELECT id FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid)
    smsg1 = await q1("SELECT count(*) FROM messages WHERE dedupe_key LIKE $1", f"order_summary:{iid}:%")
    _EX.clear()
    _EX.append(FULL())  # identical redelivery
    _S.clear()
    _S.append({"text": "ok"})
    await send(f"tg:n1-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234")
    v2 = await sv(cid)
    smsg2 = await q1("SELECT count(*) FROM messages WHERE dedupe_key LIKE $1", f"order_summary:{iid}:%")
    ck("234-02.1 identical proposal -> KHONG bump version", v1 == v2, f"v1={v1} v2={v2}")
    ck("234-02.1 identical proposal -> KHONG them summary row", smsg1 == smsg2 == 1, f"{smsg1}->{smsg2}")

    # ================= 234-02.2 explicit-clear reachable via extraction =================
    cid2 = await setup(f"tg:c2-{RUN}")
    await enroll_tg(cid2)
    _EX.clear()
    _EX.append({"sku": "SPV2F", "quantity": 1, "customer_name": "Nam", "phone": "0900001234"})
    _S.clear()
    _S.append({"text": "cần địa chỉ ạ"})
    await send(f"tg:c2-{RUN}", "đặt 1 hũ tên Nam 0900001234")
    ph_before = await q1("SELECT draft_phone FROM order_intents WHERE customer_id=$1 "
                         "ORDER BY created_at DESC LIMIT 1", cid2)
    _EX.clear()
    _EX.append({"clear": ["phone"]})  # khach: 'bo so dien thoai di'
    _S.clear()
    _S.append({"text": "dạ em đã bỏ SĐT, anh cho xin lại ạ"})
    await send(f"tg:c2-{RUN}", "bỏ số điện thoại đi")
    ph_after = await q1("SELECT draft_phone FROM order_intents WHERE customer_id=$1 "
                        "ORDER BY created_at DESC LIMIT 1", cid2)
    ck("234-02.2 explicit-clear qua extraction -> draft_phone NULL",
       ph_before == "0900001234" and ph_after is None, f"{ph_before}->{ph_after}")

    # ================= 234-02.3 regression READY -> COLLECTING khi correction lam thieu =================
    cid3 = await setup(f"tg:r3-{RUN}")
    await enroll_tg(cid3)
    await drive_ready_tg(f"tg:r3-{RUN}", cid3)
    ck("234-02.3 baseline READY", await st(cid3) == "READY_TO_COMMIT", await st(cid3))
    _EX.clear()
    _EX.append({"clear": ["phone"]})
    _S.clear()
    _S.append({"text": "cho xin lại SĐT ạ"})
    await send(f"tg:r3-{RUN}", "bỏ số điện thoại")
    ck("234-02.3 correction lam thieu -> REGRESSION ve COLLECTING (khong ket READY)",
       await st(cid3) == "COLLECTING" and await norders(cid3) == 0, await st(cid3))

    # ================= 234-02.4 revalidate ngay truoc commit (SKU bi xoa) =================
    cid4 = await setup(f"tg:v4-{RUN}", sku="SPTMP4")
    await enroll_tg(cid4)
    await drive_ready_tg(f"tg:v4-{RUN}", cid4, sku="SPTMP4")
    ck("234-02.4 baseline READY", await st(cid4) == "READY_TO_COMMIT")
    await ex("DELETE FROM products WHERE sku='SPTMP4'")  # SP bien mat sau khi present summary
    _S.clear()
    _S.append({"text": "..."})
    await send(f"tg:v4-{RUN}", "xác nhận")
    ck("234-02.4 SKU bi xoa -> revalidate chan commit (0 order)", await norders(cid4) == 0,
       await norders(cid4))
    await setup(f"tg:v4-{RUN}", sku="SPTMP4")  # restore product cho lan chay sau

    # ================= 234-02.5 committed-replay PARTIAL (khong reorder) =================
    cid5 = await setup(f"tg:p5-{RUN}")
    await enroll_tg(cid5)
    await drive_ready_tg(f"tg:p5-{RUN}", cid5)
    _S.clear()
    _S.append({"text": "..."})
    await send(f"tg:p5-{RUN}", "xác nhận")
    ck("234-02.5 baseline commit", await norders(cid5) == 1 and await st(cid5) == "COMMITTED")
    ni5 = await q1("SELECT count(*) FROM order_intents WHERE customer_id=$1", cid5)
    _EX.clear()
    _EX.append({"quantity": 2})  # PARTIAL, khong explicit reorder
    _S.clear()
    _S.append({"text": "..."})
    await send(f"tg:p5-{RUN}", "à cho 2 hũ")
    ck("234-02.5 partial stale sau COMMITTED (khong reorder) -> KHONG intent/order moi",
       await q1("SELECT count(*) FROM order_intents WHERE customer_id=$1", cid5) == ni5
       and await norders(cid5) == 1,
       f"intents={await q1('SELECT count(*) FROM order_intents WHERE customer_id=$1', cid5)}")

    # ================= 234-03 armed => persisted response exists =================
    orphan = await q1("SELECT count(*) FROM order_intents oi WHERE oi.state='READY_TO_COMMIT' "
                      "AND oi.summary_presented_at IS NOT NULL AND oi.summary_content_hash IS NOT NULL "
                      "AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.dedupe_key="
                      "'order_summary:'||oi.id||':'||oi.summary_version)")
    ck("234-03 MOI armed pending-confirm co persisted summary response (0 orphan)", orphan == 0, orphan)

    # ================= 234-04 one-delivery o channel boundary (telegram + messenger) =================
    from app.services.command.outbox_worker import SendResult
    for ch, psid in (("telegram_customer", f"tg:d-{RUN}"), ("messenger", f"msgr-{RUN}")):
        cidd = await setup(psid)
        if ch == "telegram_customer":
            await enroll_tg(cidd)
        else:
            settings.m1_reliable_order_command = True
            settings.enable_gate_e_order_wiring = True
            settings.enable_address_resolver = False  # M1 route khong yeu cau Gate E resolution binding
        _EX.clear()
        _EX.append(FULL())
        _S.clear()
        _S.append({"text": "ok"})
        await send(psid, "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234", ch=ch)
        _S.clear()
        _S.append({"text": "..."})
        await orchestrator.handle_message(psid, "xác nhận", channel=ch, provider_message_id=mid())
        oid = await q1("SELECT committed_order_id FROM order_intents WHERE customer_id=$1 "
                       "AND state='COMMITTED' ORDER BY updated_at DESC LIMIT 1", cidd)
        staff = await q1("SELECT count(*) FROM messages WHERE dedupe_key=$1", f"order_receipt:{oid}")
        obx = await q1("SELECT count(*) FROM outbox_events WHERE event_type='order.receipt.customer' "
                       "AND dedupe_key=$1", f"order_receipt:{oid}")
        ck(f"234-04[{ch}] 1 order + 1 staff-row + 1 outbox receipt",
           oid is not None and staff == 1 and obx == 1, f"oid={oid} staff={staff} obx={obx}")

        # deliver via outbox worker with mock transport -> exactly-once send for this order
        sends = {"n": 0}

        async def _mock_send(destination, payload, _o=oid):
            if payload.get("order_id") == _o and payload.get("text"):
                sends["n"] += 1
            return SendResult(ok=True, http_status=200, provider_message_id="pm1")

        await isolate_receipt(oid)
        for _ in range(6):
            await outbox_worker.run_once(send_fn=_mock_send)
        ck(f"234-04[{ch}] outbox delivery effectively-once (drains -> 1 send)", sends["n"] == 1, sends["n"])

        # replay confirmation -> 0 additional order/receipt/staff-row
        _S.clear()
        _S.append({"text": "..."})
        await orchestrator.handle_message(psid, "xác nhận", channel=ch, provider_message_id=mid())
        staff2 = await q1("SELECT count(*) FROM messages WHERE dedupe_key=$1", f"order_receipt:{oid}")
        obx2 = await q1("SELECT count(*) FROM outbox_events WHERE event_type='order.receipt.customer' "
                        "AND dedupe_key=$1", f"order_receipt:{oid}")
        ck(f"234-04[{ch}] replay confirm -> +0 order/receipt/staff-row",
           await norders(cidd) == 1 and staff2 == 1 and obx2 == 1, f"orders={await norders(cidd)}")

    # ================= 234-04 retry effectively-once + staff-log failure non-reversing =================
    cidr = await setup(f"tg:rt-{RUN}")
    await enroll_tg(cidr)
    await drive_ready_tg(f"tg:rt-{RUN}", cidr)
    _S.clear()
    _S.append({"text": "..."})
    await send(f"tg:rt-{RUN}", "xác nhận")
    oidr = await q1("SELECT committed_order_id FROM order_intents WHERE customer_id=$1 AND state='COMMITTED' "
                    "ORDER BY updated_at DESC LIMIT 1", cidr)
    calls = {"n": 0}

    async def _flaky(destination, payload, _o=oidr):
        if payload.get("order_id") == _o and payload.get("text"):
            calls["n"] += 1
            if calls["n"] == 1:
                return SendResult(ok=False, http_status=503, error_class="http_503")  # retryable
        return SendResult(ok=True, http_status=200, provider_message_id="pm")

    await isolate_receipt(oidr)
    await outbox_worker.run_once(send_fn=_flaky)  # attempt 1 fails -> retry_scheduled
    await ex("UPDATE outbox_events SET available_at=now() WHERE dedupe_key=$1", f"order_receipt:{oidr}")
    await outbox_worker.run_once(send_fn=_flaky)  # attempt 2 succeeds
    delivered = await q1("SELECT status FROM outbox_events WHERE dedupe_key=$1", f"order_receipt:{oidr}")
    ck("234-04 outbox retry -> delivered effectively-once", delivered == "delivered" and calls["n"] == 2,
       f"status={delivered} calls={calls['n']}")

    # staff-log failure at confirm -> order still committed (not reversed), outbox receipt intact
    cidf = await setup(f"tg:sf-{RUN}")
    await enroll_tg(cidf)
    await drive_ready_tg(f"tg:sf-{RUN}", cidf)
    _orig = oisvc.log_message_tx

    async def _boom(*a, **k):
        raise RuntimeError("staff-log failure injected")

    oisvc.log_message_tx = _boom
    try:
        _S.clear()
        _S.append({"text": "..."})
        await send(f"tg:sf-{RUN}", "xác nhận")
    finally:
        oisvc.log_message_tx = _orig
    oidf = await q1("SELECT committed_order_id FROM order_intents WHERE customer_id=$1 AND state='COMMITTED' "
                    "ORDER BY updated_at DESC LIMIT 1", cidf)
    obf = await q1("SELECT count(*) FROM outbox_events WHERE event_type='order.receipt.customer' "
                   "AND dedupe_key=$1", f"order_receipt:{oidf}")
    ck("234-04 staff-log failure -> order VAN committed + outbox receipt intact (khong reverse)",
       oidf is not None and await norders(cidf) == 1 and obf == 1, f"oid={oidf} obx={obf}")

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: ' + ', '.join(FAILS)}")
    await close_pool()
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
