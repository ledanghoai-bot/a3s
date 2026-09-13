#!/usr/bin/env python3
"""M6 test-batch isolation — CA Review 267-04. Co account non-test + batch A + batch B + order ngoai batch.

PASS:
  - create/cleanup A/B KHONG doi active bank account (van la account PO nhap).
  - instruction ngoai batch KHONG bi fixture batch lam sai (account active on dinh).
  - interruption giua create/cleanup KHONG de fixture active (mac dinh batch khong dong vao bank global).
Mac dinh: m6_test_batch.create KHONG tao/thay bank account; chi dung account active san co de phat instruction.
Chay tren m5lab.
"""
import asyncio
import os
import sys
import time

import asyncpg

from app.services.payment import payment_service as pay
from scripts import m6_test_batch as batch

RUN = str(int(time.time()))
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")
FAILS = []


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


async def _active(conn):
    return await conn.fetchrow("SELECT id, account_number, holder_name FROM bank_accounts WHERE active")


async def main():
    conn = await asyncpg.connect(DSN)
    try:
        # Account non-test do "PO" cau hinh (account that)
        po_acct = await pay.set_bank_account(conn, bank="PO BANK", account_number=f"PO{RUN[-6:]}",
                                             holder_name="PO THAT", actor="po_setup", is_test=False)
        before = await _active(conn)
        ck("setup: co active account non-test cua PO", before and before["id"] == po_acct["id"],
           before["account_number"] if before else None)

        # batch A + B (mac dinh: KHONG bank fixture)
        await batch.create(conn, f"ISOA{RUN}", 2)
        await batch.create(conn, f"ISOB{RUN}", 2)
        mid = await _active(conn)
        ck("sau create A+B: active account KHONG doi (van PO)", mid and mid["id"] == po_acct["id"],
           f"{mid['account_number'] if mid else None}")

        # order ngoai batch dung account active -> instruction tro dung account PO
        cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'EXT','0900000000') RETURNING id",
                                  f"tg:ext-{RUN}")
        pid = await conn.fetchval(
            "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g) VALUES($1,'CF',200000,999,600) "
            "ON CONFLICT(sku) DO UPDATE SET shipping_weight_g=600 RETURNING id", f"EXT-{RUN}")
        ext_oid = await conn.fetchval(
            "INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',200000,"
            "'telegram_customer') RETURNING id", cid)
        await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,1,200000)",
                           ext_oid, pid)
        from app.services.fulfillment import shipment_service as ship
        await ship.set_manual_quote(conn, ext_oid, actor="po", zone="province", weight_g=600, fee_vnd=30000)
        await pay.ensure_payment(conn, ext_oid, method="BANK_TRANSFER", actor="po")
        instr = await pay.generate_instruction(conn, ext_oid, actor="po")
        ck("instruction ngoai batch dung dung account PO (khong bi fixture batch)",
           instr["account_number_snapshot"] == po_acct["account_number"] and instr["is_test"] is False,
           f"{instr['account_number_snapshot']} test={instr['is_test']}")

        # cleanup B roi A -> active account van PO
        await batch.cleanup(conn, f"ISOB{RUN}", apply=True)
        await batch.cleanup(conn, f"ISOA{RUN}", apply=True)
        after = await _active(conn)
        ck("sau cleanup A+B: active account VAN PO (khong mat/khong doi)", after and after["id"] == po_acct["id"],
           f"{after['account_number'] if after else None}")

        # interruption: create A2 (khong cleanup) -> active van PO (mac dinh khong tao fixture active)
        await batch.create(conn, f"ISOC{RUN}", 1)
        during = await _active(conn)
        ck("interruption giua create/cleanup: active VAN PO (khong co fixture active)",
           during and during["id"] == po_acct["id"], f"{during['account_number'] if during else None}")
        await batch.cleanup(conn, f"ISOC{RUN}", apply=True)

        # guard: --bank-fixture khong co M6_TEST_DB -> tu choi (SystemExit)
        os.environ.pop("M6_TEST_DB", None)
        try:
            await batch.create(conn, f"ISOD{RUN}", 1, bank_fixture=True)
            ck("guard: bank_fixture khong M6_TEST_DB -> tu choi", False, "khong raise")
        except SystemExit:
            ck("guard: bank_fixture khong M6_TEST_DB -> tu choi", True)

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
