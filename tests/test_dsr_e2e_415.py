"""CA Review 415 §3 — DSR E2E: khach DA di qua dat don (command bus that), xac minh dia chi, M7/thanh toan, GHN, ledger
M2 + du lieu dang CU con PSID tho (truoc khi sua tu nguon) -> xoa -> quet TOAN BO bang public (row::text) + Redis.

DB+Redis (skipif not M6_TEST_DB):
- 0 hit cho PSID, SDT day du, ten, dia chi chi tiet o MOI bang; so nghiep vu giu nguyen (so dong, so tien, ma hanh chinh).
- Ham DSR quyen hep: tu choi customer chua tombstone; trigger bat bien van chan UPDATE thuong; role it quyen alpha3s_app
  khong UPDATE duoc ledger nhung goi duoc ham DSR.
- Nguon moi: audit/ledger cua don bot ghi 'customer:<id>' (khong PSID).
- Race DB commit xong + Redis loi: 'redis_pending' (subject_hmac, khong PSID) -> worker retry hoac yeu cau lap -> completed.
"""
import json
import os
import random
import uuid

import pytest

from app.services import customer_identity as ci

DB = os.environ.get("M6_TEST_DB") == "1"
dbonly = pytest.mark.skipif(not DB, reason="can DB+Redis (M6_TEST_DB=1)")
KEY1 = "dsr-test-key-one-" + "a" * 32
KEY2 = "dsr-test-key-two-" + "b" * 32


@pytest.fixture(autouse=True)
def _dsr_key(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "dsr_hmac_key", KEY1)
    monkeypatch.setattr(settings, "dsr_hmac_key_previous", "")


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


async def _redis():
    import redis.asyncio as aioredis

    from app.config import settings
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def _ident():
    tag = "".join(random.choice("0123456789") for _ in range(6))
    return {
        "psid": "7" + "".join(random.choice("0123456789") for _ in range(15)),
        "name": f"Thử Nghiệm Xóa {tag}",
        "phone": "09" + "".join(random.choice("0123456789") for _ in range(8)),
        "street": f"{tag} Đường Kiểm Thử DSR",
    }


