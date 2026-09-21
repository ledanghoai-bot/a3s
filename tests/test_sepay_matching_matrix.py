"""CA Review 308-04 — SePay Test Mode matching matrix trên candidate D306 (DB, m5lab). Skip khi khong DB.

Chung minh (fixture deterministic, KHONG giao dich that): exact match, duplicate same payload, conflicting duplicate,
wrong account/amount/code/direction, stale instruction, connector-OFF no-confirm, allowed-account tu Settings.
"""
import json
import os
import time

import pytest

from app.config import settings
from app.services.payment import payment_service as P
from app.services.payment import provider_ingest as PI
from app.services.providers import sepay as sp

DB = os.environ.get("M6_TEST_DB") == "1"
pytestmark = pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")

ACCT = "0071000123456"
BIN = "970415"


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


async def _seed(conn, *, amount=230000):
    """order + BANK_TRANSFER payment (amount_due) + active TEST bank + instruction test snapshot."""
    tag = f"SPM-{int(time.time()*1000)}-{os.urandom(2).hex()}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'T','0900000000') RETURNING id",
                              f"tg:{tag}")
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
                              "VALUES($1,'CF',100000,999,300,'hu') RETURNING id", tag)
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                              "VALUES($1,'confirmed',$2,'telegram_customer') RETURNING id", cid, amount)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,1,$3)",
                       oid, pid, amount)
    await conn.execute("INSERT INTO payments(order_id,method,amount_due_vnd,status) "
                       "VALUES($1,'BANK_TRANSFER',$2,'awaiting')", oid, amount)
    # active TEST bank
    await conn.execute("UPDATE bank_accounts SET active=false WHERE active")
    await conn.execute("INSERT INTO bank_accounts(bank,account_number,holder_name,version,active,is_test,bin) "
                       "VALUES('VietinBank',$1,'SHOP TEST',999,true,true,$2)", ACCT, BIN)
    instr = await P.generate_instruction(conn, oid, actor="t", command_key=f"{tag}:instr", code_prefix="3SCF")
    return oid, instr, tag


def _event(oid, *, account=ACCT, amount=230000, direction="in", eid=None, content=None):
    raw = {"id": eid or int(time.time() * 1e6) % 10**9, "gateway": "VietinBank",
           "transactionDate": "2026-09-13 20:02:37", "accountNumber": account,
           "code": None, "content": content if content is not None else f"3SCF {oid}", "transferType": direction,
           "transferAmount": amount, "referenceCode": "REF1", "description": ""}
    return sp.parse_envelope(json.dumps(raw).encode("utf-8"))


async def _ingest_process(conn, ev):
    async with conn.transaction():
        rid, created, conflict = await PI.ingest(conn, ev, mode="test")
    async with conn.transaction():
        st = await PI.process(conn, rid)
    return rid, created, conflict, st


async def _pay_status(conn, oid):
    return await conn.fetchval("SELECT status FROM payments WHERE order_id=$1", oid)


