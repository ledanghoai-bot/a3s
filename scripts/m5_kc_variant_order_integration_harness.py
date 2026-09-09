"""M5 matcher k/c variant — ORDER-TAKING integration harness (CA Directive 258 + Amend 259/260, DoD §9).

Path THAT qua handle_message + mock LLM, throwaway m5lab (migration 063 augment da apply). Chung minh:
  I1 variant-safe 'Krong Pak' -> auto_verified/bind -> READY -> confirm -> DUNG MOT committed order,
     snapshot immutable ward 24490, resolution rule orthographic_kc. KHONG bat khach go lai canonical.
  I2 reject/safe: wrong-province ('Bac Lieu' + 'Krong Pak') -> KHONG commit order (fail-safe).
KHONG PII/secret. Re-runnable (RUN).
"""
import asyncio
import json
import sys
import time
import types

from app.config import settings
from app.db_pool import acquire, close_pool, release
from app.services import orchestrator

RUN = str(int(time.time()))
FAILS = []


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


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


def mid():
    _C[0] += 1
    return f"tg:{RUN}{_C[0]}"


def base_flags():
    settings.m1_reliable_order_command = False
    settings.enable_gate_e_order_wiring = True
    settings.enable_address_resolver = True
    settings.enable_nlu_router = False
    settings.gate_e_canary_customer_ids = ""
    settings.address_resolver_pilot_customer_ids = ""
    settings.gate_e_kill_switch = False
    settings.gate_e_fullscope_telegram_customer = True
    settings.address_resolver_fullscope_telegram_customer = True
    settings.gate_e_fullscope_messenger = False
    settings.address_resolver_fullscope_messenger = False


async def q(s, *a):
    c = await acquire()
    try:
        return await c.fetchval(s, *a)
    finally:
        await release(c)


async def mkcust(psid):
    c = await acquire()
    try:
        cid = await c.fetchval("SELECT id FROM customers WHERE psid=$1", psid) or await c.fetchval(
            "INSERT INTO customers(psid,name,phone) VALUES($1,'Hoa','0900001234') RETURNING id", psid)
        conv = await c.fetchval("SELECT id FROM conversations WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1",
                                cid) or await c.fetchval(
            "INSERT INTO conversations(customer_id,bot_paused) VALUES($1,FALSE) RETURNING id", cid)
        return cid, conv
    finally:
        await release(c)


async def _order_then_confirm(psid, address, province, ward):
    """1 luot dat (create_order proposal + server-extract) roi 1 luot 'xac nhan'."""
    _S.clear(); _EX.clear()
    _S.append({"tools": [{"name": "create_order", "args": {
        "sku": "SPR2", "quantity": 1, "customer_name": "Hoa", "phone": "0900001234", "address": address}}]})
    _EX.append({"sku": "SPR2", "quantity": 1, "customer_name": "Hoa", "phone": "0900001234",
                "address": address, "province": province, "ward": ward})
    await orchestrator.handle_message(psid, "dat 1 hu giao " + address, channel="telegram_customer",
                                      provider_message_id=mid())
    _S.clear(); _EX.clear()
    _S.append({"text": "Dạ vâng"}); _EX.append({})
    await orchestrator.handle_message(psid, "xác nhận", channel="telegram_customer", provider_message_id=mid())


async def main():
    base_flags()
    c = await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPR2','Ca phe hu',500,90000) "
                        "ON CONFLICT(sku) DO UPDATE SET stock=500,price_vnd=90000")
        aug = await c.fetchval("SELECT count(*) FROM admin_unit_alias_augment WHERE source_batch='kc_variant_c2k_v1'")
    finally:
        await release(c)
    ck("augment present (migration 063 applied)", aug == 166, f"n={aug}")

    # ---- I1: variant-safe -> auto_verify -> commit exactly one, snapshot ward 24490 ----
    print("== I1 variant 'Krong Pak' -> one committed order ==")
    psid = f"tg:kcvar-i1-{RUN}"
    cid, conv = await mkcust(psid)
    await _order_then_confirm(psid, "12 Le Loi, Krong Pak, Dak Lak", "Đắk Lắk", "Krong Pak")
    n_intent = await q("SELECT count(*) FROM order_intents WHERE customer_id=$1 AND state='COMMITTED'", cid)
    n_order = await q("SELECT count(*) FROM orders WHERE customer_id=$1", cid)
    oid = await q("SELECT committed_order_id FROM order_intents WHERE customer_id=$1 AND state='COMMITTED'", cid)
    snap_ward = await q("SELECT ward_code FROM order_address_snapshot WHERE order_id=$1", oid) if oid else None
    res_rules = await q("SELECT rules_applied::text FROM address_resolution WHERE raw_ward=$1 "
                        "AND status='auto_verified' ORDER BY created_at DESC LIMIT 1", "Krong Pak")
    ck("I1: DUNG 1 committed intent", n_intent == 1, f"intents={n_intent}")
    ck("I1: DUNG 1 order (khong trung, khong go lai canonical)", n_order == 1, f"orders={n_order}")
    ck("I1: snapshot immutable bound ward 24490 (Krong Pac)", snap_ward == "24490", f"ward={snap_ward}")
    ck("I1: resolution auto_verified + rule orthographic_kc", res_rules and "orthographic_kc" in res_rules,
       str(res_rules))

    # ---- I2: reject-safe wrong province -> KHONG commit ----
    print("== I2 wrong-province -> no order (fail-safe) ==")
    psid2 = f"tg:kcvar-i2-{RUN}"
    cid2, conv2 = await mkcust(psid2)
    await _order_then_confirm(psid2, "9 Tran Phu, Krong Pak, Bac Lieu", "Bạc Liêu", "Krong Pak")
    n_order2 = await q("SELECT count(*) FROM orders WHERE customer_id=$1", cid2)
    ck("I2: wrong-province KHONG tao order (fail-safe)", n_order2 == 0, f"orders={n_order2}")

    await close_pool()
    print("\nRESULT:", "ALL PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
