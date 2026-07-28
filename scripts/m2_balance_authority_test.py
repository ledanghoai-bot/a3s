#!/usr/bin/env python3
"""M2 CA M2-S1-F05 + M2-S2-F01 evidence — balance-authority read + Phase C stock MIRROR contract.

  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2ba_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m2_balance_authority_test.py

Contract Phase C mirror (S2-F01): products.stock := balance.available (materialize, KHÔNG delta stale)
sau MỌI inventory write. Assert sau mỗi op: authority đúng, invariant balance đúng, stock==available
(mirror), reconcile OK, stock KHÔNG âm — cả hai hướng split-brain.
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
from app.services.inventory import reconcile as recon  # noqa: E402

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


async def snap(conn, pid, loc):
    s = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
    r = await conn.fetchrow("SELECT on_hand, reserved, on_hand-reserved AS avail FROM inventory_balances WHERE location_id=$1 AND product_id=$2", loc, pid)
    return s, r["on_hand"], r["reserved"], r["avail"]


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

        async def assert_mirror(label):
            s, oh, rv, av = await snap(conn, pid, loc)
            rep = await recon.reconcile_inventory(conn, check_stock_compat=True)
            check(s == av and s >= 0 and rv <= oh and rep.ok,
                  f"{label}: stock={s}==avail={av}, stock>=0, reserved<=on_hand, reconcile={rep.ok} "
                  f"(mismatch={rep.mismatches})")

        print("[0] baseline mirror")
        await assert_mirror("baseline")

        print("[1] flag ON: create reserve -> mirror stock:=available (no stale delta)")
        settings.m2_balance_authority = True
        r = await order_service.execute_order_create(cenv("BA-C1", 5))
        check(r.outcome == "succeeded", f"create accept theo balance ({r.outcome})")
        await assert_mirror("after create (reserved 5)")  # stock 100->95

        print("[2] STALE stock (legacy writer) + flag ON -> balance authority accept, mirror HEAL, no negative")
        await conn.execute("UPDATE products SET stock=0 WHERE id=$1", pid)  # stale: stock=0 nhưng available=95
        r = await order_service.execute_order_create(cenv("BA-C2", 3))
        check(r.outcome == "succeeded", f"accept theo balance dù stock stale=0 ({r.outcome})")
        s, oh, rv, av = await snap(conn, pid, loc)
        check(s == av and s == 92 and s >= 0, f"mirror HEAL stale: stock={s}==avail={av}==92, no negative")
        await assert_mirror("after stale+create")

        print("[3] flag OFF (legacy authority): stale stock=0 -> reject dù balance có hàng")
        settings.m2_balance_authority = False
        await conn.execute("UPDATE products SET stock=0 WHERE id=$1", pid)  # available vẫn 92
        r = await order_service.execute_order_create(cenv("BA-C3", 1))
        check(r.outcome == "rejected" and r.error_code == errors.INSUFFICIENT_STOCK,
              f"OFF -> reject theo legacy stock=0 ({r.outcome}/{r.error_code})")
        # khôi phục mirror để tiếp (materialize tay như một op)
        await conn.execute("UPDATE products p SET stock=b.on_hand-b.reserved FROM inventory_balances b WHERE b.location_id=$1 AND b.product_id=$2 AND p.id=$2", loc, pid)

        print("[4] flag ON: balance available=0 (reserved=on_hand) -> reject, stock=0, no negative")
        settings.m2_balance_authority = True
        await conn.execute("UPDATE inventory_balances SET reserved=on_hand WHERE location_id=$1 AND product_id=$2", loc, pid)
        await conn.execute("UPDATE products p SET stock=b.on_hand-b.reserved FROM inventory_balances b WHERE b.location_id=$1 AND b.product_id=$2 AND p.id=$2", loc, pid)
        r = await order_service.execute_order_create(cenv("BA-C4", 1))
        check(r.outcome == "rejected" and r.error_code == errors.INSUFFICIENT_STOCK,
              f"ON + available=0 -> reject ({r.outcome}/{r.error_code})")
        s, _, _, av = await snap(conn, pid, loc)
        check(s == 0 and av == 0 and s >= 0, f"stock=0=available, no negative ({s}/{av})")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — balance-authority (F05) + Phase C mirror contract (F01): stock==available, no negative, reconcile OK")


if __name__ == "__main__":
    asyncio.run(main())
