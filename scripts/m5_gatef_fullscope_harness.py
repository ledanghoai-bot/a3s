"""CA Directive 243 (Gate F) — full-scope per-channel activation harness. Proves AC 1-9 + 12 with an
identity OUTSIDE the allowlist, plus config matrix (OFF/allowlist/TG-full/MSGR-full/both/kill).
Extraction-primary mock; sanitized synthetic (no PII/secrets)."""
import asyncio
import json
import sys
import time
import types

from app.config import Settings, settings
from app.db_pool import acquire, close_pool, release
from app.services import m5_scope, tools
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

# CA 244-01: dem escalate/admin-notify de assert AC-5/AC-7 KHONG escalate som.
_ESC = {"n": 0}
_orig_escalate = tools.escalate_to_human


async def _counting_escalate(*a, **k):
    _ESC["n"] += 1
    return {"escalated": True}


tools.escalate_to_human = _counting_escalate


async def q1(s, *a):
    c = await acquire()
    try:
        return await c.fetchval(s, *a)
    finally:
        await release(c)


async def mkcust(psid):
    c = await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPGF','Cà phê hũ',500,90000) "
                        "ON CONFLICT(sku) DO UPDATE SET stock=500,name='Cà phê hũ',price_vnd=90000")
        return await c.fetchval("SELECT id FROM customers WHERE psid=$1", psid) or await c.fetchval(
            "INSERT INTO customers(psid,name,phone) VALUES($1,'H','0900001234') RETURNING id", psid)
    finally:
        await release(c)


ADDR = "12 Le Loi, P. Ea Kao, Dak Lak"
def FULL(qty=1):
    return {"sku": "SPGF", "quantity": qty, "customer_name": "Hoa", "phone": "0900001234", "address": ADDR,
            "province": "Tỉnh Đắk Lắk", "ward": "Phường Ea Kao"}
_C = [0]
def mid(pfx="tg"):
    _C[0] += 1
    return f"{pfx}:{RUN}{_C[0]}"


def base_flags():
    settings.m1_reliable_order_command = False
    settings.enable_gate_e_order_wiring = True
    settings.enable_address_resolver = True
    settings.enable_nlu_router = False
    settings.gate_e_canary_customer_ids = ""       # EMPTY allowlist -> chỉ full-scope mới enroll
    settings.address_resolver_pilot_customer_ids = ""
    settings.gate_e_kill_switch = False
    settings.gate_e_fullscope_telegram_customer = False
    settings.gate_e_fullscope_messenger = False
    settings.address_resolver_fullscope_telegram_customer = False
    settings.address_resolver_fullscope_messenger = False


async def route(psid, ch):
    return await tools._gate_e_pilot_route(psid, {"channel": ch})


