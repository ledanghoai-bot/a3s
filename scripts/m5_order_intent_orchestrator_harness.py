"""Full-conversation harness qua handle_message (CA Amendment 224 §10) — mock LLM deterministic.
Chung minh duong ORCHESTRATOR that (khong goi gateway truc tiep nhu flow_e2e):
 H1 (case 1)  incomplete -> LLM hoi lai, 0 order, 0 intent committed
 H2 (case 5+7+14) don du -> commit 1 lan; luot xac nhan (LLM goi create_order LAI, message KHAC) -> 0 don moi
 H3 (case 20) Gate E pilot (m1=False) -> command bus commit + deterministic receipt
"""
import asyncio, sys, json, types, time
RUN=str(int(time.time()))  # duy nhat moi run -> customer/message tuoi, tranh idempotency collision cross-run
from app.config import settings
from app.db_pool import acquire, release, close_pool
from app.services import orchestrator

FAILS=[]
def ck(n,c): print(f"  [{'PASS' if c else 'FAIL'}] {n}"); (FAILS.append(n) if not c else None)

# ---- mock LLM: hang doi phan hoi scripted, moi phan tu la tool_calls HOAC text ----
_SCRIPT=[]  # list cua dict: {"tools":[{"name","args"}]} hoac {"text": "..."}
def _mk_msg(item):
    tcs=None
    if item.get("tools"):
        tcs=[]
        for i,t in enumerate(item["tools"]):
            fn=types.SimpleNamespace(name=t["name"], arguments=json.dumps(t["args"], ensure_ascii=False))
            tcs.append(types.SimpleNamespace(id=f"call_{i}", function=fn))
    return types.SimpleNamespace(content=item.get("text"), tool_calls=tcs)
async def _fake_llm(client, **kwargs):
    item=_SCRIPT.pop(0) if _SCRIPT else {"text":"..."}
    choice=types.SimpleNamespace(message=_mk_msg(item),
        finish_reason=("tool_calls" if item.get("tools") else "stop"))
    return types.SimpleNamespace(choices=[choice],
        usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=5))
orchestrator._llm_create=_fake_llm

ORD={"sku":"SPH","quantity":1,"customer_name":"Hoa","phone":"0900001234","address":"12 Le Loi, Buon Ma Thuot"}

async def n_orders(cid):
    conn=await acquire()
    try: return await conn.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
    finally: await release(conn)

async def setup_customer(psid):
    conn=await acquire()
    try:
        await conn.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPH','x',500,1000) ON CONFLICT(sku) DO UPDATE SET stock=500")
        cid=await conn.fetchval("SELECT id FROM customers WHERE psid=$1",psid) or \
            await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'Hoa','0900001234') RETURNING id",psid)
        return cid
    finally: await release(conn)

