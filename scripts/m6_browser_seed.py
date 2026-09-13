#!/usr/bin/env python3
"""Seed cho browser smoke 267-05: tao staff (full M6 perms) + session token + 2 don.
In ra JSON {token, order_instr, order_disc} de browser smoke dung. Chay tren m5lab.
 - order_instr: BANK_TRANSFER + quoted + co active bank account -> browser tao/nhin/copy instruction.
 - order_disc: BANK_TRANSFER + quoted + excess -> discrepancy -> browser chon event goc + correction + reload.
"""
import asyncio
import json
import os
import sys
import time

import asyncpg

from app.services import auth_service
from app.services.fulfillment import shipment_service as ship
from app.services.payment import payment_service as pay

RUN = str(int(time.time()))
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")


async def _mk_order(conn, total=200000):
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'Smoke','0900000000') RETURNING id",
                              f"tg:m6sm-{RUN}-{total}-{await conn.fetchval('SELECT count(*) FROM customers')}")
    pid = await conn.fetchval(
        "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g) VALUES($1,'CF',$2,999,600) "
        "ON CONFLICT(sku) DO UPDATE SET shipping_weight_g=600 RETURNING id", f"SMOKE-{RUN}-{total}", total)
    oid = await conn.fetchval(
        "INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',$2,"
        "'telegram_customer') RETURNING id", cid, total)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,1,$3)",
                       oid, pid, total)
    await ship.set_manual_quote(conn, oid, actor="seed", zone="province", weight_g=600, fee_vnd=30000)
    await pay.ensure_payment(conn, oid, method="BANK_TRANSFER", actor="seed")
    return oid


async def main():
    conn = await asyncpg.connect(DSN)
    try:
        uname = f"smoke_{RUN}"
        st = await auth_service.create_staff_user(uname, "smoke_pw_12345678", "SMOKE PO", role_key="admin")
        token = await auth_service.create_session(st["id"])

        # active bank account (PO) de instruction phat duoc
        await pay.set_bank_account(conn, bank="VIETCOMBANK", account_number="0123456789",
                                   holder_name="CONG TY 3S COFFEE", actor="seed", is_test=False)

        order_instr = await _mk_order(conn, total=200000)       # due 230000

        order_disc = await _mk_order(conn, total=200000)        # due 230000
        await pay.record_evidence(conn, order_disc, kind="customer_reported", amount_vnd=250000, recorded_by="cust",
                                  command_key=f"{RUN}-seed-rep")
        await pay.record_evidence(conn, order_disc, kind="shop_confirmed_received", amount_vnd=250000,
                                  recorded_by="po", command_key=f"{RUN}-seed-conf")   # 250k/230k -> discrepancy excess

        print(json.dumps({"token": token, "order_instr": order_instr, "order_disc": order_disc,
                          "username": uname}))
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
