#!/usr/bin/env python3
"""M6 notification qua worker — CA Review 267-03. Chay THAT qua outbox_worker.run_once voi mock sender + DB.

Chung minh:
  N1 chuoi handover -> failed -> re-dispatch -> delivered (drain giua moi buoc): MOI transition hop le co
     DUNG 1 notify; in_transit xuat hien HAI lan (re-dispatch KHONG bi dedupe mat) — dung loi 267-03.
  N2 stale: enqueue handover roi advance sang delivered TRUOC khi drain -> handover (version cu) bi CANCELLED,
     delivered duoc gui.
  N3 retry: run_once lan 2 -> 0 notify moi cho don nay (khong nhan doi).
Scope assert theo order_id trong payload (bo qua event don khac dang pending tren m5lab).
"""
import asyncio
import os
import sys
import time

import asyncpg

from app.services.command import outbox_worker as ow
from app.services.fulfillment import shipment_service as ship
from app.services.payment import payment_service as pay

RUN = str(int(time.time()))
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")
FAILS = []
_SEQ = [0]
_SENT = []  # moi phan tu: stale_check dict cua notify da gui


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


async def _mock_send(destination, payload):
    _SENT.append(payload.get("stale_check") or {})
    return ow.SendResult(ok=True, http_status=200, provider_message_id="mock")


async def _drain():
    return await ow.run_once(send_fn=_mock_send)


def _sent_for(order_id):
    return [s for s in _SENT if s.get("order_id") == order_id]


async def _mk_order(conn):
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'C','0900000000') RETURNING id",
                              f"tg:m6nw-{tag}")
    pid = await conn.fetchval(
        "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g) VALUES($1,'CF',200000,999,600) "
        "ON CONFLICT(sku) DO UPDATE SET shipping_weight_g=600 RETURNING id", f"M6NW-{tag}")
    oid = await conn.fetchval(
        "INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',200000,"
        "'telegram_customer') RETURNING id", cid)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,1,200000)",
                       oid, pid)
    async with conn.transaction():
        await ship.set_manual_quote(conn, oid, actor="nw", zone="province", weight_g=600, fee_vnd=30000)
        await pay.ensure_payment(conn, oid, method="COD", actor="nw")
    return oid


async def _tx(conn, coro_fn):
    async with conn.transaction():
        return await coro_fn(conn)


async def _clear_backlog():
    """m5lab throwaway co the ton dong outbox cu tu cac lan chay truoc (BATCH=25 moi vong) -> xa het truoc khi
    test de moi _drain() chi xu ly event moi cua test nay."""
    for _ in range(50):
        st = await ow.run_once(send_fn=_mock_send)
        if st.get("claimed", 0) == 0:
            break
    _SENT.clear()


async def main():
    conn = await asyncpg.connect(DSN)
    try:
        await _clear_backlog()
        # ---- N1: drain giua moi buoc -> moi transition 1 notify; in_transit hai lan ----
        oid = await _mk_order(conn)
        await _tx(conn, lambda c: ship.change_status(c, oid, "ready_to_ship", actor="nw"))
        await _tx(conn, lambda c: ship.change_status(c, oid, "in_transit", actor="nw"))   # handover #1
        await _drain()
        await _tx(conn, lambda c: ship.record_attempt(c, oid, actor="nw", command_key=f"{RUN}-n1a",
                                                      result="failed", reason="vang"))      # -> delivery_failed
        await _drain()
        await _tx(conn, lambda c: ship.change_status(c, oid, "in_transit", actor="nw"))    # handover #2 (re-dispatch)
        await _drain()
        await _tx(conn, lambda c: ship.record_attempt(c, oid, actor="nw", command_key=f"{RUN}-n1b",
                                                      result="success"))                    # -> delivered
        await _drain()
        sent = _sent_for(oid)
        handovers = [s for s in sent if s.get("to_status") == "in_transit"]
        faileds = [s for s in sent if s.get("to_status") in ("delivery_failed", "return_pending")]
        delivereds = [s for s in sent if s.get("to_status") == "delivered"]
        ho_versions = sorted({s.get("version") for s in handovers})
        ck("N1 re-dispatch: in_transit notify GUI 2 lan (khac version, khong bi dedupe mat)",
           len(handovers) == 2 and len(ho_versions) == 2, f"handovers={len(handovers)} versions={ho_versions}")
        ck("N1 delivered + failed moi loai 1 notify", len(faileds) == 1 and len(delivereds) == 1,
           f"failed={len(faileds)} delivered={len(delivereds)}")

        # ---- N2: stale -> handover (version cu) bi cancelled, delivered duoc gui ----
        _SENT.clear()
        oid2 = await _mk_order(conn)
        await _tx(conn, lambda c: ship.change_status(c, oid2, "ready_to_ship", actor="nw"))
        await _tx(conn, lambda c: ship.change_status(c, oid2, "in_transit", actor="nw"))   # handover enqueued
        ho_ver = await conn.fetchval("SELECT version FROM shipments WHERE order_id=$1", oid2)
        # advance TRUOC khi drain: ghi success -> delivered (version tien xa hon handover)
        await _tx(conn, lambda c: ship.record_attempt(c, oid2, actor="nw", command_key=f"{RUN}-n2", result="success"))
        stats = await _drain()
        sent2 = _sent_for(oid2)
        sent_status = sorted({s.get("to_status") for s in sent2})
        # handover event (dedupe handover:oid2:ho_ver) phai la 'cancelled', KHONG nam trong _SENT
        ho_row = await conn.fetchrow("SELECT status FROM outbox_events WHERE dedupe_key=$1",
                                     f"shipment_handover:{oid2}:{ho_ver}")
        ck("N2 handover lac hau -> cancelled (khong gui)", ho_row and ho_row["status"] == "cancelled"
           and "in_transit" not in sent_status, f"ho_status={ho_row['status'] if ho_row else None} sent={sent_status}")
        ck("N2 delivered (hien hanh) -> duoc gui", "delivered" in sent_status
           and stats.get("cancelled", 0) >= 1, f"sent={sent_status} cancelled={stats.get('cancelled')}")

        # ---- N3: retry run_once -> khong gui lai cho don nay ----
        _SENT.clear()
        await _drain()
        ck("N3 drain lai -> 0 notify moi (khong nhan doi)", len(_sent_for(oid)) == 0 and len(_sent_for(oid2)) == 0,
           f"oid={len(_sent_for(oid))} oid2={len(_sent_for(oid2))}")

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        await ow_close()
        await conn.close()


async def ow_close():
    from app.db_pool import close_pool
    await close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
