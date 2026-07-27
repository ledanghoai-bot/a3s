#!/usr/bin/env python3
"""M2 CA M2-S1-F07 evidence — EXISTING-APPLY migration rehearsal (AC-M2-16).

Chung minh migration 021..RC apply an toan tu DB DA TON TAI o moc 020 (khong chi fresh). Seed du lieu
dai dien (products + orders nhieu legacy status + items + customer) o 020, ghi schema_migrations 001..020
nhu mot DB that, roi apply 021..RC (record schema_migrations). Kiem tra:
  - PRE/POST: du lieu hien huu KHONG mat (orders/products count + checksum id/status/stock identical).
  - Constraint/data hien huu migrate an toan (025 status CHECK khop legacy status dang co).
  - New schema (021..027) hien dien; postcondition moi migration PASS (RAISE neu fail).
  - KHONG PII trong output (chi count/checksum/status aggregate).

  docker exec alpha3s-api-1 python scripts/m2_existing_apply_rehearsal.py
"""
import asyncio
import hashlib
import sys
import time
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
ADMIN = "postgresql://alpha3s:alpha3s@db:5432/postgres"
TEST_DB = "m2exist_itest"
URL = "postgresql://alpha3s:alpha3s@db:5432/" + TEST_DB
EXISTING_THROUGH = 20  # DB "hien huu" o moc M1 = migration 020

_fail = []


def check(cond, label):
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        _fail.append(label)


def _num(p):
    return int(p.name[:3])


async def _apply(conn, files):
    for p in files:
        sql = p.read_text(encoding="utf-8")
        async with conn.transaction():
            await conn.execute(sql)
        await conn.execute(
            "INSERT INTO schema_migrations(version,checksum,applied_by) VALUES ($1,$2,'rehearsal') "
            "ON CONFLICT (version) DO NOTHING",
            p.stem, hashlib.sha256(sql.encode()).hexdigest())


async def _data_checksum(conn):
    orders = await conn.fetch("SELECT id, status FROM orders ORDER BY id")
    prods = await conn.fetch("SELECT id, stock FROM products ORDER BY id")
    blob = ";".join(f"{r['id']}:{r['status']}" for r in orders) + "|" + \
           ";".join(f"{r['id']}:{r['stock']}" for r in prods)
    return hashlib.sha256(blob.encode()).hexdigest(), len(orders), len(prods)


async def main():  # noqa: C901
    t0 = time.monotonic() if hasattr(time, "monotonic") else 0
    admin = await asyncpg.connect(ADMIN)
    await admin.execute(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{TEST_DB}' AND pid<>pg_backend_pid()")
    await admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    await admin.execute(f"CREATE DATABASE {TEST_DB}")
    await admin.close()

    files = sorted((p for p in MIG.glob("*.sql") if p.name[:3].isdigit()), key=_num)
    existing = [p for p in files if _num(p) <= EXISTING_THROUGH]
    m2 = [p for p in files if _num(p) > EXISTING_THROUGH]
    print(f"[setup] existing=001..{EXISTING_THROUGH:03d} ({len(existing)} files); apply={[p.stem[:3] for p in m2]}")

    conn = await asyncpg.connect(URL)
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT, transactional BOOLEAN NOT NULL DEFAULT true)")

        print("[1] dựng DB hiện hữu ở mốc 020 + seed dữ liệu đại diện")
        await _apply(conn, existing)
        cust = await conn.fetchval("INSERT INTO customers (psid,name,phone,address) VALUES ('psid-ex','C','0912345678','addr') RETURNING id")
        await conn.execute("UPDATE products SET stock=500 WHERE sku='3S-100G'")
        pid = await conn.fetchval("SELECT id FROM products WHERE sku='3S-100G'")
        # orders nhiều legacy status (bài toán existing-data cho 025 status CHECK)
        for stt in ["new", "confirmed", "shipped", "done", "cancelled"]:
            oid = await conn.fetchval("INSERT INTO orders (customer_id,status,total_vnd) VALUES ($1,$2,1000) RETURNING id", cust, stt)
            await conn.execute("INSERT INTO order_items (order_id,product_id,quantity,unit_price_vnd) VALUES ($1,$2,1,1000)", oid, pid)
        applied_through = await conn.fetchval("SELECT max(version) FROM schema_migrations")
        check("020" in applied_through, f"schema_migrations tới 020 ({applied_through})")

        pre_ck, pre_orders, pre_prods = await _data_checksum(conn)
        legacy_statuses = sorted(r["status"] for r in await conn.fetch("SELECT DISTINCT status FROM orders"))
        print(f"[pre] orders={pre_orders} products={pre_prods} statuses={legacy_statuses} checksum={pre_ck[:12]}")

        print("[2] EXISTING-APPLY: migration 021..RC trên DB đã có dữ liệu")
        try:
            await _apply(conn, m2)
            check(True, f"apply 021..{m2[-1].stem[:3]} thành công (postcondition mỗi migration PASS)")
        except Exception as e:  # noqa: BLE001
            check(False, f"existing-apply FAIL: {e}")
            raise

        print("[3] POST integrity")
        post_ck, post_orders, post_prods = await _data_checksum(conn)
        check(post_ck == pre_ck, f"du lieu hien huu KHONG doi (checksum {pre_ck[:12]} == {post_ck[:12]})")
        check(post_orders == pre_orders and post_prods == pre_prods,
              f"orders/products count giữ nguyên ({pre_orders}/{pre_prods} -> {post_orders}/{post_prods})")
        # new schema present
        for t in ["inventory_balances", "inventory_movements", "order_events", "inventory_adjustment_requests"]:
            ok = await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{t}")
            check(ok, f"new table {t} hiện diện sau existing-apply")
        # cot moi tren orders (existing rows nhan default/null)
        io = await conn.fetchval("SELECT count(*) FROM orders WHERE inventory_status='unreserved'")
        check(io == pre_orders, f"orders.inventory_status default 'unreserved' cho existing rows ({io})")
        oc_null = await conn.fetchval("SELECT count(*) FROM orders WHERE origin_channel IS NULL")
        check(oc_null == pre_orders, f"orders.origin_channel NULL cho existing rows ({oc_null})")
        # 025 status CHECK chap nhan legacy statuses dang ton tai (khong vi pham khi ADD CONSTRAINT)
        cdef = await conn.fetchval("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='orders_status_check'")
        check(cdef and "shipped" in cdef and "ready_for_fulfillment" in cdef,
              "orders_status_check bao gom legacy + M2 status (existing data hop le)")
        # runtime role (024) + mutation perms (026) + origin_channel (027)
        role_ok = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname='alpha3s_app'")
        perm_ok = await conn.fetchval("SELECT 1 FROM permissions WHERE key='order.complete'")
        check(role_ok and perm_ok, "024 runtime role + 026 mutation perms hiện diện")

        dur = round((time.monotonic() - t0), 2) if t0 else "n/a"
        print(f"[duration] {dur}s")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — existing-apply 020->RC an toan; du lieu hien huu bao toan; no PII in output")


if __name__ == "__main__":
    asyncio.run(main())
