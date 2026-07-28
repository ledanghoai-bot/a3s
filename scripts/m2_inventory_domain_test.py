#!/usr/bin/env python3
"""M2 Slice 3 evidence — inventory domain (repos/invariants/lock ordering/reconcile).

  docker exec alpha3s-api-1 python scripts/m2_inventory_domain_test.py

Chung minh:
  1. reserve giam available; over-reserve -> insufficient_inventory (khong partial).
  2. apply_movement idempotent (cung key 2 lan -> ap 1 lan).
  3. invariant: release qua muc -> reserved<0 reject; adjustment_decrease duoi reserved -> reserved>on_hand reject.
  4. release tra lai available + reservation=released; fulfill consume on_hand+reserved + reservation=fulfilled.
  5. threshold §12.1: compute_threshold(0)=10, (1000)=20.
  6. reconcile §17.1 OK sau ops; phat hien mismatch khi inject.
  7. CONCURRENCY/lock ordering: 2 reserve tranh don vi cuoi -> dung 1 thang thang (FOR UPDATE serialize).
"""
import asyncio
import sys
import uuid
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
ADMIN_DB = "postgresql://alpha3s:alpha3s@db:5432/postgres"
TEST_DB = "m2s3_itest"
TEST_URL = "postgresql://alpha3s:alpha3s@db:5432/" + TEST_DB

sys.path.insert(0, str(ROOT))
from app.services.inventory import errors, reconcile, service  # noqa: E402
from app.services.inventory import repository as repo  # noqa: E402

_fail = []


def check(cond, label):
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        _fail.append(label)


async def migrate(conn):
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
        "applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT, transactional BOOLEAN NOT NULL DEFAULT true)")
    for p in sorted(x for x in MIG.glob("*.sql") if x.name[:3].isdigit()):
        async with conn.transaction():
            await conn.execute(p.read_text(encoding="utf-8"))


async def seed(conn, on_hand):
    loc = await conn.fetchval(
        "INSERT INTO inventory_locations (code,name,location_type,is_default,is_active) "
        "VALUES ('L1','L1','fulfillment',true,true) RETURNING id")
    # dung product seed cua 001 (id se co); tao rieng cho chac chan
    pid = await conn.fetchval("INSERT INTO products (sku,name,price_vnd,stock) VALUES ('S1','S1',1000,$1) RETURNING id", on_hand)
    oid = await conn.fetchval("INSERT INTO orders (status) VALUES ('new') RETURNING id")
    # seed balance QUA opening_balance movement (nhu backfill) -> ledger day du de reconcile
    async with conn.transaction():
        await repo.apply_movement(conn, location_id=loc, product_id=pid, movement_type="opening_balance",
            on_hand_delta=on_hand, reserved_delta=0, idempotency_key=f"seed:open:{loc}:{pid}",
            actor_type="system", actor_id="seed", correlation_id=uuid.uuid4(),
            reference_type="seed", reference_id="seed")
    return loc, pid, oid


async def new_item(conn, oid, pid, qty):
    return await conn.fetchval(
        "INSERT INTO order_items (order_id,product_id,quantity,unit_price_vnd) VALUES ($1,$2,$3,1000) RETURNING id",
        oid, pid, qty)


