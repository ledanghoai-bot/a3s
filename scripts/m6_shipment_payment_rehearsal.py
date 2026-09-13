"""M6 shipment + payment — DB rehearsal (CA Directive 265 §5). Chay tren m5lab (schema >= 064).

Chung minh: auto_quote (bmt_inner fee 0 / province 30k), COD e2e (collected->reconciled), transfer e2e
(reported->confirmed) + instruction, partial khong auto-confirm, idempotency evidence theo reference, max 3
attempts, wrong transition reject. KHONG PII/secret. Re-runnable (RUN suffix).
"""
import asyncio
import os
import sys
import time

import asyncpg

from app.services.fulfillment import shipment_service as ship
from app.services.payment import payment_service as pay

RUN = str(int(time.time()))
FAILS = []
_SEQ = [0]
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


async def _mk_order(conn, *, ward, weight, qty, total):
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'Test','0900000000') RETURNING id",
                              f"tg:m6-{tag}")
    pid = await conn.fetchval(
        "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g) VALUES($1,'CF',$2,999,$3) "
        "ON CONFLICT(sku) DO UPDATE SET shipping_weight_g=$3 RETURNING id", f"M6-{tag}", total, weight)
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd) VALUES($1,'confirmed',$2) RETURNING id",
                              cid, total)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,$3,$4)",
                       oid, pid, qty, total)
    rid = await conn.fetchval(
        "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,"
        "method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,'66',$1,'current',1.0) "
        "RETURNING id", ward)
    await conn.execute(
        "INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,dataset_version,"
        "verification_method,bound_by) VALUES($1,$2,'66',$3,'VN-TEST','test','rehearsal')", oid, rid, ward)
    return oid


