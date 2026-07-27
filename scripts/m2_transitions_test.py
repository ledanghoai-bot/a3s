#!/usr/bin/env python3
"""M2 Slice 4 evidence — order state machine + transition service + order.create reservation.

Chay tren throwaway DB khop DATABASE_URL (an toan: db name phai chua 'test'):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2s4_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m2_transitions_test.py

Chung minh:
  1. Matrix guard §7.2: legal -> spec; illegal / terminal -> IllegalTransition (409).
  2. order.create (flag M2 on) reserve ATOMIC: order.inventory_status=reserved, reservation active TTL~24h,
     order.created event, balance.reserved=qty, products.stock==available (compat §15.6).
  3. Lifecycle: confirm (bỏ expiry, giữ reservation) -> processing -> ready -> fulfill (consume on_hand/reserved).
  4. cancel (new->cancelled) release + KHÔI PHỤC legacy stock (sửa cancel-no-restore); products.stock==available.
  5. Illegal transition trên đơn thật -> 409; event append idempotent.
  6. Fail-closed: reserve bất nhất (available<qty dù legacy stock đủ) -> rollback toàn bộ create (no order).
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
from app.services.inventory import repository as inv_repo  # noqa: E402
from app.services.order import transition_service as txn  # noqa: E402
from app.services.order import transitions  # noqa: E402
from app.services.order.events import append_order_event  # noqa: E402

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


async def bal_avail(conn, sku):
    return await conn.fetchrow(
        "SELECT b.on_hand, b.reserved, b.on_hand-b.reserved AS available, p.stock "
        "FROM inventory_balances b JOIN products p ON p.id=b.product_id WHERE p.sku=$1", sku)


def env(key, qty, **o):
    payload = dict(customer_name="A", phone="0912345678", address="12 Le Loi", sku="3S-100G",
                   quantity=qty, unit_price_vnd=150000, **o)
    return build_order_create_envelope(raw_payload=payload, actor=Actor("staff", STAFF_ID),
                                       channel="dashboard", idempotency_key=key)


STAFF_ID = "1"


async def main():  # noqa: C901
    dbname = _db().rsplit("/", 1)[-1]
    if "test" not in dbname:
        print(f"ABORT: DATABASE_URL db='{dbname}' khong chua 'test' — tu choi (an toan).")
        return 2

    # ---- matrix guard (pure) ----
    print("[1] matrix guard")
    check(transitions.resolve("new", "confirm").to_status == "confirmed", "new--confirm-->confirmed")
    check(transitions.resolve("ready_for_fulfillment", "fulfill").inventory_effect == transitions.EFFECT_CONSUME,
          "ready--fulfill--> consume")
    for frm, act in [("new", "fulfill"), ("confirmed", "fulfill"), ("cancelled", "confirm"), ("completed", "cancel")]:
        try:
            transitions.resolve(frm, act)
            check(False, f"{frm}--{act} should be illegal")
        except transitions.IllegalTransition:
            check(True, f"{frm}--{act}--> illegal (409)")

    admin = await asyncpg.connect("postgresql://alpha3s:alpha3s@db:5432/postgres")
    await admin.execute(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{dbname}' AND pid<>pg_backend_pid()")
    await admin.execute(f"DROP DATABASE IF EXISTS {dbname}")
    await admin.execute(f"CREATE DATABASE {dbname}")
    await admin.close()

    conn = await asyncpg.connect(_db())
    try:
        await migrate(conn)
        if await conn.fetchval("SELECT count(*) FROM products WHERE sku='3S-100G'") != 1:
            check(False, "seed 3S-100G missing")
            raise SystemExit
        await conn.execute("UPDATE products SET stock=100 WHERE sku='3S-100G'")
        # backfill -> balance cho san pham seed
        plan = await bf.build_plan(conn)
        async with conn.transaction():
            await bf.apply(conn, plan, "00000000-0000-0000-0000-0000000000a4")
        global STAFF_ID
        st = await auth_service.create_staff_user("itest_s4", "pw12345678", "IT", role_key="admin")
        STAFF_ID = str(st["id"])
        settings.m2_inventory_ledger = True

        print("[2] order.create reserve atomic (flag on)")
        r1 = await order_service.execute_order_create(env("S4-CREATE-0001", qty=3))
        oid = r1.resource["id"]
        o = await conn.fetchrow("SELECT status, inventory_status, inventory_location_id FROM orders WHERE id=$1", oid)
        check(o["status"] == "new" and o["inventory_status"] == "reserved" and o["inventory_location_id"],
              f"order new + inventory_status=reserved + location (got {dict(o)})")
        b = await bal_avail(conn, "3S-100G")
        check(b["reserved"] == 3 and b["available"] == 97 and b["stock"] == 97 and b["stock"] == b["available"],
              f"reserved=3 available=97 stock==available (got {dict(b)})")
        resv = await conn.fetchrow("SELECT status, expires_at FROM inventory_reservations WHERE order_id=$1", oid)
        check(resv["status"] == "active" and resv["expires_at"] is not None, "reservation active with TTL")
        nev = await conn.fetchval("SELECT count(*) FROM order_events WHERE order_id=$1 AND event_type='order.created'", oid)
        check(nev == 1, f"order.created event appended (got {nev})")

        print("[3] confirm -> processing -> ready -> fulfill")
        import uuid as _uuid
        corr = _uuid.uuid4()
        async with conn.transaction():
            res = await txn.apply_transition(conn, order_id=oid, action="confirm", actor_type="staff",
                actor_id=STAFF_ID, correlation_id=corr, idem_prefix="cmdC")
        check(res.to_status == "confirmed", "new->confirmed")
        exp = await conn.fetchval("SELECT expires_at FROM inventory_reservations WHERE order_id=$1", oid)
        b = await bal_avail(conn, "3S-100G")
        check(exp is None and b["reserved"] == 3, f"confirm clears expiry, keeps reservation (exp={exp} reserved={b['reserved']})")

        # illegal from confirmed
        try:
            async with conn.transaction():
                await txn.apply_transition(conn, order_id=oid, action="fulfill", actor_type="staff",
                    actor_id=STAFF_ID, correlation_id=corr, idem_prefix="cmdX")
            check(False, "confirmed--fulfill should be illegal")
        except transitions.IllegalTransition:
            check(True, "confirmed--fulfill--> 409 illegal on real order")

        for act in ["start_processing", "ready_for_fulfillment"]:
            async with conn.transaction():
                await txn.apply_transition(conn, order_id=oid, action=act, actor_type="staff",
                    actor_id=STAFF_ID, correlation_id=corr, idem_prefix="cmd_" + act)
        async with conn.transaction():
            resF = await txn.apply_transition(conn, order_id=oid, action="fulfill", actor_type="staff",
                actor_id=STAFF_ID, correlation_id=corr, idem_prefix="cmdF")
        b = await bal_avail(conn, "3S-100G")
        rstat = await conn.fetchval("SELECT status FROM inventory_reservations WHERE order_id=$1", oid)
        check(resF.to_status == "fulfilled" and b["on_hand"] == 97 and b["reserved"] == 0 and rstat == "fulfilled",
              f"fulfill consume on_hand=97 reserved=0 reservation=fulfilled (got on_hand={b['on_hand']} reserved={b['reserved']} rstat={rstat})")
        check(b["stock"] == b["available"], f"compat stock==available after fulfill ({b['stock']}=={b['available']})")

        print("[4] cancel new->cancelled release + restore legacy stock")
        r2 = await order_service.execute_order_create(env("S4-CREATE-0002", qty=5))
        oid2 = r2.resource["id"]
        b_before = await bal_avail(conn, "3S-100G")
        async with conn.transaction():
            resC = await txn.apply_transition(conn, order_id=oid2, action="cancel", actor_type="staff",
                actor_id=STAFF_ID, correlation_id=corr, idem_prefix="cmdCancel")
        b_after = await bal_avail(conn, "3S-100G")
        check(resC.to_status == "cancelled" and resC.inventory_effect == transitions.EFFECT_RELEASE and resC.affected_quantity == 5,
              f"cancel released 5 (got {resC})")
        check(b_after["reserved"] == b_before["reserved"] - 5 and b_after["available"] == b_before["available"] + 5,
              f"release: reserved -5, available +5 (before {dict(b_before)} after {dict(b_after)})")
        check(b_after["stock"] == b_after["available"],
              f"legacy stock RESTORED -> stock==available ({b_after['stock']}=={b_after['available']})")

        print("[5] event append idempotent")
        first = await append_order_event(conn, order_id=oid2, event_type="order.note", to_status="cancelled",
            idempotency_key="dup-key-1", correlation_id=corr, actor_type="staff", actor_id=STAFF_ID)
        second = await append_order_event(conn, order_id=oid2, event_type="order.note", to_status="cancelled",
            idempotency_key="dup-key-1", correlation_id=corr, actor_type="staff", actor_id=STAFF_ID)
        check(first and not second, f"event idempotent (first={first} second={second})")

        print("[6] fail-closed: reserve inconsistency -> rollback whole create")
        # legacy stock du nhung balance short: zero out balance on_hand cho product
        pid = await conn.fetchval("SELECT id FROM products WHERE sku='3S-100G'")
        await conn.execute("UPDATE products SET stock=50 WHERE id=$1", pid)  # legacy says 50 available
        loc = await inv_repo.resolve_default_location(conn)
        # dua available ledger ve 0 (reserved=on_hand) de reserve chac chan insufficient
        await conn.execute("UPDATE inventory_balances SET reserved=on_hand WHERE location_id=$1 AND product_id=$2", loc, pid)
        n_orders = await conn.fetchval("SELECT count(*) FROM orders")
        try:
            await order_service.execute_order_create(env("S4-FAILCLOSED-0003", qty=5))
            check(False, "inconsistent reserve should reject create")
        except errors.CommandError as e:
            check(e.code == errors.INSUFFICIENT_STOCK and e.http_status == 422, f"create rejected 422 ({e.code})")
        n_orders2 = await conn.fetchval("SELECT count(*) FROM orders")
        check(n_orders2 == n_orders, "no order created on fail-closed rollback")
        cmd = await conn.fetchval("SELECT count(*) FROM command_executions WHERE idempotency_key='S4-FAILCLOSED-0003'")
        check(cmd == 0, "command row rolled back (no partial)")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — transition matrix/guard/events + order.create reservation + lifecycle + compat proven")


if __name__ == "__main__":
    asyncio.run(main())
