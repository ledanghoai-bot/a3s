import asyncio, sys, uuid
from app.config import settings
from app.db_pool import acquire, release, close_pool
from app.services.command import order_gateway, order_intent as oi, order_intent_flow as flow

FAILS=[]
def ck(n,c): print(f"  [{'PASS' if c else 'FAIL'}] {n}"); (FAILS.append(n) if not c else None)

async def main():
    settings.m1_reliable_order_command=True
    conn=await acquire()
    try:
        await conn.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPF','x',100,1000) ON CONFLICT(sku) DO UPDATE SET stock=100")
        cid=await conn.fetchval("SELECT id FROM customers WHERE psid='tg:flow'") or \
            await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES('tg:flow','I','0900000001') RETURNING id")
        conv=await conn.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cid)  # conversation THAT (FK)
    finally:
        await release(conn)
    fpA=oi.order_fingerprint(sku='SPF',quantity=1,customer_name='I',phone='0900000001',address_fp='addrA')
    fpB=oi.order_fingerprint(sku='SPF',quantity=2,customer_name='I',phone='0900000001',address_fp='addrA')

    # A) tao intent moi
    r1=await flow.resolve_or_create(customer_id=cid,conversation_id=conv,channel='telegram_customer',order_fp=fpA,addr_fp='addrA')
    i1=r1.get('order_intent_id'); ck("A tao intent moi", i1 is not None)
    # A') cung fp -> REUSE cung intent (open anchor §5)
    r2=await flow.resolve_or_create(customer_id=cid,conversation_id=conv,channel='telegram_customer',order_fp=fpA,addr_fp='addrA')
    ck("A' cung fp -> REUSE cung intent (open)", r2.get('order_intent_id')==i1)
    # B) fp khac -> intent MOI
    rB=await flow.resolve_or_create(customer_id=cid,conversation_id=conv,channel='telegram_customer',order_fp=fpB,addr_fp='addrA')
    ck("B fp khac -> intent MOI", rB.get('order_intent_id') not in (None,i1))

    # C) commit intent i1 qua gateway (order_intent_id=i1) -> 1 don + mark pointer
    g1=await order_gateway.create_order_command(channel='telegram_customer',actor_type='customer',actor_id='tg:flow',
        idempotency_key=None,provider_message_id=f'm1-{conv}',customer_name='I',phone='0900000001',address='1 A',
        sku='SPF',quantity=1,psid='tg:flow',order_intent_id=i1)
    oid=g1.get('order_id'); ck("C commit i1 -> order", oid is not None)
    await flow.mark_committed_pointer(conversation_id=conv,intent_id=i1,order_fp=fpA,order_id=oid)

    conn=await acquire()
    try:
        n_after=await conn.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
    finally:
        await release(conn)

    # D) STALE-CONFIRM sau commit: cung fp, khong con open intent (i1 COMMITTED) -> tra i1 (stale_confirm)
    rS=await flow.resolve_or_create(customer_id=cid,conversation_id=conv,channel='telegram_customer',order_fp=fpA,addr_fp='addrA')
    ck("D stale-confirm -> tra lai i1", rS.get('order_intent_id')==i1)
    ck("D stale_confirm flag", rS.get('stale_confirm') is True)
    # D') gateway voi i1 lan 2 (stale) -> duplicate, KHONG don moi
    g2=await order_gateway.create_order_command(channel='telegram_customer',actor_type='customer',actor_id='tg:flow',
        idempotency_key=None,provider_message_id=f'm2-{conv}',customer_name='I',phone='0900000001',address='1 A',
        sku='SPF',quantity=1,psid='tg:flow',order_intent_id=i1)
    ck("D' stale commit -> duplicate same order", g2.get('order_id')==oid and g2.get('duplicate') is True)

    # E) EXPLICIT second identical order (§7.5) -> intent MOI (bo qua stale-confirm) -> don thu 2 that
    rE=await flow.resolve_or_create(customer_id=cid,conversation_id=conv,channel='telegram_customer',order_fp=fpA,addr_fp='addrA',explicit_new_order=True)
    iE=rE.get('order_intent_id'); ck("E explicit new -> intent MOI (khac i1)", iE not in (None,i1))
    gE=await order_gateway.create_order_command(channel='telegram_customer',actor_type='customer',actor_id='tg:flow',
        idempotency_key=None,provider_message_id=f'm3-{conv}',customer_name='I',phone='0900000001',address='1 A',
        sku='SPF',quantity=1,psid='tg:flow',order_intent_id=iE)
    ck("E explicit new -> don thu 2 THAT (khac oid)", gE.get('order_id') not in (None,oid))

    conn=await acquire()
    try:
        n_final=await conn.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
        # sau commit i1: n_after; stale-confirm KHONG tang; explicit new +1
        ck("stale-confirm KHONG tao don (count giu)", n_final==n_after+1)  # +1 = don explicit E
    finally:
        await release(conn)
    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool(); sys.exit(1 if FAILS else 0)

asyncio.run(main())