async def _full_scan(conn, needles: list[str]) -> dict:
    """Moi bang public, moi dong (row::text) — khong chon truoc kho nao."""
    tables = [r["table_name"] for r in await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")]
    hits = {}
    for t in tables:
        for nd in needles:
            n = await conn.fetchval(f'SELECT count(*) FROM public."{t}" x WHERE strpos(x::text, $1) > 0', nd)
            if n:
                hits[f"{t}:{nd[:4]}…"] = n
    return hits


async def _seed_journey(conn, idn: dict) -> dict:
    """Hanh trinh khach that: hoi thoai -> don qua command bus THAT -> dia chi verified -> M7/payment/GHN/ledger.
    Them cac dong DANG CU (truoc khi sua nguon) con PSID tho de chung minh xu ly du lieu cu."""
    from app.services import conversation_log
    from app.services.command import order_service
    from app.services.command.envelope import Actor
    from app.services.command.order_gateway import build_order_create_envelope
    P, name, phone, street = idn["psid"], idn["name"], idn["phone"], idn["street"]
    conv = await conversation_log.ensure_conversation(P, channel="messenger")
    cid = await conn.fetchval("SELECT id FROM customers WHERE psid=$1", P)
    await conn.execute("UPDATE customers SET name=$2, phone=$3, address=$4 WHERE id=$1", cid, name, phone, street)
    await conn.execute("INSERT INTO messages(conversation_id,role,content) VALUES($1,'customer',$2)", conv,
                       f"em {name}, sdt {phone}, giao {street}")
    sku = f"T415-{uuid.uuid4().hex[:8]}"
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock) VALUES($1,'CF',100000,50) RETURNING id",
                              sku)
    env = build_order_create_envelope(
        raw_payload=dict(customer_name=name, phone=phone, address=street, sku=sku, quantity=2, psid=P),
        actor=Actor("customer", P), channel="messenger", idempotency_key=uuid.uuid4().hex, conversation_id=conv)
    rc = await order_service.execute_order_create(env)
    assert rc.outcome == "succeeded", rc
    oid = rc.resource["id"] if rc.resource else rc.result["order_id"]
    # Nguon MOI: audit don bot = customer:<id>, khong PSID.
    assert await conn.fetchval("SELECT actor_ref FROM audit_log WHERE action='order.create' AND entity_id=$1",
                               str(oid)) == f"customer:{cid}"
    tag = uuid.uuid4().hex[:8]
    dsv = await conn.fetchval("SELECT version FROM admin_unit_dataset ORDER BY version LIMIT 1")
    if dsv is None:
        dsv = f"VN-ADMIN-2097-10-v{random.randint(10**6, 10**9)}"
        await conn.execute("INSERT INTO admin_unit_dataset (version, status, source_url, source_kind, sha256, license) "
                           "VALUES ($1,'draft','test','cross_reference',$2,'test')", dsv, "0" * 64)
    # --- intent + dia chi (resolution + snapshot) ---
    await conn.execute(
        "INSERT INTO order_intents(customer_id,conversation_id,channel,state,draft_customer_name,draft_phone,"
        "draft_address,committed_order_id) VALUES($1,$2,'messenger','COMMITTED',$3,$4,$5,$6)",
        cid, conv, name, phone, street, oid)
    res = await conn.fetchval(
        "INSERT INTO address_resolution(subject_type,subject_id,raw_province,raw_ward,street_text,province_code,"
        "ward_code,dataset_version,status,method,candidates,rules_applied,idempotency_key,resolved_by) "
        "VALUES('customer',$1,'Đắk Lắk','Buôn Ma Thuột',$2,'66','24121',$4,'auto_verified','current','[]','[]',$3,"
        "'live-verify:messenger') RETURNING id", str(cid), street, f"lv:{P}:{tag}", dsv)     # dang CU: PSID trong key
    await conn.execute(
        "INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,province_name,ward_name,"
        "street_text,dataset_version,provenance_ref,bound_by) VALUES($1,$2,'66','24121','Đắk Lắk','Buôn Ma Thuột',$3,"
        "$4,'{}','gate-e')", oid, res, street, dsv)
    await conn.execute("UPDATE customers SET current_address_resolution_id=$2 WHERE id=$1", cid, res)
    await conn.execute("INSERT INTO address_change_log(customer_ref,old_value,new_value,actor,reason,ticket) "
                       "VALUES($1,$2,$3,'cli','t','T415')", P, "1 Đường Cũ", street)
    # --- M2 ledger + audit dang CU (actor = PSID tho) ---
    loc = await conn.fetchval("INSERT INTO inventory_locations(code,name,location_type) VALUES($1,'T','warehouse') "
                              "RETURNING id", f"T415-{tag}")
    await conn.execute(
        "INSERT INTO inventory_movements(id,location_id,product_id,movement_type,on_hand_delta,reserved_delta,"
        "before_on_hand,after_on_hand,before_reserved,after_reserved,reference_type,reference_id,idempotency_key,"
        "actor_type,actor_id,correlation_id) VALUES($1,$2,$3,'reserve',0,2,10,10,0,2,'order',$4,$5,'bot',$6,$7)",
        uuid.uuid4(), loc, pid, str(oid), f"reserve:{oid}:{P}", P, uuid.uuid4())
    await conn.execute(
        "INSERT INTO order_events(id,order_id,event_type,event_version,to_status,actor_type,actor_id,correlation_id,"
        "causation_id,idempotency_key) VALUES($1,$2,'order.created',1,'new','bot',$3,$4,$3,$5)",
        uuid.uuid4(), oid, P, uuid.uuid4(), f"evt:{oid}:{P}")
    await conn.execute("INSERT INTO audit_log(actor_type,actor_ref,action,entity_type,entity_id,after) "
                       "VALUES('customer',$1,'shipment.ghn_create.prepare','order',$2,$3::jsonb)",
                       f"customer:{P}", str(oid), json.dumps({"by": P, "order_id": oid}))
    # audit cua staff tren don (entity lien ket) co ten/dia chi nguoi nhan trong after (vd sua don tay).
    await conn.execute("INSERT INTO audit_log(actor_type,actor_ref,action,entity_type,entity_id,after) "
                       "VALUES('staff','staff:1','order.edit','order',$1,$2::jsonb)", str(oid),
                       json.dumps({"customer_name": name, "note": f"giao {street}"}))
    # --- M7 / payment / shipment / GHN / SePay ---
    await conn.execute("INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,policy_version) "
                       "VALUES($1,'messenger',$2,'completed',1)", oid, P)
    await conn.execute(
        "INSERT INTO fulfillment_conversation_events(order_id,command_key,source,from_step,to_step,detail,reply_text) "
        "VALUES($1,$2,'customer','awaiting_method','completed',$3::jsonb,$4)",
        oid, f"msg:{P}", json.dumps({"by": f"customer:{P}"}), f"Dạ chị {name}, đơn giao tới {street} ạ")
    pay = await conn.fetchval("INSERT INTO payments(order_id,method,amount_due_vnd,amount_received_vnd,status) "
                              "VALUES($1,'BANK_TRANSFER',200000,200000,'confirmed') RETURNING id", oid)
    await conn.execute("INSERT INTO payment_events(payment_id,kind,amount_vnd,recorded_by,command_key,reference) "
                       "VALUES($1,'customer_reported',200000,$2,$3,'FT26101012345')",
                       pay, f"customer:{P}", f"fc:{oid}:msg:{P}")
    await conn.execute("INSERT INTO provider_events(provider,provider_event_id,payload_hash,raw,order_id,mode) "
                       "VALUES('sepay',$1,$2,$3::jsonb,$4,'test')", f"t415-{tag}", "0" * 64,
                       json.dumps({"id": 1, "transferAmount": 200000, "referenceCode": "FT26101012345",
                                   "content": f"SEVQR {oid} {name.upper()} CHUYEN TIEN",
                                   "description": f"{name} ck don {oid}"}), oid)
    sh = await conn.fetchval("INSERT INTO shipments(order_id,status,zone,fee_status) VALUES($1,'in_transit','province',"
                             "'unknown') RETURNING id", oid)
    await conn.execute("INSERT INTO shipment_delivery_attempts(shipment_id,attempt_no,result,recorded_by,command_key,"
                       "note) VALUES($1,1,'no_contact','staff:1',$2,$3)", sh, f"sda:{tag}", f"goi {phone} khong nghe")
    op = await conn.fetchval(
        "INSERT INTO ghn_shipment_create_operations(order_id,source,initiator_customer_id,command_key,"
        "request_fingerprint,mode,config_revision,client_order_code,state,policy_version,request_snapshot,max_attempts) "
        "VALUES($1,'bot',$2,$3,'fp','staging',1,$4,'prepared','v1',$5::jsonb,3) RETURNING id",
        oid, cid, f"bot:{oid}:msg:{P}", f"A3S-{oid}-{tag}",
        json.dumps({"recipient": {"name": name, "phone": phone, "address_text": f"{street}, Buôn Ma Thuột"},
                    "address": {"province_code": "66", "ward_code": "24121"}, "order": {"id": oid}}))
    await conn.execute("INSERT INTO ghn_shipment_create_attempts(operation_id,attempt_no,kind,outcome,actor) "
                       "VALUES($1,1,'create','unknown',$2)", op, f"customer:{P}")
    await conn.execute("INSERT INTO staff_attention(order_id,reason,detail,created_by) VALUES($1,'address',$2::jsonb,"
                       "'m7:bot')", oid, json.dumps({"customer_ref": P}))
    await conn.execute("INSERT INTO price_overrides(customer_id,quantity,unit_price_vnd,note,status) "
                       "VALUES($1,2,90000,$2,'used')", cid, f"giam cho {name}")
    r = await _redis()
    try:
        await r.set(f"chat:{P}", json.dumps([{"role": "user", "content": phone}]), ex=600)
        await r.set(f"nlu_state:{P}", "{}", ex=600)
        await r.set(f"addr_clarify:{P}:fp1", "1", ex=600)
        await r.lpush("dead_letter:messages", json.dumps({"event": {"sender": {"id": P}, "message": {"text": phone}}}))
    finally:
        await r.aclose()
    return {"cid": cid, "oid": oid, "pay": pay, "op": op, "res": res, "sh": sh}


