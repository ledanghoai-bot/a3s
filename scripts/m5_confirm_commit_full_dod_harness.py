"""CA 232 §9 — harness DAY DU DoD confirm-to-commit. Orchestrator (handle_message + mock LLM co the
DELIBERATELY refuse create_order) + service/DB. DoD 8/9/10/12/13 da co o cc_core+cc_orch (khong lap)."""
import asyncio, sys, json, types, time
RUN=str(int(time.time()))
from app.config import settings
from app.db_pool import acquire, release, close_pool
from app.services import orchestrator
from app.services.command import order_intent as oi, order_intent_service as svc, order_intent_flow as flow
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
async def qr(s,*a):
    c=await acquire()
    try:
        r=await c.fetchrow(s,*a); return dict(r) if r else None
    finally: await release(c)
async def setup(psid):
    c=await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPH','x',500,1000) ON CONFLICT(sku) DO UPDATE SET stock=500")
        return await c.fetchval("SELECT id FROM customers WHERE psid=$1",psid) or await c.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'H','0900001234') RETURNING id",psid)
    finally: await release(c)
async def newconv(cid):
    c=await acquire()
    try: return await c.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cid)
    finally: await release(c)
GOOD={"sku":"SPH","quantity":1,"customer_name":"Hoa","phone":"0900001234","address":"12 Le Loi, P. Ea Kao, Dak Lak","province":"Tỉnh Đắk Lắk","ward":"Phường Ea Kao"}
async def norders(cid): return await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
async def nintents(cid): return await q1("SELECT count(*) FROM order_intents WHERE customer_id=$1",cid)
async def laststate(cid): return await q1("SELECT state FROM order_intents WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 1",cid)

_CTR=[0]
def _mid():
    _CTR[0]+=1
    return f"tg:{RUN}{_CTR[0]}"  # numeric tg:<so> hop le cho verify
async def commit_via_confirm(psid,cid):
    global _S
    _S.clear(); _S+=[{"tools":[{"name":"create_order","args":GOOD}]},{"text":"Xác nhận giúp em nhé?"}]
    await orchestrator.handle_message(psid,"đặt 1 hũ Ea Kao Hoa 0900001234",channel="telegram_customer",provider_message_id=_mid())
    _S.clear(); _S+=[{"text":"noop"}]
    await orchestrator.handle_message(psid,"xác nhận",channel="telegram_customer",provider_message_id=_mid())

