import asyncio
import sys
from app.db_pool import acquire, release, close_pool
from app.services.command import order_intent_service as svc

FAILS = []
def ck(n, c): print(f"  [{'PASS' if c else 'FAIL'}] {n}"); (FAILS.append(n) if not c else None)

async def main():
    conn = await acquire()
    try:
        cid = await conn.fetchval("SELECT id FROM customers WHERE psid='tg:9000001'") \
            or await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES('tg:intsvc','I','0900000000') RETURNING id")
        # create
        it = await svc.create_intent(conn, customer_id=cid, conversation_id=None, channel='telegram_customer')
        ck("create COLLECTING v0", it['state']=='COLLECTING' and it['state_version']==0)
        iid = it['id']
        # valid transition COLLECTING->ADDRESS_CHECK (v0->v1)
        r = await svc.transition(conn, iid, expected_version=0, to_state='ADDRESS_CHECK', order_fingerprint='FP1')
        ck("COLLECTING->ADDRESS_CHECK v1", r and r['state']=='ADDRESS_CHECK' and r['state_version']==1)
        # version mismatch (dung v0 lai) -> None
        r2 = await svc.transition(conn, iid, expected_version=0, to_state='READY_TO_COMMIT')
        ck("version mismatch -> None (concurrency guard)", r2 is None)
        # invalid transition ADDRESS_CHECK->COMMITTED -> None (fail-closed)
        r3 = await svc.transition(conn, iid, expected_version=1, to_state='COMMITTED')
        ck("invalid ADDRESS_CHECK->COMMITTED -> None", r3 is None)
        # ADDRESS_CHECK->READY_TO_COMMIT->COMMITTING
        r = await svc.transition(conn, iid, expected_version=1, to_state='READY_TO_COMMIT',
                                 verified_address_fingerprint='AF1')
        ck("->READY_TO_COMMIT v2", r and r['state']=='READY_TO_COMMIT' and r['state_version']==2)
        r = await svc.transition(conn, iid, expected_version=2, to_state='COMMITTING')
        ck("->COMMITTING v3", r and r['state']=='COMMITTING' and r['state_version']==3)
        # mark_committed atomic (v3) -> order 12345 (fake, no FK check? committed_order_id FK to orders!)
        oid = await conn.fetchval("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPX','x',10,1000) ON CONFLICT(sku) DO UPDATE SET stock=10 RETURNING id")
        real_order = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,shipping_name,shipping_phone,shipping_address) VALUES($1,'new',1000,'I','0900000000','x') RETURNING id", cid)
        m = await svc.mark_committed(conn, iid, expected_version=3, order_id=real_order)
        ck("mark_committed COMMITTING v3 -> COMMITTED", m and m['state']=='COMMITTED' and m['committed_order_id']==real_order)
        # mark_committed lan 2 (stale v3) -> None (at-most-once)
        m2 = await svc.mark_committed(conn, iid, expected_version=3, order_id=real_order)
        ck("2nd mark_committed stale -> None (at-most-once)", m2 is None)
        # get_intent COMMITTED
        g = await svc.get_intent(conn, iid)
        ck("get_intent COMMITTED terminal", g['state']=='COMMITTED' and g['committed_order_id']==real_order)
        # transition ra khoi COMMITTED (terminal) -> None
        rt = await svc.transition(conn, iid, expected_version=g['state_version'], to_state='COMMITTING')
        ck("terminal COMMITTED cannot reopen", rt is None)
    finally:
        await release(conn)
    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool()
    sys.exit(1 if FAILS else 0)

asyncio.run(main())