async def _ledger_counts(conn, s):
    return {
        "order_events": await conn.fetchval("SELECT count(*) FROM order_events WHERE order_id=$1", s["oid"]),
        "inventory": await conn.fetchval("SELECT count(*) FROM inventory_movements WHERE reference_id=$1",
                                         str(s["oid"])),
        "payment_events": await conn.fetchval("SELECT count(*) FROM payment_events WHERE payment_id=$1", s["pay"]),
        "total": await conn.fetchval("SELECT total_vnd FROM orders WHERE id=$1", s["oid"]),
        "received": await conn.fetchval("SELECT amount_received_vnd FROM payments WHERE id=$1", s["pay"]),
        "ghn_state": await conn.fetchval("SELECT state FROM ghn_shipment_create_operations WHERE id=$1", s["op"]),
        "codes": tuple(await conn.fetchrow("SELECT province_code, ward_code FROM order_address_snapshot "
                                           "WHERE order_id=$1", s["oid"])),
    }


@dbonly
@pytest.mark.asyncio
async def test_e2e_full_journey_delete_scans_whole_db_and_redis():
    from app.services import data_deletion as dd
    idn = _ident()
    needles = [idn["psid"], idn["phone"], idn["name"], idn["street"]]
    conn = await _conn()
    try:
        s = await _seed_journey(conn, idn)
        before = await _full_scan(conn, needles)
        assert len(before) >= 15, before                      # hanh trinh thuc su de lai dau vet o nhieu kho
        ledger = await _ledger_counts(conn, s)
        res = await dd.process_deletion(idn["psid"])
        summ = res["summary"]
        assert summ and summ["customer_found"] and not summ["redis_pending"], summ
        imm = summ["immutable_anonymized"]
        for k in ("audit_log", "order_events", "inventory_movements", "address_resolution", "order_address_snapshot",
                  "ghn_shipment_create_operations", "fulfillment_conversation_events", "payment_events",
                  "provider_events", "price_overrides", "address_change_log"):
            assert imm[k] >= 1, (k, imm)
        after = await _full_scan(conn, needles)
        assert after == {}, after                              # KHONG con ban sao nhan dien o BAT KY bang nao
        assert await _ledger_counts(conn, s) == ledger         # so nghiep vu giu nguyen
        tomb = ci.tombstone(res["confirmation_code"])
        assert await conn.fetchval("SELECT actor_id FROM order_events WHERE order_id=$1 AND actor_id LIKE 'deleted:%'",
                                   s["oid"]) == tomb
        snap = json.loads(await conn.fetchval("SELECT request_snapshot FROM ghn_shipment_create_operations WHERE id=$1",
                                              s["op"]))
        assert snap["recipient"] == {"name": None, "address_text": None, "phone": "***" + idn["phone"][-3:],
                                     "dsr_anonymized": True} and snap["address"]["ward_code"] == "24121"
        a = await conn.fetchrow("SELECT after FROM audit_log WHERE action='dsr.anonymize' AND entity_id=$1",
                                res["confirmation_code"])
        assert a is not None and idn["psid"] not in a["after"]
        r = await _redis()
        try:
            keys = [k async for k in r.scan_iter(match=f"*{idn['psid']}*")]
            dl = [x for x in await r.lrange("dead_letter:messages", 0, -1) if idn["psid"] in x or idn["phone"] in x]
            assert keys == [] and dl == []
        finally:
            await r.aclose()
    finally:
        await conn.close()


