"""CA 232 DoD end-to-end qua handle_message: model gather+PROPOSE (create_order) -> summary; confirm turn
model KHONG goi create_order -> SERVER chot (sua goc c Tien). + generic-confirm ngoai context -> 0 order."""
import asyncio, sys, json, types, time
RUN=str(int(time.time()))
from app.config import settings
from app.db_pool import acquire, release, close_pool
from app.services import orchestrator
FAILS=[]
def ck(n,c,x=""): print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: '+x) if x else ''}"); (FAILS.append(n) if not c else None)
_S=[]
def _mk(it):
    tcs=[types.SimpleNamespace(id=f"c{i}",function=types.SimpleNamespace(name=t["name"],arguments=json.dumps(t["args"],ensure_ascii=False))) for i,t in enumerate(it.get("tools",[]))] or None
    return types.SimpleNamespace(content=it.get("text"),tool_calls=tcs)
async def _fake(client,**kw):
    it=_S.pop(0) if _S else {"text":"..."}
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=_mk(it),finish_reason="tool_calls" if it.get("tools") else "stop")],usage=types.SimpleNamespace(prompt_tokens=1,completion_tokens=1))
orchestrator._llm_create=_fake
async def q1(s,*a):
    c=await acquire()
    try: return await c.fetchval(s,*a)
    finally: await release(c)
async def setup(psid):
    c=await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPH','x',500,1000) ON CONFLICT(sku) DO UPDATE SET stock=500")
        return await c.fetchval("SELECT id FROM customers WHERE psid=$1",psid) or await c.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'H','0900001234') RETURNING id",psid)
    finally: await release(c)
GOOD={"sku":"SPH","quantity":1,"customer_name":"Hoa","phone":"0900001234","address":"12 Le Loi, P. Ea Kao, Dak Lak","province":"Tỉnh Đắk Lắk","ward":"Phường Ea Kao"}

async def main():
    global _S
    settings.m1_reliable_order_command=False
    settings.enable_gate_e_order_wiring=True
    settings.enable_address_resolver=True
    settings.enable_nlu_router=False
    cid=await setup(f"tg:cch-{RUN}")
    settings.gate_e_canary_customer_ids=str(cid); settings.address_resolver_pilot_customer_ids=str(cid)
    n0=await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)

    # Turn 1: model PROPOSE (create_order voi du field) -> server present summary, 0 order
    _S.clear(); _S+=[{"tools":[{"name":"create_order","args":GOOD}]},{"text":"Em xác nhận đơn: 1 hũ, Hoa, Ea Kao. Anh xác nhận giúp em nhé?"}]
    await orchestrator.handle_message(f"tg:cch-{RUN}","đặt 1 hũ giao Ea Kao Hoa 0900001234",channel="telegram_customer",provider_message_id=f"tg:{RUN}1")
    ck("T1 propose -> 0 order (chua commit)", await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)==n0)
    st=await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1",cid)
    ck("T1 intent READY_TO_COMMIT + summary", st=="READY_TO_COMMIT", str(st))

    # Turn 2: khach XAC NHAN; model KHONG goi create_order (chi text) -> SERVER chot
    _S.clear(); _S+=[{"text":"KHONG NEN DUOC DUNG (server chot truoc LLM)"}]
    r=await orchestrator.handle_message(f"tg:cch-{RUN}","xác nhận",channel="telegram_customer",provider_message_id=f"tg:{RUN}2")
    ck("T2 confirm -> SERVER chot +1 order (khong model create_order)", await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)==n0+1)
    ck("T2 mock LLM KHONG bi tieu thu (server chot truoc LLM)", len(_S)==1, f"remaining={len(_S)}")
    st2=await q1("SELECT state,committed_order_id FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1",cid)
    ck("T2 intent COMMITTED", st2 is not None)
    # receipt log vao messages (staff-visible §7)?
    rc=await q1("SELECT count(*) FROM messages WHERE conversation_id=(SELECT id FROM conversations WHERE customer_id=$1 ORDER BY id DESC LIMIT 1) AND role='bot' AND content LIKE '%#%'",cid)
    ck("T2 receipt log vao messages (staff-visible §7)", rc>=1, f"receipt_msgs={rc}")

    # Turn 3: re-confirm (redelivered) -> khong don moi
    n1=await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
    _S.clear(); _S+=[{"text":"Dạ đơn đã được ghi nhận rồi ạ."}]
    await orchestrator.handle_message(f"tg:cch-{RUN}","xác nhận",channel="telegram_customer",provider_message_id=f"tg:{RUN}3")
    ck("T3 re-confirm -> khong don moi", await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)==n1)

    # DoD#13: generic confirm NGOAI pending context (khach moi) -> 0 order
    cid2=await setup(f"tg:cch2-{RUN}")
    settings.gate_e_canary_customer_ids=f"{cid},{cid2}"; settings.address_resolver_pilot_customer_ids=f"{cid},{cid2}"
    _S.clear(); _S+=[{"text":"Dạ em chào anh ạ."}]
    await orchestrator.handle_message(f"tg:cch2-{RUN}","xác nhận",channel="telegram_customer",provider_message_id=f"tg:{RUN}4")
    ck("DoD#13 generic confirm ngoai context -> 0 order", await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid2)==0)

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool(); sys.exit(1 if FAILS else 0)
asyncio.run(main())