@pytest.mark.asyncio
async def test_exact_match_and_duplicate_idempotent():
    conn = await _conn()
    try:
        oid, instr, tag = await _seed(conn)
        ev = _event(oid, eid=int(f"{int(time.time())%100000}1"))
        _, created, conflict, st = await _ingest_process(conn, ev)
        assert created and not conflict and st == "matched"
        assert await _pay_status(conn, oid) == "confirmed"
        # duplicate SAME payload (same event id) -> idempotent, khong confirm lai
        rid2, created2, conflict2, st2 = await _ingest_process(conn, ev)
        assert not created2 and not conflict2   # duplicate detected
        assert await _pay_status(conn, oid) == "confirmed"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_conflicting_duplicate_same_id_diff_payload():
    conn = await _conn()
    try:
        oid, instr, tag = await _seed(conn)
        eid = int(f"{int(time.time())%100000}2")
        ev1 = _event(oid, eid=eid, amount=230000)
        await _ingest_process(conn, ev1)
        ev2 = _event(oid, eid=eid, amount=999999)   # cung id, khac payload
        async with conn.transaction():
            _, created, conflict = await PI.ingest(conn, ev2, mode="test")
        assert not created and conflict   # payload_hash_conflict fail-closed
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_wrong_amount_account_code_direction_no_confirm():
    conn = await _conn()
    try:
        # wrong amount -> discrepancy
        oid, _, _ = await _seed(conn)
        _, _, _, st = await _ingest_process(conn, _event(oid, amount=100000, eid=int(f"{int(time.time())%100000}3")))
        assert st == "discrepancy" and await _pay_status(conn, oid) != "confirmed"
        # wrong account -> discrepancy
        oid2, _, _ = await _seed(conn)
        _, _, _, st2 = await _ingest_process(conn, _event(oid2, account="9999999999",
                                                          eid=int(f"{int(time.time())%100000}4")))
        assert st2 == "discrepancy" and await _pay_status(conn, oid2) != "confirmed"
        # missing code -> unmatched
        oid3, _, _ = await _seed(conn)
        ev = _event(oid3, eid=int(f"{int(time.time())%100000}5"), content="khong co ma don")
        _, _, _, st3 = await _ingest_process(conn, ev)
        assert st3 == "unmatched" and await _pay_status(conn, oid3) != "confirmed"
        # direction out -> ignored
        oid4, _, _ = await _seed(conn)
        _, _, _, st4 = await _ingest_process(conn, _event(oid4, direction="out",
                                                          eid=int(f"{int(time.time())%100000}6")))
        assert st4 == "ignored" and await _pay_status(conn, oid4) != "confirmed"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_stale_instruction_after_regenerate():
    conn = await _conn()
    try:
        oid, instr, tag = await _seed(conn)
        # regenerate instruction voi amount moi (doi active bank amount qua due) -> instruction moi la current
        await conn.execute("UPDATE payments SET amount_due_vnd=500000, version=version+1 WHERE order_id=$1", oid)
        await P.generate_instruction(conn, oid, actor="t", command_key=f"{tag}:instr2", code_prefix="3SCF")
        # event khop instruction CU (230000) -> khong khop current (500000) -> discrepancy, no confirm
        _, _, _, st = await _ingest_process(conn, _event(oid, amount=230000,
                                                        eid=int(f"{int(time.time())%100000}7")))
        assert st == "discrepancy" and await _pay_status(conn, oid) != "confirmed"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_allowed_accounts_precedence(monkeypatch):
    """315-02: precedence tat dinh. OFF->env baseline; ON+DB active-> DB authoritative (KHONG union env, stale env bi loai);
    ON+DB empty-> fail-closed enforce rong; ON+no-DB+no-fallback-> fail-closed; ON+no-DB+fallback-> env."""
    import base64
    conn = await _conn()
    iid = None
    try:
        monkeypatch.setattr(settings, "sepay_allowed_accounts", "9999999999")   # env stale
        monkeypatch.setattr(settings, "config_enc_keys", f"k1:{base64.b64encode(b'A'*32).decode()}")
        monkeypatch.setattr(settings, "config_enc_key_current", "k1")
        monkeypatch.setattr(settings, "config_secret_fp_key", base64.b64encode(b'F'*32).decode())
        from app.services.settings import integrations as S

        # module OFF -> env baseline (enforce vi env co)
        monkeypatch.setattr(settings, "settings_integrations_enabled", False)
        acc, enf = await PI._allowed_accounts(conn)
        assert acc == {"9999999999"} and enf is True

        # ON + no DB + no fallback -> fail-closed (rong, enforce)
        monkeypatch.setattr(settings, "settings_integrations_enabled", True)
        monkeypatch.setattr(settings, "settings_integrations_env_fallback", False)
        acc, enf = await PI._allowed_accounts(conn)
        assert acc == set() and enf is True
        # ON + no DB + fallback -> env
        monkeypatch.setattr(settings, "settings_integrations_env_fallback", True)
        acc, enf = await PI._allowed_accounts(conn)
        assert acc == {"9999999999"} and enf is True
        monkeypatch.setattr(settings, "settings_integrations_env_fallback", False)

        # ON + DB active allowlist=[ACCT] -> DB authoritative, stale env 9999 bi LOAI
        async with conn.transaction():
            it = await S.create_integration(conn, kind="payment", provider="sepay", label="SP", mode="test",
                                            config_public={"code_prefix": "3SCF", "allowed_accounts": ACCT},
                                            actor="po", command_key=f"sp-{os.urandom(3).hex()}")
        iid = it["id"]
        await conn.execute("UPDATE integrations SET enabled=true WHERE id=$1", iid)
        acc, enf = await PI._allowed_accounts(conn)
        assert acc == {ACCT} and enf is True and "9999999999" not in acc

        # ON + DB active nhung allowlist RONG -> fail-closed (enforce rong)
        async with conn.transaction():
            await conn.execute("UPDATE integrations SET config_public=jsonb_set(config_public,'{allowed_accounts}','\"\"') "
                               "WHERE id=$1", iid)
        acc, enf = await PI._allowed_accounts(conn)
        assert acc == set() and enf is True
    finally:
        if iid:
            async with conn.transaction():
                await conn.execute("DELETE FROM integration_commands WHERE integration_id=$1", iid)
                await conn.execute("DELETE FROM integrations WHERE id=$1", iid)
        await conn.close()