async def _subject_rows(conn, s: dict, psid: str) -> dict:
    """Moi dong lien ket voi 1 khach (theo khoa lien ket, KHONG theo gia tri PII) -> {bang: [row::text ...]} de so
    byte-for-byte truoc/sau khi xoa khach KHAC."""
    cid, oid = s["cid"], s["oid"]
    q = {
        "customers": ("SELECT x::text FROM customers x WHERE id=$1", cid),
        "orders": ("SELECT x::text FROM orders x WHERE customer_id=$1", cid),
        "audit_log": ("SELECT x::text FROM audit_log x WHERE (entity_type IN ('order','orders') AND entity_id=$1) "
                      "OR actor_ref IN ($2, 'customer:' || $2)", str(oid), psid),
        "order_events": ("SELECT x::text FROM order_events x WHERE order_id=$1", oid),
        "inventory_movements": ("SELECT x::text FROM inventory_movements x WHERE reference_id=$1", str(oid)),
        "address_resolution": ("SELECT x::text FROM address_resolution x WHERE id=$1", s["res"]),
        "order_address_snapshot": ("SELECT x::text FROM order_address_snapshot x WHERE order_id=$1", oid),
        "address_change_log": ("SELECT x::text FROM address_change_log x WHERE customer_ref=$1", psid),
        "ghn_ops": ("SELECT x::text FROM ghn_shipment_create_operations x WHERE id=$1", s["op"]),
        "ghn_attempts": ("SELECT x::text FROM ghn_shipment_create_attempts x WHERE operation_id=$1", s["op"]),
        "fce": ("SELECT x::text FROM fulfillment_conversation_events x WHERE order_id=$1", oid),
        "fc": ("SELECT x::text FROM fulfillment_conversations x WHERE order_id=$1", oid),
        "payments": ("SELECT x::text FROM payments x WHERE order_id=$1", oid),
        "payment_events": ("SELECT x::text FROM payment_events x WHERE payment_id=$1", s["pay"]),
        "provider_events": ("SELECT x::text FROM provider_events x WHERE order_id=$1", oid),
        "shipments": ("SELECT x::text FROM shipments x WHERE order_id=$1", oid),
        "sda": ("SELECT x::text FROM shipment_delivery_attempts x WHERE shipment_id=$1", s["sh"]),
        "staff_attention": ("SELECT x::text FROM staff_attention x WHERE order_id=$1", oid),
        "price_overrides": ("SELECT x::text FROM price_overrides x WHERE customer_id=$1", cid),
        "order_intents": ("SELECT x::text FROM order_intents x WHERE customer_id=$1", cid),
        "command_executions": ("SELECT x::text FROM command_executions x WHERE customer_id=$1", cid),
        "outbox_events": ("SELECT x::text FROM outbox_events x WHERE payload->>'order_id'=$1 OR command_id IN "
                          "(SELECT id FROM command_executions WHERE customer_id=$2)", str(oid), cid),
        "messages": ("SELECT x::text FROM messages x WHERE conversation_id IN "
                     "(SELECT id FROM conversations WHERE customer_id=$1)", cid),
    }
    out = {}
    for name, (sql, *args) in q.items():
        out[name] = sorted(r[0] for r in await conn.fetch(sql, *args))
    return out


