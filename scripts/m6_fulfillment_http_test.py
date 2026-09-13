#!/usr/bin/env python3
"""M6 Delivery & Payment dashboard API — HTTP e2e (CA Directive 265 §4.1 + Review 266-01/03).

In-process ASGI (httpx.AsyncClient + ASGITransport, real routing + require_permission), override
require_staff_session = staff. Bao phu (qua HTTP that, khong goi service truc tiep):
  - AUTH: khong override -> 401 (thieu token); override staff du quyen -> 200.
  - RBAC 403: staff THIEU quyen payment.transfer_confirm -> evidence shop_confirmed_received bi 403.
  - VALIDATION 4xx: evidence thieu command_key -> 422; amount_vnd sai kieu -> 422; attempt next_contact_at sai
    dinh dang -> 422; shipment/status thieu to_status -> 422; transition sai -> 400; stale expected_version -> 409.
  - HAPPY: manual-quote -> ensure COD -> cod_collected -> reconciled (du tien) -> reconciled; board + detail 200.
  - IDEMPOTENCY qua HTTP: cung command_key -> duplicate=True (khong tao event moi).
Chay tren m5lab (schema >= 064). Self-contained order (customer/product/order_items). Re-runnable.
"""
import asyncio
import sys
import time

import asyncpg
from httpx import ASGITransport, AsyncClient

from app.api.auth import require_staff_session
from app.config import settings
from app.main import app

RUN = str(int(time.time()))
BASE = "/dashboard/fulfillment"
FULL = {"shipment.manage", "fulfillment.status_change", "payment.cod_record",
        "payment.transfer_confirm", "payment.reconcile", "bank.config"}
STAFF_FULL = {"id": 9001, "username": f"m6http_{RUN}", "name": "M6 HTTP", "rbac_provisioned": True,
              "permissions": FULL, "must_change_password": False}
STAFF_LIMITED = {"id": 9002, "username": f"m6lim_{RUN}", "name": "M6 LIM", "rbac_provisioned": True,
                 "permissions": {"shipment.manage"}, "must_change_password": False}
FAILS: list[str] = []


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


def _db():
    return settings.database_url.replace("+asyncpg", "")


async def _mk_order(conn, total=200000):
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'HTTP','0900000000') RETURNING id",
                              f"tg:m6http-{RUN}-{int(time.time()*1000) % 100000}")
    pid = await conn.fetchval(
        "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g) VALUES($1,'CF',$2,999,600) "
        "ON CONFLICT(sku) DO UPDATE SET shipping_weight_g=600 RETURNING id", f"M6HTTP-{RUN}-{total}", total)
    oid = await conn.fetchval(
        "INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',$2,"
        "'telegram_customer') RETURNING id", cid, total)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,1,$3)",
                       oid, pid, total)
    return oid


