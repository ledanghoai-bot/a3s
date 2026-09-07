import asyncio, sys
from app.config import settings
from app.db_pool import acquire, release, close_pool
from app.services.command import order_gateway, order_intent_service as svc

FAILS=[]
def ck(n,c): print(f"  [{'PASS' if c else 'FAIL'}] {n}"); (FAILS.append(n) if not c else None)

async def main():
    settings.m1_reliable_order_command=True  # route command bus (khong can Gate E scope cho test nay)
    conn=await acquire()
    try:
        await conn.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPX','x',100,1000) ON CONFLICT(sku) DO UPDATE SET stock=100")
        cid=await conn.fetchval("SELECT id FROM customers WHERE psid='tg:e2e'") or \
            await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES('tg:e2e','I','0900000000') RETURNING id")
        async with conn.transaction():
            it=await svc.create_intent(conn, customer_id=cid, conversation_id=None, channel='telegram_customer')
            await svc.transition(conn,it['id'],expected_version=0,to_state='ADDRESS_CHECK',order_fingerprint='FP-E2E')
            await svc.transition(conn,it['id'],expected_version=1,to_state='READY_TO_COMMIT')
        iid=it['id']
        n0=await conn.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
    finally:
        await release(conn)

    # Luot 1: create_order voi order_intent_id, message msg1
    r1=await order_gateway.create_order_command(channel='telegram_customer',actor_type='customer',actor_id='tg:e2e',
        idempotency_key=None,provider_message_id='msg1',customer_name='I',phone='0900000000',address='12 X, P.Ea Kao, Dak Lak',
        sku='SPX',quantity=1,psid='tg:e2e',order_intent_id=iid)
    # Luot 2: CUNG intent, message KHAC msg2 (stale-confirm/redelivery) -> phai duplicate, KHONG tao don moi
    r2=await order_gateway.create_order_command(channel='telegram_customer',actor_type='customer',actor_id='tg:e2e',
        idempotency_key=None,provider_message_id='msg2',customer_name='I',phone='0900000000',address='12 X, P.Ea Kao, Dak Lak',
        sku='SPX',quantity=1,psid='tg:e2e',order_intent_id=iid)

    ck("luot1 tao order",r1.get('order_id') is not None)
    ck("luot2 SAME order_id (idempotent qua intent, message khac)",r2.get('order_id')==r1.get('order_id'))
    ck("luot2 duplicate=True",r2.get('duplicate') is True)
    conn=await acquire()
    try:
        n1=await conn.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
        ck("CHI 1 don tao (khong trung du 2 message khac)", n1==n0+1)
        st=await conn.fetchrow("SELECT state,committed_order_id FROM order_intents WHERE id=$1",iid)
        ck("intent COMMITTED -> order1", st['state']=='COMMITTED' and st['committed_order_id']==r1.get('order_id'))
    finally:
        await release(conn)
    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool(); sys.exit(1 if FAILS else 0)

asyncio.run(main())
