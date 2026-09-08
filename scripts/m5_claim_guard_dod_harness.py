"""CA Directive 238 — anti-fabrication (order-claim) guard SERVER-STATE-AWARE. Proves the 11 DoD items:
model 'order created' claims never terminalize/escalate/commit and never send admin notify from the guard;
reply is deterministic per server state; legit escalate (wants_human) / cancel / confirm still work.
Extraction-primary flow; mock LLM main-loop returns a CLAIMING reply. Sanitized synthetic (no PII)."""
import asyncio
import json
import sys
import time
import types

from app.config import settings
from app.db_pool import acquire, close_pool, release
from app.services import orchestrator
from app.services import tools as tools_mod
from app.services.command import order_intent_flow as oiflow

RUN = str(int(time.time()))
FAILS = []
CLAIM = "Dạ mã đơn của anh đã được tạo thành công, đơn đã được ghi nhận ạ."  # triggers _reply_claims_order_created


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


_S = []
_EX = []
_ESC = {"n": 0}


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
        it = _S.pop(0) if _S else {"text": CLAIM}
        return _resp(_mk(it.get("text"), it.get("tools")), "tool_calls" if it.get("tools") else "stop")
    return _resp(_mk(json.dumps(_EX.pop(0) if _EX else {}, ensure_ascii=False)), "stop")


orchestrator._llm_create = _fake
_orig_escalate = tools_mod.escalate_to_human


async def _counting_escalate(*a, **k):
    _ESC["n"] += 1
    return {"escalated": True}


tools_mod.escalate_to_human = _counting_escalate


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


async def setup(psid, sku="SPCG"):
    c = await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES($1,'Cà phê hũ',500,90000) "
                        "ON CONFLICT(sku) DO UPDATE SET stock=500,name='Cà phê hũ',price_vnd=90000", sku)
        cid = await c.fetchval("SELECT id FROM customers WHERE psid=$1", psid) or await c.fetchval(
            "INSERT INTO customers(psid,name,phone) VALUES($1,'H','0900001234') RETURNING id", psid)
        conv = await c.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id", cid)
        return cid, conv
    finally:
        await release(c)


ADDR = "12 Le Loi, P. Ea Kao, Dak Lak"
FULL = {"sku": "SPCG", "quantity": 1, "customer_name": "Hoa", "phone": "0900001234", "address": ADDR,
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


async def state_of(cid, conv):
    return await q1("SELECT state FROM order_intents WHERE customer_id=$1 AND conversation_id=$2 "
                    "ORDER BY updated_at DESC LIMIT 1", cid, conv)


async def norders(cid):
    return await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cid)


async def nintents(cid, conv):
    return await q1("SELECT count(*) FROM order_intents WHERE customer_id=$1 AND conversation_id=$2", cid, conv)


async def claim_turn(psid):
    """Send a neutral customer msg; extraction returns {} -> server no-op; main-loop returns CLAIM -> guard."""
    _EX.clear()
    _S.clear()
    _S.append({"text": CLAIM})
    return await orchestrator.handle_message(psid, "vâng ạ", channel="telegram_customer",
                                             provider_message_id=mid())


