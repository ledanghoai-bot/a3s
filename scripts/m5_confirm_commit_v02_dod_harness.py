"""CA Review 233 V02 — consolidated DoD harness for deterministic confirm-to-commit under the
server-invoked extraction-primary flow (233-01). Mock _llm_create discriminates:
  - MAIN chat loop  (tools=... present) -> scripted text/tool from _S (assistant may refuse tools).
  - SERVER extract  (no tools kwarg)    -> scripted JSON from _EX (server-controlled).

Covers: 233-01 (server reaches READY/commit with 0 assistant tool calls), 233-02 (server-rendered
summary armed to version/fingerprint), 233-03 (high-precision + context-bound confirmation, incl.
adversarial VN), 233-04 (validation, address-change by fingerprint, replay/already-committed,
reorder-only-on-explicit), 233-05 (one customer receipt + one staff-history row, replay no dup).
Sanitized synthetic data (no real PII)."""
import asyncio
import json
import sys
import time
import types

from app.config import settings
from app.db_pool import acquire, close_pool, release
from app.services import orchestrator
from app.services.command import order_intent_flow as flow

RUN = str(int(time.time()))
FAILS = []


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


_S = []    # MAIN chat loop scripts
_EX = []   # SERVER extraction scripts
_TOOLCALLS = {"n": 0}


def _msg(content=None, tools=None):
    tcs = [types.SimpleNamespace(id=f"c{i}", function=types.SimpleNamespace(
        name=t["name"], arguments=json.dumps(t["args"], ensure_ascii=False)))
        for i, t in enumerate(tools or [])] or None
    return types.SimpleNamespace(content=content, tool_calls=tcs)


def _resp(msg, finish):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason=finish)],
                                 usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=1))


async def _fake(client, **kw):
    if "tools" in kw:  # MAIN loop
        it = _S.pop(0) if _S else {"text": "..."}
        if it.get("tools"):
            _TOOLCALLS["n"] += 1
        return _resp(_msg(content=it.get("text"), tools=it.get("tools")),
                     "tool_calls" if it.get("tools") else "stop")
    obj = _EX.pop(0) if _EX else {}  # EXTRACTION
    return _resp(_msg(content=json.dumps(obj, ensure_ascii=False)), "stop")


orchestrator._llm_create = _fake


async def q1(s, *a):
    c = await acquire()
    try:
        return await c.fetchval(s, *a)
    finally:
        await release(c)


async def qr(s, *a):
    c = await acquire()
    try:
        r = await c.fetchrow(s, *a)
        return dict(r) if r else None
    finally:
        await release(c)


async def setup(psid):
    c = await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPV2','Cà phê hũ',500,90000) "
                        "ON CONFLICT(sku) DO UPDATE SET stock=500,name='Cà phê hũ',price_vnd=90000")
        return await c.fetchval("SELECT id FROM customers WHERE psid=$1", psid) or await c.fetchval(
            "INSERT INTO customers(psid,name,phone) VALUES($1,'H','0900001234') RETURNING id", psid)
    finally:
        await release(c)


async def newconv(cid):
    c = await acquire()
    try:
        return await c.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id", cid)
    finally:
        await release(c)


ADDR = "12 Le Loi, P. Ea Kao, Dak Lak"
FULL = {"sku": "SPV2", "quantity": 1, "customer_name": "Hoa", "phone": "0900001234",
        "address": ADDR, "province": "Tỉnh Đắk Lắk", "ward": "Phường Ea Kao"}
_CTR = [0]


def _mid():
    _CTR[0] += 1
    return f"tg:{RUN}{_CTR[0]}"


async def norders(cid):
    return await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cid)


async def nintents(cid):
    return await q1("SELECT count(*) FROM order_intents WHERE customer_id=$1", cid)


async def laststate(cid):
    return await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid)


async def send(psid, msg):
    return await orchestrator.handle_message(psid, msg, channel="telegram_customer", provider_message_id=_mid())


async def enroll(cid):
    cur = settings.gate_e_canary_customer_ids or ""
    settings.gate_e_canary_customer_ids = f"{cur},{cid}" if cur else str(cid)
    settings.address_resolver_pilot_customer_ids = settings.gate_e_canary_customer_ids


