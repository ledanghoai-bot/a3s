"""Full-conversation harness qua handle_message (CA Amendment 224 §10) — mock LLM deterministic.
Chung minh duong ORCHESTRATOR that (khong goi gateway truc tiep nhu flow_e2e):
 H1 (case 1)  incomplete -> LLM hoi lai, 0 order, 0 intent committed
 H2 (case 5+7+14) don du -> commit 1 lan; luot xac nhan (LLM goi create_order LAI, message KHAC) -> 0 don moi
 H3 (case 20) Gate E pilot (m1=False) -> command bus commit + deterministic receipt
"""
import asyncio, sys, json, types, time
RUN=str(int(time.time()))  # duy nhat moi run -> customer/message tuoi, tranh idempotency collision cross-run
from app.config import settings
from app.db_pool import acquire, release, close_pool
from app.services import orchestrator
from app.services.command import order_intent as oi, order_intent_service as svc, order_intent_flow as flow

FAILS=[]
def ck(n,c): print(f"  [{'PASS' if c else 'FAIL'}] {n}"); (FAILS.append(n) if not c else None)

# ---- mock LLM: hang doi phan hoi scripted, moi phan tu la tool_calls HOAC text ----
_SCRIPT=[]  # list cua dict: {"tools":[{"name","args"}]} hoac {"text": "..."}
def _mk_msg(item):
    tcs=None
    if item.get("tools"):
        tcs=[]
        for i,t in enumerate(item["tools"]):
            fn=types.SimpleNamespace(name=t["name"], arguments=json.dumps(t["args"], ensure_ascii=False))
            tcs.append(types.SimpleNamespace(id=f"call_{i}", function=fn))
    return types.SimpleNamespace(content=item.get("text"), tool_calls=tcs)
async def _fake_llm(client, **kwargs):
    item=_SCRIPT.pop(0) if _SCRIPT else {"text":"..."}
    choice=types.SimpleNamespace(message=_mk_msg(item),
        finish_reason=("tool_calls" if item.get("tools") else "stop"))
    return types.SimpleNamespace(choices=[choice],
        usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=5))
orchestrator._llm_create=_fake_llm

ORD={"sku":"SPH","quantity":1,"customer_name":"Hoa","phone":"0900001234","address":"12 Le Loi, Buon Ma Thuot"}

async def n_orders(cid):
    conn=await acquire()
    try: return await conn.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1",cid)
    finally: await release(conn)

async def setup_customer(psid):
    conn=await acquire()
    try:
        await conn.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPH','x',500,1000) ON CONFLICT(sku) DO UPDATE SET stock=500")
        cid=await conn.fetchval("SELECT id FROM customers WHERE psid=$1",psid) or \
            await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'Hoa','0900001234') RETURNING id",psid)
        return cid
    finally: await release(conn)