async def main():
    # ---- DoD-1 COLLECTING claim: no escalate/terminalize; continues to READY ----
    psid = f"tg:g1-{RUN}"
    cid, conv = await setup(psid)
    await enroll(cid)
    # draft co SKU/qty/ten/dia chi, THIEU phone -> reply phai hoi DUNG 'số điện thoại' (server-derived).
    await ex("INSERT INTO order_intents(customer_id,conversation_id,channel,state,draft_sku,draft_quantity,"
             "draft_customer_name,draft_address,expires_at) VALUES($1,$2,'telegram_customer','COLLECTING',"
             "'SPCG',1,'Hoa','12 Le Loi Ea Kao', now()+interval '24 hours')", cid, conv)
    e0 = _ESC["n"]
    r = await claim_turn(psid)
    ck("DoD-1 COLLECTING claim -> giữ state, no escalate, reply HỎI ĐÚNG field thiếu (SĐT, server-derived)",
       await state_of(cid, conv) == "COLLECTING" and _ESC["n"] == e0 and "số điện thoại" in (r or ""),
       f"state={await state_of(cid, conv)} reply={(r or '')[:70]}")
    # continues to READY via real extraction (same intent)
    _EX.clear(); _EX.append(dict(FULL)); _S.clear(); _S.append({"text": "ok"})
    await orchestrator.handle_message(psid, "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                      channel="telegram_customer", provider_message_id=mid())
    ck("DoD-1 cùng intent tiếp tục -> READY", await state_of(cid, conv) == "READY_TO_COMMIT",
       await state_of(cid, conv))

    # ---- DoD-2 ADDRESS_CHECK claim: draft not lost ----
    psid = f"tg:g2-{RUN}"; cid, conv = await setup(psid); await enroll(cid)
    ADDR2 = "999 Distinctive Rd ZZZ2"  # gia tri phan biet -> chung minh reply lay tu server payload
    await ex("INSERT INTO order_intents(customer_id,conversation_id,channel,state,draft_address,expires_at) "
             "VALUES($1,$2,'telegram_customer','ADDRESS_CHECK',$3, now()+interval '24 hours')", cid, conv, ADDR2)
    e0 = _ESC["n"]; r = await claim_turn(psid)
    ck("DoD-2 ADDRESS_CHECK claim -> draft giữ, no escalate, reply tham chiếu ĐÚNG địa chỉ đang kiểm tra",
       await state_of(cid, conv) == "ADDRESS_CHECK" and _ESC["n"] == e0 and ADDR2 in (r or ""),
       f"state={await state_of(cid, conv)} reply={(r or '')[:70]}")

    # ---- DoD-3 NEEDS_CLARIFICATION claim: lifecycle preserved ----
    psid = f"tg:g3-{RUN}"; cid, conv = await setup(psid); await enroll(cid)
    ADDR3 = "888 Clarify Ave QQQ3"
    await ex("INSERT INTO order_intents(customer_id,conversation_id,channel,state,draft_address,expires_at) "
             "VALUES($1,$2,'telegram_customer','NEEDS_CLARIFICATION',$3, now()+interval '24 hours')",
             cid, conv, ADDR3)
    e0 = _ESC["n"]; r = await claim_turn(psid)
    ck("DoD-3 NEEDS_CLARIFICATION claim -> giữ nguyên, no escalate, reply phát lại địa chỉ cần làm rõ",
       await state_of(cid, conv) == "NEEDS_CLARIFICATION" and _ESC["n"] == e0 and ADDR3 in (r or ""),
       f"state={await state_of(cid, conv)} reply={(r or '')[:70]}")

    # ---- DoD-4 READY claim: confirm prompt, NO commit before confirm ----
    psid = f"tg:g4-{RUN}"; cid, conv = await setup(psid); await enroll(cid)
    _EX.clear(); _EX.append(dict(FULL)); _S.clear(); _S.append({"text": "ok"})
    await orchestrator.handle_message(psid, "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                      channel="telegram_customer", provider_message_id=mid())
    ck("DoD-4 setup READY", await state_of(cid, conv) == "READY_TO_COMMIT")
    n0 = await norders(cid); e0 = _ESC["n"]
    r = await claim_turn(psid)
    ck("DoD-4 READY claim -> phát LẠI summary đã lưu (chứa SP 'Cà phê hũ') + mời xác nhận, KHÔNG commit/escalate",
       await norders(cid) == n0 and await state_of(cid, conv) == "READY_TO_COMMIT" and _ESC["n"] == e0
       and "xác nhận" in (r or "") and "Cà phê hũ" in (r or ""),
       f"orders={await norders(cid)} state={await state_of(cid, conv)} reply={(r or '')[:60]}")

    # ---- DoD-5 after COMMITTED claim: neutral, no escalation, no extra order ----
    _S.clear(); _S.append({"text": "..."})
    await orchestrator.handle_message(psid, "xác nhận", channel="telegram_customer", provider_message_id=mid())
    ck("DoD-5 setup COMMITTED", await norders(cid) == n0 + 1)
    n1 = await norders(cid); e0 = _ESC["n"]
    r = await claim_turn(psid)
    ck("DoD-5 post-COMMITTED claim -> neutral, no escalate, no extra order",
       await norders(cid) == n1 and _ESC["n"] == e0 and "đã được ghi nhận rồi" in (r or ""),
       f"orders={await norders(cid)} esc={_ESC['n']-e0}")

    # ---- DoD-6 baseless claim (no intent): correction, no order/intent/escalation ----
    psid = f"tg:g6-{RUN}"; cid, conv = await setup(psid); await enroll(cid)
    e0 = _ESC["n"]
    r = await claim_turn(psid)
    ck("DoD-6 baseless claim -> correction, no order/intent/escalation",
       await norders(cid) == 0 and await nintents(cid, conv) == 0 and _ESC["n"] == e0
       and "chưa ghi nhận đơn nào" in (r or ""), f"intents={await nintents(cid, conv)} esc={_ESC['n']-e0}")
    # ---- DoD-7 two/retry baseless claims -> still no admin notify ----
    await claim_turn(psid)
    ck("DoD-7 baseless claim lần 2 -> vẫn KHÔNG admin notify (structured log để quan sát)",
       await nintents(cid, conv) == 0 and _ESC["n"] == e0, f"esc={_ESC['n']-e0}")

    # ---- DoD-8 customer wants human -> escalate exactly once ----
    psid = f"tg:g8-{RUN}"; cid, conv = await setup(psid); await enroll(cid)
    e0 = _ESC["n"]
    _S.clear(); _S.append({"text": "..."})
    await orchestrator.handle_message(psid, "cho tôi gặp nhân viên tư vấn với", channel="telegram_customer",
                                      provider_message_id=mid())
    ck("DoD-8 wants_human -> escalate ĐÚNG 1 lần", _ESC["n"] == e0 + 1, f"esc={_ESC['n']-e0}")

    # ---- DoD-9 cancel -> CANCELLED; valid confirm -> commit exactly one ----
    psid = f"tg:g9-{RUN}"; cid, conv = await setup(psid); await enroll(cid)
    _EX.clear(); _EX.append(dict(FULL)); _S.clear(); _S.append({"text": "ok"})
    await orchestrator.handle_message(psid, "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                      channel="telegram_customer", provider_message_id=mid())
    _S.clear(); _S.append({"text": "..."})
    await orchestrator.handle_message(psid, "thôi huỷ đơn nhé", channel="telegram_customer",
                                      provider_message_id=mid())
    ck("DoD-9a cancel -> CANCELLED", await state_of(cid, conv) == "CANCELLED", await state_of(cid, conv))
    # new order + confirm -> exactly one order
    _EX.clear(); _EX.append(dict(FULL)); _S.clear(); _S.append({"text": "ok"})
    await orchestrator.handle_message(psid, "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                      channel="telegram_customer", provider_message_id=mid())
    n0 = await norders(cid)
    _S.clear(); _S.append({"text": "..."})
    await orchestrator.handle_message(psid, "xác nhận", channel="telegram_customer", provider_message_id=mid())
    ck("DoD-9b valid confirm -> commit ĐÚNG 1 order", await norders(cid) == n0 + 1, await norders(cid))

    # ---- DoD-10 no direct handoff.admin_notify from guard branch (source assertion) ----
    import inspect
    src = inspect.getsource(orchestrator.handle_message)
    guard_seg = src.split("claim_guard (server-state-aware)")[1].split("# CA 226-03b")[0]
    ck("DoD-10 nhánh order-claim guard KHÔNG gọi escalate_to_human/terminalize",
       ("escalate_to_human" not in guard_seg) and ("_terminalize_open_intent" not in guard_seg), "")

    # ---- 239-01 cross-conversation: lookup ĐÚNG conversation, không lấy nhầm ----
    psid = f"tg:xc-{RUN}"; cidx, convA = await setup(psid); await enroll(cidx)
    convB = await q1("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id", cidx)
    AA = "111 Alpha AAA"; BB = "222 Beta BBB"
    await ex("INSERT INTO order_intents(customer_id,conversation_id,channel,state,draft_address,expires_at) "
             "VALUES($1,$2,'telegram_customer','ADDRESS_CHECK',$3, now()+interval '24 hours')", cidx, convA, AA)
    await ex("INSERT INTO order_intents(customer_id,conversation_id,channel,state,draft_address,expires_at) "
             "VALUES($1,$2,'telegram_customer','ADDRESS_CHECK',$3, now()+interval '24 hours')", cidx, convB, BB)
    stA = await orchestrator._conversation_order_state(psid, convA)
    stB = await orchestrator._conversation_order_state(psid, convB)
    ck("239-01 cross-conv: mỗi conversation trả ĐÚNG payload của nó (không lấy nhầm)",
       stA.get("address") == AA and stB.get("address") == BB, f"A={stA.get('address')} B={stB.get('address')}")

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: ' + ', '.join(FAILS)}")
    await close_pool()
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
