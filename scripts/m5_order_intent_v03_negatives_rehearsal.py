"""CA 226-01/02 service/DB-tx tests: committed-replay identity/ownership negatives (khong lo receipt);
business rejection -> COMMITTING->REJECTED, command-row final, zero partial mutation."""
import asyncio, sys, uuid, time
RUN=str(int(time.time()))
from app.config import settings
from app.db_pool import acquire, release, close_pool
from app.services.command import order_gateway, order_intent as oi, order_intent_service as svc

FAILS=[]
def ck(n,c,x=""): print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: '+x) if x else ''}"); (FAILS.append(n) if not c else None)

async def mk_ready(cid,conv,ofp,ch='telegram_customer',afp=None,res=None):
    c=await acquire()
    try:
        async with c.transaction():
            it=await svc.create_intent(c,customer_id=cid,conversation_id=conv,channel=ch)
            r=await svc.transition(c,it['id'],expected_version=0,to_state='ADDRESS_CHECK',order_fingerprint=ofp,verified_address_fingerprint=afp,verified_resolution_id=res)
            await svc.transition(c,it['id'],expected_version=r['state_version'],to_state='READY_TO_COMMIT')
        return str(it['id'])
    finally: await release(c)

async def call(psid,iid,conv,ch="telegram_customer",sku="SPX3",qty=1,name="H",phone="0900005000"):
    return await order_gateway.create_order_command(channel=ch,actor_type="customer",actor_id=psid,
        idempotency_key=None,provider_message_id=f"v-{uuid.uuid4().hex[:8]}",psid=psid,conversation_id=conv,
        order_intent_id=iid,customer_name=name,phone=phone,address="1 A",sku=sku,quantity=qty)

async def orders():
    c=await acquire()
    try: return await c.fetchval("SELECT count(*) FROM orders")
    finally: await release(c)
async def intent_state(iid):
    c=await acquire()
    try: return await c.fetchval("SELECT state FROM order_intents WHERE id=$1",iid)
    finally: await release(c)

async def main():
    settings.m1_reliable_order_command=True
    c=await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPX3','x',5,1000) ON CONFLICT(sku) DO UPDATE SET stock=5")
        cidA=await c.fetchval("SELECT id FROM customers WHERE psid=$1",f"tg:vA-{RUN}") or await c.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'A','0900005000') RETURNING id",f"tg:vA-{RUN}")
        cidB=await c.fetchval("SELECT id FROM customers WHERE psid=$1",f"tg:vB-{RUN}") or await c.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'B','0900005001') RETURNING id",f"tg:vB-{RUN}")
        convA=await c.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cidA)
        convB=await c.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cidB)
    finally: await release(c)
    ofpA=oi.order_fingerprint(sku='SPX3',quantity=1,customer_name='H',phone='0900005000',address_fp=None)

    # --- 226-01: COMMIT 1 don cua A, roi thu replay voi danh tinh SAI -> reject, KHONG lo receipt ---
    iA=await mk_ready(cidA,convA,ofpA)
    g=await call(f"tg:vA-{RUN}",iA,convA); oidA=g.get("order_id"); ck("setup commit A",oidA is not None)
    # N1 owner mismatch (psid B, intent A committed)
    r=await call(f"tg:vB-{RUN}",iA,convB); ck("226-01 N1 owner mismatch -> reject, KHONG lo receipt A",bool(r.get("error")) and r.get("order_id") is None)
    # N2 channel mismatch
    r=await call(f"tg:vA-{RUN}",iA,convA,ch="messenger"); ck("226-01 N2 channel mismatch -> reject",bool(r.get("error")) and r.get("order_id") is None)
    # N3 conversation mismatch
    r=await call(f"tg:vA-{RUN}",iA,convB); ck("226-01 N3 conversation mismatch -> reject",bool(r.get("error")) and r.get("order_id") is None)
    # N4 fingerprint mismatch (qty khac)
    r=await call(f"tg:vA-{RUN}",iA,convA,qty=2); ck("226-01 N4 fingerprint mismatch -> reject",bool(r.get("error")) and r.get("order_id") is None)
    # legit stale-confirm (dung danh tinh) -> duplicate = order cu
    r=await call(f"tg:vA-{RUN}",iA,convA); ck("226-01 legit stale-confirm -> duplicate order cu",r.get("order_id")==oidA and r.get("duplicate") is True)

    # --- 226-02: business rejection sau claim -> intent REJECTED, 0 order moi ---
    # product-not-found
    n0=await orders()
    c=await acquire()
    try: convP=await c.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cidA)
    finally: await release(c)
    ofpNF=oi.order_fingerprint(sku='NOPE',quantity=1,customer_name='H',phone='0900005000',address_fp=None)
    iNF=await mk_ready(cidA,convP,ofpNF)
    r=await call(f"tg:vA-{RUN}",iNF,convP,sku="NOPE"); ck("226-02 product-not-found -> reject",bool(r.get("error")))
    ck("226-02 intent -> REJECTED (khong treo COMMITTING)",await intent_state(iNF)=="REJECTED",await intent_state(iNF))
    # insufficient stock (stock=5, qty=99) — dung conv rieng
    c=await acquire()
    try: convS=await c.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cidA)
    finally: await release(c)
    ofpS=oi.order_fingerprint(sku='SPX3',quantity=99,customer_name='H',phone='0900005000',address_fp=None)
    iS=await mk_ready(cidA,convS,ofpS)
    r=await call(f"tg:vA-{RUN}",iS,convS,qty=99); ck("226-02 insufficient-stock -> reject",bool(r.get("error")))
    ck("226-02 intent -> REJECTED",await intent_state(iS)=="REJECTED",await intent_state(iS))
    # quantity exceeds auto limit (qty lon, khong override) — dung conv rieng
    c=await acquire()
    try:
        await c.execute("UPDATE products SET stock=100000 WHERE sku='SPX3'")
        convQ=await c.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cidA)
    finally: await release(c)
    from app.services.tools import MAX_AUTO_QUANTITY
    bigq=MAX_AUTO_QUANTITY+1
    ofpQ=oi.order_fingerprint(sku='SPX3',quantity=bigq,customer_name='H',phone='0900005000',address_fp=None)
    iQ=await mk_ready(cidA,convQ,ofpQ)
    r=await call(f"tg:vA-{RUN}",iQ,convQ,qty=bigq); ck("226-02 qty-exceeds -> reject",bool(r.get("error")))
    ck("226-02 intent -> REJECTED",await intent_state(iQ)=="REJECTED",await intent_state(iQ))
    ck("226-02 ZERO order moi tu 3 business reject",await orders()==n0,f"n0={n0} now={await orders()}")

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool(); sys.exit(1 if FAILS else 0)

asyncio.run(main())
