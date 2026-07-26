#!/usr/bin/env python3
"""Command service order.create.v1 — integration/concurrency evidence (I-B M1 Slice 3).

Bao phu:
  AC-M1-02 atomicity  : success -> order + command(succeeded) + outbox + audit CUNG ton tai.
  AC-M1-03 duplicate  : cung key + cung payload -> receipt cu, duplicate=true, KHONG order thu hai.
  AC-M1-04 conflict   : cung key + khac payload -> 409, KHONG order moi, audit conflict.
  AC-M1-05 concurrency: 20 request dong thoi cung key -> dung 1 order/command/outbox (khong oversell).
  Business reject     : insufficient_stock / product_not_found / quantity_exceeds_auto_limit
                        -> failed_terminal, KHONG order, KHONG outbox (reject idempotent).
  Redaction (§7.4)    : request_payload co phone_masked, KHONG phone/address raw.

Chay tren throwaway DB da migrate 001-019:
  docker exec -e DATABASE_URL=...m1_itest -e PYTHONPATH=/srv -w /srv api python scripts/command_order_service_test.py
"""
import asyncio
import sys

import asyncpg

from app.config import settings
from app.services import auth_service
from app.services.command import errors, order_service
from app.services.command.envelope import Actor, build_order_create_envelope

BASE = {
    "customer_name": "Nguyen Van A",
    "phone": "0912345678",
    "address": "12 Le Loi, Q1, HCM",
    "sku": "3S-100G",
    "quantity": 1,
}

STAFF_ID = "1"  # gan lai bang staff that trong main() (actor.id staff = staff_users.id, FK audit)


def _db() -> str:
    return settings.database_url.replace("+asyncpg", "")


def staff_env(key, **over):
    payload = dict(BASE, unit_price_vnd=150000, **over)  # staff-priced (manual)
    return build_order_create_envelope(
        raw_payload=payload, actor=Actor("staff", STAFF_ID), channel="dashboard", idempotency_key=key)


def ai_env(key, **over):
    payload = dict(BASE, psid="psid-itest", **over)  # system-priced (AI)
    return build_order_create_envelope(
        raw_payload=payload, actor=Actor("customer", "psid-itest"), channel="messenger",
        idempotency_key=key)


async def orders_count(conn) -> int:
    return await conn.fetchval("SELECT count(*) FROM orders")


async def stock(conn) -> int:
    return await conn.fetchval("SELECT stock FROM products WHERE sku='3S-100G'")


async def reset(conn):
    await conn.execute("TRUNCATE order_items, orders, command_executions, outbox_events, "
                       "delivery_attempts, price_overrides RESTART IDENTITY CASCADE")
    await conn.execute("UPDATE products SET stock=1000 WHERE sku='3S-100G'")


