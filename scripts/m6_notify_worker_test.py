#!/usr/bin/env python3
"""M6 notification qua worker — CA Review 267-03 + 268-01. Chay THAT qua outbox_worker.run_once + mock sender + DB.

CA 268-01 PASS (4 case bat buoc):
  P1 enqueue in_transit@N -> doi carrier/tracking (version N+1, status VAN in_transit) -> DUNG 1 thong bao ban
     giao hop le, va text da RE-RENDER carrier moi (khong stale, khong bi huy vi version cao hon).
  P2 enqueue in_transit@N -> state -> delivered -> handover cu bi CANCEL, delivered hien hanh duoc gui.
  P3 in_transit -> failed -> in_transit: gui HAI transition handover khac nhau (re-dispatch khong mat).
  P4 retry cung outbox event -> khong gui trung.
Scope assert theo order_id trong payload. Xa backlog outbox cu truoc khi assert.
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
_SENT = []  # (stale_check dict, text)


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


async def _mock_send(destination, payload):
    _SENT.append((payload.get("stale_check") or {}, payload.get("text") or ""))
    return ow.SendResult(ok=True, http_status=200, provider_message_id="mock")


async def _drain():
    return await ow.run_once(send_fn=_mock_send)


async def _clear_backlog():
    for _ in range(80):
        st = await ow.run_once(send_fn=_mock_send)
        if st.get("claimed", 0) == 0:
            break
    _SENT.clear()


def _sent_for(order_id):
    return [(s, t) for (s, t) in _SENT if s.get("order_id") == order_id]


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


async def main():
    conn = await asyncpg.connect(DSN)
    try:
        await _clear_backlog()

        # ---- P1: carrier change sau handover (version tang, status giu) -> 1 handover hop le + carrier moi ----
        oid = await _mk_order(conn)
        await _tx(conn, lambda c: ship.change_status(c, oid, "ready_to_ship", actor="nw"))
        await _tx(conn, lambda c: ship.change_status(c, oid, "in_transit", actor="nw"))   # handover@N (carrier None)
        v1 = await conn.fetchval("SELECT version FROM shipments WHERE order_id=$1", oid)
        await _tx(conn, lambda c: ship.set_carrier(c, oid, actor="nw", carrier="GHTK", tracking_text="TN123"))
        v2 = await conn.fetchval("SELECT version FROM shipments WHERE order_id=$1", oid)
        await _drain()
        sent = _sent_for(oid)
        handovers = [(s, t) for (s, t) in sent if s.get("to_status") == "in_transit"]
        ck("P1 carrier-change (v tang, status giu in_transit) -> DUNG 1 handover, KHONG bi huy nham",
           len(handovers) == 1 and v2 > v1, f"handovers={len(handovers)} v {v1}->{v2}")
        ck("P1 handover re-render carrier moi (khong stale snapshot)",
           len(handovers) == 1 and "GHTK" in handovers[0][1] and "TN123" in handovers[0][1],
           handovers[0][1] if handovers else "(none)")

        # ---- P2: in_transit@N -> delivered -> handover cancel, delivered gui ----
        _SENT.clear()
        oid2 = await _mk_order(conn)
        await _tx(conn, lambda c: ship.change_status(c, oid2, "ready_to_ship", actor="nw"))
        await _tx(conn, lambda c: ship.change_status(c, oid2, "in_transit", actor="nw"))
        ho_ver = await conn.fetchval("SELECT version FROM shipments WHERE order_id=$1", oid2)
        await _tx(conn, lambda c: ship.record_attempt(c, oid2, actor="nw", command_key=f"{RUN}-p2", result="success"))
        stats = await _drain()
        ho_row = await conn.fetchrow("SELECT status FROM outbox_events WHERE dedupe_key=$1",
                                     f"shipment_handover:{oid2}:{ho_ver}")
        sent2_status = sorted({s.get("to_status") for s, _ in _sent_for(oid2)})
        ck("P2 in_transit@N -> delivered: handover cancel + delivered gui",
           ho_row and ho_row["status"] == "cancelled" and "in_transit" not in sent2_status
           and "delivered" in sent2_status and stats.get("cancelled", 0) >= 1,
           f"ho={ho_row['status'] if ho_row else None} sent={sent2_status}")

        # ---- P3: in_transit -> failed -> in_transit -> HAI handover khac nhau ----
        _SENT.clear()
        oid3 = await _mk_order(conn)
        await _tx(conn, lambda c: ship.change_status(c, oid3, "ready_to_ship", actor="nw"))
        await _tx(conn, lambda c: ship.change_status(c, oid3, "in_transit", actor="nw"))    # handover #1
        await _drain()
        await _tx(conn, lambda c: ship.record_attempt(c, oid3, actor="nw", command_key=f"{RUN}-p3", result="failed"))
        await _drain()
        await _tx(conn, lambda c: ship.change_status(c, oid3, "in_transit", actor="nw"))     # handover #2
        await _drain()
        ho3 = [s for s, _ in _sent_for(oid3) if s.get("to_status") == "in_transit"]
        ho3_versions = sorted({s.get("version") for s in ho3})
        ck("P3 re-dispatch: HAI handover khac version (khong bi dedupe mat)",
           len(ho3) == 2 and len(ho3_versions) == 2, f"handovers={len(ho3)} versions={ho3_versions}")

        # ---- P4: retry cung outbox event -> khong gui trung ----
        _SENT.clear()
        await _drain()
        ck("P4 drain lai -> 0 notify moi cho cac don tren (khong nhan doi)",
           len(_sent_for(oid)) == 0 and len(_sent_for(oid2)) == 0 and len(_sent_for(oid3)) == 0,
           f"o1={len(_sent_for(oid))} o2={len(_sent_for(oid2))} o3={len(_sent_for(oid3))}")

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        from app.db_pool import close_pool
        await close_pool()
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