@dbonly
@pytest.mark.asyncio
async def test_two_customers_shared_pii_and_wildcards_other_customer_untouched():
    """CA 416 finding 1: A va B TRUNG dia chi; ten A chua '%'/'_' ma neu dung LIKE se khop ten B. Xoa A -> MOI dong
    lien ket B giu nguyen byte-for-byte; audit khong lien ket ai co chua dia chi chung cung giu nguyen."""
    from app.services import data_deletion as dd
    tag = "".join(random.choice("0123456789") for _ in range(6))
    street = f"{tag} Đường Trùng Nhau DSR"
    a = {**_ident(), "name": f"Lê_Văn%{tag}", "street": street}
    b = {**_ident(), "name": f"Lê Văn Bình {tag}", "street": street}     # LIKE '%Lê_Văn%<tag>%' se khop ten B
    conn = await _conn()
    try:
        sa = await _seed_journey(conn, a)
        sb = await _seed_journey(conn, b)
        unrelated = await conn.fetchval(
            "INSERT INTO audit_log(actor_type,actor_ref,action,entity_type,entity_id,after) VALUES('staff','staff:9',"
            "'note','product','999999',$1::jsonb) RETURNING id", json.dumps({"txt": f"{street} / {b['name']}"}))
        before_b = await _subject_rows(conn, sb, b["psid"])
        before_unrel = await conn.fetchval("SELECT x::text FROM audit_log x WHERE id=$1", unrelated)
        assert sum(len(v) for v in before_b.values()) >= 25
        res = await dd.process_deletion(a["psid"])
        assert res["summary"]["customer_found"] and not res["summary"]["redis_pending"]
        assert await _subject_rows(conn, sb, b["psid"]) == before_b                    # B byte-for-byte
        assert await conn.fetchval("SELECT x::text FROM audit_log x WHERE id=$1", unrelated) == before_unrel
        # A: khong con PSID/SDT o bat ky bang nao; ten/dia chi chi con o dong cua B + dong khong lien ket.
        assert await _full_scan(conn, [a["psid"], a["phone"]]) == {}
        assert street in json.dumps(before_b, ensure_ascii=False)
        assert a["name"] not in json.dumps(await _subject_rows(conn, sa, "x"), ensure_ascii=False)
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_definer_takes_no_identifiers_and_rejects_misuse():
    """CA 416 finding 2: ham nhan (customer_id, code) — khong co tham so dinh danh/PII. Tu choi: code khong co yeu cau
    received / da dung cho subject khac / customer da tombstone. App role khong UPDATE truc tiep kho bat bien."""
    import asyncpg

    from app.services import data_deletion as dd
    a, b = _ident(), _ident()
    conn = await _conn()
    try:
        args = await conn.fetchval("SELECT pg_get_function_identity_arguments('dsr_erase_subject'::regproc)")
        assert args == "p_customer_id bigint, p_code text"
        sa = await _seed_journey(conn, a)
        sb = await _seed_journey(conn, b)
        before_b = await _subject_rows(conn, sb, b["psid"])
        # code ngau nhien khong co yeu cau xoa -> tu choi
        with pytest.raises(asyncpg.RaiseError):
            await conn.fetchval("SELECT dsr_erase_subject($1, $2)", sb["cid"], "0123456789abcdef")
        # xoa A that -> code A da gan subject; dung lai code A cho B -> tu choi
        res = await dd.process_deletion(a["psid"])
        with pytest.raises(asyncpg.RaiseError):
            await conn.fetchval("SELECT dsr_erase_subject($1, $2)", sb["cid"], res["confirmation_code"])
        # A da tombstone + yeu cau moi hop le -> van tu choi (khong lam lai tren khach da xoa)
        code2 = uuid.uuid4().hex[:16]
        await conn.execute("INSERT INTO data_deletion_requests(confirmation_code,status) VALUES($1,'received')", code2)
        with pytest.raises(asyncpg.RaiseError):
            await conn.fetchval("SELECT dsr_erase_subject($1, $2)", sa["cid"], code2)
        assert await _subject_rows(conn, sb, b["psid"]) == before_b
        # trigger bat bien van chan UPDATE thuong (ke ca superuser)
        with pytest.raises(asyncpg.RaiseError):
            await conn.execute("UPDATE order_events SET actor_id='x' WHERE order_id=$1", sb["oid"])
        if await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_app')"):
            for sql in ("UPDATE audit_log SET actor_ref='x' WHERE id=-1",
                        "UPDATE order_events SET actor_id='x' WHERE order_id=-1",
                        "UPDATE inventory_movements SET actor_id='x' WHERE reference_id='-1'"):
                async with conn.transaction():
                    await conn.execute("SET LOCAL ROLE alpha3s_app")
                    with pytest.raises(asyncpg.InsufficientPrivilegeError):
                        async with conn.transaction():
                            await conn.execute(sql)
            assert await conn.fetchval("SELECT has_function_privilege('alpha3s_app', "
                                       "'dsr_erase_subject(bigint,text)', 'EXECUTE')")
            assert not await conn.fetchval("SELECT pg_has_role('alpha3s_app', 'alpha3s_dsr', 'MEMBER')")
        acl = await conn.fetchval("SELECT proacl::text FROM pg_proc WHERE proname='dsr_erase_subject'")
        assert acl and "{=X/" not in acl and ",=X/" not in acl                     # khong cap EXECUTE cho PUBLIC
    finally:
        await conn.close()


