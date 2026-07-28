#!/usr/bin/env python3
"""M2 CA M2-S1-F02 evidence — adjustment giữ dual-write compatibility (products.stock == available).

  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2adj_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m2_adjustment_compat_test.py

Chung minh (m2_inventory_ledger ON, m2_balance_authority OFF = compat window):
  - baseline reconcile (check_stock_compat) OK.
  - small adjustment (default loc): on_hand & products.stock cung tang -> reconcile OK.
  - large approve (default loc): dual-write -> reconcile OK.
  - decrease: dual-write -> reconcile OK.
  - reject: khong doi stock.
  - retry approve (cung key): idempotent, stock KHONG nhan doi.
  - NON-default location adjustment: KHONG dua products.stock (compat chi default loc).
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
from app.services.command import lifecycle, registry  # noqa: E402
from app.services.command.envelope import Actor  # noqa: E402
from app.services.inventory import reconcile as recon  # noqa: E402

bf_spec = importlib.util.spec_from_file_location("m2_backfill", ROOT / "scripts" / "m2_backfill.py")
bf = importlib.util.module_from_spec(bf_spec)
bf_spec.loader.exec_module(bf)

_fail = []


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


def aenv(ct, key, actor_id, **pl):
    return lifecycle.build_lifecycle_envelope(command_type=ct, payload=pl,
        actor=Actor("staff", str(actor_id)), channel="dashboard", idempotency_key=key)


async def stock_and_avail(conn, pid, loc):
    stock = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
    row = await conn.fetchrow("SELECT on_hand, on_hand-reserved AS available FROM inventory_balances WHERE location_id=$1 AND product_id=$2", loc, pid)
    return stock, row["on_hand"], row["available"]


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
            await bf.apply(conn, plan, "00000000-0000-0000-0000-0000000000d2")
        settings.m2_inventory_ledger = True
        settings.m2_balance_authority = False
        req = await auth_service.create_staff_user("adj_req", "pw12345678", "IT", role_key="warehouse")
        head = await auth_service.create_staff_user("adj_head", "pw12345678", "IT", role_key="unit_head")
        pid = await conn.fetchval("SELECT id FROM products WHERE sku='3S-100G'")
        loc = await conn.fetchval("SELECT id FROM inventory_locations WHERE is_default")
        await conn.execute("INSERT INTO inventory_unit_members (staff_id,location_id,unit_role) VALUES ($1,$2,'unit_head')", head["id"], loc)

        async def reconc_ok(label):
            rep = await recon.reconcile_inventory(conn, check_stock_compat=True)
            check(rep.ok, f"{label}: reconcile stock==available OK ({rep.mismatches})")

        print("[0] baseline")
        s, oh, av = await stock_and_avail(conn, pid, loc)
        check(s == 100 and oh == 100 and av == 100, f"baseline stock=on_hand=available=100 ({s}/{oh}/{av})")
        await reconc_ok("baseline")

        print("[1] small +5 (threshold=max(10,2%*100=2)=10 -> small)")
        await lifecycle.execute_lifecycle(aenv(registry.ADJUST_REQUEST, "ADJ-S1", req["id"],
            location_id=loc, product_id=pid, quantity_delta=5, reason="count"))
        s, oh, av = await stock_and_avail(conn, pid, loc)
        check(s == 105 and oh == 105 and av == 105 and s == av, f"small +5 -> stock=avail=105 ({s}/{oh}/{av})")
        await reconc_ok("after small")

        print("[2] large +50 approve")
        rq = await lifecycle.execute_lifecycle(aenv(registry.ADJUST_REQUEST, "ADJ-L1", req["id"],
            location_id=loc, product_id=pid, quantity_delta=50, reason="recount"))
        adj = rq.result["request_id"]
        await lifecycle.execute_lifecycle(aenv(registry.ADJUST_APPROVE, "ADJ-L1-APR", head["id"], request_id=adj))
        s, oh, av = await stock_and_avail(conn, pid, loc)
        check(s == 155 and av == 155 and s == av, f"large +50 -> stock=avail=155 ({s}/{oh}/{av})")
        await reconc_ok("after large approve")

        print("[3] retry approve idempotent (stock khong nhan doi)")
        await lifecycle.execute_lifecycle(aenv(registry.ADJUST_APPROVE, "ADJ-L1-APR", head["id"], request_id=adj))
        s2, _, av2 = await stock_and_avail(conn, pid, loc)
        check(s2 == 155 and av2 == 155, f"retry approve -> stock van 155 ({s2}/{av2})")

        print("[4] decrease -5")
        await lifecycle.execute_lifecycle(aenv(registry.ADJUST_REQUEST, "ADJ-D1", req["id"],
            location_id=loc, product_id=pid, quantity_delta=-5, reason="shrink"))
        s, oh, av = await stock_and_avail(conn, pid, loc)
        check(s == 150 and av == 150, f"decrease -5 -> stock=avail=150 ({s}/{av})")
        await reconc_ok("after decrease")

        print("[5] reject: khong doi stock")
        rq = await lifecycle.execute_lifecycle(aenv(registry.ADJUST_REQUEST, "ADJ-L2", req["id"],
            location_id=loc, product_id=pid, quantity_delta=99, reason="big"))
        adj2 = rq.result["request_id"]
        s_before = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
        await lifecycle.execute_lifecycle(aenv(registry.ADJUST_REJECT, "ADJ-L2-REJ", head["id"], request_id=adj2, reason="no"))
        s_after = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
        check(s_before == s_after == 150, f"reject -> stock khong doi ({s_before}->{s_after})")
        await reconc_ok("after reject")

        print("[6] NON-default location: KHONG dual-write products.stock")
        loc2 = await conn.fetchval("INSERT INTO inventory_locations (code,name,location_type,is_default) VALUES ('WH2','WH2','warehouse',false) RETURNING id")
        await conn.execute("INSERT INTO inventory_balances (location_id,product_id,on_hand,reserved) VALUES ($1,$2,0,0)", loc2, pid)
        await conn.execute("INSERT INTO inventory_unit_members (staff_id,location_id,unit_role) VALUES ($1,$2,'unit_head')", head["id"], loc2)
        s_before = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
        await lifecycle.execute_lifecycle(aenv(registry.ADJUST_REQUEST, "ADJ-NL", req["id"],
            location_id=loc2, product_id=pid, quantity_delta=7, reason="wh2"))
        s_after = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
        oh2 = await conn.fetchval("SELECT on_hand FROM inventory_balances WHERE location_id=$1 AND product_id=$2", loc2, pid)
        check(s_before == s_after and oh2 == 7, f"non-default adjust: products.stock khong doi ({s_before}->{s_after}), loc2 on_hand=7 ({oh2})")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — adjustment dual-write compat: products.stock==available giu qua small/large/decrease/reject/retry")


if __name__ == "__main__":
    asyncio.run(main())
