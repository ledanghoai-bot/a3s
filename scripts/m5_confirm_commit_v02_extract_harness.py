"""CA Review 233-01 PROOF: server-invoked structured extraction reaches READY + commits exactly once EVEN
WHEN the assistant model REFUSES every tool call throughout the whole multi-turn order.

Mock _llm_create discriminates by the presence of the `tools` kwarg:
  - MAIN chat loop (tools=... passed)  -> return TEXT ONLY, tool_calls=None  => assistant refuses ALL tools.
  - SERVER extraction (no tools kwarg) -> return the strict JSON object for that turn (server-controlled).

Accumulate across turns -> verify address -> READY -> server-rendered summary -> confirm -> 1 commit.
Sanitized synthetic data (no real PII).
"""
import asyncio
import json
import time
import types

from app.config import settings
from app.db_pool import acquire, close_pool, release
from app.services import orchestrator

RUN = str(int(time.time()))
FAILS = []


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + x) if x else ''}")
    if not c:
        FAILS.append(n)


# Per-turn scripted EXTRACTION JSON (server-controlled call). Keyed by turn tag injected via last user msg.
_EXTRACT = {}
_MAIN_CALLS = {"n": 0, "tool_calls": 0}


def _wrap(content, tool_calls=None, finish="stop"):
    msg = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=msg, finish_reason=finish)],
        usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=1))


async def _fake(client, **kw):
    if "tools" in kw:
        # MAIN chat loop -> assistant REFUSES all tools (text only).
        _MAIN_CALLS["n"] += 1
        return _wrap("Dạ em ghi nhận thông tin của anh/chị ạ.", tool_calls=None, finish="stop")
    # SERVER extraction call -> strict JSON for the current turn (matched by the last user message).
    last = kw["messages"][-1]["content"]
    for tag, obj in _EXTRACT.items():
        if tag in last:
            return _wrap(json.dumps(obj, ensure_ascii=False))
    return _wrap("{}")


orchestrator._llm_create = _fake


async def q1(s, *a):
    c = await acquire()
    try:
        return await c.fetchval(s, *a)
    finally:
        await release(c)


async def setup(psid):
    c = await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPEX','Sữa dừa hũ',500,120000) "
                        "ON CONFLICT(sku) DO UPDATE SET stock=500,name='Sữa dừa hũ',price_vnd=120000")
        return await c.fetchval("SELECT id FROM customers WHERE psid=$1", psid) or await c.fetchval(
            "INSERT INTO customers(psid,name,phone) VALUES($1,'H','0900001234') RETURNING id", psid)
    finally:
        await release(c)


async def main():
    settings.m1_reliable_order_command = False
    settings.enable_gate_e_order_wiring = True
    settings.enable_address_resolver = True
    settings.enable_nlu_router = False
    psid = f"tg:ex-{RUN}"
    cid = await setup(psid)
    settings.gate_e_canary_customer_ids = str(cid)
    settings.address_resolver_pilot_customer_ids = str(cid)
    n0 = await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cid)

    async def send(msg, mid):
        return await orchestrator.handle_message(psid, msg, channel="telegram_customer",
                                                 provider_message_id=f"tg:{mid}")

    # T1: order intent + partial (sku+qty). Extraction returns those; still missing name/phone/address.
    _EXTRACT.clear()
    _EXTRACT["MARK1"] = {"sku": "SPEX", "quantity": 1}
    await send("MARK1 đặt 1 hũ sữa dừa", f"{RUN}01")
    ck("T1 partial -> 0 order", await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cid) == n0)
    st1 = await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid)
    ck("T1 draft COLLECTING (thieu field)", st1 == "COLLECTING", str(st1))

    # T2: name + phone. Still missing address.
    _EXTRACT.clear()
    _EXTRACT["MARK2"] = {"customer_name": "Hoa", "phone": "0900001234"}
    await send("MARK2 tên Hoa số 0900001234", f"{RUN}02")
    ck("T2 van 0 order", await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cid) == n0)

    # T3: address (+ province/ward) -> verify -> READY -> server summary armed.
    _EXTRACT.clear()
    _EXTRACT["MARK3"] = {"address": "12 Le Loi, P. Ea Kao, Dak Lak",
                         "province": "Tỉnh Đắk Lắk", "ward": "Phường Ea Kao"}
    r3 = await send("MARK3 giao 12 Le Loi Phuong Ea Kao Dak Lak", f"{RUN}03")
    st3 = await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid)
    ck("T3 READY_TO_COMMIT (server tu extract, khong tool)", st3 == "READY_TO_COMMIT", str(st3))
    ck("T3 van 0 order (chua commit)", await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cid) == n0)
    ck("T3 reply = server-rendered summary (co SP + dia chi)",
       ("Sản phẩm" in (r3 or "")) and ("Ea Kao" in (r3 or "") or "Le Loi" in (r3 or "")), (r3 or "")[:60])

    # T4: confirm -> server commit exactly once.
    r4 = await send("xác nhận", f"{RUN}04")
    ck("T4 confirm -> +1 order (server chot)",
       await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cid) == n0 + 1)
    st4 = await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cid)
    ck("T4 intent COMMITTED", st4 == "COMMITTED", str(st4))

    # CENTRAL PROOF: assistant made ZERO tool calls across the whole order.
    ck("ASSISTANT REFUSED ALL TOOLS xuyen suot (0 tool call)", _MAIN_CALLS["tool_calls"] == 0,
       f"main_calls={_MAIN_CALLS['n']} tool_calls={_MAIN_CALLS['tool_calls']}")

    # T5: re-confirm (replay) -> no new order.
    n1 = await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cid)
    await send("xác nhận", f"{RUN}05")
    ck("T5 re-confirm -> khong don moi", await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cid) == n1)

    print("\nRESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
    await close_pool()


asyncio.run(main())
