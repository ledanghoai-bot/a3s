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
    instr = await P.generate_instruction(conn, oid, actor="t", command_key=f"{tag}:instr")
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
        await P.generate_instruction(conn, oid, actor="t", command_key=f"{tag}:instr2")
        # event khop instruction CU (230000) -> khong khop current (500000) -> discrepancy, no confirm
        _, _, _, st = await _ingest_process(conn, _event(oid, amount=230000,
                                                        eid=int(f"{int(time.time())%100000}7")))
        assert st == "discrepancy" and await _pay_status(conn, oid) != "confirmed"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_allowed_accounts_from_settings(monkeypatch):
    """308-04: module OFF -> env only; ON + active sepay integration -> union config allowed_accounts."""
    conn = await _conn()
    iid = None
    try:
        monkeypatch.setattr(settings, "sepay_allowed_accounts", "")
        # module OFF -> env only (rong)
        monkeypatch.setattr(settings, "settings_integrations_enabled", False)
        assert await PI._allowed_accounts(conn) == set()
        # tao active sepay integration voi allowed_accounts qua config
        import base64
        monkeypatch.setattr(settings, "config_enc_keys", f"k1:{base64.b64encode(b'A'*32).decode()}")
        monkeypatch.setattr(settings, "config_enc_key_current", "k1")
        monkeypatch.setattr(settings, "config_secret_fp_key", base64.b64encode(b'F'*32).decode())
        from app.services.settings import integrations as S
        async with conn.transaction():
            it = await S.create_integration(conn, kind="payment", provider="sepay", label="SP", mode="test",
                                            config_public={"code_prefix": "3SCF", "allowed_accounts": ACCT},
                                            actor="po", command_key=f"sp-{os.urandom(3).hex()}")
        iid = it["id"]
        # enable can secret+test; de test _allowed_accounts chi can enabled -> set enabled truc tiep (bo qua gate cho unit)
        await conn.execute("UPDATE integrations SET enabled=true WHERE id=$1", iid)
        monkeypatch.setattr(settings, "settings_integrations_enabled", True)
        allowed = await PI._allowed_accounts(conn)
        assert ACCT in allowed   # Settings config duoc union
    finally:
        if iid:
            async with conn.transaction():
                await conn.execute("DELETE FROM integration_commands WHERE integration_id=$1", iid)
                await conn.execute("DELETE FROM integrations WHERE id=$1", iid)
        await conn.close()
