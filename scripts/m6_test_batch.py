"""M6 test batch tooling (CA Directive 265 §5). Tao / list / cleanup batch test co ID.

- create: tao N don test (customer psid 'm6test:<batch>:<seq>', origin telegram_customer, KHONG snapshot M5 ->
  fully cleanable) + shipment (manual zone/fee) + payment (COD/transfer luan phien) + vai evidence.
- list: liet ke batch + so don.
- cleanup: preview EXACT IDs (mac dinh) hoac --apply xoa DUNG batch do (SET LOCAL m6.cleanup='on' de xoa
  append-only test; KHONG dung production, KHONG truncate, KHONG sua migration ledger). Chi record co psid
  prefix m6test:<batch>:.

Usage:
  python scripts/m6_test_batch.py create --n 3 [--batch <id>]
  python scripts/m6_test_batch.py list
  python scripts/m6_test_batch.py cleanup --batch <id> [--apply]
"""
import argparse
import asyncio
import os
import time

import asyncpg

from app.services.fulfillment import shipment_service as ship
from app.services.payment import payment_service as pay

DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")


def _prefix(batch: str) -> str:
    return f"m6test:{batch}:"


async def create(conn, batch: str, n: int) -> list[int]:
    # bank fixture test (nhan ro TEST)
    await pay.set_bank_account(conn, bank="TEST BANK — KHONG CHUYEN TIEN", account_number="00000000",
                              holder_name="ROBANME TEST", actor=f"m6batch:{batch}", is_test=True)
    order_ids = []
    for seq in range(1, n + 1):
        psid = f"{_prefix(batch)}{seq}"
        cid = await conn.fetchval(
            "INSERT INTO customers(psid,name,phone) VALUES($1,$2,'0900000000') RETURNING id",
            psid, f"TEST batch {batch} #{seq}")
        pid = await conn.fetchval(
            "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g) VALUES($1,'CF test',150000,999,600) "
            "ON CONFLICT(sku) DO UPDATE SET shipping_weight_g=600 RETURNING id", f"M6TEST-{batch}-{seq}")
        oid = await conn.fetchval(
            "INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',150000,"
            "'telegram_customer') RETURNING id", cid)
        await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) "
                           "VALUES($1,$2,1,150000)", oid, pid)
        # shipment: manual zone/fee luan phien (bmt_inner free / province 30k)
        if seq % 2 == 1:
            await ship.set_manual_quote(conn, oid, actor=f"m6batch:{batch}", zone="province", weight_g=600,
                                        fee_vnd=30000, eta_text="dự kiến 1–3 ngày")
            method = "COD"
        else:
            await ship.set_manual_quote(conn, oid, actor=f"m6batch:{batch}", zone="bmt_inner", weight_g=600,
                                        fee_vnd=0, eta_text="khoảng 3 giờ")
            method = "BANK_TRANSFER"
        await pay.ensure_payment(conn, oid, method=method, actor=f"m6batch:{batch}")
        await pay.recompute_amount_due(conn, oid, actor=f"m6batch:{batch}")
        order_ids.append(oid)
    return order_ids


async def batch_ids(conn, batch: str) -> dict:
    rows = await conn.fetch(
        "SELECT o.id AS order_id, cu.id AS customer_id, s.id AS shipment_id, p.id AS payment_id "
        "FROM customers cu JOIN orders o ON o.customer_id=cu.id "
        "LEFT JOIN shipments s ON s.order_id=o.id LEFT JOIN payments p ON p.order_id=o.id "
        "WHERE cu.psid LIKE $1", _prefix(batch) + "%")
    return {"orders": [r["order_id"] for r in rows],
            "customers": sorted({r["customer_id"] for r in rows}),
            "shipments": [r["shipment_id"] for r in rows if r["shipment_id"]],
            "payments": [r["payment_id"] for r in rows if r["payment_id"]]}


async def cleanup(conn, batch: str, apply: bool) -> dict:
    ids = await batch_ids(conn, batch)
    if not apply:
        return {"preview": ids}
    async with conn.transaction():
        await conn.execute("SET LOCAL m6.cleanup = 'on'")  # cho phep xoa append-only test (chi trong tx nay)
        sh_ids = ids["shipments"]
        p_ids = ids["payments"]
        o_ids = ids["orders"]
        c_ids = ids["customers"]
        if p_ids:
            await conn.execute("DELETE FROM payment_events WHERE payment_id = ANY($1::bigint[])", p_ids)
            await conn.execute("DELETE FROM payment_instructions WHERE payment_id = ANY($1::bigint[])", p_ids)
        if sh_ids:
            await conn.execute("DELETE FROM shipment_delivery_attempts WHERE shipment_id = ANY($1::bigint[])", sh_ids)
        if p_ids:
            await conn.execute("DELETE FROM payments WHERE id = ANY($1::bigint[])", p_ids)
        if sh_ids:
            await conn.execute("DELETE FROM shipments WHERE id = ANY($1::bigint[])", sh_ids)
        if o_ids:
            await conn.execute("DELETE FROM order_items WHERE order_id = ANY($1::bigint[])", o_ids)
            await conn.execute("DELETE FROM orders WHERE id = ANY($1::bigint[])", o_ids)
        if c_ids:
            await conn.execute("DELETE FROM customers WHERE id = ANY($1::bigint[])", c_ids)
    return {"deleted": ids}


async def list_batches(conn) -> list[dict]:
    rows = await conn.fetch(
        "SELECT split_part(substring(psid from 8), ':', 1) AS batch, count(*) AS orders "
        "FROM customers cu JOIN orders o ON o.customer_id=cu.id WHERE cu.psid LIKE 'm6test:%' "
        "GROUP BY 1 ORDER BY 1")
    return [dict(r) for r in rows]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["create", "list", "cleanup"])
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--batch", default=None)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = await asyncpg.connect(DSN)
    try:
        if args.cmd == "create":
            batch = args.batch or str(int(time.time()))
            oids = await create(conn, batch, args.n)
            print(f"BATCH {batch} created: orders={oids}  (cleanup: --batch {batch})")
        elif args.cmd == "list":
            for b in await list_batches(conn):
                print(f"  batch={b['batch']}  orders={b['orders']}")
        elif args.cmd == "cleanup":
            if not args.batch:
                raise SystemExit("cleanup can --batch <id>")
            out = await cleanup(conn, args.batch, args.apply)
            print(("APPLIED " if args.apply else "PREVIEW ") + str(out))
    finally:
        await conn.close()


asyncio.run(main())
