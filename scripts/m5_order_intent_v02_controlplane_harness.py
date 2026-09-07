"""V02 control-plane smoke (CA 225-01/02/03/04): drive qua handle_message, assert PERSISTED intent state
+ command-row lifecycle sau moi buoc."""
import asyncio, sys, json, types, time
RUN=str(int(time.time()))
from app.config import settings
from app.db_pool import acquire, release, close_pool
from app.services import orchestrator

FAILS=[]
def ck(n,c,extra=""): print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: '+extra) if extra else ''}"); (FAILS.append(n) if not c else None)

_SCRIPT=[]
def _mk(item):
    tcs=None
    if item.get("tools"):
        tcs=[types.SimpleNamespace(id=f"c{i}",function=types.SimpleNamespace(
            name=t["name"],arguments=json.dumps(t["args"],ensure_ascii=False))) for i,t in enumerate(item["tools"])]
    return types.SimpleNamespace(content=item.get("text"),tool_calls=tcs)
async def _fake(client,**kw):
    it=_SCRIPT.pop(0) if _SCRIPT else {"text":"..."}
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=_mk(it),
        finish_reason="tool_calls" if it.get("tools") else "stop")],
        usage=types.SimpleNamespace(prompt_tokens=1,completion_tokens=1))
orchestrator._llm_create=_fake

async def q1(sql,*a):
    c=await acquire()
    try: return await c.fetchval(sql,*a)
    finally: await release(c)
async def qr(sql,*a):
    c=await acquire()
    try: return await c.fetchrow(sql,*a)
    finally: await release(c)

async def setup(psid):
    c=await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPV','x',500,1000) ON CONFLICT(sku) DO UPDATE SET stock=500")
        cid=await c.fetchval("SELECT id FROM customers WHERE psid=$1",psid) or \
            await c.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'H','0900002000') RETURNING id",psid)
        return cid
    finally: await release(c)

GOOD={"sku":"SPV","quantity":1,"customer_name":"H","phone":"0900002000",
      "address":"12 Le Loi, P. Ea Kao, Dak Lak","province":"Tỉnh Đắk Lắk","ward":"Phường Ea Kao"}
BAD=dict(GOOD,address="cho khong ro",province="Tinh Khong Co",ward="Phuong Khong Co")

