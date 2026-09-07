"""CA Review 235 — targeted corrections harness (235-01 expiry+mandatory binding, 235-02 provider-event
replay + explicit-new-order, 235-03 staff-receipt retry). Extraction-primary flow, sanitized synthetic."""
import asyncio
import json
import sys
import time
import types

from app.config import settings
from app.db_pool import acquire, close_pool, release
from app.services import orchestrator
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


async def setup(psid, sku="SPV2G"):
    c = await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES($1,'Cà phê hũ',500,90000) "
                        "ON CONFLICT(sku) DO UPDATE SET stock=500,name='Cà phê hũ',price_vnd=90000", sku)
        return await c.fetchval("SELECT id FROM customers WHERE psid=$1", psid) or await c.fetchval(
            "INSERT INTO customers(psid,name,phone) VALUES($1,'H','0900001234') RETURNING id", psid)
    finally:
        await release(c)


ADDR = "12 Le Loi, P. Ea Kao, Dak Lak"


def FULL(sku="SPV2G", qty=1):
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


async def send(psid, msg, pmid=None, ch="telegram_customer"):
    return await orchestrator.handle_message(psid, msg, channel=ch, provider_message_id=pmid or mid())


async def drive_ready(psid, cid, sku="SPV2G"):
    _EX.clear()
    _EX.append(FULL(sku))
    _S.clear()
    _S.append({"text": "ok"})
    return await send(psid, "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234")


async def st(cid):
    return await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid)


async def norders(cid):
    return await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cid)


async def nintents(cid):
    return await q1("SELECT count(*) FROM order_intents WHERE customer_id=$1", cid)


async def confirm(psid):
    _S.clear()
    _S.append({"text": "..."})
    return await send(psid, "xác nhận")