async def main():
    global _SCRIPT
    settings.enable_address_resolver=False  # co lap intent machinery (dia chi da co test rieng)
    settings.enable_gate_e_order_wiring=False
    settings.enable_nlu_router=False

    # H1 — incomplete -> hoi lai, 0 order
    settings.m1_reliable_order_command=True
    cid=await setup_customer(f"tg:h1-{RUN}"); n0=await n_orders(cid)
    _SCRIPT.clear(); _SCRIPT.append({"text":"Dạ cho em xin địa chỉ giao và số điện thoại ạ."})
    await orchestrator.handle_message(f"tg:h1-{RUN}","cho mình 1 gói",channel="telegram_customer",provider_message_id=f"h1m1-{RUN}")
    ck("H1 incomplete -> 0 order", await n_orders(cid)==n0)

    # H2 — don du: turn1 commit; turn2 xac nhan (create_order LAI, message khac) -> 0 don moi (case 5+7+14)
    cid=await setup_customer(f"tg:h2-{RUN}"); n0=await n_orders(cid)
    _SCRIPT.clear()
    _SCRIPT+=[{"tools":[{"name":"create_order","args":ORD}]}, {"text":"Đã tạo đơn cho anh/chị."}]  # turn1
    await orchestrator.handle_message(f"tg:h2-{RUN}","đặt 1 gói giao 12 Le Loi BMT, 0900001234, Hoa",
                                      channel="telegram_customer",provider_message_id=f"h2m1-{RUN}")
    n1=await n_orders(cid); ck("H2 turn1 -> +1 order", n1==n0+1)
    _SCRIPT.clear()
    _SCRIPT+=[{"tools":[{"name":"create_order","args":ORD}]}, {"text":"Đơn của anh/chị đã được xác nhận."}]  # turn2 confirm
    await orchestrator.handle_message(f"tg:h2-{RUN}","ok xác nhận đơn nha",
                                      channel="telegram_customer",provider_message_id=f"h2m2-{RUN}")
    n2=await n_orders(cid); ck("H2 turn2 xac nhan (create_order lai, msg khac) -> KHONG don moi (case 7/14)", n2==n1)

    # H3 — Gate E pilot khi m1=False (case 20): command bus commit + verified-address binding + deterministic
    # receipt. Bat resolver + pilot scope + dia chi verify duoc (Ea Kao/Dak Lak da proven auto_verified).
    settings.m1_reliable_order_command=False
    settings.enable_gate_e_order_wiring=True
    settings.enable_address_resolver=True
    cid=await setup_customer(f"tg:h3-{RUN}"); n0=await n_orders(cid)
    settings.gate_e_canary_customer_ids=str(cid)          # _gate_e_scope_ids() doc settings live
    settings.address_resolver_pilot_customer_ids=str(cid)  # _pilot_scope() doc settings live
    ORD3=dict(ORD, address="123 duong X, Phuong Ea Kao, Dak Lak",
              province="Tỉnh Đắk Lắk", ward="Phường Ea Kao")
    _SCRIPT.clear()
    _SCRIPT+=[{"tools":[{"name":"create_order","args":ORD3}]}, {"text":"Đã tạo đơn."}]
    await orchestrator.handle_message(f"tg:h3-{RUN}","đặt 1 gói giao Phường Ea Kao Đắk Lắk 0900001234 Hoa",
                                      channel="telegram_customer",provider_message_id=f"tg:{RUN}")  # tg:<so> hop le cho verify
    n1=await n_orders(cid); ck("H3 Gate E pilot (m1=False) -> +1 order qua command bus (case 20)", n1==n0+1)
    conn=await acquire()
    try:
        snap=await conn.fetchval("SELECT count(*) FROM order_address_snapshot s JOIN orders o ON o.id=s.order_id WHERE o.customer_id=$1",cid)
        ck("H3 verified-address snapshot bound (Gate E)", snap>=1)
    finally: await release(conn)
    # verify command_executions co ban ghi (command bus that su chay)
    conn=await acquire()
    try:
        cnt=await conn.fetchval("SELECT count(*) FROM command_executions WHERE channel='telegram_customer' AND status='succeeded'")
        ck("H3 command_executions succeeded ton tai (command bus)", cnt>=1)
    finally: await release(conn)

    # H4 — duplicate provider event (case 6): CUNG provider_message_id 2 lan -> command idempotency -> 1 don
    settings.m1_reliable_order_command=True
    settings.enable_gate_e_order_wiring=False
    settings.enable_address_resolver=False
    cid=await setup_customer(f"tg:h4-{RUN}"); n0=await n_orders(cid)
    for _ in range(2):
        _SCRIPT.clear(); _SCRIPT+=[{"tools":[{"name":"create_order","args":ORD}]}, {"text":"Đã tạo đơn."}]
        await orchestrator.handle_message(f"tg:h4-{RUN}","đặt 1 gói 12 Le Loi 0900001234 Hoa",
                                          channel="telegram_customer",provider_message_id=f"h4dup-{RUN}")  # CUNG id
    ck("H4 duplicate provider event -> 1 don (case 6)", await n_orders(cid)==n0+1)

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool(); sys.exit(1 if FAILS else 0)

asyncio.run(main())