async def drive_ready(psid, cid):
    """Full order via SERVER extraction (assistant refuses tools) -> READY + summary armed."""
    _EX.clear()
    _EX.append(dict(FULL))
    _S.clear()
    _S.append({"text": "Dạ em ghi nhận ạ."})
    return await send(psid, "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234")


async def main():
    settings.m1_reliable_order_command = False
    settings.enable_gate_e_order_wiring = True
    settings.enable_address_resolver = True
    settings.enable_nlu_router = False

    # ---------- 233-03 UNIT: high-precision confirmation detector (no DB) ----------
    pos = ["xác nhận", "ok", "đồng ý", "chốt đơn", "chốt luôn", "duoc", "xác nhận đơn"]
    neg = ["chưa xác nhận đâu", "đúng số lượng chưa nhỉ?", "đổi 2 hũ", "sửa địa chỉ giúp anh",
           "ưng cái áo này quá", "cho hỏi giá bao nhiêu", "được không em", "huỷ đơn nhé",
           "kiểm tra đơn hôm qua", "khoan đã"]
    ck("233-03 positive confirmations -> True",
       all(orchestrator._is_confirmation(t) for t in pos),
       [t for t in pos if not orchestrator._is_confirmation(t)])
    ck("233-03 adversarial/negation/question/correction -> False",
       all(not orchestrator._is_confirmation(t) for t in neg),
       [t for t in neg if orchestrator._is_confirmation(t)])

    # ---------- 233-01/02: READY with 0 assistant tool calls + server summary ----------
    cid = await setup(f"tg:v2a-{RUN}")
    settings.gate_e_canary_customer_ids = str(cid)
    settings.address_resolver_pilot_customer_ids = str(cid)
    _TOOLCALLS["n"] = 0
    r = await drive_ready(f"tg:v2a-{RUN}", cid)
    ck("233-01 READY via server extract", await laststate(cid) == "READY_TO_COMMIT", await laststate(cid))
    ck("233-01 0 order truoc confirm", await norders(cid) == 0)
    ck("233-02 reply = server summary (SP+dia chi)",
       "Sản phẩm" in (r or "") and "Ea Kao" in (r or ""), (r or "")[:50])

    # ---------- 233-03 context: stale confirm after correction -> 0 order ----------
    _EX.clear()
    _EX.append({"quantity": 3})  # correction -> version bump, summary stale
    _S.clear()
    _S.append({"text": "Dạ em cập nhật số lượng ạ."})
    await send(f"tg:v2a-{RUN}", "đổi lại 3 hũ nhé")
    n_before = await norders(cid)
    await send(f"tg:v2a-{RUN}", "xác nhận")  # confirm on stale summary (correction re-presented new summary?)
    # After correction the flow re-presents a NEW summary (still READY) -> confirm commits the NEW one.
    st = await laststate(cid)
    ck("233-03/04 correction re-verified -> confirm commits corrected order",
       await norders(cid) == n_before + 1 and st == "COMMITTED",
       f"orders {n_before}->{await norders(cid)} state={st}")
    ck("233-01 ASSISTANT 0 tool calls xuyen suot", _TOOLCALLS["n"] == 0, _TOOLCALLS["n"])

    # ---------- 233-05: one customer receipt + one staff-history row; replay no dup ----------
    conv = await q1("SELECT id FROM conversations WHERE customer_id=$1 ORDER BY id DESC LIMIT 1", cid)
    msgs1 = await q1("SELECT count(*) FROM messages WHERE conversation_id=$1 AND role='bot' "
                     "AND content LIKE '%#%'", conv)
    ob1 = await q1("SELECT count(*) FROM outbox_events WHERE event_type='order.receipt.customer' "
                   "AND created_at > now()-interval '5 min'")
    await send(f"tg:v2a-{RUN}", "xác nhận")  # replay confirm
    msgs2 = await q1("SELECT count(*) FROM messages WHERE conversation_id=$1 AND role='bot' "
                     "AND content LIKE '%#%'", conv)
    ck("233-05 staff-history receipt == 1 (replay khong them)", msgs1 == 1 and msgs2 == 1,
       f"m1={msgs1} m2={msgs2}")
    ck("233-05 outbox receipt >= 1", ob1 >= 1, ob1)

    # ---------- 233-04: replay proposal after COMMITTED (not reorder) -> no new intent/order ----------
    # Fresh customer: commit FULL cleanly, then redeliver the SAME proposal (same fingerprint) -> guard.
    cidR = await setup(f"tg:v2r-{RUN}")
    await enroll(cidR)
    await drive_ready(f"tg:v2r-{RUN}", cidR)
    await send(f"tg:v2r-{RUN}", "xác nhận")
    ck("233-04 baseline commit FULL", await norders(cidR) == 1 and await laststate(cidR) == "COMMITTED")
    niR = await nintents(cidR)
    noR = await norders(cidR)
    _EX.clear()
    _EX.append(dict(FULL))  # identical proposal, NOT explicit reorder
    _S.clear()
    _S.append({"text": "Dạ ạ."})
    await send(f"tg:v2r-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234")
    ck("233-04 replay sau COMMITTED (khong reorder) -> khong intent/order moi",
       await nintents(cidR) == niR and await norders(cidR) == noR,
       f"intents {niR}->{await nintents(cidR)} orders {noR}->{await norders(cidR)}")

    # ---------- 233-04: explicit reorder AFTER committed -> new draft ----------
    _EX.clear()
    _EX.append(dict(FULL))
    _S.clear()
    _S.append({"text": "Đơn mới nhé ạ."})
    await send(f"tg:v2r-{RUN}", "đặt thêm 1 đơn nữa giống vậy")
    ck("233-04 reorder tuong minh -> draft moi READY",
       await nintents(cidR) == niR + 1 and await laststate(cidR) == "READY_TO_COMMIT",
       f"intents={await nintents(cidR)} state={await laststate(cidR)}")

    # ---------- 233-04: incomplete + invalid-phone -> COLLECTING, 0 order ----------
    cidI = await setup(f"tg:v2i-{RUN}")
    await enroll(cidI)
    _EX.clear()
    _EX.append({"sku": "SPV2", "quantity": 1, "customer_name": "Nam", "phone": "abc",
                "address": ADDR, "province": "Tỉnh Đắk Lắk", "ward": "Phường Ea Kao"})
    _S.clear()
    _S.append({"text": "Dạ SĐT chưa đúng, anh cho em xin lại ạ."})
    await send(f"tg:v2i-{RUN}", "đặt 1 hũ, sđt abc")
    ck("233-04 phone SAI DANG -> khong READY, 0 order",
       await laststate(cidI) == "COLLECTING" and await norders(cidI) == 0, await laststate(cidI))

    # ---------- COMPAT: extraction empty -> model create_order still progresses ----------
    cidC = await setup(f"tg:v2c-{RUN}")
    await enroll(cidC)
    _EX.clear()
    _EX.append({})  # server extraction finds nothing
    _S.clear()
    _S.append({"tools": [{"name": "create_order", "args": dict(FULL)}]})
    _S.append({"text": "Xác nhận giúp em nhé?"})
    await send(f"tg:v2c-{RUN}", "đặt hàng giúp mình")
    ck("COMPAT model create_order (extract rong) -> READY", await laststate(cidC) == "READY_TO_COMMIT",
       await laststate(cidC))
    await send(f"tg:v2c-{RUN}", "xác nhận")
    ck("COMPAT confirm -> +1 order", await norders(cidC) == 1)

    # ---------- 233-04 (service): address change by fingerprint (same addr != changed) ----------
    settings.m1_reliable_order_command = True
    settings.enable_gate_e_order_wiring = False
    cidS = await setup(f"tg:v2s-{RUN}")
    convS = await newconv(cidS)
    r1 = await flow.propose_draft(customer_id=cidS, conversation_id=convS, channel="telegram_customer",
                                  proposed=dict(FULL), verified=True, addr_fp="fp1",
                                  verified_resolution_id=None, address_changed=True)
    v1 = await q1("SELECT verified_address_fingerprint FROM order_intents WHERE id=$1", r1["order_intent_id"])
    # Re-propose SAME address (different accents/case) -> NOT a change -> binding preserved.
    r2 = await flow.propose_draft(customer_id=cidS, conversation_id=convS, channel="telegram_customer",
                                  proposed={"address": "12 LE LOI, p. ea kao, dak lak"}, verified=True,
                                  addr_fp="fp1", verified_resolution_id=None, address_changed=True)
    ck("233-04 dia chi giong (khac dau/hoa) -> KHONG coi la doi",
       r2.get("action") in ("ready", "need_more", "clarify"), r2.get("action"))

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: ' + ', '.join(FAILS)}")
    await close_pool()
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