async def main():
    # ===== 235-01a EXPIRED READY -> 0 order =====
    cid = await setup(f"tg:e1-{RUN}")
    await enroll(cid)
    await drive_ready(f"tg:e1-{RUN}", cid)
    await ex("UPDATE order_intents SET expires_at=now()-interval '1 hour' WHERE customer_id=$1 "
             "AND state='READY_TO_COMMIT'", cid)
    await confirm(f"tg:e1-{RUN}")
    ck("235-01a expired READY -> 0 order + EXPIRED", await norders(cid) == 0 and await st(cid) == "EXPIRED",
       await st(cid))

    # ===== 235-01b NULL content_hash -> 0 order =====
    cid = await setup(f"tg:e2-{RUN}")
    await enroll(cid)
    await drive_ready(f"tg:e2-{RUN}", cid)
    await ex("UPDATE order_intents SET summary_content_hash=NULL WHERE customer_id=$1 "
             "AND state='READY_TO_COMMIT'", cid)
    await confirm(f"tg:e2-{RUN}")
    ck("235-01b NULL content_hash -> 0 order (fail-closed)", await norders(cid) == 0, await norders(cid))

    # ===== 235-01c missing persisted summary row -> 0 order =====
    cid = await setup(f"tg:e3-{RUN}")
    await enroll(cid)
    await drive_ready(f"tg:e3-{RUN}", cid)
    iid = await q1("SELECT id FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid)
    await ex("DELETE FROM messages WHERE dedupe_key LIKE $1", f"order_summary:{iid}:%")
    await confirm(f"tg:e3-{RUN}")
    ck("235-01c missing summary response row -> 0 order (fail-closed)", await norders(cid) == 0,
       await norders(cid))

    # ===== 235-02a provider-event REPLAY -> no 2nd mutation =====
    cid = await setup(f"tg:r2-{RUN}")
    await enroll(cid)
    FIX = f"tg:{RUN}FIXA"
    _EX.clear()
    _EX.append(FULL())
    _S.clear()
    _S.append({"text": "ok"})
    await send(f"tg:r2-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234", pmid=FIX)
    v1 = await q1("SELECT state_version FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid)
    ni1 = await nintents(cid)
    sm1 = await q1("SELECT count(*) FROM messages WHERE dedupe_key LIKE $1", f"order_summary:{iid}:%") if iid else 0
    # replay SAME event id -> claim fails -> no extraction/mutation
    _EX.clear()
    _EX.append(FULL(qty=9))  # would-be different, but MUST NOT be applied (replay)
    _S.clear()
    _S.append({"text": "ok"})
    await send(f"tg:r2-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234", pmid=FIX)
    v2 = await q1("SELECT state_version FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid)
    ck("235-02a provider replay -> KHONG bump version / KHONG intent moi",
       v1 == v2 and await nintents(cid) == ni1, f"v {v1}->{v2} intents {ni1}->{await nintents(cid)}")
    q = await q1("SELECT draft_quantity FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid)
    ck("235-02a replay -> draft KHONG bi mutate (qty van 1, khong phai 9)", q == 1, q)

    # ===== 235-02b explicit new order WITHOUT 'thêm' after COMMITTED -> new intent =====
    cid = await setup(f"tg:n2-{RUN}")
    await enroll(cid)
    await drive_ready(f"tg:n2-{RUN}", cid)
    await confirm(f"tg:n2-{RUN}")
    ck("235-02b baseline commit", await norders(cid) == 1 and await st(cid) == "COMMITTED")
    ni = await nintents(cid)
    _EX.clear()
    _EX.append(FULL(qty=2))  # clear order + product, KHONG 'them'
    _S.clear()
    _S.append({"text": "ok"})
    await send(f"tg:n2-{RUN}", "đặt 2 hũ cà phê giao Ea Kao Hoa 0900001234")  # order marker 'dat 2'
    ck("235-02b direct new order (khong 'them') -> intent MOI",
       await nintents(cid) == ni + 1 and await st(cid) == "READY_TO_COMMIT",
       f"intents {ni}->{await nintents(cid)} state={await st(cid)}")

    # ===== 235-02c partial stale after COMMITTED ENTERS path + rejected (no-op) =====
    cid = await setup(f"tg:p2-{RUN}")
    await enroll(cid)
    await drive_ready(f"tg:p2-{RUN}", cid)
    await confirm(f"tg:p2-{RUN}")
    ni = await nintents(cid)
    no = await norders(cid)
    _EX.clear()
    _EX.append({"quantity": 5})  # PARTIAL (no sku) — order marker 'dat' co mat -> relevant, ENTERS path
    _S.clear()
    _S.append({"text": "..."})
    await send(f"tg:p2-{RUN}", "đặt hàng số lượng 5")  # 'dat hang' = order marker -> relevant
    ck("235-02c partial stale sau COMMITTED (ENTERS path) -> no-op, khong intent/order moi",
       await nintents(cid) == ni and await norders(cid) == no,
       f"intents {ni}->{await nintents(cid)}")

    # ===== 235-02d missing provider id on enrolled -> fail-closed (no intent) =====
    cid = await setup(f"tg:f2-{RUN}")
    await enroll(cid)
    _EX.clear()
    _EX.append(FULL())
    _S.clear()
    _S.append({"text": "..."})
    await orchestrator.handle_message(f"tg:f2-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                      channel="telegram_customer", provider_message_id=None)
    ck("235-02d thieu provider_message_id -> fail-closed (0 intent, khong dung sender_id lam event id)",
       await nintents(cid) == 0, await nintents(cid))

    # ===== 235-03 staff-receipt retry: failure -> reconcile creates exactly one, repeat zero =====
    cid = await setup(f"tg:s3-{RUN}")
    await enroll(cid)
    await drive_ready(f"tg:s3-{RUN}", cid)
    _orig = oisvc.log_message_tx

    async def _boom(conn, conversation_id, role, content, dedupe_key=None):
        if dedupe_key and dedupe_key.startswith("order_receipt:"):
            raise RuntimeError("staff-log failure injected")
        return await _orig(conn, conversation_id, role, content, dedupe_key=dedupe_key)

    oisvc.log_message_tx = _boom
    try:
        await confirm(f"tg:s3-{RUN}")
    finally:
        oisvc.log_message_tx = _orig
    oid = await q1("SELECT committed_order_id FROM order_intents WHERE customer_id=$1 AND state='COMMITTED' "
                   "ORDER BY updated_at DESC LIMIT 1", cid)
    staff0 = await q1("SELECT count(*) FROM messages WHERE dedupe_key=$1", f"order_receipt:{oid}")
    ck("235-03 staff-log failure -> order committed + staff row THIEU (chua co)",
       oid is not None and await norders(cid) == 1 and staff0 == 0, f"oid={oid} staff0={staff0}")
    n1 = await staff_receipt_reconcile.reconcile_staff_receipts()
    staff1 = await q1("SELECT count(*) FROM messages WHERE dedupe_key=$1", f"order_receipt:{oid}")
    n2 = await staff_receipt_reconcile.reconcile_staff_receipts()
    staff2 = await q1("SELECT count(*) FROM messages WHERE dedupe_key=$1", f"order_receipt:{oid}")
    ck("235-03 reconcile -> tao ĐÚNG 1 staff row; chay lai -> +0", staff1 == 1 and staff2 == 1,
       f"staff {staff0}->{staff1}->{staff2} (reconciled n1>={1 if n1 else 0})")

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: ' + ', '.join(FAILS)}")
    await close_pool()
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