async def main():
    global _SCRIPT
    settings.m1_reliable_order_command=False
    settings.enable_gate_e_order_wiring=True
    settings.enable_address_resolver=True
    settings.enable_nlu_router=False

    # S1 verified order -> COMMITTED + command row succeeded (not processing)
    cid=await setup(f"tg:v1-{RUN}")
    settings.gate_e_canary_customer_ids=str(cid); settings.address_resolver_pilot_customer_ids=str(cid)
    n0=await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
    _SCRIPT.clear(); _SCRIPT+=[{"tools":[{"name":"create_order","args":GOOD}]},{"text":"Đã tạo đơn."}]
    s1reply=await orchestrator.handle_message(f"tg:v1-{RUN}","dat 1 goi Ea Kao",channel="telegram_customer",provider_message_id=f"tg:{RUN}01")
    ck("S1 +1 order",await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)==n0+1)
    ck("S8 reply DETERMINISTIC (225-07: khac raw LLM 'Đã tạo đơn.', m1=False)", s1reply!="Đã tạo đơn." and bool(s1reply), repr(s1reply)[:80])
    st=await qr("SELECT state,committed_order_id FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1",cid)
    ck("S1 intent COMMITTED + committed_order_id",st and st["state"]=="COMMITTED" and st["committed_order_id"],str(dict(st) if st else None))
    proc=await q1("SELECT count(*) FROM command_executions WHERE channel='telegram_customer' AND status='processing'")
    ck("S1 khong command row 'processing' mo coi (225-03)",proc==0,f"processing={proc}")

    # S2 stale-confirm same content different msg -> duplicate, 0 new order, replay row finalized
    n1=await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
    _SCRIPT.clear(); _SCRIPT+=[{"tools":[{"name":"create_order","args":GOOD}]},{"text":"Đơn đã xác nhận."}]
    await orchestrator.handle_message(f"tg:v1-{RUN}","xac nhan nha",channel="telegram_customer",provider_message_id=f"tg:{RUN}02")
    ck("S2 stale-confirm KHONG don moi (case 14)",await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)==n1)
    proc2=await q1("SELECT count(*) FROM command_executions WHERE channel='telegram_customer' AND status='processing'")
    ck("S2 replay row finalized (khong 'processing') (225-03)",proc2==0,f"processing={proc2}")

    # S3 ambiguous -> durable NEEDS_CLARIFICATION, 0 order
    cid3=await setup(f"tg:v3-{RUN}")
    settings.gate_e_canary_customer_ids=f"{cid},{cid3}"; settings.address_resolver_pilot_customer_ids=f"{cid},{cid3}"
    m0=await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid3)
    _SCRIPT.clear(); _SCRIPT+=[{"tools":[{"name":"create_order","args":BAD}]},{"text":"Cho em xin lai phuong a."}]
    await orchestrator.handle_message(f"tg:v3-{RUN}","giao cho khong ro",channel="telegram_customer",provider_message_id=f"tg:{RUN}03")
    ck("S3 ambiguous 0 order",await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid3)==m0)
    st3=await qr("SELECT id,state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1",cid3)
    ck("S3 intent DURABLE NEEDS_CLARIFICATION (225-01)",st3 and st3["state"]=="NEEDS_CLARIFICATION",str(dict(st3) if st3 else None))

    # S4 correction same conv -> SAME intent, COMMITTED
    _SCRIPT.clear(); _SCRIPT+=[{"tools":[{"name":"create_order","args":GOOD}]},{"text":"Đã tạo đơn."}]
    await orchestrator.handle_message(f"tg:v3-{RUN}","a Phuong Ea Kao Dak Lak",channel="telegram_customer",provider_message_id=f"tg:{RUN}04")
    ck("S4 correction +1 order",await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid3)==m0+1)
    st4=await qr("SELECT id,state,committed_order_id FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1",cid3)
    ck("S4 CUNG intent (id khong doi) -> COMMITTED (correction 225-01)",
       st4 and str(st4["id"])==str(st3["id"]) and st4["state"]=="COMMITTED",
       f"s3={st3['id']} s4={st4['id'] if st4 else None}")
    cnt_intent=await q1("SELECT count(*) FROM order_intents WHERE customer_id=$1",cid3)
    ck("S4 chi 1 intent cho conv (khong song song)",cnt_intent==1,f"intents={cnt_intent}")

    # S5 explicit reorder (case 15): same conv v1 (da COMMITTED), marker 'dat them' -> intent MOI + don 2
    n_v1=await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
    ni_v1=await q1("SELECT count(*) FROM order_intents WHERE customer_id=$1",cid)
    _SCRIPT.clear(); _SCRIPT+=[{"tools":[{"name":"create_order","args":GOOD}]},{"text":"Đã tạo đơn."}]
    await orchestrator.handle_message(f"tg:v1-{RUN}","cho minh dat them 1 don nua giong vay",channel="telegram_customer",provider_message_id=f"tg:{RUN}05")
    ck("S5 explicit reorder -> don THU 2 (case 15)",await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)==n_v1+1)
    ck("S5 intent MOI duoc tao (khong stale-confirm)",await q1("SELECT count(*) FROM order_intents WHERE customer_id=$1",cid)==ni_v1+1)

    # S6 cancel (case 11): tao intent ambiguous (open) roi huy -> CANCELLED, 0 order
    cid6=await setup(f"tg:v6-{RUN}")
    settings.gate_e_canary_customer_ids=f"{cid},{cid3},{cid6}"; settings.address_resolver_pilot_customer_ids=f"{cid},{cid3},{cid6}"
    k0=await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid6)
    _SCRIPT.clear(); _SCRIPT+=[{"tools":[{"name":"create_order","args":BAD}]},{"text":"Cho em xin lai phuong a."}]
    await orchestrator.handle_message(f"tg:v6-{RUN}","giao cho khong ro",channel="telegram_customer",provider_message_id=f"tg:{RUN}06")
    await orchestrator.handle_message(f"tg:v6-{RUN}","thoi huy don nhe",channel="telegram_customer",provider_message_id=f"tg:{RUN}07")
    st6=await qr("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1",cid6)
    ck("S6 cancel -> intent CANCELLED (case 11)",st6 and st6["state"]=="CANCELLED",str(dict(st6) if st6 else None))
    ck("S6 cancel -> 0 order",await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid6)==k0)

    # S7 escalate wants_human (case 12): open intent -> ESCALATED
    cid7=await setup(f"tg:v7-{RUN}")
    settings.gate_e_canary_customer_ids=f"{cid},{cid3},{cid6},{cid7}"; settings.address_resolver_pilot_customer_ids=f"{cid},{cid3},{cid6},{cid7}"
    _SCRIPT.clear(); _SCRIPT+=[{"tools":[{"name":"create_order","args":BAD}]},{"text":"Cho em xin lai phuong a."}]
    await orchestrator.handle_message(f"tg:v7-{RUN}","giao cho khong ro",channel="telegram_customer",provider_message_id=f"tg:{RUN}08")
    await orchestrator.handle_message(f"tg:v7-{RUN}","cho minh gap nhan vien voi",channel="telegram_customer",provider_message_id=f"tg:{RUN}09")
    st7=await qr("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1",cid7)
    ck("S7 wants_human -> intent ESCALATED (case 12)",st7 and st7["state"]=="ESCALATED",str(dict(st7) if st7 else None))

    # S9 legacy province (CA 225-07): 'Phu Yen'/'Tuy Hoa' KHONG co trong v2 -> clarify/escalate GRACEFUL,
    # KHONG 'loi he thong', 0 order (khong bia).
    cid9=await setup(f"tg:v9-{RUN}")
    settings.gate_e_canary_customer_ids=f"{cid},{cid3},{cid6},{cid7},{cid9}"; settings.address_resolver_pilot_customer_ids=f"{cid},{cid3},{cid6},{cid7},{cid9}"
    OLD=dict(GOOD,address="1 Tran Hung Dao, Tuy Hoa, Phu Yen",province="Tỉnh Phú Yên",ward="Phường Tuy Hòa")
    _SCRIPT.clear(); _SCRIPT+=[{"tools":[{"name":"create_order","args":OLD}]},{"text":"Cho em xin lai phuong/tinh hien tai a."}]
    s9=await orchestrator.handle_message(f"tg:v9-{RUN}","giao Tuy Hoa Phu Yen",channel="telegram_customer",provider_message_id=f"tg:{RUN}09b")
    ck("S9 old-province 0 order",await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid9)==0)
    st9=await qr("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1",cid9)
    ck("S9 old-province -> NEEDS_CLARIFICATION|ESCALATED (khong crash)",st9 and st9["state"] in ("NEEDS_CLARIFICATION","ESCALATED"),str(dict(st9) if st9 else None))
    ck("S9 reply KHONG phai 'loi he thong'",bool(s9) and "lỗi" not in s9.lower(),repr(s9)[:80])

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool(); sys.exit(1 if FAILS else 0)

asyncio.run(main())