async def main():
    conn = await asyncpg.connect(DSN)
    try:
        # zone config (PO cau hinh): 66/24169 = bmt_inner ; 66/NULL = province default
        await conn.execute("INSERT INTO delivery_zones(province_code,ward_code,zone) VALUES('66','24169','bmt_inner') "
                           "ON CONFLICT DO NOTHING")
        await conn.execute("INSERT INTO delivery_zones(province_code,ward_code,zone) VALUES('66',NULL,'province') "
                           "ON CONFLICT DO NOTHING")

        # G1: auto_quote
        oid_bmt = await _mk_order(conn, ward="24169", weight=300, qty=2, total=200000)  # 600g bmt_inner -> fee 0
        q1 = await ship.auto_quote(conn, oid_bmt, actor="staff1")
        ck("G1 bmt_inner 600g -> fee 0 quoted", q1["zone"] == "bmt_inner" and q1["delivery_fee_vnd"] == 0
           and q1["fee_status"] == "quoted", f"{q1['zone']}/{q1['delivery_fee_vnd']}/{q1['fee_status']}")
        oid_prov = await _mk_order(conn, ward="99999", weight=300, qty=2, total=200000)  # province -> fee 30000
        q2 = await ship.auto_quote(conn, oid_prov, actor="staff1")
        ck("G1 province 600g -> fee 30000 quoted", q2["zone"] == "province" and q2["delivery_fee_vnd"] == 30000,
           f"{q2['zone']}/{q2['delivery_fee_vnd']}")

        # G2: COD e2e
        p_cod = await pay.ensure_payment(conn, oid_prov, method="COD", actor="staff1")
        ck("G2 COD amount_due = total+fee = 230000", p_cod["amount_due_vnd"] == 230000, p_cod["amount_due_vnd"])
        await ship.change_status(conn, oid_prov, "ready_to_ship", actor="staff1")
        s_it = await ship.change_status(conn, oid_prov, "in_transit", actor="staff1")
        ck("G2 in_transit set handover_at", s_it["handover_at"] is not None)
        a = await ship.record_attempt(conn, oid_prov, actor="delivery1", result="success")
        ck("G2 attempt success -> delivered", a["shipment_status"] == "delivered", a["shipment_status"])
        r = await pay.record_evidence(conn, oid_prov, kind="cod_collected", amount_vnd=230000, recorded_by="delivery1")
        ck("G2 cod_collected -> collected", r["status"] == "collected", r["status"])
        r2 = await pay.record_evidence(conn, oid_prov, kind="reconciled", amount_vnd=230000, recorded_by="po")
        ck("G2 reconciled(du tien) -> reconciled", r2["status"] == "reconciled" and r2["discrepancy"] is None,
           r2["status"])

        # G3: transfer e2e + instruction
        await pay.set_bank_account(conn, bank="TEST BANK", account_number="00012345",
                                   holder_name="ROBANME TEST", actor="po", is_test=True)
        p_tr = await pay.ensure_payment(conn, oid_bmt, method="BANK_TRANSFER", actor="staff1")
        ck("G3 transfer amount_due = 200000 (fee 0)", p_tr["amount_due_vnd"] == 200000, p_tr["amount_due_vnd"])
        instr = await pay.generate_instruction(conn, oid_bmt, actor="staff1")
        ck("G3 instruction deterministic content + acct 0-dau giu",
           instr["transfer_content"] == f"3SCF {oid_bmt}" and instr["account_number_snapshot"] == "00012345"
           and instr["is_test"] is True, instr["transfer_content"])
        rr = await pay.record_evidence(conn, oid_bmt, kind="customer_reported", amount_vnd=200000,
                                       recorded_by="customer", reference="FT123")
        ck("G3 customer_reported -> reported (khong tu confirmed)", rr["status"] == "reported", rr["status"])
        rc = await pay.record_evidence(conn, oid_bmt, kind="shop_confirmed_received", amount_vnd=200000,
                                       recorded_by="po")
        ck("G3 shop_confirmed(du) -> confirmed", rc["status"] == "confirmed", rc["status"])

        # G4: partial khong auto-confirm
        oid_p = await _mk_order(conn, ward="99999", weight=300, qty=2, total=200000)
        await ship.auto_quote(conn, oid_p, actor="staff1")
        await pay.ensure_payment(conn, oid_p, method="BANK_TRANSFER", actor="staff1")
        await pay.record_evidence(conn, oid_p, kind="customer_reported", amount_vnd=100000, recorded_by="customer")
        rp = await pay.record_evidence(conn, oid_p, kind="shop_confirmed_received", amount_vnd=100000,
                                       recorded_by="po")
        ck("G4 partial (100k/230k) KHONG auto-confirm", rp["status"] != "confirmed"
           and rp["discrepancy"] and rp["discrepancy"]["kind"] == "partial", rp["status"])

        # G5: idempotency evidence theo reference
        n_before = await conn.fetchval(
            "SELECT count(*) FROM payment_events pe JOIN payments p ON p.id=pe.payment_id WHERE p.order_id=$1 "
            "AND pe.reference='FT123'", oid_bmt)
        dup = await pay.record_evidence(conn, oid_bmt, kind="customer_reported", amount_vnd=200000,
                                        recorded_by="customer", reference="FT123")
        n_after = await conn.fetchval(
            "SELECT count(*) FROM payment_events pe JOIN payments p ON p.id=pe.payment_id WHERE p.order_id=$1 "
            "AND pe.reference='FT123'", oid_bmt)
        ck("G5 cung reference -> duplicate, khong ghi/cong lan 2", dup["duplicate"] is True and n_after == n_before,
           f"{n_before}->{n_after}")

        # G6: max 3 attempts
        oid_f = await _mk_order(conn, ward="99999", weight=300, qty=2, total=200000)
        await ship.auto_quote(conn, oid_f, actor="staff1")
        await ship.change_status(conn, oid_f, "ready_to_ship", actor="staff1")
        await ship.change_status(conn, oid_f, "in_transit", actor="staff1")
        for i in range(3):
            await ship.record_attempt(conn, oid_f, actor="delivery1", result="failed", reason="no answer")
        try:
            await ship.record_attempt(conn, oid_f, actor="delivery1", result="failed")
            ck("G6 attempt thu 4 bi tu choi", False, "khong raise")
        except ship.ShipmentError:
            ck("G6 attempt thu 4 bi tu choi (max 3)", True)

        # G7: wrong transition
        try:
            await ship.change_status(conn, oid_prov, "in_transit", actor="staff1")  # dang delivered
            ck("G7 delivered->in_transit reject", False, "khong raise")
        except ship.ShipmentError:
            ck("G7 transition sai bi reject", True)

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        sys.exit(1 if FAILS else 0)
    finally:
        await conn.close()


asyncio.run(main())
