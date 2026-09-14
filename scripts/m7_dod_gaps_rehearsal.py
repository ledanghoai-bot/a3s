#!/usr/bin/env python3
"""M7 DoD gap rehearsal (CA Directive 272 §5) — bù coverage: Money nonzero fee / GHN versioned map (cache) /
Recovery crash-between-ingest-process / SePay extra branches. Chay m5lab (schema >= 065 revised).

Bổ sung cho m7_conversational_rehearsal.py + m7_amendment273_rehearsal.py. Re-runnable (RUN suffix).
"""
import asyncio
import json
import os
import sys
import time

import asyncpg

from app.config import settings
from app.services.fulfillment import conversation as C
from app.services.fulfillment import shipment_service as SH
from app.services.payment import provider_ingest as PI
from app.services.providers import ghn as GHN
from app.services.providers import sepay as SP

RUN = str(int(time.time()))
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")
ACCT = "0011223344"
FAILS = []
_SEQ = [0]


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


async def _mk_order(conn, *, ward="24169", qty=2, price=100000, snapshot=True):
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    psid = f"tg:m7g-{tag}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'G','0900000000') RETURNING id", psid)
    pid = await conn.fetchval(
        "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) VALUES($1,'CF',$2,999,300,'hũ') "
        "RETURNING id", f"M7G-{tag}", price)
    total = qty * price
    oid = await conn.fetchval(
        "INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',$2,'telegram_customer') "
        "RETURNING id", cid, total)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,$3,$4)",
                       oid, pid, qty, price)
    if snapshot:
        rid = await conn.fetchval(
            "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,"
            "method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,'66',$1,'current',1.0) RETURNING id",
            ward)
        await conn.execute(
            "INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,dataset_version,"
            "verification_method,bound_by) VALUES($1,$2,'66',$3,'VN-TEST','test','gap')", oid, rid, ward)
    return oid, psid, total


async def _mk_transfer(conn, *, amount_due=200000):
    """Order + BANK_TRANSFER payment + instruction (account ACCT) — cho SePay/Recovery tests."""
    oid, psid, _ = await _mk_order(conn)
    await conn.execute("UPDATE orders SET total_vnd=$2 WHERE id=$1", oid, amount_due)
    payid = await conn.fetchval(
        "INSERT INTO payments(order_id,method,amount_due_vnd,status) VALUES($1,'BANK_TRANSFER',$2,'awaiting') RETURNING id",
        oid, amount_due)
    iid = await conn.fetchval(
        "INSERT INTO payment_instructions(order_id,payment_id,bank_account_id,account_version,bank_snapshot,"
        "account_number_snapshot,holder_snapshot,transfer_content,amount_vnd,is_test,command_key) VALUES "
        "($1,$2,$5,1,'VTB',$6,'H',$3,$4,true,$7) RETURNING id", oid, payid, f"3SCF {oid}", amount_due,
        await _bank_id(conn), ACCT, f"g:{oid}")
    return oid, payid, iid


async def _bank_id(conn):
    bid = await conn.fetchval("SELECT id FROM bank_accounts WHERE account_number=$1", ACCT)
    if bid is None:
        bid = await conn.fetchval(
            "INSERT INTO bank_accounts(bank,account_number,holder_name,version,active,is_test) "
            "VALUES('VTB',$1,'GAP',1,false,true) RETURNING id", ACCT)
    return bid


async def _sepay(conn, *, ev_id, order_id, amount, direction="in", content=None, account=ACCT):
    raw = json.dumps({"id": ev_id, "gateway": "VietinBank", "transactionDate": "2026-09-14 10:00:00",
                      "accountNumber": account, "content": content if content is not None else f"3SCF {order_id}",
                      "transferType": direction, "transferAmount": amount,
                      "referenceCode": f"R-{RUN}-{ev_id}"}).encode()
    ev = SP.parse_envelope(raw)
    async with conn.transaction():
        rid, _created, _conflict = await PI.ingest(conn, ev, mode="test")
    async with conn.transaction():
        st = await PI.process(conn, rid)
    return rid, st


