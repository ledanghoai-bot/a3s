#!/usr/bin/env python3
"""M2 Slice 2 evidence — backfill + reconciliation (Spec §15.3-15.5, §17.1).

  docker exec alpha3s-api-1 python scripts/m2_backfill_test.py

Chung minh tren throwaway DB (m2s2_itest):
  1. Migrations 001..024 ap fresh.
  2. Reconstruct KHONG copy mu: opening_on_hand=stock+reserved, available==stock; consumed/cancelled
     KHONG cong lai; product stock=0 van co balance.
  3. Opening + reserve movements; ledger reconcile == balance (§17.1).
  4. Idempotent/resumable: apply 2 lan -> state khong doi (reserved khong nhan doi).
  5. Abort-on-anomaly: negative stock -> abort; unknown status -> abort (khong ghi).
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
ADMIN_DB = "postgresql://alpha3s:alpha3s@db:5432/postgres"
TEST_DB = "m2s2_itest"
TEST_URL = "postgresql://alpha3s:alpha3s@db:5432/" + TEST_DB

_spec = importlib.util.spec_from_file_location("m2_backfill", MIG.parent / "scripts" / "m2_backfill.py")
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)

_fail = []


def check(cond, label):
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        _fail.append(label)


async def apply_migrations(conn):
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
        "applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT, transactional BOOLEAN NOT NULL DEFAULT true)"
    )
    for p in sorted(x for x in MIG.glob("*.sql") if x.name[:3].isdigit()):
        async with conn.transaction():
            await conn.execute(p.read_text(encoding="utf-8"))


async def seed_legacy(conn):
    a = await conn.fetchval("INSERT INTO products (sku,name,price_vnd,stock) VALUES ('PA','A',170000,998) RETURNING id")
    b = await conn.fetchval("INSERT INTO products (sku,name,price_vnd,stock) VALUES ('PB','B',160000,0) RETURNING id")
    c = await conn.fetchval("INSERT INTO products (sku,name,price_vnd,stock) VALUES ('PC','C',140000,50) RETURNING id")

    async def order(status, items):
        oid = await conn.fetchval("INSERT INTO orders (status) VALUES ($1) RETURNING id", status)
        for pid, qty in items:
            await conn.execute(
                "INSERT INTO order_items (order_id,product_id,quantity,unit_price_vnd) VALUES ($1,$2,$3,1000)",
                oid, pid, qty,
            )
        return oid

    await order("new", [(a, 1)])
    await order("new", [(a, 1)])          # A: active reserved = 2
    await order("new", [(c, 3)])          # C: active reserved = 3
    await order("shipped", [(c, 5)])      # consumed -> KHONG cong lai
    await order("cancelled", [(c, 2)])    # cancelled -> bo qua
    return a, b, c


async def fresh_db():
    admin = await asyncpg.connect(ADMIN_DB)
    await admin.execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{TEST_DB}' AND pid<>pg_backend_pid()")
    await admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    await admin.execute(f"CREATE DATABASE {TEST_DB}")
    await admin.close()


async def bal(conn, loc, pid):
    return await conn.fetchrow(
        "SELECT on_hand, reserved, on_hand-reserved AS available FROM inventory_balances "
        "WHERE location_id=$1 AND product_id=$2", loc, pid)


async def main():
    await fresh_db()
    conn = await asyncpg.connect(TEST_URL)
    try:
        print("[1] migrations 001..024")
        await apply_migrations(conn)
        a, b, c = await seed_legacy(conn)
        check(True, "seeded legacy (3 products, 5 orders)")

        print("[2] audit clean -> plan -> apply")
        au = await bf.audit(conn)
        check(au["ok"], f"audit clean (anomalies={au['anomalies']})")
        plan = await bf.build_plan(conn)
        batch = "00000000-0000-0000-0000-000000000001"
        async with conn.transaction():
            await bf.apply(conn, plan, batch)

        loc = await conn.fetchval("SELECT id FROM inventory_locations WHERE code=$1", bf.DEFAULT_LOCATION_CODE)
        check(loc is not None, "default location 'default-fulfillment' created")

        ba, bb, bc = await bal(conn, loc, a), await bal(conn, loc, b), await bal(conn, loc, c)
        check(ba["on_hand"] == 1000 and ba["reserved"] == 2 and ba["available"] == 998,
              f"A on_hand=1000 reserved=2 available=998 (got {dict(ba)})")
        check(bb["on_hand"] == 0 and bb["reserved"] == 0,
              f"B stock=0 has balance on_hand=0 reserved=0 (got {dict(bb)})")
        check(bc["on_hand"] == 53 and bc["reserved"] == 3 and bc["available"] == 50,
              f"C on_hand=53 reserved=3 available=50 — consumed/cancelled NOT restored (got {dict(bc)})")

        nres = await conn.fetchval("SELECT count(*) FROM inventory_reservations WHERE status='active'")
        check(nres == 3, f"3 active reservations (A x2, C x1) (got {nres})")
        nprod = await conn.fetchval("SELECT count(*) FROM products")
        nopen = await conn.fetchval("SELECT count(*) FROM inventory_movements WHERE movement_type='opening_balance'")
        check(nopen == nprod, f"opening_balance movement per product incl seeded (products={nprod}, opening={nopen})")

        print("[3] reconcile §17.1")
        rc = await bf.reconcile(conn)
        check(rc["ok"], f"reconcile OK (mismatches={rc['mismatches']})")

        print("[4] idempotent re-apply")
        plan2 = await bf.build_plan(conn)
        check(plan2["checksum"] == plan["checksum"], "plan checksum stable across runs")
        async with conn.transaction():
            await bf.apply(conn, plan2, batch)
        ba2 = await bal(conn, loc, a)
        check(ba2["reserved"] == 2 and ba2["on_hand"] == 1000, f"A unchanged after re-apply (got {dict(ba2)})")
        nres2 = await conn.fetchval("SELECT count(*) FROM inventory_reservations WHERE status='active'")
        check(nres2 == 3, f"reservations not duplicated after re-apply (got {nres2})")
        nmov = await conn.fetchval("SELECT count(*) FROM inventory_movements")
        async with conn.transaction():
            await bf.apply(conn, plan2, batch)
        nmov2 = await conn.fetchval("SELECT count(*) FROM inventory_movements")
        check(nmov == nmov2, f"movements not duplicated (got {nmov} -> {nmov2})")
        rc2 = await bf.reconcile(conn)
        check(rc2["ok"], "reconcile still OK after re-apply")

        print("[5] abort-on-anomaly")
        # migration 028 CHECK stock>=0 chặn set -5 -> tạm drop để mô phỏng legacy data pre-028
        await conn.execute("ALTER TABLE products DROP CONSTRAINT products_stock_nonneg")
        await conn.execute("UPDATE products SET stock=-5 WHERE id=$1", b)
        au_neg = await bf.audit(conn)
        check(not au_neg["ok"] and any("negative_stock" in x for x in au_neg["anomalies"]),
              f"negative stock -> abort (anomalies={au_neg['anomalies']})")
        await conn.execute("UPDATE products SET stock=0 WHERE id=$1", b)
        await conn.execute("ALTER TABLE products ADD CONSTRAINT products_stock_nonneg CHECK (stock >= 0)")

        await conn.execute("ALTER TABLE orders DROP CONSTRAINT orders_status_check")
        await conn.execute("INSERT INTO orders (status) VALUES ('mystery')")
        au_unk = await bf.audit(conn)
        check(not au_unk["ok"] and any("unknown_status" in x for x in au_unk["anomalies"]),
              f"unknown status -> abort (anomalies={au_unk['anomalies']})")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — backfill reconstruct + reconcile + idempotent + abort-on-anomaly proven")


if __name__ == "__main__":
    asyncio.run(main())