async def main():
    global _S
    settings.m1_reliable_order_command=False
    settings.enable_gate_e_order_wiring=True
    settings.enable_address_resolver=True
    settings.enable_nlu_router=False
    cid=await setup(f"tg:d-{RUN}")
    settings.gate_e_canary_customer_ids=str(cid); settings.address_resolver_pilot_customer_ids=str(cid)

    # D1: incomplete order (model HOI info, KHONG goi create_order) -> COLLECTING + 0 order
    psid=f"tg:d-{RUN}"
    _S.clear(); _S+=[{"text":"Dạ anh cho em xin địa chỉ và SĐT giao ạ."}]
    await orchestrator.handle_message(psid,"mình muốn đặt hàng 1 hũ",channel="telegram_customer",provider_message_id=f"tg:{RUN}d1")
    ck("D1 incomplete -> COLLECTING + 0 order", await laststate(cid)=="COLLECTING" and await norders(cid)==0, await laststate(cid))

    # D21: ordinary chat + order-status -> KHONG tao draft/order
    n_before_i=await nintents(cid)
    _S.clear(); _S+=[{"text":"Dạ cà phê pha phin ngon ạ."}]
    await orchestrator.handle_message(psid,"cà phê này pha sao ạ",channel="telegram_customer",provider_message_id=f"tg:{RUN}d21a")
    _S.clear(); _S+=[{"text":"Dạ em kiểm tra giúp ạ."}]
    await orchestrator.handle_message(psid,"kiểm tra đơn hôm qua giúp anh",channel="telegram_customer",provider_message_id=f"tg:{RUN}d21b")
    ck("D21 ordinary+status chat -> KHONG them intent", await nintents(cid)==n_before_i, f"{n_before_i}->{await nintents(cid)}")

    # D6: ambiguous address -> clarify, KHONG commit
    cid6=await setup(f"tg:d6-{RUN}"); settings.gate_e_canary_customer_ids=f"{cid},{cid6}"; settings.address_resolver_pilot_customer_ids=f"{cid},{cid6}"
    BAD=dict(GOOD,address="cho X",province="Tinh Khong Co",ward="Phuong Khong Co")
    _S.clear(); _S+=[{"tools":[{"name":"create_order","args":BAD}]},{"text":"Cho em xin lại phường ạ."}]
    await orchestrator.handle_message(f"tg:d6-{RUN}","giao cho X",channel="telegram_customer",provider_message_id=f"tg:{RUN}6")
    ck("D6 ambiguous -> clarify, 0 order", await norders(cid6)==0 and await laststate(cid6) in ("NEEDS_CLARIFICATION","ESCALATED"), await laststate(cid6))

    # D2 + D19: commit 1 don, roi reorder -> draft moi
    cid2=await setup(f"tg:d2-{RUN}"); settings.gate_e_canary_customer_ids=f"{cid},{cid6},{cid2}"; settings.address_resolver_pilot_customer_ids=settings.gate_e_canary_customer_ids
    await commit_via_confirm(f"tg:d2-{RUN}",cid2)
    ck("D2/D19 commit don dau", await norders(cid2)==1)
    convid=await q1("SELECT id FROM conversations WHERE customer_id=$1 ORDER BY id DESC LIMIT 1",cid2)
    rc=await q1("SELECT count(*) FROM messages WHERE conversation_id=$1 AND role='bot' AND content LIKE '%#%'",convid)
    ob=await q1("SELECT count(*) FROM outbox_events WHERE event_type='order.receipt.customer' AND created_at>now()-interval '5 min'")
    ck("D19 receipt: 1 lan messages", rc==1, f"msgs={rc}")
    ni=await nintents(cid2)
    _S.clear(); _S+=[{"tools":[{"name":"create_order","args":GOOD}]},{"text":"Đơn mới, xác nhận nhé?"}]
    await orchestrator.handle_message(f"tg:d2-{RUN}","đặt thêm 1 đơn nữa giống vậy",channel="telegram_customer",provider_message_id=_mid())
    ck("D2 reorder -> draft MOI (intent moi)", await nintents(cid2)==ni+1 and await laststate(cid2)=="READY_TO_COMMIT")

    # D18: model claim 'don se duoc xu ly' voi READY draft dang cho -> thay bang confirm-prompt, 0 order
    cid18=await setup(f"tg:d18-{RUN}"); settings.gate_e_canary_customer_ids=f"{cid},{cid6},{cid2},{cid18}"; settings.address_resolver_pilot_customer_ids=settings.gate_e_canary_customer_ids
    _S.clear(); _S+=[{"tools":[{"name":"create_order","args":GOOD}]},{"text":"Đơn hàng của anh sẽ được đội ngũ 3S Coffee xử lý và liên hệ ạ."}]
    r18=await orchestrator.handle_message(f"tg:d18-{RUN}","đặt 1 hũ Ea Kao Hoa 0900001234",channel="telegram_customer",provider_message_id=f"tg:{RUN}18")
    ck("D18 claim-khong-receipt -> thay confirm-prompt, 0 order", await norders(cid18)==0 and "xác nhận" in r18.lower(), repr(r18)[:60])

    # D15: cancel -> 0 order + KHONG vao model loop (script khong tieu thu)
    cid15=await setup(f"tg:d15-{RUN}"); settings.gate_e_canary_customer_ids=f"{settings.gate_e_canary_customer_ids},{cid15}"; settings.address_resolver_pilot_customer_ids=settings.gate_e_canary_customer_ids
    _S.clear(); _S+=[{"tools":[{"name":"create_order","args":GOOD}]}]
    await orchestrator.handle_message(f"tg:d15-{RUN}","thôi huỷ đơn nhé",channel="telegram_customer",provider_message_id=f"tg:{RUN}15")
    ck("D15 cancel -> 0 order + script khong tieu thu", await norders(cid15)==0 and len(_S)==1)

    # ---- service-level (m1 route: khong Gate E binding -> khong can resolution that) ----
    settings.m1_reliable_order_command=True
    settings.enable_gate_e_order_wiring=False
    # D4: correction doi field -> version tang (fingerprint doi khi ready)
    convx=await newconv(cid)
    r=await flow.propose_draft(customer_id=cid,conversation_id=convx,channel='telegram_customer',proposed={"sku":"SPH","quantity":1,"customer_name":"A","phone":"0900001234","address":"1 A, Phuong Ea Kao, Dak Lak"},verified=True,addr_fp=None,verified_resolution_id=None,address_changed=True)
    st_a=await qr("SELECT state_version,draft_quantity FROM order_intents WHERE id=$1",r["order_intent_id"])
    r2=await flow.propose_draft(customer_id=cid,conversation_id=convx,channel='telegram_customer',proposed={"quantity":5},verified=True,addr_fp=None,verified_resolution_id=None,address_changed=False)
    st_b=await qr("SELECT state_version,draft_quantity FROM order_intents WHERE id=$1",r["order_intent_id"])
    ck("D4 correction -> version tang + field thay", st_b["state_version"]>st_a["state_version"] and st_b["draft_quantity"]==5)

    # D11: concurrent confirmation -> 1 order (2 try_server_commit song song cung intent READY)
    cid11=await setup(f"tg:d11-{RUN}"); conv11=await newconv(cid11)
    settings.gate_e_canary_customer_ids=f"{settings.gate_e_canary_customer_ids},{cid11}"
    await flow.propose_draft(customer_id=cid11,conversation_id=conv11,channel='telegram_customer',proposed={"sku":"SPH","quantity":1,"customer_name":"H","phone":"0900001234","address":"1 A"},verified=True,addr_fp=None,verified_resolution_id=None,address_changed=True)
    n11=await norders(cid11)
    rA,rB=await asyncio.gather(
        flow.try_server_commit(customer_id=cid11,conversation_id=conv11,channel='telegram_customer',actor_id=f'tg:d11-{RUN}',provider_message_id=f'tg:{RUN}c1'),
        flow.try_server_commit(customer_id=cid11,conversation_id=conv11,channel='telegram_customer',actor_id=f'tg:d11-{RUN}',provider_message_id=f'tg:{RUN}c2'))
    oids={x.get("order_id") for x in (rA,rB) if x and x.get("order_id")}
    ck("D11 concurrent confirm -> 1 order", await norders(cid11)==n11+1 and len(oids)==1, str(oids))

    # D20: Redis flush -> draft van con (DB) + confirm van chot
    import redis.asyncio as aioredis
    cid20=await setup(f"tg:d20-{RUN}"); conv20=await newconv(cid20)
    settings.gate_e_canary_customer_ids=f"{settings.gate_e_canary_customer_ids},{cid20}"
    await flow.propose_draft(customer_id=cid20,conversation_id=conv20,channel='telegram_customer',proposed={"sku":"SPH","quantity":1,"customer_name":"H","phone":"0900001234","address":"1 A"},verified=True,addr_fp=None,verified_resolution_id=None,address_changed=True)
    rc=await aioredis.from_url(settings.redis_url,decode_responses=True); await rc.flushall(); await rc.aclose()
    n20=await norders(cid20)
    r20=await flow.try_server_commit(customer_id=cid20,conversation_id=conv20,channel='telegram_customer',actor_id=f'tg:d20-{RUN}',provider_message_id=f'tg:{RUN}20')
    ck("D20 Redis-loss -> draft con + confirm chot", r20 is not None and r20.get("order_id") and await norders(cid20)==n20+1)

    # D17: business rejection (stock=0) qua server-commit -> REJECTED, 0 order
    c=await acquire()
    try: await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPOUT','x',0,1000) ON CONFLICT(sku) DO UPDATE SET stock=0")
    finally: await release(c)
    cid17=await setup(f"tg:d17-{RUN}"); conv17=await newconv(cid17)
    settings.gate_e_canary_customer_ids=f"{settings.gate_e_canary_customer_ids},{cid17}"
    await flow.propose_draft(customer_id=cid17,conversation_id=conv17,channel='telegram_customer',proposed={"sku":"SPOUT","quantity":5,"customer_name":"H","phone":"0900001234","address":"1 A"},verified=True,addr_fp=None,verified_resolution_id=None,address_changed=True)
    n17=await norders(cid17)
    r17=await flow.try_server_commit(customer_id=cid17,conversation_id=conv17,channel='telegram_customer',actor_id=f'tg:d17-{RUN}',provider_message_id=f'tg:{RUN}17')
    ck("D17 business reject (het hang) -> 0 order + REJECTED", await norders(cid17)==n17 and await laststate(cid17)=="REJECTED", str(r17))

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool(); sys.exit(1 if FAILS else 0)
asyncio.run(main())
