#!/usr/bin/env python3
"""M7 test batch runbook (CA Directive 272 §5 Cleanup + §7). create / list / cleanup exact-ID.

- create: N don test (customer psid 'm7test:<batch>:<seq>', products sales_unit='hũ') driven qua conversational
  flow that (ensure_started -> advance_routing -> COD | CK). Sinh rows across M7 tables (conversations, events,
  staff_attention, instructions, reminders, provider_events) de test cleanup day du.
- list: liet ke batch + so don.
- cleanup: preview EXACT IDs (mac dinh) hoac --apply xoa DUNG batch (FK order). Dọn M7 + M6 artifacts + test
  outbox + provider_events. KHONG doi active bank / policy / routing config dung chung. Escape LIKE. Chi record
  psid prefix m7test:<batch>:.

Usage:
  python scripts/m7_test_batch.py create --n 3 [--batch <id>]
  python scripts/m7_test_batch.py list
  python scripts/m7_test_batch.py cleanup --batch <id> [--apply]
"""
import argparse
import asyncio
import os
import time

import asyncpg

from app.services.fulfillment import conversation as C

DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")

# CA: order_address_snapshot BAT BIEN (trigger oas_no_mutate KHONG co bypass) -> batch prod-safe KHONG tao snapshot.
# Don route MANUAL_REVIEW (address) -> staff_attention; cac bang phia thanh toan (payment/instruction/reminder/
# provider_event) duoc seed truc tiep de test cleanup phu HET bang M7 ma van xoa duoc sach (khong ket snapshot).


def _prefix(batch: str) -> str:
    return f"m7test:{batch}:"


def _like(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _bank_holder(batch: str) -> str:
    return f"M7BATCH {batch}"


async def _bank_id(conn, batch: str) -> int:
    """Bank INACTIVE tag theo batch (KHONG doi active bank dung chung). Cleanup xoa theo holder."""
    bid = await conn.fetchval("SELECT id FROM bank_accounts WHERE holder_name=$1", _bank_holder(batch))
    if bid is None:
        bid = await conn.fetchval(
            "INSERT INTO bank_accounts(bank,account_number,holder_name,version,active,is_test) "
            "VALUES('TESTBANK','000000',$1,1,false,true) RETURNING id", _bank_holder(batch))
    return bid


async def _mk_order(conn, batch: str, seq: int, *, seed_transfer: bool) -> int:
    psid = f"{_prefix(batch)}{seq}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,$2,'0900000000') RETURNING id",
                              psid, f"TEST m7 {batch} #{seq}")
    pid = await conn.fetchval(
        "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
        "VALUES($1,'CF m7',100000,9999,300,'hũ') RETURNING id", f"M7T-{batch}-{seq}")
    oid = await conn.fetchval(
        "INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',200000,"
        "'telegram_customer') RETURNING id", cid)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,2,100000)",
                       oid, pid)
    # conversation flow (khong snapshot -> route MANUAL_REVIEW address -> staff_attention): phu conversations/
    # conversation_events/staff_attention/outbox
    await C.ensure_started(conn, oid, channel="telegram_customer", customer_ref=psid, command_key=f"start:{oid}")
    async with conn.transaction():
        await C.advance_routing(conn, oid, ghn_result=None)
    if seed_transfer:
        # seed truc tiep payment_instruction + reminder + provider_event (phu them cac bang thanh toan M7)
        payid = await conn.fetchval(
            "INSERT INTO payments(order_id,method,amount_due_vnd,status) VALUES($1,'BANK_TRANSFER',200000,'awaiting') "
            "RETURNING id", oid)
        iid = await conn.fetchval(
            "INSERT INTO payment_instructions(order_id,payment_id,bank_account_id,account_version,bank_snapshot,"
            "account_number_snapshot,holder_snapshot,transfer_content,amount_vnd,is_test,command_key) VALUES "
            "($1,$2,$5,1,'T','0','H',$3,200000,true,$4) RETURNING id", oid, payid, f"3SCF {oid}", f"m7t:{oid}",
            await _bank_id(conn, batch))
        await conn.execute("INSERT INTO fulfillment_reminders(payment_instruction_id,reminder_no) VALUES($1,1)", iid)
        await conn.execute(
            "INSERT INTO provider_events(provider,provider_event_id,mode,payload_hash,raw,processing_state,order_id) "
            "VALUES('sepay',$1,'test','h','{}'::jsonb,'unmatched',$2)", f"m7t-ev-{oid}", oid)
    return oid