async def main():
    global _SCRIPT
    settings.enable_address_resolver=False  # co lap intent machinery (dia chi da co test rieng)
    settings.enable_gate_e_order_wiring=False
    settings.enable_nlu_router=False

    # H1 — incomplete -> hoi lai, 0 order
    settings.m1_reliable_order_command=True
    cid=await setup_customer(f"tg:h1-{RUN}"); n0=await n_orders(cid)
    _SCRIPT.clear(); _SCRIPT.append({"text":"Dạ cho em xin địa chỉ giao và số điện thoại ạ."})
    await orchestrator.handle_message(f"tg:h1-{RUN}","cho mình 1 gói",channel="telegram_customer",provider_message_id=f"h1m1-{RUN}")
    ck("H1 incomplete -> 0 order", await n_orders(cid)==n0)

    # H2 — don du: turn1 commit; turn2 xac nhan (create_order LAI, message khac) -> 0 don moi (case 5+7+14)
    cid=await setup_customer(f"tg:h2-{RUN}"); n0=await n_orders(cid)
    _SCRIPT.clear()
    _SCRIPT+=[{"tools":[{"name":"create_order","args":ORD}]}, {"text":"Đã tạo đơn cho anh/chị."}]  # turn1
    await orchestrator.handle_message(f"tg:h2-{RUN}","đặt 1 gói giao 12 Le Loi BMT, 0900001234, Hoa",
                                      channel="telegram_customer",provider_message_id=f"h2m1-{RUN}")
    n1=await n_orders(cid); ck("H2 turn1 -> +1 order", n1==n0+1)
    _SCRIPT.clear()
    _SCRIPT+=[{"tools":[{"name":"create_order","args":ORD}]}, {"text":"Đơn của anh/chị đã được xác nhận."}]  # turn2 confirm
    await orchestrator.handle_message(f"tg:h2-{RUN}","ok xác nhận đơn nha",
                                      channel="telegram_customer",provider_message_id=f"h2m2-{RUN}")
    n2=await n_orders(cid); ck("H2 turn2 xac nhan (create_order lai, msg khac) -> KHONG don moi (case 7/14)", n2==n1)

    # H3 — Gate E pilot khi m1=False (case 20): command bus commit + verified-address binding + deterministic
    # receipt. Bat resolver + pilot scope + dia chi verify duoc (Ea Kao/Dak Lak da proven auto_verified).
    settings.m1_reliable_order_command=False
    settings.enable_gate_e_order_wiring=True
    settings.enable_address_resolver=True
    cid=await setup_customer(f"tg:h3-{RUN}"); n0=await n_orders(cid)
    settings.gate_e_canary_customer_ids=str(cid)          # _gate_e_scope_ids() doc settings live
    settings.address_resolver_pilot_customer_ids=str(cid)  # _pilot_scope() doc settings live
    ORD3=dict(ORD, address="123 duong X, Phuong Ea Kao, Dak Lak",
              province="Tỉnh Đắk Lắk", ward="Phường Ea Kao")
    _SCRIPT.clear()
    _SCRIPT+=[{"tools":[{"name":"create_order","args":ORD3}]}, {"text":"Đã tạo đơn."}]
    await orchestrator.handle_message(f"tg:h3-{RUN}","đặt 1 gói giao Phường Ea Kao Đắk Lắk 0900001234 Hoa",
                                      channel="telegram_customer",provider_message_id=f"tg:{RUN}")  # tg:<so> hop le cho verify
    n1=await n_orders(cid); ck("H3 Gate E pilot (m1=False) -> +1 order qua command bus (case 20)", n1==n0+1)
    conn=await acquire()
    try:
        snap=await conn.fetchval("SELECT count(*) FROM order_address_snapshot s JOIN orders o ON o.id=s.order_id WHERE o.customer_id=$1",cid)
        ck("H3 verified-address snapshot bound (Gate E)", snap>=1)
    finally: await release(conn)
    # verify command_executions co ban ghi (command bus that su chay)
    conn=await acquire()
    try:
        cnt=await conn.fetchval("SELECT count(*) FROM command_executions WHERE channel='telegram_customer' AND status='succeeded'")
        ck("H3 command_executions succeeded ton tai (command bus)", cnt>=1)
    finally: await release(conn)

    # H4 — duplicate provider event (case 6): CUNG provider_message_id 2 lan -> command idempotency -> 1 don
    settings.m1_reliable_order_command=True
    settings.enable_gate_e_order_wiring=False
    settings.enable_address_resolver=False
    cid=await setup_customer(f"tg:h4-{RUN}"); n0=await n_orders(cid)
    for _ in range(2):
        _SCRIPT.clear(); _SCRIPT+=[{"tools":[{"name":"create_order","args":ORD}]}, {"text":"Đã tạo đơn."}]
        await orchestrator.handle_message(f"tg:h4-{RUN}","đặt 1 gói 12 Le Loi 0900001234 Hoa",
                                          channel="telegram_customer",provider_message_id=f"h4dup-{RUN}")  # CUNG id
    ck("H4 duplicate provider event -> 1 don (case 6)", await n_orders(cid)==n0+1)

    # H5 — ambiguous/unverifiable address (case 2): resolver+GateE ON, dia chi khong verify -> CLARIFY, 0 order
    settings.m1_reliable_order_command=False
    settings.enable_gate_e_order_wiring=True
    settings.enable_address_resolver=True
    cid=await setup_customer(f"tg:h5-{RUN}"); n0=await n_orders(cid)
    settings.gate_e_canary_customer_ids=str(cid); settings.address_resolver_pilot_customer_ids=str(cid)
    ORD5=dict(ORD, address="cho X, tinh Y khong ro", province="Tinh Khong Ton Tai", ward="Phuong Khong Ro")
    _SCRIPT.clear(); _SCRIPT+=[{"tools":[{"name":"create_order","args":ORD5}]}, {"text":"Anh/chị cho em xin lại phường/tỉnh ạ."}]
    await orchestrator.handle_message(f"tg:h5-{RUN}","giao cho X tinh Y khong ro 0900001234 Hoa",
                                      channel="telegram_customer",provider_message_id=f"tg:9{RUN}")
    ck("H5 ambiguous address -> CLARIFY, 0 order (case 2)", await n_orders(cid)==n0)

    # H6 — CORRECTION (case 3): turn1 ambiguous -> clarify 0 order; turn2 corrected -> bind CHI resolution da sua
    settings.m1_reliable_order_command=False
    settings.enable_gate_e_order_wiring=True
    settings.enable_address_resolver=True
    cid=await setup_customer(f"tg:h6-{RUN}"); n0=await n_orders(cid)
    settings.gate_e_canary_customer_ids=str(cid); settings.address_resolver_pilot_customer_ids=str(cid)
    ORD_amb=dict(ORD, address="cho X khong ro", province="Tinh Khong Ton Tai", ward="Phuong Khong Ro")
    ORD_fix=dict(ORD, address="99 duong Y, Phuong Ea Kao, Dak Lak", province="Tỉnh Đắk Lắk", ward="Phường Ea Kao")
    _SCRIPT.clear(); _SCRIPT+=[{"tools":[{"name":"create_order","args":ORD_amb}]}, {"text":"Cho em xin lại phường ạ."}]
    await orchestrator.handle_message(f"tg:h6-{RUN}","giao cho X khong ro 0900001234 Hoa",
                                      channel="telegram_customer",provider_message_id=f"tg:6{RUN}1")
    ck("H6 turn1 ambiguous -> clarify, 0 order", await n_orders(cid)==n0)
    _SCRIPT.clear(); _SCRIPT+=[{"tools":[{"name":"create_order","args":ORD_fix}]}, {"text":"Đã tạo đơn."}]
    await orchestrator.handle_message(f"tg:h6-{RUN}","à Phường Ea Kao Đắk Lắk nha",
                                      channel="telegram_customer",provider_message_id=f"tg:6{RUN}2")
    ck("H6 turn2 corrected -> +1 order", await n_orders(cid)==n0+1)
    conn=await acquire()
    try:
        w=await conn.fetchval("SELECT s.ward_code FROM order_address_snapshot s JOIN orders o ON o.id=s.order_id WHERE o.customer_id=$1 ORDER BY s.created_at DESC LIMIT 1",cid)
        ck("H6 snapshot bind CHI resolution da sua (ward 24169 Ea Kao, KHONG ke thua ambiguous) (case 3)", w=='24169')
    finally: await release(conn)

    # H7 — TG vs Messenger identity KHONG cross-use (case 19): cung fingerprint, 2 khach/2 kenh -> intent PHAN BIET
    convA=None; convB=None
    conn=await acquire()
    try:
        cidA=await conn.fetchval("SELECT id FROM customers WHERE psid=$1",f"tg:19a-{RUN}") or \
             await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'A','0900000010') RETURNING id",f"tg:19a-{RUN}")
        cidB=await conn.fetchval("SELECT id FROM customers WHERE psid=$1",f"msg19b-{RUN}") or \
             await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'B','0900000011') RETURNING id",f"msg19b-{RUN}")
        convA=await conn.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cidA)
        convB=await conn.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cidB)
    finally: await release(conn)
    fp19=oi.order_fingerprint(sku='SPH',quantity=1,customer_name='X',phone='0900000010',address_fp='shared')
    rA=await flow.resolve_or_create(customer_id=cidA,conversation_id=convA,channel='telegram_customer',order_fp=fp19)
    rB=await flow.resolve_or_create(customer_id=cidB,conversation_id=convB,channel='messenger',order_fp=fp19)
    iA=rA.get('order_intent_id'); iB=rB.get('order_intent_id')
    ck("H7 cung fingerprint 2 khach/kenh -> intent PHAN BIET (khong cross-use) (case 19)", iA is not None and iB is not None and iA!=iB)
    conn=await acquire()
    try:
        row=await conn.fetch("SELECT id,customer_id,channel FROM order_intents WHERE id=ANY($1::uuid[])",[iA,iB])
        m={str(r['id']):(r['customer_id'],r['channel']) for r in row}
        ck("H7 IA=(cidA,telegram) IB=(cidB,messenger)", m.get(iA)==(cidA,'telegram_customer') and m.get(iB)==(cidB,'messenger'))
    finally: await release(conn)

    # H8 — interruption unknown -> RETRYING -> recover, KHONG dup (case 9)
    conn=await acquire()
    try:
        await conn.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SPH','x',500,1000) ON CONFLICT(sku) DO UPDATE SET stock=GREATEST(products.stock,500)")
        cid9=await conn.fetchval("SELECT id FROM customers WHERE psid=$1",f"tg:h9c-{RUN}") or \
             await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'R','0900000012') RETURNING id",f"tg:h9c-{RUN}")
        conv9=await conn.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cid9)
        async def _mk_order():
            oid=await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,shipping_name,shipping_phone,shipping_address) VALUES($1,'new',1000,'R','0900000012','x') RETURNING id",cid9)
            return oid
        async with conn.transaction():
            it=await svc.create_intent(conn,customer_id=cid9,conversation_id=conv9,channel='telegram_customer')
            r=await svc.transition(conn,it['id'],expected_version=0,to_state='ADDRESS_CHECK',order_fingerprint='FP-RETRY')
            r=await svc.transition(conn,it['id'],expected_version=r['state_version'],to_state='READY_TO_COMMIT')
            r=await svc.transition(conn,it['id'],expected_version=r['state_version'],to_state='COMMITTING')
            await svc.transition(conn,it['id'],expected_version=r['state_version'],to_state='RETRYING')  # transient unknown
        n_before=await conn.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1",cid9)
        async with conn.transaction():
            oid,dup=await svc.commit_via_intent(conn,it['id'],do_create=_mk_order)  # RETRYING->COMMITTING->commit
        ck("H8 RETRYING recover -> commit (not dup)", oid is not None and dup is False)
        async with conn.transaction():
            oid2,dup2=await svc.commit_via_intent(conn,it['id'],do_create=_mk_order)  # da COMMITTED
        ck("H8 retry lai (committed) -> duplicate zero mutation", dup2 is True and oid2==oid)
        n_final=await conn.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1",cid9)
        ck("H8 CHI 1 don (RETRYING khong nhan doi) (case 9)", n_final==n_before+1)
    finally: await release(conn)

    # H9 — abandoned open intent -> EXPIRED; request sau tao intent MOI (case 13)
    conn=await acquire()
    try:
        cid13=await conn.fetchval("SELECT id FROM customers WHERE psid=$1",f"tg:h13c-{RUN}") or \
              await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'E','0900000013') RETURNING id",f"tg:h13c-{RUN}")
        conv13=await conn.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id",cid13)
    finally: await release(conn)
    fp13=oi.order_fingerprint(sku='SPH',quantity=1,customer_name='E',phone='0900000013',address_fp='ab13')
    r1=await flow.resolve_or_create(customer_id=cid13,conversation_id=conv13,channel='telegram_customer',order_fp=fp13)
    i1=r1.get('order_intent_id')
    conn=await acquire()
    try:  # simulate reaper: open intent -> EXPIRED
        cur=await conn.fetchrow("SELECT state_version FROM order_intents WHERE id=$1",i1)
        await svc.transition(conn,i1,expected_version=cur['state_version'],to_state='EXPIRED',terminal_reason='ttl')
        st=await conn.fetchval("SELECT state FROM order_intents WHERE id=$1",i1)
    finally: await release(conn)
    r2=await flow.resolve_or_create(customer_id=cid13,conversation_id=conv13,channel='telegram_customer',order_fp=fp13)
    i2=r2.get('order_intent_id')
    ck("H9 abandoned EXPIRED + request sau -> intent MOI (case 13)", st=='EXPIRED' and i2 is not None and i2!=i1)

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAIL: '+','.join(FAILS)}")
    await close_pool(); sys.exit(1 if FAILS else 0)

asyncio.run(main())
