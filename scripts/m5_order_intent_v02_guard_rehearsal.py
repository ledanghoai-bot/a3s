"""CA 225-02 fail-closed guard tests: commit attempted voi intent missing/owner-mismatch/channel-mismatch/
conv-mismatch/disallowed-state/fingerprint-mismatch -> ZERO mutation (0 order), reject."""
import asyncio, sys, uuid, time
RUN=str(int(time.time()))
from app.config import settings
from app.db_pool import acquire, release, close_pool
from app.services.command import order_gateway, order_intent as oi, order_intent_service as svc

FAILS=[]
def ck(n,c,x=""): print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: '+x) if x else ''}"); (FAILS.append(n) if not c else None)

async def call(psid,intent_id,conv,channel="telegram_customer",addr_fp=None,res_id=None,**over):
    a=dict(customer_name="H",phone="0900003000",address="1 A",sku="SPG",quantity=1)
    a.update(over)
    return await order_gateway.create_order_command(
        channel=channel,actor_type="customer",actor_id=psid,idempotency_key=None,
        provider_message_id=f"g-{uuid.uuid4().hex[:8]}",psid=psid,conversation_id=conv,
        order_intent_id=intent_id,verified_address_fingerprint=addr_fp,verified_resolution_id=res_id,**a)

async def main():
    settings.m1_reliable_order_command=True
    conn=await acquire()
    try:
        await conn.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPG','x',500,1000) ON CONFLICT(sku) DO UPDATE SET stock=500")
        cidA=await conn.fetchval("SELECT id FROM customers WHERE psid=$1",f"tg:gA-{RUN}") or \
             await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'A','0900003000') RETURNING id",f"tg:gA-{RUN}")
        cidB=await conn.fetchval("SELECT id FROM customers WHERE psid=$1",f"tg:gB-{RUN}") or \
             await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'B','0900003001') RETURNING id",f"tg:gB-{RUN}")
        convA=await conn.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cidA)
        convB=await conn.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cidB)
        # helper tao intent READY cho cidA/convA voi fingerprint chuan
        good_ofp=oi.order_fingerprint(sku='SPG',quantity=1,customer_name='H',phone='0900003000',address_fp=None)
        n0=await conn.fetchval("SELECT count(*) FROM orders")
    finally:
        await release(conn)

    async def mk(state,cust=cidA,ofp=good_ofp,afp=None,res=None,ch='telegram_customer'):
        """Tao intent o `state` voi conversation RIENG (index one-open-per-conversation). Tra (id, conv)."""
        c=await acquire()
        try:
            conv=await c.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cust)
            async with c.transaction():
                it=await svc.create_intent(c,customer_id=cust,conversation_id=conv,channel=ch)
                if state!='COLLECTING':
                    r=await svc.transition(c,it['id'],expected_version=0,to_state='ADDRESS_CHECK',order_fingerprint=ofp,verified_address_fingerprint=afp,verified_resolution_id=res)
                    if state=='READY_TO_COMMIT':
                        await svc.transition(c,it['id'],expected_version=r['state_version'],to_state='READY_TO_COMMIT')
                    elif state=='NEEDS_CLARIFICATION':
                        await svc.transition(c,it['id'],expected_version=r['state_version'],to_state='NEEDS_CLARIFICATION')
            return str(it['id']),conv
        finally:
            await release(c)

    async def orders():
        c=await acquire()
        try: return await c.fetchval("SELECT count(*) FROM orders")
        finally: await release(c)

    # G1 missing intent
    r=await call(f"tg:gA-{RUN}",str(uuid.uuid4()),convA); ck("G1 missing intent -> reject",bool(r.get("error")),str(r.get("error_code")))
    # G2 owner mismatch (intent cua cidB, psid=cidA)
    iB,cvB=await mk('READY_TO_COMMIT',cust=cidB); r=await call(f"tg:gA-{RUN}",iB,cvB); ck("G2 owner mismatch -> reject",bool(r.get("error")))
    # G3 channel mismatch (intent messenger, call telegram)
    iCh,cvCh=await mk('READY_TO_COMMIT',ch='messenger'); r=await call(f"tg:gA-{RUN}",iCh,cvCh,channel="telegram_customer"); ck("G3 channel mismatch -> reject",bool(r.get("error")))
    # G4 conversation mismatch (intent o cvC, call voi convB khac)
    iC,cvC=await mk('READY_TO_COMMIT'); r=await call(f"tg:gA-{RUN}",iC,convB); ck("G4 conversation mismatch -> reject",bool(r.get("error")))
    # G5 disallowed states (moi cai conv rieng)
    for stt in ('COLLECTING','ADDRESS_CHECK','NEEDS_CLARIFICATION'):
        i,cv=await mk(stt); r=await call(f"tg:gA-{RUN}",i,cv); ck(f"G5 state {stt} not committable -> reject",bool(r.get("error")))
    # G6 order_fingerprint mismatch (intent co ofp bogus)
    iF,cvF=await mk('READY_TO_COMMIT',ofp='BOGUS-FP'); r=await call(f"tg:gA-{RUN}",iF,cvF); ck("G6 order_fingerprint mismatch -> reject",bool(r.get("error")))
    # G7 addr_fingerprint mismatch (intent afp='X', call afp='Y')
    iA,cvA2=await mk('READY_TO_COMMIT',ofp=oi.order_fingerprint(sku='SPG',quantity=1,customer_name='H',phone='0900003000',address_fp='Y'),afp='X')
    r=await call(f"tg:gA-{RUN}",iA,cvA2,addr_fp='Y'); ck("G7 addr_fingerprint mismatch -> reject",bool(r.get("error")))
    n_after=await orders()
    ck("ZERO mutation: 0 order tao tu moi guard",n_after==n0,f"before={n0} after={n_after}")

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool(); sys.exit(1 if FAILS else 0)

asyncio.run(main())
