#!/usr/bin/env python3
"""M6 DB concurrency — CA Review 267-02. Hai connection that, transaction rieng, chay DONG THOI (asyncio.gather).

Chung minh ket qua XAC DINH, KHONG 500, KHONG double effect/outbox cho:
  C1 cung command_key + cung payload        -> 1 insert, 1 duplicate.
  C2 cung command_key + KHAC payload         -> 1 insert, 1 REJECT (fingerprint mismatch), khong double.
  C3 hai key khac nhau + cung attempt state   -> FOR UPDATE serialize: 1 attempt, request sau thay state moi
                                                 (khong con in_transit) -> ShipmentError, KHONG loi DB uq_attempt_no.
  C4 hai key khac nhau + cung payment reference -> 1 insert, 1 duplicate (reference atomic uniqueness).
Chay tren m5lab. Moi record_* chay trong `async with conn.transaction()` de giu lock FOR UPDATE den commit.
"""
import asyncio
import os
import sys
import time

import asyncpg

from app.services.fulfillment import shipment_service as ship
from app.services.payment import payment_service as pay

RUN = str(int(time.time()))
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")
FAILS = []
_SEQ = [0]


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


async def _mk_order(pool, *, total=200000, method="BANK_TRANSFER", in_transit=False):
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    async with pool.acquire() as conn:
        cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'C','0900000000') RETURNING id",
                                  f"tg:m6cc-{tag}")
        pid = await conn.fetchval(
            "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g) VALUES($1,'CF',$2,999,600) "
            "ON CONFLICT(sku) DO UPDATE SET shipping_weight_g=600 RETURNING id", f"M6CC-{tag}", total)
        oid = await conn.fetchval(
            "INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',$2,"
            "'telegram_customer') RETURNING id", cid, total)
        await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,1,$3)",
                           oid, pid, total)
        await ship.set_manual_quote(conn, oid, actor="cc", zone="province", weight_g=600, fee_vnd=30000)
        await pay.ensure_payment(conn, oid, method=method, actor="cc")
        if in_transit:
            # du dieu kien handover cho COD
            await ship.change_status(conn, oid, "ready_to_ship", actor="cc")
            await ship.change_status(conn, oid, "in_transit", actor="cc")
    return oid


async def _run_tx(pool, coro_fn):
    """Chay record_* trong transaction rieng tren connection rieng; tra ('ok', result) hoac ('err', ExcName)."""
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                r = await coro_fn(conn)
            return ("ok", r)
        except (pay.PaymentError, ship.ShipmentError) as e:
            return ("err", type(e).__name__ + ":" + str(e)[:40])


