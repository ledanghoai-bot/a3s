"""CA 232: propose_draft (accumulate + advance + summary, KHONG commit) -> try_server_commit (confirm).
Tai hien c Tien: model de xuat field qua cac luot, KHONG commit; server chot khi confirm."""
import asyncio, sys, time
RUN=str(int(time.time()))
from app.config import settings
from app.db_pool import acquire, release, close_pool
from app.services.command import order_intent_flow as flow, order_intent_service as svc

FAILS=[]
def ck(n,c,x=""): print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: '+x) if x else ''}"); (FAILS.append(n) if not c else None)

async def q1(sql,*a):
    c=await acquire()
    try: return await c.fetchval(sql,*a)
    finally: await release(c)
async def istate(cid,conv):
    c=await acquire()
    try:
        r=await c.fetchrow("SELECT state,state_version,draft_sku,draft_address,summary_version FROM order_intents WHERE customer_id=$1 AND conversation_id=$2 ORDER BY created_at DESC LIMIT 1",cid,conv)
        return dict(r) if r else None
    finally: await release(c)

async def main():
    settings.m1_reliable_order_command=True
    c=await acquire()
    try:
        await c.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPP','x',500,1000) ON CONFLICT(sku) DO UPDATE SET stock=500")
        cid=await c.fetchval("SELECT id FROM customers WHERE psid='tg:pp'") or await c.fetchval("INSERT INTO customers(psid,name,phone) VALUES('tg:pp','H','0900008000') RETURNING id")
        conv=await c.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cid)
    finally: await release(c)
    n0=await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)

    # Luot 1: model de xuat 1 phan (sku+qty, thieu contact/address) -> need_more
    r=await flow.propose_draft(customer_id=cid,conversation_id=conv,channel='telegram_customer',
        proposed={"sku":"SPP","quantity":2}, verified=False, addr_fp=None, verified_resolution_id=None, address_changed=False)
    ck("L1 thieu field -> need_more", r["action"]=="need_more", str(r.get("missing")))
    ck("L1 0 order", await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)==n0)
    st=await istate(cid,conv); ck("L1 state COLLECTING + draft_sku luu", st and st["state"]=="COLLECTING" and st["draft_sku"]=="SPP")

    # Luot 2: bo sung contact + address (verified) -> ready + summary
    r=await flow.propose_draft(customer_id=cid,conversation_id=conv,channel='telegram_customer',
        proposed={"customer_name":"c Tien","phone":"0945303009","address":"03 Truong Quang Tuan, Tan Lap"},
        verified=True, addr_fp=None, verified_resolution_id=None, address_changed=True)
    ck("L2 du field + verified -> ready", r["action"]=="ready", str(r.get("draft")))
    ck("L2 VAN 0 order (chua commit)", await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)==n0)
    st=await istate(cid,conv); ck("L2 READY + summary present", st and st["state"]=="READY_TO_COMMIT" and st["summary_version"]==st["state_version"])

    # Luot 3: khach XAC NHAN -> server commit (KHONG model create_order)
    rc=await flow.try_server_commit(customer_id=cid,conversation_id=conv,channel='telegram_customer',actor_id='tg:pp',provider_message_id=f'tg:{RUN}3')
    ck("L3 confirm -> SERVER commit (khong model)", rc is not None and rc.get("order_id") is not None, str(rc.get("order_id") if rc else None))
    ck("L3 +1 order", await q1("SELECT count(*) FROM orders WHERE customer_id=$1",cid)==n0+1)
    st=await istate(cid,conv); ck("L3 intent COMMITTED", st and st["state"]=="COMMITTED")
    # kiem tra order dung noi dung draft
    o=await q1("SELECT shipping_name FROM orders WHERE customer_id=$1 ORDER BY id DESC LIMIT 1",cid)
    ck("L3 order dung ten draft (c Tien)", o=="c Tien", str(o))

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool(); sys.exit(1 if FAILS else 0)

asyncio.run(main())