async def main() -> int:  # noqa: C901
    conn = await asyncpg.connect(_db())
    try:
        oid = await _mk_order(conn, total=200000)

        transport = ASGITransport(app=app)
        # 1) AUTH: khong override -> 401
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get(f"{BASE}/board")
            ck("auth thieu token -> 401", r.status_code == 401, r.status_code)

        app.dependency_overrides[require_staff_session] = lambda: STAFF_FULL
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            # 2) board + manual-quote (fee 30000) -> ensure COD -> due 230000
            r = await c.get(f"{BASE}/board")
            ck("GET board 200", r.status_code == 200, r.status_code)
            r = await c.post(f"{BASE}/orders/{oid}/shipment/manual-quote",
                             json={"zone": "province", "weight_g": 600, "fee_vnd": 30000, "eta_text": "1-3 ngay"})
            ck("manual-quote 200 + quoted", r.status_code == 200 and r.json()["fee_status"] == "quoted",
               f"{r.status_code} {r.text[:80]}")
            # 2b) money sai kieu -> 422
            r = await c.post(f"{BASE}/orders/{oid}/shipment/manual-quote", json={"fee_vnd": "abc"})
            ck("manual-quote fee sai kieu -> 422", r.status_code == 422, r.status_code)
            r = await c.post(f"{BASE}/orders/{oid}/shipment/manual-quote", json={"fee_vnd": -5})
            ck("manual-quote fee am -> 422", r.status_code == 422, r.status_code)

            r = await c.post(f"{BASE}/orders/{oid}/payment/ensure", json={"method": "COD"})
            ck("ensure COD 200 + due 230000", r.status_code == 200 and r.json()["amount_due_vnd"] == 230000,
               f"{r.status_code} {r.text[:80]}")
            r = await c.post(f"{BASE}/orders/{oid}/payment/ensure", json={"method": "X"})
            ck("ensure method sai -> 422", r.status_code == 422, r.status_code)

            # 3) evidence validation
            r = await c.post(f"{BASE}/orders/{oid}/payment/evidence",
                             json={"kind": "cod_collected", "amount_vnd": 230000})  # thieu command_key
            ck("evidence thieu command_key -> 422", r.status_code == 422, r.status_code)
            r = await c.post(f"{BASE}/orders/{oid}/payment/evidence",
                             json={"kind": "cod_collected", "amount_vnd": "x", "command_key": "k1"})
            ck("evidence amount sai kieu -> 422", r.status_code == 422, r.status_code)

            # 3b) happy COD: collected -> reconciled
            r = await c.post(f"{BASE}/orders/{oid}/payment/evidence",
                             json={"kind": "cod_collected", "amount_vnd": 230000, "command_key": f"{RUN}-coll"})
            ck("evidence cod_collected 200 -> collected", r.status_code == 200 and r.json()["status"] == "collected",
               f"{r.status_code} {r.text[:80]}")
            # idempotency: cung command_key -> duplicate
            r2 = await c.post(f"{BASE}/orders/{oid}/payment/evidence",
                              json={"kind": "cod_collected", "amount_vnd": 230000, "command_key": f"{RUN}-coll"})
            ck("evidence command_key replay -> duplicate", r2.status_code == 200 and r2.json()["duplicate"] is True,
               f"{r2.status_code} {r2.text[:80]}")
            r = await c.post(f"{BASE}/orders/{oid}/payment/evidence",
                             json={"kind": "reconciled", "amount_vnd": 230000, "command_key": f"{RUN}-rec"})
            ck("evidence reconciled(du) 200 -> reconciled", r.status_code == 200 and r.json()["status"] == "reconciled",
               f"{r.status_code} {r.text[:80]}")

            # 4) shipment status validation: thieu to_status -> 422 ; wrong transition -> 400
            r = await c.post(f"{BASE}/orders/{oid}/shipment/status", json={})
            ck("status thieu to_status -> 422", r.status_code == 422, r.status_code)
            r = await c.post(f"{BASE}/orders/{oid}/shipment/status", json={"to_status": "delivered"})
            ck("status transition sai (pending_prep->delivered) -> 400", r.status_code == 400,
               f"{r.status_code} {r.text[:80]}")
            # ready_to_ship OK -> roi stale expected_version -> 409
            r = await c.post(f"{BASE}/orders/{oid}/shipment/status", json={"to_status": "ready_to_ship"})
            ck("status ready_to_ship 200", r.status_code == 200, f"{r.status_code} {r.text[:80]}")
            cur_v = await conn.fetchval("SELECT version FROM shipments WHERE order_id=$1", oid)
            r = await c.post(f"{BASE}/orders/{oid}/shipment/status",
                             json={"to_status": "pending_prep", "expected_version": cur_v - 1})
            ck("status stale expected_version -> 409", r.status_code == 409, f"{r.status_code} {r.text[:80]}")

            # 5) attempt validation: thieu command_key -> 422 ; datetime sai -> 422
            r = await c.post(f"{BASE}/orders/{oid}/shipment/attempt", json={"result": "failed"})
            ck("attempt thieu command_key -> 422", r.status_code == 422, r.status_code)
            r = await c.post(f"{BASE}/orders/{oid}/shipment/attempt",
                             json={"result": "failed", "command_key": "a1", "next_contact_at": "khong-phai-ngay"})
            ck("attempt next_contact_at sai dinh dang -> 422", r.status_code == 422, r.status_code)

            # 6) detail 200 + phan anh state
            r = await c.get(f"{BASE}/orders/{oid}")
            body = r.json() if r.status_code == 200 else {}
            ck("GET detail 200 + payment reconciled", r.status_code == 200
               and body.get("payment", {}).get("status") == "reconciled", f"{r.status_code}")

        # 7) RBAC 403: staff THIEU payment.transfer_confirm -> shop_confirmed_received 403
        oid2 = await _mk_order(conn, total=200000)
        app.dependency_overrides[require_staff_session] = lambda: STAFF_LIMITED
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post(f"{BASE}/orders/{oid2}/payment/evidence",
                             json={"kind": "shop_confirmed_received", "amount_vnd": 200000, "command_key": "x"})
            ck("RBAC: thieu payment.transfer_confirm -> 403", r.status_code == 403, f"{r.status_code} {r.text[:80]}")
            # nhung shipment.manage co -> manual-quote 200
            r = await c.post(f"{BASE}/orders/{oid2}/shipment/manual-quote", json={"fee_vnd": 0, "zone": "bmt_inner"})
            ck("RBAC: co shipment.manage -> manual-quote 200", r.status_code == 200, r.status_code)
            # bank.config THIEU -> set bank 403
            r = await c.post(f"{BASE}/bank-account",
                             json={"bank": "B", "account_number": "1", "holder_name": "H"})
            ck("RBAC: thieu bank.config -> 403", r.status_code == 403, r.status_code)
    finally:
        app.dependency_overrides.pop(require_staff_session, None)
        await conn.close()

    print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