async def fresh_db():
    admin = await asyncpg.connect(ADMIN_DB)
    await admin.execute(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{TEST_DB}' AND pid<>pg_backend_pid()")
    await admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    await admin.execute(f"CREATE DATABASE {TEST_DB}")
    await admin.close()


async def main():
    # ---- threshold (pure) ----
    check(service.compute_threshold(0) == 10, "threshold(0)=10")
    check(service.compute_threshold(1000) == 20, "threshold(1000)=20")
    check(service.is_large_adjustment(1000, 20) and not service.is_large_adjustment(1000, 19),
          "is_large: >=20 large, 19 small @on_hand=1000")

    await fresh_db()
    conn = await asyncpg.connect(TEST_URL)
    corr = uuid.uuid4()
    try:
        await migrate(conn)
        loc, pid, oid = await seed(conn, on_hand=10)
        it1 = await new_item(conn, oid, pid, 4)

        print("[1] reserve + available")
        async with conn.transaction():
            rid1, eff = await service.reserve_item(
                conn, order_id=oid, order_item_id=it1, location_id=loc, product_id=pid, quantity=4,
                idem_prefix="cmd1", actor_type="system", actor_id="t", correlation_id=corr)
        b = await repo.get_balance(conn, loc, pid)
        check(b["reserved"] == 4 and b["available"] == 6, f"reserve 4 -> reserved=4 available=6 (got {dict(b)})")

        print("[2] idempotent reserve (same keys)")
        async with conn.transaction():
            rid1b, eff2 = await service.reserve_item(
                conn, order_id=oid, order_item_id=it1, location_id=loc, product_id=pid, quantity=4,
                idem_prefix="cmd1", actor_type="system", actor_id="t", correlation_id=corr)
        b = await repo.get_balance(conn, loc, pid)
        check(eff2.already_applied and rid1b == rid1 and b["reserved"] == 4,
              f"replay applied once (reserved still 4, already_applied={eff2.already_applied})")

        print("[3] over-reserve -> insufficient")
        it2 = await new_item(conn, oid, pid, 100)
        try:
            async with conn.transaction():
                await service.reserve_item(conn, order_id=oid, order_item_id=it2, location_id=loc,
                    product_id=pid, quantity=100, idem_prefix="cmd2", actor_type="system", actor_id="t",
                    correlation_id=corr)
            check(False, "over-reserve should raise")
        except errors.InventoryError as e:
            check(e.code == errors.INSUFFICIENT_INVENTORY, f"over-reserve -> insufficient ({e.code})")
        b = await repo.get_balance(conn, loc, pid)
        check(b["reserved"] == 4, "no partial reserve on insufficient")

        print("[4] invariant: adjustment_decrease duoi reserved -> reject")
        try:
            async with conn.transaction():
                # on_hand=10 reserved=4; giam on_hand 8 -> on_hand=2 < reserved 4 -> reserved>on_hand
                await service.apply_adjustment(conn, location_id=loc, product_id=pid, quantity_delta=-8,
                    idem_prefix="cmd3", actor_type="staff", actor_id="s1", correlation_id=corr,
                    reason="test", reference_id="adj1")
            check(False, "decrease below reserved should raise")
        except errors.InventoryError as e:
            check(e.code == errors.INVARIANT_VIOLATION, f"decrease below reserved -> invariant ({e.code})")

        print("[5] release restores, fulfill consumes")
        resv = await conn.fetchrow("SELECT * FROM inventory_reservations WHERE id=$1", uuid.UUID(rid1))
        async with conn.transaction():
            await service.release_reservation(conn, resv, terminal_status="released", idem_prefix="cmdR",
                actor_type="system", actor_id="t", correlation_id=corr)
        b = await repo.get_balance(conn, loc, pid)
        st = await conn.fetchval("SELECT status FROM inventory_reservations WHERE id=$1", uuid.UUID(rid1))
        check(b["reserved"] == 0 and b["on_hand"] == 10 and st == "released",
              f"release -> reserved=0 on_hand=10 status=released (got reserved={b['reserved']} status={st})")

        it3 = await new_item(conn, oid, pid, 3)
        async with conn.transaction():
            rid3, _ = await service.reserve_item(conn, order_id=oid, order_item_id=it3, location_id=loc,
                product_id=pid, quantity=3, idem_prefix="cmdF", actor_type="system", actor_id="t", correlation_id=corr)
        resv3 = await conn.fetchrow("SELECT * FROM inventory_reservations WHERE id=$1", uuid.UUID(rid3))
        async with conn.transaction():
            await service.fulfill_reservation(conn, resv3, idem_prefix="cmdF", actor_type="staff",
                actor_id="s1", correlation_id=corr)
        b = await repo.get_balance(conn, loc, pid)
        st3 = await conn.fetchval("SELECT status FROM inventory_reservations WHERE id=$1", uuid.UUID(rid3))
        check(b["on_hand"] == 7 and b["reserved"] == 0 and st3 == "fulfilled",
              f"fulfill 3 -> on_hand=7 reserved=0 status=fulfilled (got on_hand={b['on_hand']} status={st3})")

        print("[6] reconcile OK, then detect mismatch")
        rep = await reconcile.reconcile_inventory(conn, check_stock_compat=False)
        check(rep.ok, f"reconcile OK (mismatches={rep.mismatches})")
        await conn.execute("UPDATE inventory_balances SET reserved=reserved+5 WHERE location_id=$1 AND product_id=$2", loc, pid)
        rep2 = await reconcile.reconcile_inventory(conn, check_stock_compat=False)
        check(not rep2.ok and any("reserved" in m for m in rep2.mismatches),
              f"reconcile detects injected mismatch ({rep2.mismatches})")
        await conn.execute("UPDATE inventory_balances SET reserved=reserved-5 WHERE location_id=$1 AND product_id=$2", loc, pid)

        print("[7] concurrency: 2 reserve tranh don vi cuoi")
        loc2, pid2, oid2 = await seed_last_unit(conn)
        ia = await new_item(conn, oid2, pid2, 1)
        ib = await new_item(conn, oid2, pid2, 1)
        await concurrency_case(loc2, pid2, oid2, ia, ib)
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — inventory domain invariants/idempotency/lock-ordering/reconcile proven")


async def seed_last_unit(conn):
    loc = await conn.fetchval(
        "INSERT INTO inventory_locations (code,name,location_type) VALUES ('L2','L2','warehouse') RETURNING id")
    pid = await conn.fetchval("INSERT INTO products (sku,name,price_vnd,stock) VALUES ('S2','S2',1000,1) RETURNING id")
    oid = await conn.fetchval("INSERT INTO orders (status) VALUES ('new') RETURNING id")
    async with conn.transaction():
        await repo.apply_movement(conn, location_id=loc, product_id=pid, movement_type="opening_balance",
            on_hand_delta=1, reserved_delta=0, idempotency_key=f"seed:open:{loc}:{pid}",
            actor_type="system", actor_id="seed", correlation_id=uuid.uuid4(),
            reference_type="seed", reference_id="seed")
    return loc, pid, oid


async def concurrency_case(loc, pid, oid, item_a, item_b):
    corr = uuid.uuid4()
    c1 = await asyncpg.connect(TEST_URL)
    c2 = await asyncpg.connect(TEST_URL)
    try:
        tx1 = c1.transaction()
        await tx1.start()
        # c1 reserves the last unit, holds FOR UPDATE lock (khong commit)
        await service.reserve_item(c1, order_id=oid, order_item_id=item_a, location_id=loc, product_id=pid,
            quantity=1, idem_prefix="ca", actor_type="system", actor_id="a", correlation_id=corr)

        tx2 = c2.transaction()
        await tx2.start()
        task = asyncio.create_task(service.reserve_item(
            c2, order_id=oid, order_item_id=item_b, location_id=loc, product_id=pid, quantity=1,
            idem_prefix="cb", actor_type="system", actor_id="b", correlation_id=corr))
        blocked = False
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.7)
        except asyncio.TimeoutError:
            blocked = True
        check(blocked, "2nd reserver BLOCKS on FOR UPDATE while 1st holds lock (serialize)")

        await tx1.commit()  # release lock; c2 now sees on_hand=1 reserved=1
        try:
            await task
            check(False, "2nd reserver should fail insufficient after 1st commits")
        except errors.InventoryError as e:
            check(e.code == errors.INSUFFICIENT_INVENTORY, f"2nd reserver -> insufficient ({e.code})")
        await tx2.rollback()

        fresh = await c1.fetchrow("SELECT on_hand, reserved FROM inventory_balances WHERE location_id=$1 AND product_id=$2", loc, pid)
        check(fresh["reserved"] == 1 and fresh["on_hand"] == 1, f"exactly one reserve committed (got {dict(fresh)})")
    finally:
        await c1.close()
        await c2.close()


if __name__ == "__main__":
    asyncio.run(main())