async def main() -> int:  # noqa: C901
    conn = await asyncpg.connect(_db())
    fails: list[str] = []
    try:
        if await conn.fetchval("SELECT count(*) FROM products WHERE sku='3S-100G'") != 1:
            print("SKIP: khong co seed 3S-100G")
            return 2
        await reset(conn)
        # staff that de audit.actor_staff_id thoa FK (production: id tu authenticated session)
        global STAFF_ID
        st = await auth_service.create_staff_user("itest_staff", "pw12345678", "IT", role_key="admin")
        STAFF_ID = str(st["id"])

        # === T1 atomicity (AC-M1-02) + redaction ===
        r1 = await order_service.execute_order_create(staff_env("KEY-ATOMIC-0001"))
        oid = r1.resource and r1.resource["id"]
        if not (r1.outcome == "succeeded" and oid and not r1.duplicate):
            fails.append(f"T1: receipt sai: {r1.to_dict()}")
        crow = await conn.fetchrow("SELECT status, result_payload, request_payload, resource_id "
                                   "FROM command_executions WHERE idempotency_key='KEY-ATOMIC-0001'")
        if crow is None or crow["status"] != "succeeded":
            fails.append("T1: command khong succeeded")
        elif crow["resource_id"] != str(oid):
            fails.append("T1: resource_id khong khop order")
        rp = crow["request_payload"] if crow else ""
        if "phone_masked" not in rp or "0912345678" in rp or "Le Loi" in rp:
            fails.append(f"T1: request_payload redaction sai: {rp}")
        if await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key=$1",
                               f"order_created:{oid}") != 1:
            fails.append("T1: outbox event khong dung 1")
        if await conn.fetchval("SELECT count(*) FROM audit_log WHERE action='order.create' "
                               "AND entity_id=$1", str(oid)) != 1:
            fails.append("T1: audit order.create khong dung 1")
        if await conn.fetchval("SELECT count(*) FROM order_items WHERE order_id=$1", oid) != 1:
            fails.append("T1: order_items khong dung 1")

        # === T2 duplicate same payload (AC-M1-03) ===
        n_before = await orders_count(conn)
        r2 = await order_service.execute_order_create(staff_env("KEY-ATOMIC-0001"))
        if not (r2.outcome == "succeeded" and r2.duplicate and r2.resource["id"] == oid):
            fails.append(f"T2: duplicate khong tra receipt cu: {r2.to_dict()}")
        if await orders_count(conn) != n_before:
            fails.append("T2: duplicate tao them order (phai KHONG)")
        if await conn.fetchval("SELECT count(*) FROM command_executions "
                               "WHERE idempotency_key='KEY-ATOMIC-0001'") != 1:
            fails.append("T2: co >1 command row cung key")

        # === T3 conflict diff payload same key (AC-M1-04) ===
        n_before = await orders_count(conn)
        try:
            await order_service.execute_order_create(staff_env("KEY-ATOMIC-0001", quantity=2))
            fails.append("T3: khac payload cung key KHONG raise 409")
        except errors.CommandError as e:
            if e.code != errors.IDEMPOTENCY_CONFLICT or e.http_status != 409:
                fails.append(f"T3: sai loi {e.code}/{e.http_status}")
        if await orders_count(conn) != n_before:
            fails.append("T3: conflict tao order moi")
        if await conn.fetchval("SELECT count(*) FROM audit_log "
                               "WHERE action='command.idempotency_conflict'") < 1:
            fails.append("T3: khong audit conflict")

        # === T4 insufficient stock -> rejected, no order/outbox ===
        await conn.execute("UPDATE products SET stock=5 WHERE sku='3S-100G'")
        n_before = await orders_count(conn)
        ob_before = await conn.fetchval("SELECT count(*) FROM outbox_events")
        r4 = await order_service.execute_order_create(staff_env("KEY-STOCK-0001", quantity=10))
        if not (r4.outcome == "rejected" and r4.error_code == errors.INSUFFICIENT_STOCK):
            fails.append(f"T4: khong reject insufficient_stock: {r4.to_dict()}")
        if await orders_count(conn) != n_before:
            fails.append("T4: reject van tao order")
        if await conn.fetchval("SELECT count(*) FROM outbox_events") != ob_before:
            fails.append("T4: reject van tao outbox")
        if await conn.fetchval("SELECT status FROM command_executions "
                               "WHERE idempotency_key='KEY-STOCK-0001'") != "failed_terminal":
            fails.append("T4: command khong failed_terminal")
        await conn.execute("UPDATE products SET stock=1000 WHERE sku='3S-100G'")

        # === T5 product not found -> rejected ===
        r5 = await order_service.execute_order_create(staff_env("KEY-NOSKU-0001", sku="NO-SUCH-XYZ"))
        if not (r5.outcome == "rejected" and r5.error_code == errors.PRODUCT_NOT_FOUND):
            fails.append(f"T5: khong reject product_not_found: {r5.to_dict()}")

        # === T6 quantity exceeds auto limit (AI, no override) -> rejected ===
        r6 = await order_service.execute_order_create(ai_env("KEY-LIMIT-0001", quantity=101))
        if not (r6.outcome == "rejected" and r6.error_code == errors.QUANTITY_EXCEEDS_AUTO_LIMIT):
            fails.append(f"T6: khong reject quantity limit: {r6.to_dict()}")

        # === T7 concurrency 20 same key -> 1 order (AC-M1-05) ===
        await reset(conn)
        s0 = await stock(conn)
        envs = [staff_env("KEY-CONC-0001") for _ in range(20)]
        results = await asyncio.gather(*[order_service.execute_order_create(e) for e in envs],
                                       return_exceptions=True)
        exc = [r for r in results if isinstance(r, Exception)]
        oks = [r for r in results if not isinstance(r, Exception)]
        order_ids = {r.resource["id"] for r in oks if r.resource}
        if await orders_count(conn) != 1:
            fails.append(f"T7: tao {await orders_count(conn)} order (mong 1)")
        if len(order_ids) != 1:
            fails.append(f"T7: cac receipt tro nhieu order khac nhau: {order_ids}")
        if exc:
            fails.append(f"T7: co exception khong mong doi: {exc[:2]}")
        if await stock(conn) != s0 - 1:
            fails.append(f"T7: oversell — stock {s0}->{await stock(conn)} (mong -1)")
        if await conn.fetchval("SELECT count(*) FROM command_executions "
                               "WHERE idempotency_key='KEY-CONC-0001'") != 1:
            fails.append("T7: >1 command row cung key")
        if await conn.fetchval("SELECT count(*) FROM outbox_events") != 1:
            fails.append("T7: >1 outbox event")

        # === T8 concurrency mixed payload same key -> 1 success group + conflicts, no oversell ===
        await reset(conn)
        s0 = await stock(conn)
        mixed = ([staff_env("KEY-MIX-0001", quantity=1) for _ in range(10)]
                 + [staff_env("KEY-MIX-0001", quantity=2) for _ in range(10)])
        res = await asyncio.gather(*[order_service.execute_order_create(e) for e in mixed],
                                   return_exceptions=True)
        conflicts = [r for r in res if isinstance(r, errors.CommandError)
                     and r.code == errors.IDEMPOTENCY_CONFLICT]
        succ = [r for r in res if not isinstance(r, Exception)]
        if await orders_count(conn) != 1:
            fails.append(f"T8: tao {await orders_count(conn)} order (mong 1)")
        if len(conflicts) != 10:
            fails.append(f"T8: conflicts={len(conflicts)} (mong 10 — nhom hash thua)")
        if len(succ) != 10:
            fails.append(f"T8: successes={len(succ)} (mong 10 — nhom hash thang)")
        other = [r for r in res if isinstance(r, Exception) and r not in conflicts]
        if other:
            fails.append(f"T8: exception la: {other[:2]}")

        # === T9 (FINDING 1) khách MỚI, 2 đơn khác idempotency-key đồng thời -> CẢ HAI tạo đơn ===
        # (không misroute customers.psid UNIQUE thành 'duplicate'); đúng 1 customer.
        await reset(conn)

        def race_env(key):
            return build_order_create_envelope(
                raw_payload=dict(BASE, psid="psid-brandnew-xyz"),
                actor=Actor("customer", "psid-brandnew-xyz"), channel="messenger",
                idempotency_key=key)

        rr = await asyncio.gather(
            order_service.execute_order_create(race_env("KEY-RACE-A-00001")),
            order_service.execute_order_create(race_env("KEY-RACE-B-00001")),
            return_exceptions=True)
        exc9 = [r for r in rr if isinstance(r, Exception)]
        oks9 = [r for r in rr if not isinstance(r, Exception)]
        if exc9:
            fails.append(f"T9: có exception (misroute new-customer race?): {exc9[:2]}")
        if len(oks9) != 2 or not all(r.outcome == "succeeded" and not r.duplicate for r in oks9):
            fails.append(f"T9: không phải cả 2 succeeded non-duplicate: {[r.to_dict() for r in oks9]}")
        if await orders_count(conn) != 2:
            fails.append(f"T9: tạo {await orders_count(conn)} order (mong 2)")
        ncust = await conn.fetchval("SELECT count(*) FROM customers WHERE psid='psid-brandnew-xyz'")
        if ncust != 1:
            fails.append(f"T9: {ncust} customer cho psid (mong 1)")

        # === T10 (FINDING 2) override single-use KHÔNG double-spend qua 2 SKU đồng thời ===
        await reset(conn)
        await conn.execute("INSERT INTO products (sku,name,description,price_vnd,stock) "
                           "VALUES ('3S-TEST2','Test2','t',200000,1000) "
                           "ON CONFLICT (sku) DO UPDATE SET stock=1000")
        cid_ovr = await conn.fetchval(
            "INSERT INTO customers (psid,name,phone,address) "
            "VALUES ('psid-ovr','O','0912345678','x') "
            "ON CONFLICT (psid) DO UPDATE SET name='O' RETURNING id")
        await conn.execute("DELETE FROM price_overrides WHERE customer_id=$1", cid_ovr)
        await conn.execute("INSERT INTO price_overrides (customer_id,quantity,unit_price_vnd,note) "
                           "VALUES ($1,3,50000,'test')", cid_ovr)

        def ovr_env(key, sku):
            return build_order_create_envelope(
                raw_payload={**BASE, "sku": sku, "quantity": 3, "psid": "psid-ovr"},
                actor=Actor("customer", "psid-ovr"), channel="messenger", idempotency_key=key)

        ro = await asyncio.gather(
            order_service.execute_order_create(ovr_env("KEY-OVR-A-00001", "3S-100G")),
            order_service.execute_order_create(ovr_env("KEY-OVR-B-00001", "3S-TEST2")),
            return_exceptions=True)
        oks10 = [r for r in ro if not isinstance(r, Exception)]
        if len(oks10) != 2:
            fails.append(f"T10: không phải 2 đơn thành công: {ro}")
        used_n = await conn.fetchval(
            "SELECT count(*) FROM price_overrides WHERE customer_id=$1 AND used=TRUE", cid_ovr)
        if used_n != 1:
            fails.append(f"T10: override used={used_n} (mong 1 — single-use, không double-spend)")
        ovr_priced = [r for r in oks10 if r.result and r.result["unit_price_vnd"] == 50000]
        if len(ovr_priced) != 1:
            fails.append(f"T10: {len(ovr_priced)} đơn dùng giá override (mong đúng 1)")
    finally:
        await conn.close()

    if fails:
        print("COMMAND-ORDER-SERVICE FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("COMMAND-ORDER-SERVICE PASS: T1 atomicity+redaction; T2 dup same-payload; T3 409 conflict; "
          "T4 insufficient_stock; T5 product_not_found; T6 qty-limit; T7 20-conc=1 order no-oversell; "
          "T8 mixed-key 10 success/10 conflict no-oversell; T9 new-customer race=2 orders/1 customer "
          "(FINDING 1); T10 override single-use no double-spend (FINDING 2)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
