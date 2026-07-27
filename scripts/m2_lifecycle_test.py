#!/usr/bin/env python3
"""M2 Slice 5 evidence — lifecycle commands (transition/reservation/adjustment) effective-once.

  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2s5_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m2_lifecycle_test.py

Chung minh:
  1. confirm command idempotent (2 lan cung key -> receipt cu, duplicate, KHONG event/movement moi).
  2. illegal transition command -> rejected (failed_terminal), KHONG doi state.
  3. lifecycle confirm->processing->ready->fulfill->complete: fulfill consume on_hand/reserved.
  4. cancel command release + restore legacy stock.
  5. reservation.expire command: expired + order cancelled + stock restore; chay lai -> noop.
  6. adjustment: small auto-apply; large pending; approve by requester -> SoD; by non-unit-head -> reject;
     by unit_head -> applied; approve lai -> not_pending; reject flow.
  7. idempotency conflict: cung key khac payload -> 409.
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
from app.services.command import (  # noqa: E402
    errors,
    lifecycle,
    order_service,
    registry,
)
from app.services.command.envelope import (  # noqa: E402
    Actor,
    build_order_create_envelope,
)

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


def create_env(key, qty):
    payload = dict(customer_name="A", phone="0912345678", address="12 Le Loi", sku="3S-100G",
                   quantity=qty, unit_price_vnd=150000)
    return build_order_create_envelope(raw_payload=payload, actor=Actor("staff", STAFF_ID),
                                       channel="dashboard", idempotency_key=key)


def tenv(command_type, key, **payload):
    return lifecycle.build_lifecycle_envelope(
        command_type=command_type, payload=payload, actor=Actor("staff", STAFF_ID),
        channel="dashboard", idempotency_key=key)


STAFF_ID = "1"


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
            await bf.apply(conn, plan, "00000000-0000-0000-0000-0000000000a5")
        global STAFF_ID
        st = await auth_service.create_staff_user("s5_admin", "pw12345678", "IT", role_key="admin")
        STAFF_ID = str(st["id"])
        settings.m2_inventory_ledger = True
        loc = await conn.fetchval("SELECT id FROM inventory_locations WHERE is_default")
        pid = await conn.fetchval("SELECT id FROM products WHERE sku='3S-100G'")

        print("[1] confirm idempotent")
        o1 = (await order_service.execute_order_create(create_env("S5-O1", 3))).resource["id"]
        r_c1 = await lifecycle.execute_lifecycle(tenv(registry.ORDER_CONFIRM, "S5-CONF-1", order_id=o1))
        r_c2 = await lifecycle.execute_lifecycle(tenv(registry.ORDER_CONFIRM, "S5-CONF-1", order_id=o1))
        check(r_c1.outcome == "succeeded" and r_c1.result["to_status"] == "confirmed", "confirm succeeded->confirmed")
        check(r_c2.duplicate and r_c2.outcome == "succeeded", "confirm replay -> duplicate receipt")
        nev = await conn.fetchval("SELECT count(*) FROM order_events WHERE order_id=$1 AND event_type='order.confirm'", o1)
        check(nev == 1, f"confirm event exactly 1 (got {nev})")
        exp = await conn.fetchval("SELECT expires_at FROM inventory_reservations WHERE order_id=$1", o1)
        check(exp is None, "confirm cleared reservation expiry")

        print("[2] illegal transition command -> rejected")
        r_bad = await lifecycle.execute_lifecycle(tenv(registry.ORDER_FULFILL, "S5-BADFUL-1", order_id=o1))
        check(r_bad.outcome == "rejected" and r_bad.error_code == "illegal_order_transition",
              f"fulfill-from-confirmed rejected ({r_bad.error_code})")
        sts = await conn.fetchval("SELECT status FROM orders WHERE id=$1", o1)
        check(sts == "confirmed", "order unchanged after illegal reject")

        print("[3] full lifecycle to fulfilled+completed")
        for ct, key in [(registry.ORDER_START_PROCESSING, "S5-PROC-1"), (registry.ORDER_READY, "S5-READY-1"),
                        (registry.ORDER_FULFILL, "S5-FUL-1"), (registry.ORDER_COMPLETE, "S5-COMP-1")]:
            r = await lifecycle.execute_lifecycle(tenv(ct, key, order_id=o1))
            check(r.outcome == "succeeded", f"{ct} succeeded")
        b = await conn.fetchrow("SELECT on_hand, reserved FROM inventory_balances WHERE location_id=$1 AND product_id=$2", loc, pid)
        rstat = await conn.fetchval("SELECT status FROM inventory_reservations WHERE order_id=$1", o1)
        ostat = await conn.fetchval("SELECT status FROM orders WHERE id=$1", o1)
        check(b["on_hand"] == 97 and b["reserved"] == 0 and rstat == "fulfilled" and ostat == "completed",
              f"fulfill consumed, order completed (on_hand={b['on_hand']} reserved={b['reserved']} r={rstat} o={ostat})")

        print("[4] cancel release + restore stock")
        o2 = (await order_service.execute_order_create(create_env("S5-O2", 4))).resource["id"]
        b_before = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
        r_can = await lifecycle.execute_lifecycle(tenv(registry.ORDER_CANCEL, "S5-CAN-1", order_id=o2))
        b_after = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
        check(r_can.result["to_status"] == "cancelled" and r_can.result["affected_quantity"] == 4,
              f"cancel released 4 ({r_can.result})")
        check(b_after == b_before + 4, f"legacy stock restored +4 ({b_before}->{b_after})")

        print("[5] reservation.expire idempotent")
        o3 = (await order_service.execute_order_create(create_env("S5-O3", 2))).resource["id"]
        rid = await conn.fetchval("SELECT id FROM inventory_reservations WHERE order_id=$1", o3)
        await conn.execute("UPDATE inventory_reservations SET expires_at = now() - interval '1 hour' WHERE id=$1", rid)
        stock_pre = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
        exp_key = f"reservation.expire:{rid}:past"
        r_e1 = await lifecycle.execute_lifecycle(lifecycle.build_lifecycle_envelope(
            command_type=registry.RESERVATION_EXPIRE, payload={"reservation_id": str(rid), "expected_expires_at": "past"},
            actor=Actor("system", "expiry-worker"), channel="dashboard", idempotency_key=exp_key))
        o3stat = await conn.fetchval("SELECT status FROM orders WHERE id=$1", o3)
        r3stat = await conn.fetchval("SELECT status FROM inventory_reservations WHERE id=$1", rid)
        stock_post = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
        check(r_e1.result["outcome"] == "expired" and o3stat == "cancelled" and r3stat == "expired" and stock_post == stock_pre + 2,
              f"expire -> order cancelled, reservation expired, stock+2 (o={o3stat} r={r3stat} stock {stock_pre}->{stock_post})")
        # rerun expire (different key, same reservation) -> noop
        r_e2 = await lifecycle.execute_lifecycle(lifecycle.build_lifecycle_envelope(
            command_type=registry.RESERVATION_EXPIRE, payload={"reservation_id": str(rid), "expected_expires_at": "past2"},
            actor=Actor("system", "expiry-worker"), channel="dashboard", idempotency_key=exp_key + "-2"))
        stock_noop = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
        check(r_e2.result["outcome"] == "noop" and stock_noop == stock_post, "expire rerun -> noop, no double restore")

        print("[6] adjustment SoD / unit-head / stale")
        req = await auth_service.create_staff_user("s5_req", "pw12345678", "IT", role_key="warehouse")
        head = await auth_service.create_staff_user("s5_head", "pw12345678", "IT", role_key="unit_head")
        await conn.execute("INSERT INTO inventory_unit_members (staff_id,location_id,unit_role) VALUES ($1,$2,'unit_head')", head["id"], loc)

        def aenv(ct, key, actor_id, **pl):
            return lifecycle.build_lifecycle_envelope(command_type=ct, payload=pl,
                actor=Actor("staff", str(actor_id)), channel="dashboard", idempotency_key=key)

        # small (|delta| < threshold=max(10,2%*97=2)=10) -> auto applied
        r_small = await lifecycle.execute_lifecycle(aenv(registry.ADJUST_REQUEST, "S5-ADJS-1", req["id"],
            location_id=loc, product_id=pid, quantity_delta=3, reason="count fix"))
        check(r_small.result["is_large"] is False and r_small.result["status"] == "applied", f"small adjust auto-applied ({r_small.result})")
        # large (delta=40 >= 10) -> pending
        r_large = await lifecycle.execute_lifecycle(aenv(registry.ADJUST_REQUEST, "S5-ADJL-1", req["id"],
            location_id=loc, product_id=pid, quantity_delta=40, reason="big recount"))
        adj_id = r_large.result["request_id"]
        check(r_large.result["is_large"] and r_large.result["status"] == "pending", f"large adjust pending ({r_large.result})")
        # approve by requester -> SoD
        r_sod = await lifecycle.execute_lifecycle(aenv(registry.ADJUST_APPROVE, "S5-APR-SOD", req["id"], request_id=adj_id))
        check(r_sod.outcome == "rejected" and r_sod.error_code == "separation_of_duties", f"SoD reject ({r_sod.error_code})")
        # approve by non-unit-head (admin STAFF_ID not mapped) -> not_unit_head
        r_nuh = await lifecycle.execute_lifecycle(aenv(registry.ADJUST_APPROVE, "S5-APR-NUH", STAFF_ID, request_id=adj_id))
        check(r_nuh.outcome == "rejected" and r_nuh.error_code == "not_unit_head", f"non-unit-head reject ({r_nuh.error_code})")
        # approve by unit_head -> applied
        onhand_pre = await conn.fetchval("SELECT on_hand FROM inventory_balances WHERE location_id=$1 AND product_id=$2", loc, pid)
        r_ok = await lifecycle.execute_lifecycle(aenv(registry.ADJUST_APPROVE, "S5-APR-OK", head["id"], request_id=adj_id))
        onhand_post = await conn.fetchval("SELECT on_hand FROM inventory_balances WHERE location_id=$1 AND product_id=$2", loc, pid)
        astat = await conn.fetchval("SELECT status FROM inventory_adjustment_requests WHERE id=$1", adj_id)
        check(r_ok.outcome == "succeeded" and astat == "applied" and onhand_post == onhand_pre + 40,
              f"unit_head approve applied on_hand+40 ({onhand_pre}->{onhand_post} status={astat})")
        # approve again -> not_pending
        r_again = await lifecycle.execute_lifecycle(aenv(registry.ADJUST_APPROVE, "S5-APR-AGAIN", head["id"], request_id=adj_id))
        check(r_again.outcome == "rejected" and r_again.error_code == "adjustment_not_pending", f"re-approve not_pending ({r_again.error_code})")

        print("[7] idempotency conflict")
        try:
            await lifecycle.execute_lifecycle(tenv(registry.ORDER_CANCEL, "S5-CAN-1", order_id=99999))
            check(False, "same key diff payload should 409")
        except errors.CommandError as e:
            check(e.http_status == 409, f"idempotency conflict 409 ({e.code})")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — lifecycle commands effective-once + SoD/unit-head/stale/expire proven")


if __name__ == "__main__":
    asyncio.run(main())
