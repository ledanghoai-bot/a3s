#!/usr/bin/env python3
"""M2 CA M2-S1-F05 evidence — balance-authority read path (AC-M2-13), chống split-brain.

  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2ba_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m2_balance_authority_test.py

Chung minh order.create accept-decision doc TU dung nguon theo flag:
  - m2_balance_authority OFF (Phase A/B): authority = legacy products.stock.
      * stock=0 & balance available>0 -> REJECT (legacy authority).
  - m2_balance_authority ON (Phase C): authority = balance.available.
      * stock=0 (mirror) & balance available>0 -> ACCEPT (balance authority) + reserve.
      * balance available=0 & stock>0 -> REJECT (balance authority) — khong oversell tu legacy stale.
  - Gate: chi doi hanh vi khi flag ON; OFF giu nguyen. Reserve duoi FOR UPDATE la guard cuoi.
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services import auth_service  # noqa: E402
from app.services.command import errors, order_service  # noqa: E402
from app.services.command.envelope import (  # noqa: E402
    Actor,
    build_order_create_envelope,
)

bf_spec = importlib.util.spec_from_file_location("m2_backfill", ROOT / "scripts" / "m2_backfill.py")
bf = importlib.util.module_from_spec(bf_spec)
bf_spec.loader.exec_module(bf)

_fail = []
STAFF_ID = "1"


def check(cond, label):
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        _fail.append(label)


def _db():
    return settings.database_url.replace("+asyncpg", "")


async def migrate(conn):
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
        "applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT, transactional BOOLEAN NOT NULL DEFAULT true)")
    for p in sorted(x for x in MIG.glob("*.sql") if x.name[:3].isdigit()):
        async with conn.transaction():
            await conn.execute(p.read_text(encoding="utf-8"))


def cenv(key, qty):
    payload = dict(customer_name="A", phone="0912345678", address="12 Le Loi", sku="3S-100G",
                   quantity=qty, unit_price_vnd=150000)
    return build_order_create_envelope(raw_payload=payload, actor=Actor("staff", STAFF_ID),
                                       channel="dashboard", idempotency_key=key)


async def main():  # noqa: C901
    dbname = _db().rsplit("/", 1)[-1]
    if "test" not in dbname:
        print(f"ABORT: db='{dbname}' khong chua 'test'.")
        return 2
    admin = await asyncpg.connect("postgresql://alpha3s:alpha3s@db:5432/postgres")
    await admin.execute(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{dbname}' AND pid<>pg_backend_pid()")
    await admin.execute(f"DROP DATABASE IF EXISTS {dbname}")
    await admin.execute(f"CREATE DATABASE {dbname}")
    await admin.close()

    conn = await asyncpg.connect(_db())
    try:
        await migrate(conn)
        await conn.execute("UPDATE products SET stock=100 WHERE sku='3S-100G'")
        plan = await bf.build_plan(conn)
        async with conn.transaction():
            await bf.apply(conn, plan, "00000000-0000-0000-0000-0000000000f5")
        st = await auth_service.create_staff_user("ba_admin", "pw12345678", "IT", role_key="admin")
        global STAFF_ID
        STAFF_ID = str(st["id"])
        settings.m2_inventory_ledger = True
        pid = await conn.fetchval("SELECT id FROM products WHERE sku='3S-100G'")
        loc = await conn.fetchval("SELECT id FROM inventory_locations WHERE is_default")

        # Tạo split-brain có kiểm soát: legacy stock=0 nhưng balance available=100
        await conn.execute("UPDATE products SET stock=0 WHERE id=$1", pid)

        print("[1] flag OFF (legacy authority): stock=0 -> REJECT dù balance có hàng")
        settings.m2_balance_authority = False
        r = await order_service.execute_order_create(cenv("BA-OFF", 5))
        check(r.outcome == "rejected" and r.error_code == errors.INSUFFICIENT_STOCK,
              f"OFF -> reject theo legacy stock=0 ({r.outcome}/{r.error_code})")

        print("[2] flag ON (balance authority): stock=0 (mirror) nhưng balance available=100 -> ACCEPT")
        settings.m2_balance_authority = True
        r = await order_service.execute_order_create(cenv("BA-ON", 5))
        check(r.outcome == "succeeded", f"ON -> accept theo balance available ({r.outcome} {r.error_code})")
        bal = await conn.fetchrow("SELECT on_hand, reserved FROM inventory_balances WHERE location_id=$1 AND product_id=$2", loc, pid)
        check(bal["reserved"] == 5, f"đã reserve 5 trên balance ({dict(bal)})")

        print("[3] flag ON: balance available=0 nhưng legacy stock cao -> REJECT (không oversell từ stale)")
        # đẩy reserved = on_hand -> available 0; set legacy stock cao (stale)
        await conn.execute("UPDATE inventory_balances SET reserved=on_hand WHERE location_id=$1 AND product_id=$2", loc, pid)
        await conn.execute("UPDATE products SET stock=999 WHERE id=$1", pid)
        r = await order_service.execute_order_create(cenv("BA-ON-EMPTY", 1))
        check(r.outcome == "rejected" and r.error_code == errors.INSUFFICIENT_STOCK,
              f"ON + balance available=0 -> reject dù legacy stock=999 ({r.outcome}/{r.error_code})")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — balance-authority read path (AC-M2-13): authority switch theo flag, chong split-brain")


if __name__ == "__main__":
    asyncio.run(main())