@pytest.mark.asyncio
async def test_connector_off_webhook_404_and_worker_inert(monkeypatch):
    """315-03: connector OFF -> webhook 404, run_once INERT (khong claim), event ton dong khong auto-confirm."""
    from fastapi.testclient import TestClient

    from app.main import app
    monkeypatch.setattr(settings, "m7_sepay_test_connector", False)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/webhooks/sepay", json={"id": 1, "transferType": "in"})
    assert r.status_code == 404   # webhook khong ton tai khi connector OFF
    # worker inert
    stats = await PI.run_once()
    assert stats.get("skipped") == "connector_off" and stats["claimed"] == 0
    # event ton dong (seed thang) khong bi confirm khi connector OFF
    conn = await _conn()
    try:
        oid, _, _ = await _seed(conn)
        ev = _event(oid, eid=int(f"{int(time.time())%100000}8"))
        async with conn.transaction():
            await PI.ingest(conn, ev, mode="test")
        await PI.run_once()   # inert
        assert await _pay_status(conn, oid) != "confirmed"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_concurrent_delivery_one_durable_confirm(monkeypatch):
    """315-03: hai delivery/process dong thoi cung event -> dung MOT durable confirm + count assertions."""
    import asyncio
    conn = await _conn()
    c1 = await _conn()
    c2 = await _conn()
    oid = None
    try:
        oid, _, _ = await _seed(conn)
        ev = _event(oid, eid=int(f"{int(time.time())%100000}9"))
        # ingest MOT lan (cung event); hai process dong thoi tren 2 connection
        async with conn.transaction():
            rid, created, _ = await PI.ingest(conn, ev, mode="test")
        assert created

        async def _proc(cc):
            try:
                async with cc.transaction():
                    return await PI.process(cc, rid)
            except Exception:  # noqa: BLE001
                return "err"
        r1, r2 = await asyncio.gather(_proc(c1), _proc(c2))
        # dung MOT durable effect: payment confirmed + dung 1 evidence row cho payment nay
        pid = await conn.fetchval("SELECT id FROM payments WHERE order_id=$1", oid)
        confirms = await conn.fetchval("SELECT count(*) FROM payment_events WHERE payment_id=$1", pid)
        assert confirms == 1, f"phai dung 1 confirmation evidence, co {confirms} ({r1},{r2})"
        assert await _pay_status(conn, oid) == "confirmed"
    finally:
        await conn.close()
        await c1.close()
        await c2.close()


@pytest.mark.asyncio
async def test_concurrent_ingest_same_id(monkeypatch):
    """315-03: cung event ID concurrent — same payload -> dung 1 created (con lai duplicate); diff payload -> conflict."""
    import asyncio
    setup = await _conn()
    c1 = await _conn()
    c2 = await _conn()
    oid = None
    try:
        oid, _, _ = await _seed(setup)
        eid = int(f"{int(time.time())%100000}0")
        # same payload concurrent
        evA = _event(oid, eid=eid)

        async def _ing(cc, ev):
            async with cc.transaction():
                return await PI.ingest(cc, ev, mode="test")
        (_, cr1, cf1), (_, cr2, cf2) = await asyncio.gather(_ing(c1, evA), _ing(c2, evA))
        assert [cr1, cr2].count(True) == 1 and not (cf1 or cf2)   # dung 1 created, khong conflict
        # diff payload concurrent (event moi, cung id) -> 1 created, 1 conflict
        eid2 = int(f"{int(time.time())%100000}1")
        evB1 = _event(oid, eid=eid2, amount=230000)
        evB2 = _event(oid, eid=eid2, amount=111111)
        (_, crb1, cfb1), (_, crb2, cfb2) = await asyncio.gather(_ing(c1, evB1), _ing(c2, evB2))
        assert [crb1, crb2].count(True) == 1 and [cfb1, cfb2].count(True) == 1   # 1 created, 1 conflict
    finally:
        await setup.close()
        await c1.close()
        await c2.close()