async def main():
    # ================= AC-12: fail-closed default + parse-error =================
    s_fresh = Settings(_env_file=None)
    ck("AC-12 fresh config -> full-scope OFF (fail-closed)",
       not s_fresh.gate_e_fullscope_telegram_customer and not s_fresh.gate_e_fullscope_messenger
       and not s_fresh.address_resolver_fullscope_telegram_customer, "")
    s_bad = Settings(_env_file=None, gate_e_fullscope_telegram_customer="garbage",
                     gate_e_fullscope_messenger="maybe")
    ck("AC-12 parse-error/invalid token -> OFF (không crash, không bật scope)",
       s_bad.gate_e_fullscope_telegram_customer is False and s_bad.gate_e_fullscope_messenger is False, "")

    # ================= Config matrix + AC-8 (independent) + AC-9 (kill priority) =================
    cidT = await mkcust(f"tg:gf-{RUN}")      # KHÔNG trong allowlist
    cidM = await mkcust(f"msgr-gf-{RUN}")
    base_flags()
    # OFF (wiring off)
    settings.enable_gate_e_order_wiring = False
    ck("matrix OFF -> route False cả 2 kênh",
       (await route(f"tg:gf-{RUN}", "telegram_customer")) is False
       and (await route(f"msgr-gf-{RUN}", "messenger")) is False)
    # allowlist mode (wiring on, canary=[cidT], no fullscope)
    base_flags(); settings.gate_e_canary_customer_ids = str(cidT)
    ck("matrix allowlist -> chỉ customer trong list; ngoài list False",
       (await route(f"tg:gf-{RUN}", "telegram_customer")) is True
       and (await route(f"msgr-gf-{RUN}", "messenger")) is False)
    # Telegram-only full (AC-8: messenger KHÔNG bị enroll lây)
    base_flags(); settings.gate_e_fullscope_telegram_customer = True
    ck("matrix TG-only full -> TG(out-of-list)=True, MSGR=False (độc lập, không lây)",
       (await route(f"tg:gf-{RUN}", "telegram_customer")) is True
       and (await route(f"msgr-gf-{RUN}", "messenger")) is False)
    # Messenger-only full
    base_flags(); settings.gate_e_fullscope_messenger = True
    ck("matrix MSGR-only full -> MSGR=True, TG=False (độc lập)",
       (await route(f"msgr-gf-{RUN}", "messenger")) is True
       and (await route(f"tg:gf-{RUN}", "telegram_customer")) is False)
    # both full
    base_flags(); settings.gate_e_fullscope_telegram_customer = True; settings.gate_e_fullscope_messenger = True
    ck("matrix both full -> cả 2 True",
       (await route(f"tg:gf-{RUN}", "telegram_customer")) is True
       and (await route(f"msgr-gf-{RUN}", "messenger")) is True)
    # kill ON (priority) — dù both full + allowlist
    settings.gate_e_kill_switch = True; settings.gate_e_canary_customer_ids = str(cidT)
    ck("AC-9 kill ON -> route False cả full-scope lẫn allowlist (ưu tiên cao nhất)",
       (await route(f"tg:gf-{RUN}", "telegram_customer")) is False
       and (await route(f"msgr-gf-{RUN}", "messenger")) is False)

    # ================= AC-1 Telegram full-scope: identity NGOÀI allowlist -> full lifecycle -> commit =================
    base_flags()
    settings.gate_e_fullscope_telegram_customer = True
    settings.address_resolver_fullscope_telegram_customer = True
    psid = f"tg:gf-{RUN}"
    n0 = await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cidT)
    _EX.clear(); _EX.append(FULL()); _S.clear(); _S.append({"text": "ok"})
    r = await orchestrator.handle_message(psid, "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                          channel="telegram_customer", provider_message_id=mid())
    ck("AC-1 TG full-scope: out-of-allowlist -> READY + server summary",
       (await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cidT))
       == "READY_TO_COMMIT" and "Sản phẩm" in (r or ""), (r or "")[:40])
    ck("AC-6 chưa commit trước confirm", await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cidT) == n0)
    _S.clear(); _S.append({"text": "..."})
    await orchestrator.handle_message(psid, "xác nhận", channel="telegram_customer", provider_message_id=mid())
    ck("AC-1 confirm -> commit (out-of-allowlist identity chốt được đơn)",
       await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cidT) == n0 + 1)

    # ================= AC-2 Messenger full-scope: external identity -> lifecycle + dedupe =================
    base_flags()
    settings.gate_e_fullscope_messenger = True
    settings.address_resolver_fullscope_messenger = True
    mp = f"msgr-gf-{RUN}"
    nm0 = await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cidM)
    MMID = f"mid.{RUN}.gf1"
    _EX.clear(); _EX.append(FULL()); _S.clear(); _S.append({"text": "ok"})
    await orchestrator.handle_message(mp, "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                      channel="messenger", provider_message_id=MMID)
    st_m = await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cidM)
    ck("AC-2 MSGR full-scope: external identity -> READY", st_m == "READY_TO_COMMIT", st_m)
    # dedupe: replay SAME mid -> no 2nd extraction/mutation (inbound-event effective-once)
    v_before = await q1("SELECT state_version FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cidM)
    _EX.clear(); _EX.append(FULL(qty=9)); _S.clear(); _S.append({"text": "ok"})
    await orchestrator.handle_message(mp, "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                      channel="messenger", provider_message_id=MMID)
    ck("AC-4 MSGR provider-event replay -> KHÔNG mutate (dedupe bắt buộc)",
       await q1("SELECT state_version FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cidM) == v_before)
    _S.clear(); _S.append({"text": "..."})
    await orchestrator.handle_message(mp, "xác nhận", channel="messenger", provider_message_id=mid("mid."))
    ck("AC-2 MSGR confirm -> commit ĐÚNG 1", await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cidM) == nm0 + 1)

    # ================= AC-3 invalid input dưới full-scope -> KHÔNG order =================
    base_flags(); settings.gate_e_fullscope_telegram_customer = True
    settings.address_resolver_fullscope_telegram_customer = True
    cidI = await mkcust(f"tg:gfi-{RUN}"); await route(f"tg:gfi-{RUN}", "telegram_customer")
    _EX.clear(); _EX.append({"sku": "SPGF", "quantity": 1, "phone": "abc"}); _S.clear(); _S.append({"text": "SĐT chưa đúng ạ"})
    await orchestrator.handle_message(f"tg:gfi-{RUN}", "đặt 1 hũ sđt abc", channel="telegram_customer", provider_message_id=mid())
    ck("AC-3 full-scope nhưng input sai (SĐT) -> KHÔNG order",
       await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cidI) == 0)

    # ================= AC-5 address unclear -> server clarification (out-of-allowlist, full-scope) =================
    cidA = await mkcust(f"tg:gfa-{RUN}")
    _e0 = _ESC["n"]
    # (1) address ĐỦ DÀI nhưng tỉnh/phường KHÔNG resolve -> NEEDS_CLARIFICATION (không tự áp sai, không escalate).
    _EX.clear(); _EX.append({"sku": "SPGF", "quantity": 1, "customer_name": "Nam", "phone": "0900001234",
                             "address": "123 Duong Khong Ro Rang", "province": "Tinh Khong Co Thuc",
                             "ward": "Phuong Khong Co Thuc"})
    _S.clear(); _S.append({"text": "cho em xin lại tỉnh/phường ạ"})
    await orchestrator.handle_message(f"tg:gfa-{RUN}", "đặt 1 hũ giao 123 Duong Khong Ro Rang",
                                      channel="telegram_customer", provider_message_id=mid())
    st5 = await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cidA)
    ck("AC-5a địa chỉ không rõ -> ĐÚNG NEEDS_CLARIFICATION, 0 order, 0 escalation (không tự áp sai/không escalate sớm)",
       st5 == "NEEDS_CLARIFICATION"
       and await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cidA) == 0 and _ESC["n"] == _e0,
       f"state={st5} esc={_ESC['n']-_e0}")
    # (2) model claim trong NEEDS_CLARIFICATION -> reply SERVER-DERIVED clarification (chứa ĐÚNG địa chỉ), no escalate.
    _EX.clear(); _S.clear()
    _S.append({"text": "Dạ mã đơn của anh đã được tạo, đơn đã được ghi nhận ạ."})  # claim -> guard
    r5 = await orchestrator.handle_message(f"tg:gfa-{RUN}", "vâng ạ",
                                           channel="telegram_customer", provider_message_id=mid())
    ck("AC-5b clarification reply là SERVER-DERIVED (chứa đúng địa chỉ intent), state giữ, 0 order/escalation",
       "123 Duong Khong Ro Rang" in (r5 or "") and _ESC["n"] == _e0
       and await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1", cidA)
       == "NEEDS_CLARIFICATION" and await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cidA) == 0,
       f"reply={(r5 or '')[:55]}")

    # ================= AC-7 model claim (full-scope, out-of-allowlist) -> no escalate/terminalize =================
    cidC = await mkcust(f"tg:gfc-{RUN}")
    _e0 = _ESC["n"]
    _EX.clear(); _S.clear(); _S.append({"text": "Dạ đơn đã được ghi nhận, mã đơn của anh đã được tạo ạ."})
    await orchestrator.handle_message(f"tg:gfc-{RUN}", "vâng ạ", channel="telegram_customer", provider_message_id=mid())
    ck("AC-7 model claim (full-scope) -> no escalate/terminalize",
       _ESC["n"] == _e0 and await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cidC) == 0)

    # ================= AC-9 kill switch end-to-end: ON chặn, OFF khôi phục không dup =================
    base_flags(); settings.gate_e_fullscope_telegram_customer = True
    settings.address_resolver_fullscope_telegram_customer = True
    cidK = await mkcust(f"tg:gfk-{RUN}")
    settings.gate_e_kill_switch = True
    _EX.clear(); _EX.append(FULL()); _S.clear(); _S.append({"text": "..."})
    await orchestrator.handle_message(f"tg:gfk-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                      channel="telegram_customer", provider_message_id=mid())
    ck("AC-9 kill ON -> KHÔNG tạo intent/order (chặn new processing)",
       await q1("SELECT count(*) FROM order_intents WHERE customer_id=$1", cidK) == 0)
    settings.gate_e_kill_switch = False  # OFF -> khôi phục
    _EX.clear(); _EX.append(FULL()); _S.clear(); _S.append({"text": "ok"})
    await orchestrator.handle_message(f"tg:gfk-{RUN}", "đặt 1 hũ cà phê giao Ea Kao Hoa 0900001234",
                                      channel="telegram_customer", provider_message_id=mid())
    _S.clear(); _S.append({"text": "..."})
    await orchestrator.handle_message(f"tg:gfk-{RUN}", "xác nhận", channel="telegram_customer", provider_message_id=mid())
    ck("AC-9 kill OFF -> khôi phục, commit ĐÚNG 1 (không dup)",
       await q1("SELECT count(*) FROM orders WHERE customer_id=$1", cidK) == 1)

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: ' + ', '.join(FAILS)}")
    await close_pool()
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