async def _noop_sleep(*a, **k):
    return None


async def _boom(psid, summary):
    raise ConnectionError("redis down")


@dbonly
@pytest.mark.asyncio
async def test_redis_failure_after_db_commit_then_worker_completes(monkeypatch):
    from app.services import data_deletion as dd
    idn = _ident()
    P = idn["psid"]
    conn = await _conn()
    try:
        await _seed_journey(conn, idn)
        real = dd._clear_redis
        monkeypatch.setattr(dd, "_clear_redis", _boom)
        monkeypatch.setattr(dd.asyncio, "sleep", _noop_sleep)
        res = await dd.process_deletion(P)
        code = res["confirmation_code"]
        assert res["summary"]["customer_found"] and res["summary"]["redis_pending"]
        row = await conn.fetchrow("SELECT status, subject_hmac, detail FROM data_deletion_requests "
                                  "WHERE confirmation_code=$1", code)
        kid, key = dd.hmac_keys()[0]
        assert row["status"] == "redis_pending" and row["subject_hmac"] == dd.subject_hmac(P, key)
        assert json.loads(row["detail"])["hmac_key_id"] == kid and P not in row["detail"] + row["subject_hmac"]
        assert await conn.fetchval("SELECT count(*) FROM customers WHERE psid=$1", P) == 0     # DB da xoa
        r = await _redis()
        try:
            assert await r.exists(f"chat:{P}")                                                # Redis chua don
        finally:
            await r.aclose()
        monkeypatch.setattr(dd, "_clear_redis", real)
        st = await dd.retry_redis_pending()
        assert st["completed"] >= 1 and st["keys_deleted"] >= 3 and st["dead_letters_removed"] >= 1
        row = await conn.fetchrow("SELECT status, subject_hmac, detail FROM data_deletion_requests "
                                  "WHERE confirmation_code=$1", code)
        assert row["status"] == "completed" and row["subject_hmac"] is None
        d = json.loads(row["detail"])
        assert d["redis_completed_by"] == "worker" and d["subject_bound"] is True
        r = await _redis()
        try:
            assert [k async for k in r.scan_iter(match=f"*{P}*")] == []
        finally:
            await r.aclose()
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_redis_failure_then_repeat_request_completes_pending(monkeypatch):
    from app.services import data_deletion as dd
    idn = _ident()
    P = idn["psid"]
    conn = await _conn()
    try:
        await _seed_journey(conn, idn)
        real = dd._clear_redis
        monkeypatch.setattr(dd, "_clear_redis", _boom)
        monkeypatch.setattr(dd.asyncio, "sleep", _noop_sleep)
        first = await dd.process_deletion(P)
        monkeypatch.setattr(dd, "_clear_redis", real)
        second = await dd.process_deletion(P)                  # khach/Meta goi lai: customer da tombstone
        assert second["summary"]["customer_found"] is False and second["summary"]["pending_completed"] == 1
        st = await conn.fetchrow("SELECT status, subject_hmac, detail FROM data_deletion_requests "
                                 "WHERE confirmation_code=$1", first["confirmation_code"])
        assert st["status"] == "completed" and st["subject_hmac"] is None
        assert json.loads(st["detail"])["redis_completed_by"] == "repeat_request"
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_hmac_key_rotation_and_missing_key(monkeypatch):
    """CA 416 ghi chu: khoa DSR rieng. Pending tao bang khoa cu -> sau rotation (cu -> PREVIOUS) worker van ghep duoc.
    Thieu khoa -> khong tao hmac du doan duoc; request giu redis_pending (khong gia 'xong') + bao unmatchable."""
    from app.config import settings
    from app.services import data_deletion as dd
    monkeypatch.setattr(dd.asyncio, "sleep", _noop_sleep)
    conn = await _conn()
    try:
        # khoa 1 tao pending -> rotation -> worker dung khoa PREVIOUS
        idn = _ident()
        await _seed_journey(conn, idn)
        real = dd._clear_redis
        monkeypatch.setattr(dd, "_clear_redis", _boom)
        r1 = await dd.process_deletion(idn["psid"])
        monkeypatch.setattr(settings, "dsr_hmac_key", KEY2)
        monkeypatch.setattr(settings, "dsr_hmac_key_previous", KEY1)
        monkeypatch.setattr(dd, "_clear_redis", real)
        await dd.retry_redis_pending()
        assert await conn.fetchval("SELECT status FROM data_deletion_requests WHERE confirmation_code=$1",
                                   r1["confirmation_code"]) == "completed"
        # thieu khoa hoan toan
        monkeypatch.setattr(settings, "dsr_hmac_key", "")
        monkeypatch.setattr(settings, "dsr_hmac_key_previous", "")
        idn2 = _ident()
        await _seed_journey(conn, idn2)
        monkeypatch.setattr(dd, "_clear_redis", _boom)
        r2 = await dd.process_deletion(idn2["psid"])
        row = await conn.fetchrow("SELECT status, subject_hmac, detail FROM data_deletion_requests "
                                  "WHERE confirmation_code=$1", r2["confirmation_code"])
        assert row["status"] == "redis_pending" and row["subject_hmac"] is None
        assert json.loads(row["detail"])["hmac_unavailable"] is True
        monkeypatch.setattr(dd, "_clear_redis", real)
        st = await dd.retry_redis_pending()
        assert st["unmatchable"] >= 1
        assert await conn.fetchval("SELECT status FROM data_deletion_requests WHERE confirmation_code=$1",
                                   r2["confirmation_code"]) == "redis_pending"
        # don sach de khong de lai pending cho cac test khac
        await conn.execute("UPDATE data_deletion_requests SET status='completed' WHERE confirmation_code=$1",
                           r2["confirmation_code"])
    finally:
        await conn.close()
