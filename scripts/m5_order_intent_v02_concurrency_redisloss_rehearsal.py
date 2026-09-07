"""CA 225 §4.5/4.7: same-intent concurrency (production _run_winner FOR UPDATE) -> 1 order/command-row
final; Redis-loss/flush khong doi duplicate semantics (drive() DB-authoritative, khong Redis pointer)."""
import asyncio, sys, uuid, time
RUN=str(int(time.time()))
from app.config import settings
from app.db_pool import acquire, release, close_pool
from app.services.command import order_gateway, order_intent as oi, order_intent_service as svc

FAILS=[]
def ck(n,c,x=""): print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: '+x) if x else ''}"); (FAILS.append(n) if not c else None)

async def main():
    settings.m1_reliable_order_command=True
    conn=await acquire()
    try:
        await conn.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPC','x',500,1000) ON CONFLICT(sku) DO UPDATE SET stock=500")
        cid=await conn.fetchval("SELECT id FROM customers WHERE psid=$1",f"tg:cc-{RUN}") or \
            await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'C','0900004000') RETURNING id",f"tg:cc-{RUN}")
        conv=await conn.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cid)
        ofp=oi.order_fingerprint(sku='SPC',quantity=1,customer_name='C',phone='0900004000',address_fp=None)
        async with conn.transaction():
            it=await svc.create_intent(conn,customer_id=cid,conversation_id=conv,channel='telegram_customer')
            r=await svc.transition(conn,it['id'],expected_version=0,to_state='ADDRESS_CHECK',order_fingerprint=ofp)
            await svc.transition(conn,it['id'],expected_version=r['state_version'],to_state='READY_TO_COMMIT')
        iid=str(it['id'])
        n0=await conn.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
    finally:
        await release(conn)

    async def fire(msg):
        return await order_gateway.create_order_command(
            channel='telegram_customer',actor_type='customer',actor_id=f"tg:cc-{RUN}",idempotency_key=None,
            provider_message_id=msg,psid=f"tg:cc-{RUN}",conversation_id=conv,order_intent_id=iid,
            customer_name='C',phone='0900004000',address='1 A',sku='SPC',quantity=1)

    # C1 CONCURRENT 2 worker cung intent (msg khac) -> 1 order
    r1,r2=await asyncio.gather(fire(f"m1-{RUN}"),fire(f"m2-{RUN}"))
    oids={x.get("order_id") for x in (r1,r2) if x.get("order_id")}
    conn=await acquire()
    try:
        n1=await conn.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
        st=await conn.fetchrow("SELECT state,committed_order_id FROM order_intents WHERE id=$1",iid)
        proc=await conn.fetchval("SELECT count(*) FROM command_executions WHERE status='processing'")
    finally:
        await release(conn)
    ck("C1 concurrent -> CHI 1 order",n1==n0+1,f"n0={n0} n1={n1}")
    ck("C1 ca 2 tra cung order_id",len(oids)==1,str(oids))
    ck("C1 intent COMMITTED 1 order",st and st["state"]=="COMMITTED" and st["committed_order_id"] in oids)
    ck("C1 command-row final: khong 'processing' mo coi (225-03)",proc==0,f"processing={proc}")

    # C2 REDIS-LOSS: flush Redis roi stale-confirm cung fingerprint -> duplicate (DB-authoritative), 0 don moi
    import redis.asyncio as aioredis
    rc=await aioredis.from_url(settings.redis_url,decode_responses=True); await rc.flushall(); await rc.aclose()
    r3=await fire(f"m3-{RUN}")  # msg khac, intent da COMMITTED -> duplicate
    conn=await acquire()
    try:
        n2=await conn.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
    finally:
        await release(conn)
    ck("C2 Redis-loss stale-confirm -> duplicate, 0 don moi (225-04)",n2==n1 and r3.get("duplicate") is True,f"n1={n1} n2={n2} dup={r3.get('duplicate')}")

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool(); sys.exit(1 if FAILS else 0)

asyncio.run(main())