async def _seed_ob(conn, *, amount=230000):
    """order + BANK_TRANSFER payment (amount_due) + active TEST bank — KHONG tao instruction (de resolver prefix)."""
    tag = f"TP-{int(time.time()*1000)}-{os.urandom(2).hex()}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'T','0900000000') RETURNING id",
                              f"tg:{tag}")
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
                              "VALUES($1,'CF',100000,999,300,'hu') RETURNING id", tag)
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                              "VALUES($1,'confirmed',$2,'telegram_customer') RETURNING id", cid, amount)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,1,$3)",
                       oid, pid, amount)
    await conn.execute("INSERT INTO payments(order_id,method,amount_due_vnd,status) "
                       "VALUES($1,'BANK_TRANSFER',$2,'awaiting')", oid, amount)
    await conn.execute("UPDATE bank_accounts SET active=false WHERE active")
    await conn.execute("INSERT INTO bank_accounts(bank,account_number,holder_name,version,active,is_test,bin) "
                       "VALUES('VietinBank',$1,'SHOP TEST',999,true,true,$2)", ACCT, BIN)
    return oid, tag


@pytest.mark.asyncio
async def test_two_dashboard_prefixes_end_to_end_no_cross_match(monkeypatch):
    """CA 323 §3: prefix do Dashboard (SEVQR & 3SCF) đi xuyên Dashboard->instruction->webhook exact match;
    đổi prefix giữ snapshot cũ/mới riêng biệt, KHÔNG cross-match; foreign prefix fail-closed. (module ON: Dashboard authoritative)"""
    from app.services.settings import integrations as S
    monkeypatch.setattr(settings, "settings_integrations_enabled", True)   # CA 324: module ON -> Dashboard la nguon prefix
    monkeypatch.setattr(settings, "sepay_allowed_accounts", "")
    conn = await _conn()
    iid = None
    n = int(time.time()) % 100000
    try:
        async with conn.transaction():
            it = await S.create_integration(conn, kind="payment", provider="sepay", label="SP", mode="test",
                                            config_public={"code_prefix": "SEVQR", "allowed_accounts": ACCT},
                                            actor="po", command_key=f"tp-{os.urandom(3).hex()}")
        iid = it["id"]
        await conn.execute("UPDATE integrations SET enabled=true WHERE id=$1", iid)   # active -> allowed_accounts DB authoritative
        # order A: instruction resolves prefix SEVQR (Dashboard) -> "SEVQR <oid>"
        oidA, tagA = await _seed_ob(conn)
        instrA = await P.generate_instruction(conn, oidA, actor="t", command_key=f"{tagA}:i")
        assert instrA["transfer_content"] == f"SEVQR {oidA}"
        _, _, _, st = await _ingest_process(conn, _event(oidA, content=f"SEVQR {oidA}", eid=int(f"{n}11")))
        assert st == "matched" and await _pay_status(conn, oidA) == "confirmed"
        # order B (SEVQR instr) nhưng webhook prefix FOREIGN "3SCF" -> snapshot mismatch, no confirm
        oidB, tagB = await _seed_ob(conn)
        await P.generate_instruction(conn, oidB, actor="t", command_key=f"{tagB}:i")
        _, _, _, stB = await _ingest_process(conn, _event(oidB, content=f"3SCF {oidB}", eid=int(f"{n}12")))
        assert stB == "discrepancy" and await _pay_status(conn, oidB) != "confirmed"
        # đổi Dashboard prefix -> 3SCF
        d = await S.get_integration(conn, iid)
        async with conn.transaction():
            await S.update_public(conn, iid, label=None,
                                  config_public={"code_prefix": "3SCF", "allowed_accounts": ACCT},
                                  expected_version=d["version"], actor="po", command_key=f"tp-{os.urandom(3).hex()}")
        # order C: instruction resolves prefix 3SCF (mới) -> "3SCF <oid>"
        oidC, tagC = await _seed_ob(conn)
        instrC = await P.generate_instruction(conn, oidC, actor="t", command_key=f"{tagC}:i")
        assert instrC["transfer_content"] == f"3SCF {oidC}"
        _, _, _, stC = await _ingest_process(conn, _event(oidC, content=f"3SCF {oidC}", eid=int(f"{n}13")))
        assert stC == "matched" and await _pay_status(conn, oidC) == "confirmed"
        # order D (3SCF instr) webhook FOREIGN "SEVQR" -> mismatch, no confirm (no cross-match prefix cũ)
        oidD, tagD = await _seed_ob(conn)
        await P.generate_instruction(conn, oidD, actor="t", command_key=f"{tagD}:i")
        _, _, _, stD = await _ingest_process(conn, _event(oidD, content=f"SEVQR {oidD}", eid=int(f"{n}14")))
        assert stD == "discrepancy" and await _pay_status(conn, oidD) != "confirmed"
    finally:
        if iid:
            async with conn.transaction():
                await conn.execute("DELETE FROM integration_commands WHERE integration_id=$1", iid)
                await conn.execute("DELETE FROM integrations WHERE id=$1", iid)
        await conn.close()