async def main():
    pool = await asyncpg.create_pool(DSN, min_size=4, max_size=8)
    try:
        # C1: cung command_key + cung payload -> 1 insert + 1 duplicate
        oid = await _mk_order(pool)
        key = f"{RUN}-c1"
        def ev(conn, k=key, amt=100000):
            return pay.record_evidence(conn, oid, kind="customer_reported", amount_vnd=amt, recorded_by="c",
                                       command_key=k)
        r1, r2 = await asyncio.gather(_run_tx(pool, ev), _run_tx(pool, lambda c: ev(c)))
        oks = [r for s, r in (r1, r2) if s == "ok"]
        dups = [r for r in oks if isinstance(r, dict) and r.get("duplicate")]
        async with pool.acquire() as c:
            n = await c.fetchval("SELECT count(*) FROM payment_events pe JOIN payments p ON p.id=pe.payment_id "
                                 "WHERE p.order_id=$1 AND pe.command_key=$2", oid, key)
        ck("C1 cung key+payload -> 1 event, 1 duplicate, khong 500",
           r1[0] == "ok" and r2[0] == "ok" and n == 1 and len(dups) >= 1, f"n={n} dups={len(dups)} {r1[0]}/{r2[0]}")

        # C2: cung command_key + KHAC payload -> 1 ok, 1 reject mismatch
        oid2 = await _mk_order(pool)
        key2 = f"{RUN}-c2"
        def ev_a(conn):
            return pay.record_evidence(conn, oid2, kind="customer_reported", amount_vnd=100000, recorded_by="c",
                                       command_key=key2)
        def ev_b(conn):
            return pay.record_evidence(conn, oid2, kind="customer_reported", amount_vnd=999999, recorded_by="c",
                                       command_key=key2)
        r1, r2 = await asyncio.gather(_run_tx(pool, ev_a), _run_tx(pool, ev_b))
        states = sorted([r1[0], r2[0]])
        errs = [r for s, r in (r1, r2) if s == "err"]
        oks2 = sum(1 for s, _ in (r1, r2) if s == "ok")
        async with pool.acquire() as c:
            n = await c.fetchval("SELECT count(*) FROM payment_events pe JOIN payments p ON p.id=pe.payment_id "
                                 "WHERE p.order_id=$1 AND pe.command_key=$2", oid2, key2)
        # 1 request insert (ok), request con lai cung command_key nhung khac payload -> PaymentError reject; 1 event.
        ck("C2 cung key khac payload -> reject mismatch, 1 event, khong double",
           n == 1 and oks2 == 1 and len(errs) == 1 and errs[0].startswith("PaymentError"),
           f"n={n} states={states} errs={errs}")

        # C3: hai key khac nhau + cung attempt state (in_transit) -> serialize, 1 attempt, loser ShipmentError
        oid3 = await _mk_order(pool, method="COD", in_transit=True)
        def att(conn, k):
            return ship.record_attempt(conn, oid3, actor="c", command_key=k, result="failed", reason="x")
        r1, r2 = await asyncio.gather(_run_tx(pool, lambda c: att(c, f"{RUN}-c3a")),
                                      _run_tx(pool, lambda c: att(c, f"{RUN}-c3b")))
        async with pool.acquire() as c:
            n_att = await c.fetchval("SELECT count(*) FROM shipment_delivery_attempts sda "
                                     "JOIN shipments s ON s.id=sda.shipment_id WHERE s.order_id=$1", oid3)
            st = await c.fetchval("SELECT status FROM shipments WHERE order_id=$1", oid3)
        oks3 = sum(1 for s, _ in (r1, r2) if s == "ok")
        errs3 = [r for s, r in (r1, r2) if s == "err"]
        ck("C3 hai key cung attempt-state -> 1 attempt, loser ShipmentError (khong 500 uq_attempt_no)",
           n_att == 1 and oks3 == 1 and len(errs3) == 1 and "ShipmentError" in errs3[0] and st == "delivery_failed",
           f"n_att={n_att} oks={oks3} errs={errs3} st={st}")

        # C4: hai key khac nhau + cung reference -> 1 insert, 1 duplicate (reference atomic uniqueness)
        oid4 = await _mk_order(pool)
        ref = f"FT-{RUN}-c4"
        def ev_ref(conn, k):
            return pay.record_evidence(conn, oid4, kind="customer_reported", amount_vnd=100000, recorded_by="c",
                                       command_key=k, reference=ref)
        r1, r2 = await asyncio.gather(_run_tx(pool, lambda c: ev_ref(c, f"{RUN}-c4a")),
                                      _run_tx(pool, lambda c: ev_ref(c, f"{RUN}-c4b")))
        async with pool.acquire() as c:
            n_ref = await c.fetchval("SELECT count(*) FROM payment_events pe JOIN payments p ON p.id=pe.payment_id "
                                     "WHERE p.order_id=$1 AND pe.reference=$2", oid4, ref)
        dups4 = sum(1 for s, r in (r1, r2) if s == "ok" and isinstance(r, dict) and r.get("duplicate"))
        ck("C4 hai key cung reference -> 1 event, 1 duplicate, khong double",
           n_ref == 1 and r1[0] == "ok" and r2[0] == "ok" and dups4 == 1,
           f"n_ref={n_ref} dups={dups4} {r1[0]}/{r2[0]}")

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