async def create(conn, batch: str, n: int) -> list[int]:
    oids = []
    for seq in range(1, n + 1):
        oids.append(await _mk_order(conn, batch, seq, seed_transfer=(seq % 2 == 0)))
    return oids


async def batch_ids(conn, batch: str) -> dict:
    rows = await conn.fetch(
        "SELECT o.id AS oid, cu.id AS cid, s.id AS sid, p.id AS pid FROM customers cu "
        "JOIN orders o ON o.customer_id=cu.id LEFT JOIN shipments s ON s.order_id=o.id "
        "LEFT JOIN payments p ON p.order_id=o.id WHERE cu.psid LIKE $1 ESCAPE '\\'", _like(_prefix(batch)))
    oids = [r["oid"] for r in rows]
    iids = [r["id"] for r in await conn.fetch(
        "SELECT id FROM payment_instructions WHERE order_id = ANY($1::bigint[])", oids)] if oids else []
    return {"orders": oids, "customers": sorted({r["cid"] for r in rows}),
            "shipments": [r["sid"] for r in rows if r["sid"]],
            "payments": [r["pid"] for r in rows if r["pid"]], "instructions": iids}


async def cleanup(conn, batch: str, apply: bool) -> dict:
    ids = await batch_ids(conn, batch)
    if not apply:
        return {"preview": ids}
    o, c, s, p, i = (ids["orders"], ids["customers"], ids["shipments"], ids["payments"], ids["instructions"])
    active_before = await conn.fetchval("SELECT id FROM bank_accounts WHERE active")
    async with conn.transaction():
        await conn.execute("SET LOCAL m6.cleanup = 'on'")
        if o:
            await conn.execute("DELETE FROM delivery_attempts da USING outbox_events oe WHERE da.outbox_event_id=oe.id "
                               "AND (oe.payload->>'order_id')::bigint = ANY($1::bigint[])", o)
            await conn.execute("DELETE FROM outbox_events WHERE (payload->>'order_id')::bigint = ANY($1::bigint[])", o)
            await conn.execute("DELETE FROM provider_events WHERE order_id = ANY($1::bigint[])", o)
            await conn.execute("DELETE FROM provider_quote_log WHERE order_id = ANY($1::bigint[])", o)
            await conn.execute("DELETE FROM staff_attention WHERE order_id = ANY($1::bigint[])", o)
            await conn.execute("DELETE FROM fulfillment_conversation_events WHERE order_id = ANY($1::bigint[])", o)
        if i:
            await conn.execute("DELETE FROM fulfillment_reminders WHERE payment_instruction_id = ANY($1::bigint[])", i)
        if o:
            await conn.execute("DELETE FROM fulfillment_conversations WHERE order_id = ANY($1::bigint[])", o)
        if p:
            await conn.execute("DELETE FROM payment_events WHERE payment_id = ANY($1::bigint[])", p)
            await conn.execute("DELETE FROM payment_instructions WHERE payment_id = ANY($1::bigint[])", p)
        if s:
            await conn.execute("DELETE FROM shipment_delivery_attempts WHERE shipment_id = ANY($1::bigint[])", s)
        if p:
            await conn.execute("DELETE FROM payments WHERE id = ANY($1::bigint[])", p)
        if s:
            await conn.execute("DELETE FROM shipments WHERE id = ANY($1::bigint[])", s)
        if o:
            await conn.execute("DELETE FROM order_items WHERE order_id = ANY($1::bigint[])", o)
            await conn.execute("DELETE FROM orders WHERE id = ANY($1::bigint[])", o)
        if c:
            await conn.execute("DELETE FROM customers WHERE id = ANY($1::bigint[])", c)
        # bank INACTIVE cua batch (instruction da xoa) — KHONG dung toi active bank dung chung
        await conn.execute("DELETE FROM bank_accounts WHERE holder_name=$1 AND NOT active", _bank_holder(batch))
    active_after = await conn.fetchval("SELECT id FROM bank_accounts WHERE active")
    assert active_before == active_after, "cleanup KHONG duoc doi active bank"
    return {"deleted": ids, "active_bank_unchanged": active_before == active_after}


async def list_batches(conn) -> list[dict]:
    rows = await conn.fetch(
        "SELECT split_part(substring(psid from 8), ':', 1) AS batch, count(*) AS orders "
        "FROM customers cu JOIN orders o ON o.customer_id=cu.id WHERE cu.psid LIKE 'm7test:%' GROUP BY 1 ORDER BY 1")
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


if __name__ == "__main__":
    asyncio.run(main())