@pytest.mark.asyncio
async def test_module_on_missing_prefix_fail_closed(monkeypatch):
    """CA 324 §3.2: module ON + không có Dashboard prefix -> generate_instruction fail-closed (không default)."""
    monkeypatch.setattr(settings, "settings_integrations_enabled", True)
    conn = await _conn()
    try:
        await conn.execute("UPDATE integrations SET archived_at=now() WHERE provider='sepay' AND archived_at IS NULL")
        oid, tag = await _seed_ob(conn)
        with pytest.raises(P.PaymentError):
            await P.generate_instruction(conn, oid, actor="t", command_key=f"{tag}:i")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_module_off_legacy_baseline_bank_transfer_works(monkeypatch):
    """CA 324-01 §3.1/§4: module OFF + 0 SePay integration -> CK/M6-M7 instruction VAN tao duoc (legacy compat baseline),
    KHONG raise loi, KHONG yeu cau Dashboard config (giu dormant behavior)."""
    monkeypatch.setattr(settings, "settings_integrations_enabled", False)   # dormant
    conn = await _conn()
    try:
        await conn.execute("UPDATE integrations SET archived_at=now() WHERE provider='sepay' AND archived_at IS NULL")
        oid, tag = await _seed_ob(conn)
        instr = await P.generate_instruction(conn, oid, actor="t", command_key=f"{tag}:i")   # KHONG code_prefix
        assert instr["transfer_content"] == f"3SCF {oid}"   # legacy compat prefix giu nguyen baseline
    finally:
        await conn.close()


# ============================ CA Directive 331: S0 tester REAL-BANK auto-confirm ============================
def _m7_tester(monkeypatch, cid):
    monkeypatch.setattr(settings, "m7_conversational_fulfillment", True)
    monkeypatch.setattr(settings, "m7_conversational_scope", "tester")
    monkeypatch.setattr(settings, "m7_tester_customer_ids", str(cid))


async def _seed_realbank(conn, *, amount=170000):
    """order + BANK_TRANSFER + active bank is_test=FALSE (thật) + instruction is_test=false (prefix SEVQR explicit)."""
    tag = f"RB-{int(time.time()*1000)}-{os.urandom(2).hex()}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'T','0900000000') RETURNING id",
                              f"tg:{tag}")
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
                              "VALUES($1,'CF',100000,999,300,'hu') RETURNING id", tag)
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                              "VALUES($1,'confirmed',$2,'telegram_customer') RETURNING id", cid, amount)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,1,$3)",
                       oid, pid, amount)
    await conn.execute("INSERT INTO payments(order_id,method,amount_due_vnd,status) "
                       "VALUES($1,'BANK_TRANSFER',$2,'awaiting')", oid, amount)
    await conn.execute("UPDATE bank_accounts SET active=false WHERE active")
    await conn.execute("INSERT INTO bank_accounts(bank,account_number,holder_name,version,active,is_test,bin) "
                       "VALUES('Vietinbank',$1,'SHOP THAT',999,true,false,$2)", ACCT, BIN)   # is_test=FALSE
    instr = await P.generate_instruction(conn, oid, actor="t", command_key=f"{tag}:i", code_prefix="SEVQR")
    assert instr["is_test"] is False and instr["transfer_content"] == f"SEVQR {oid}"
    return oid, cid, tag