async def main():  # noqa: C901
    settings.sepay_allowed_accounts = ACCT
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute("INSERT INTO delivery_zones(province_code,ward_code,zone) VALUES('66','24169','bmt_inner') "
                           "ON CONFLICT DO NOTHING")

        # ---------- Money: nonzero fee end-to-end (staff manual quote) ----------
        oid, psid, goods = await _mk_order(conn)
        await C.ensure_started(conn, oid, channel="telegram_customer", customer_ref=psid, command_key=f"s:{oid}")
        async with conn.transaction():
            await SH.set_manual_quote(conn, oid, actor="staff", zone="province", weight_g=300, fee_vnd=40000)
        async with conn.transaction():
            fc = await C.advance_routing(conn, oid, ghn_result=None)
        prompt = await conn.fetchval(
            "SELECT reply_text FROM fulfillment_conversation_events WHERE order_id=$1 AND to_step='awaiting_method' "
            "ORDER BY id DESC LIMIT 1", oid)
        async with conn.transaction():
            await C.handle_customer_text(conn, psid, "COD", command_key=f"m:{oid}")
        due = await conn.fetchval("SELECT amount_due_vnd FROM payments WHERE order_id=$1", oid)
        total_txt = f"{(goods + 40000):,}".replace(",", ".")
        ck("Money nonzero: total prompt = goods+fee, due = goods+fee (integer VND)",
           fc["step"] == "awaiting_method" and due == goods + 40000 and total_txt in (prompt or ""),
           f"due={due} goods={goods} total_txt={total_txt}")

        # ---------- GHN versioned address map (cache = version-based, snapshot-safe) ----------
        await conn.execute(
            "INSERT INTO carrier_address_map(provider,map_version,province_code,ward_code,carrier_province_id,"
            "carrier_district_id,carrier_ward_code,status,method) VALUES "
            "('ghn',1,'66','99001',201,1001,'W1','matched','x'),('ghn',2,'66','99001',201,2002,'W2','matched','x') "
            "ON CONFLICT DO NOTHING")
        m1 = await GHN.address_lookup(conn, "66", "99001", map_version=1)
        m2 = await GHN.address_lookup(conn, "66", "99001", map_version=2)
        ck("GHN versioned map: v1 vs v2 tách biệt (đổi version KHÔNG sửa map cũ)",
           m1 and m1["carrier_district_id"] == 1001 and m2 and m2["carrier_district_id"] == 2002,
           f"v1={m1['carrier_district_id'] if m1 else None} v2={m2['carrier_district_id'] if m2 else None}")

        # ---------- SePay extra branches ----------
        # payment_not_bank_transfer: order COD
        oidc, pc, _ = await _mk_order(conn)
        await conn.execute("UPDATE orders SET total_vnd=200000 WHERE id=$1", oidc)
        await conn.execute("INSERT INTO payments(order_id,method,amount_due_vnd,status) VALUES($1,'COD',200000,'awaiting')",
                           oidc)
        _, st = await _sepay(conn, ev_id=f"{RUN}-cod", order_id=oidc, amount=200000)
        ck("SePay payment_not_bank_transfer -> unmatched", st == "unmatched", st)

        # no_instruction: BANK_TRANSFER payment, khong instruction
        oidn, _pn, _ = await _mk_order(conn)
        await conn.execute("UPDATE orders SET total_vnd=200000 WHERE id=$1", oidn)
        await conn.execute("INSERT INTO payments(order_id,method,amount_due_vnd,status) "
                           "VALUES($1,'BANK_TRANSFER',200000,'awaiting')", oidn)
        _, st = await _sepay(conn, ev_id=f"{RUN}-noinstr", order_id=oidn, amount=200000)
        ck("SePay no_instruction -> unmatched", st == "unmatched", st)

        # CA 274-01: same event ID / KHAC hash -> conflict (fail-closed), khong xu ly payload cu nhu duplicate lanh
        oidc2, _p2, _i2 = await _mk_transfer(conn)
        raw1 = json.dumps({"id": f"{RUN}-conf", "gateway": "VietinBank", "accountNumber": ACCT,
                           "content": f"3SCF {oidc2}", "transferType": "in", "transferAmount": 200000,
                           "referenceCode": "R1"}).encode()
        raw2 = json.dumps({"id": f"{RUN}-conf", "gateway": "VietinBank", "accountNumber": ACCT,
                           "content": f"3SCF {oidc2}", "transferType": "in", "transferAmount": 999999,
                           "referenceCode": "R2"}).encode()
        async with conn.transaction():
            _r, c1, cf1 = await PI.ingest(conn, SP.parse_envelope(raw1), mode="test")
        async with conn.transaction():
            _r2, c2, cf2 = await PI.ingest(conn, SP.parse_envelope(raw2), mode="test")
        le = await conn.fetchval("SELECT last_error FROM provider_events WHERE provider_event_id=$1", f"{RUN}-conf")
        ck("SePay same ID same-hash=replay / different-hash=conflict (fail-closed, last_error ghi)",
           c1 is True and cf1 is False and c2 is False and cf2 is True and le == "payload_hash_conflict",
           f"c1={c1} cf1={cf1} c2={c2} cf2={cf2} le={le}")

        # amount_invalid: transferAmount = 0
        oidi, _pi2, _ii = await _mk_transfer(conn)
        _, st = await _sepay(conn, ev_id=f"{RUN}-amt0", order_id=oidi, amount=0)
        ck("SePay amount_invalid (0) -> unmatched", st == "unmatched", st)

        # ---------- Recovery: crash GIỮA ingest và process -> event giữ 'received', không double effect ----------
        oidr, payr, iidr = await _mk_transfer(conn)
        raw = json.dumps({"id": f"{RUN}-recov", "gateway": "VietinBank", "transactionDate": "2026-09-14 10:00:00",
                          "accountNumber": ACCT, "content": f"3SCF {oidr}", "transferType": "in",
                          "transferAmount": 200000, "referenceCode": f"R-{RUN}-recov"}).encode()
        ev = SP.parse_envelope(raw)
        async with conn.transaction():
            rid, _c, _cf = await PI.ingest(conn, ev, mode="test")
        orig = PI._pay.record_provider_confirmation

        async def _boom(*a, **k):
            raise RuntimeError("crash giua process (mo phong)")
        PI._pay.record_provider_confirmation = _boom
        crashed = False
        try:
            async with conn.transaction():
                await PI.process(conn, rid)
        except RuntimeError:
            crashed = True
        PI._pay.record_provider_confirmation = orig
        state_after = await conn.fetchval("SELECT processing_state FROM provider_events WHERE id=$1", rid)
        pe_cnt = await conn.fetchval("SELECT count(*) FROM payment_events WHERE payment_id=$1 AND kind='bank_auto_confirmed'", payr)
        pay_status = await conn.fetchval("SELECT status FROM payments WHERE order_id=$1", oidr)
        ck("Recovery crash: event giữ 'received', KHÔNG payment_event, payment còn awaiting (tx rollback)",
           crashed and state_after == "received" and pe_cnt == 0 and pay_status == "awaiting",
           f"crashed={crashed} state={state_after} pe={pe_cnt} pay={pay_status}")
        # retry sau khi phục hồi -> matched DUNG 1 LAN
        async with conn.transaction():
            st2 = await PI.process(conn, rid)
        pe_cnt2 = await conn.fetchval("SELECT count(*) FROM payment_events WHERE payment_id=$1 AND kind='bank_auto_confirmed'", payr)
        ck("Recovery retry sau phục hồi -> matched, đúng 1 bank_auto_confirmed (không double)",
           st2 == "matched" and pe_cnt2 == 1, f"st={st2} pe={pe_cnt2}")

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
