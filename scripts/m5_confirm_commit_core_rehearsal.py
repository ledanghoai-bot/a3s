"""CA 232 §6/DoD#10: server-side confirm->commit — READY draft + summary khop -> confirmation commit
1 order MA KHONG can model goi create_order. + DoD#13 generic-confirm ngoai context; #12 stale-summary."""
import asyncio, sys, uuid, time
RUN=str(int(time.time()))
from app.config import settings
from app.db_pool import acquire, release, close_pool
from app.services.command import order_intent as oi, order_intent_service as svc, order_intent_flow as flow

FAILS=[]
def ck(n,c,x=""): print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: '+x) if x else ''}"); (FAILS.append(n) if not c else None)

async def mk_ready_draft(cid,conv,sku='SPCC',qty=1,name='H',phone='0900007000',addr='1 A'):
    """Tao intent READY co DRAFT + order_fingerprint + summary present khop version/fingerprint."""
    ofp=oi.order_fingerprint(sku=sku,quantity=qty,customer_name=name,phone=phone,address_fp=None)
    c=await acquire()
    try:
        async with c.transaction():
            it=await svc.create_intent(c,customer_id=cid,conversation_id=conv,channel='telegram_customer')
            r=await svc.update_draft(c,it['id'],expected_version=0,sku=sku,quantity=qty,customer_name=name,phone=phone,address=addr)
            r=await svc.transition(c,it['id'],expected_version=r['state_version'],to_state='ADDRESS_CHECK',order_fingerprint=ofp)
            r=await svc.transition(c,it['id'],expected_version=r['state_version'],to_state='READY_TO_COMMIT')
            await svc.present_summary(c,it['id'],expected_version=r['state_version'],order_fingerprint=ofp)
        return str(it['id'])
    finally: await release(c)

async def n_orders(cid):
    c=await acquire()
    try: return await c.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
    finally: await release(c)
async def istate(iid):
    c=await acquire()
    try: return await c.fetchrow("SELECT state,committed_order_id FROM order_intents WHERE id=$1",iid)
    finally: await release(c)

async def main():
    settings.m1_reliable_order_command=True
    c=await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPCC','x',500,1000) ON CONFLICT(sku) DO UPDATE SET stock=500")
        cid=await c.fetchval("SELECT id FROM customers WHERE psid='tg:cc'") or await c.fetchval("INSERT INTO customers(psid,name,phone) VALUES('tg:cc','H','0900007000') RETURNING id")
        conv=await c.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cid)
    finally: await release(c)

    # DoD#10: READY draft + summary -> server commit KHONG model
    iid=await mk_ready_draft(cid,conv)
    n0=await n_orders(cid)
    r=await flow.try_server_commit(customer_id=cid,conversation_id=conv,channel='telegram_customer',actor_id='tg:cc',provider_message_id=f'tg:{RUN}1')
    ck("DoD#10 server commit tu draft (KHONG model create_order)", r is not None and r.get('order_id') is not None, str(r.get('order_id') if r else None))
    ck("DoD#10 +1 order", await n_orders(cid)==n0+1)
    st=await istate(iid); ck("DoD#10 intent COMMITTED", st and st['state']=='COMMITTED' and st['committed_order_id']==r.get('order_id'))

    # DoD#11: xac nhan lai (redelivered) -> 1 order + same receipt (duplicate)
    r2=await flow.try_server_commit(customer_id=cid,conversation_id=conv,channel='telegram_customer',actor_id='tg:cc',provider_message_id=f'tg:{RUN}2')
    # intent da COMMITTED -> find_open_intent None -> try_server_commit tra None (khong con open) -> khong don moi
    ck("DoD#11 confirm lai sau commit -> khong don moi", await n_orders(cid)==n0+1 and r2 is None)

    # DoD#12: stale-summary sau correction -> KHONG commit. Tao draft READY, present summary, roi update_draft
    # (doi field -> version tang -> summary cu stale) -> try_server_commit KHONG duoc commit.
    c=await acquire()
    try: conv2=await c.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cid)
    finally: await release(c)
    iid2=await mk_ready_draft(cid,conv2)
    n1=await n_orders(cid)
    c=await acquire()
    try:  # correction: doi qty -> version tang -> summary_version != state_version
        cur=await c.fetchval("SELECT state_version FROM order_intents WHERE id=$1",iid2)
        await svc.update_draft(c,iid2,expected_version=cur,quantity=9)
    finally: await release(c)
    r3=await flow.try_server_commit(customer_id=cid,conversation_id=conv2,channel='telegram_customer',actor_id='tg:cc',provider_message_id=f'tg:{RUN}3')
    ck("DoD#12 stale-summary sau correction -> KHONG commit", r3 is None and await n_orders(cid)==n1)

    # DoD (guard): draft chua du field -> KHONG commit
    conv3=None
    c=await acquire()
    try: conv3=await c.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cid)
    finally: await release(c)
    c=await acquire()
    try:
        async with c.transaction():
            it=await svc.create_intent(c,customer_id=cid,conversation_id=conv3,channel='telegram_customer')
            await svc.update_draft(c,it['id'],expected_version=0,sku='SPCC',quantity=1)  # thieu name/phone/addr
    finally: await release(c)
    r4=await flow.try_server_commit(customer_id=cid,conversation_id=conv3,channel='telegram_customer',actor_id='tg:cc',provider_message_id=f'tg:{RUN}4')
    ck("guard draft chua du field -> KHONG commit", r4 is None)

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool(); sys.exit(1 if FAILS else 0)

asyncio.run(main())
