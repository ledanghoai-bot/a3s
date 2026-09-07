import asyncio
import sys
from app.db_pool import acquire, release, close_pool
from app.services.command import order_intent_service as svc

FAILS = []
def ck(n, c): print(f"  [{'PASS' if c else 'FAIL'}] {n}"); (FAILS.append(n) if not c else None)


async def _mk_ready_intent(conn, cid, fp):
    it = await svc.create_intent(conn, customer_id=cid, conversation_id=None, channel='telegram_customer')
    await svc.transition(conn, it['id'], expected_version=0, to_state='ADDRESS_CHECK', order_fingerprint=fp)
    await svc.transition(conn, it['id'], expected_version=1, to_state='READY_TO_COMMIT',
                         verified_address_fingerprint='AF')
    return it['id']


async def _new_order(conn, cid):
    return await conn.fetchval(
        "INSERT INTO orders(customer_id,status,total_vnd,shipping_name,shipping_phone,shipping_address) "
        "VALUES($1,'new',1000,'I','0900000000','x') RETURNING id", cid)


async def _worker(intent_id, cid):
    conn = await acquire()
    try:
        async with conn.transaction():
            async def do_create():
                return await _new_order(conn, cid)
            return await svc.commit_via_intent(conn, intent_id, do_create=do_create)
    finally:
        await release(conn)


async def main():
    conn = await acquire()
    try:
        await conn.execute("INSERT INTO customers(psid,name,phone) VALUES('tg:intcommit','I','0900000000') ON CONFLICT(psid) DO NOTHING")
        cid = await conn.fetchval("SELECT id FROM customers WHERE psid='tg:intcommit'")
        # --- Sequential idempotency: cung intent, commit 2 lan -> 1 don ---
        async with conn.transaction():
            iid = await _mk_ready_intent(conn, cid, 'FP-SEQ')
        r1 = await _worker(iid, cid)
        r2 = await _worker(iid, cid)  # luot 2 (stale confirm) -> idempotent
        ck("seq: same intent -> same order (idempotent)", r1[0] == r2[0])
        ck("seq: 1st not dup, 2nd dup", r1[1] is False and r2[1] is True)
        n_seq = await conn.fetchval(
            "SELECT count(*) FROM order_intents WHERE committed_order_id=$1", r1[0])
        ck("seq: committed_order_id unique (1 intent)", n_seq == 1)
    finally:
        await release(conn)

    # --- Concurrency: 2 worker dong thoi cung intent -> 1 don (CA §10.8) ---
    conn = await acquire()
    try:
        async with conn.transaction():
            iid2 = await _mk_ready_intent(conn, cid, 'FP-CONC')
    finally:
        await release(conn)
    ra, rb = await asyncio.gather(_worker(iid2, cid), _worker(iid2, cid))
    ck("conc: both return SAME order_id", ra[0] == rb[0])
    ck("conc: exactly one dup=False", (ra[1] is False) != (rb[1] is False))
    conn = await acquire()
    try:
        committed = await conn.fetchval(
            "SELECT committed_order_id FROM order_intents WHERE id=$1", iid2)
        ck("conc: intent committed to 1 order", committed == ra[0])
        # KHONG co 2 order committed cho intent nay
        n = await conn.fetchval("SELECT count(*) FROM order_intents WHERE id=$1 AND state='COMMITTED'", iid2)
        ck("conc: intent COMMITTED once", n == 1)
    finally:
        await release(conn)

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool()
    sys.exit(1 if FAILS else 0)

asyncio.run(main())