def _rb_event(oid, *, amount=170000, account=ACCT, eid=None):
    # content dang THAT: bank prepend ref + SEVQR <oid> (chung minh extraction chiu duoc)
    return _event(oid, amount=amount, account=account, eid=eid, content=f"502D609218GGZCV7 SEVQR {oid}")


@pytest.mark.asyncio
async def test_331_tester_realbank_exact_autoconfirm(monkeypatch):
    """331 §3.1: tester PO + connector ON + live OFF + real-bank is_test=false + exact -> auto-confirm 1 lan."""
    monkeypatch.setattr(settings, "m7_sepay_test_connector", True)
    monkeypatch.setattr(settings, "sepay_live_enabled", False)
    conn = await _conn()
    try:
        oid, cid, tag = await _seed_realbank(conn)
        _m7_tester(monkeypatch, cid)
        _, _, _, st = await _ingest_process(conn, _rb_event(oid, eid=int(f"{int(time.time())%100000}31")))
        assert st == "matched" and await _pay_status(conn, oid) == "confirmed"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_331_non_tester_realbank_no_autoconfirm(monkeypatch):
    """331 §3.2: cùng điều kiện nhưng order KHÔNG thuộc tester scope -> zero auto-confirm (instruction_not_test)."""
    monkeypatch.setattr(settings, "m7_sepay_test_connector", True)
    monkeypatch.setattr(settings, "sepay_live_enabled", False)
    conn = await _conn()
    try:
        oid, cid, tag = await _seed_realbank(conn)
        _m7_tester(monkeypatch, cid + 999999)   # allowlist KHÁC -> order khong thuoc tester
        _, _, _, st = await _ingest_process(conn, _rb_event(oid, eid=int(f"{int(time.time())%100000}32")))
        assert st == "discrepancy" and await _pay_status(conn, oid) != "confirmed"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_331_connector_off_realbank_no_autoconfirm(monkeypatch):
    """331 §3.3/§1: connector OFF -> gate không thỏa -> is_test=false vẫn escalate (không auto-confirm)."""
    monkeypatch.setattr(settings, "m7_sepay_test_connector", False)   # connector OFF
    monkeypatch.setattr(settings, "sepay_live_enabled", False)
    conn = await _conn()
    try:
        oid, cid, tag = await _seed_realbank(conn)
        _m7_tester(monkeypatch, cid)
        _, _, _, st = await _ingest_process(conn, _rb_event(oid, eid=int(f"{int(time.time())%100000}33")))
        assert st == "discrepancy" and await _pay_status(conn, oid) != "confirmed"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_331_live_flag_on_realbank_no_autoconfirm(monkeypatch):
    """331 §1: sepay_live_enabled ON -> gate không thỏa -> escalate (không auto-confirm real-bank)."""
    monkeypatch.setattr(settings, "m7_sepay_test_connector", True)
    monkeypatch.setattr(settings, "sepay_live_enabled", True)   # live ON -> reject real-bank auto-confirm
    conn = await _conn()
    try:
        oid, cid, tag = await _seed_realbank(conn)
        _m7_tester(monkeypatch, cid)
        _, _, _, st = await _ingest_process(conn, _rb_event(oid, eid=int(f"{int(time.time())%100000}34")))
        assert st == "discrepancy" and await _pay_status(conn, oid) != "confirmed"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_331_tester_realbank_mismatch_failclosed(monkeypatch):
    """331 §3.4: tester real-bank nhưng amount/content sai -> vẫn fail-closed (no false-positive)."""
    monkeypatch.setattr(settings, "m7_sepay_test_connector", True)
    monkeypatch.setattr(settings, "sepay_live_enabled", False)
    conn = await _conn()
    try:
        # wrong amount
        oid, cid, tag = await _seed_realbank(conn)
        _m7_tester(monkeypatch, cid)
        _, _, _, st = await _ingest_process(conn, _rb_event(oid, amount=99999, eid=int(f"{int(time.time())%100000}35")))
        assert st == "discrepancy" and await _pay_status(conn, oid) != "confirmed"
        # foreign prefix (3SCF) -> snapshot mismatch
        oid2, cid2, tag2 = await _seed_realbank(conn)
        _m7_tester(monkeypatch, cid2)
        _, _, _, st2 = await _ingest_process(conn, _event(oid2, content=f"3SCF {oid2}",
                                                          eid=int(f"{int(time.time())%100000}36")))
        assert st2 == "discrepancy" and await _pay_status(conn, oid2) != "confirmed"
    finally:
        await conn.close()
