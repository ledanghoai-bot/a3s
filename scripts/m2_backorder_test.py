#!/usr/bin/env python3
"""M2 PO-change evidence — backorder (never-drop-order) + auto-reserve FIFO on topup.

  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2bo_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m2_backorder_test.py

Chung minh (flag m2_inventory_ledger + m2_backorder_escalation BAT):
  E1 capture: thieu hang -> KHONG reject; don giu (unreserved) + backorder row active + order.backordered
     event + escalation outbox (telegram_admin admin_text) + stock KHONG bi tru; receipt backordered=true.
  E1b flag off -> giu hanh vi CA spec (reject insufficient_stock).
  E2 topup: adjustment_increase -> auto-reserve backorder FIFO -> reservation + order reserved +
     backorder status=reserved + notify outbox; retry idempotent (khong reserve 2 lan).
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


def aenv(ct, key, actor_id, **pl):
    return lifecycle.build_lifecycle_envelope(command_type=ct, payload=pl,
        actor=Actor("staff", str(actor_id)), channel="dashboard", idempotency_key=key)


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
        await conn.execute("UPDATE products SET stock=2 WHERE sku='3S-100G'")  # thiếu cho đơn qty 5
        plan = await bf.build_plan(conn)
        async with conn.transaction():
            await bf.apply(conn, plan, "00000000-0000-0000-0000-0000000000b0")
        global STAFF_ID
        st = await auth_service.create_staff_user("bo_admin", "pw12345678", "IT", role_key="admin")
        STAFF_ID = str(st["id"])
        pid = await conn.fetchval("SELECT id FROM products WHERE sku='3S-100G'")
        loc = await conn.fetchval("SELECT id FROM inventory_locations WHERE is_default")

        print("[E1b] flag backorder OFF -> reject insufficient (CA spec giữ nguyên)")
        settings.m2_inventory_ledger = True
        settings.m2_backorder_escalation = False
        r_rej = await order_service.execute_order_create(cenv("BO-OFF", 5))
        check(r_rej.outcome == "rejected" and r_rej.error_code == errors.INSUFFICIENT_STOCK,
              f"flag off -> reject ({r_rej.outcome}/{r_rej.error_code})")

        print("[E1] flag backorder ON -> giữ đơn (backorder)")
        settings.m2_backorder_escalation = True
        stock_pre = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
        r = await order_service.execute_order_create(cenv("BO-ON", 5))
        oid = r.resource["id"]
        check(r.outcome == "succeeded" and r.result.get("backordered") is True,
              f"insufficient -> đơn GIỮ, backordered=true ({r.outcome} {r.result})")
        o = await conn.fetchrow("SELECT status, inventory_status FROM orders WHERE id=$1", oid)
        check(o["status"] == "new" and o["inventory_status"] == "unreserved",
              f"order new/unreserved ({dict(o)})")
        bo = await conn.fetchrow("SELECT status, quantity FROM inventory_backorders WHERE order_id=$1", oid)
        check(bo and bo["status"] == "active" and bo["quantity"] == 5, f"backorder active qty5 ({dict(bo) if bo else None})")
        stock_post = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
        check(stock_post == stock_pre, f"stock KHÔNG bị trừ ({stock_pre}->{stock_post})")
        nev = await conn.fetchval("SELECT count(*) FROM order_events WHERE order_id=$1 AND event_type='order.backordered'", oid)
        check(nev == 1, f"order.backordered event ({nev})")
        esc = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE destination='telegram_admin' AND dedupe_key=$1",
                                  f"backorder_escalation:{await conn.fetchval('SELECT id FROM order_items WHERE order_id=$1', oid)}")
        check(esc == 1, f"escalation outbox to inventory ({esc})")

        print("[E2] topup -> auto-reserve FIFO")
        # add a 2nd backorder (FIFO order) qty 3
        r2 = await order_service.execute_order_create(cenv("BO-ON-2", 3))
        oid2 = r2.resource["id"]
        # unit_head để duyệt topup lớn
        head = await auth_service.create_staff_user("bo_head", "pw12345678", "IT", role_key="unit_head")
        await conn.execute("INSERT INTO inventory_unit_members (staff_id,location_id,unit_role) VALUES ($1,$2,'unit_head')", head["id"], loc)
        # topup +20 (large @on_hand=2 threshold=10) -> request + approve -> drain
        rq = await lifecycle.execute_lifecycle(aenv(registry.ADJUST_REQUEST, "BO-ADJ", STAFF_ID,
            location_id=loc, product_id=pid, quantity_delta=20, reason="topup"))
        adj_id = rq.result["request_id"]
        ap = await lifecycle.execute_lifecycle(aenv(registry.ADJUST_APPROVE, "BO-APR", head["id"], request_id=adj_id))
        check(ap.outcome == "succeeded", f"topup approve applied ({ap.outcome})")
        b1 = await conn.fetchval("SELECT status FROM inventory_backorders WHERE order_id=$1", oid)
        b2 = await conn.fetchval("SELECT status FROM inventory_backorders WHERE order_id=$1", oid2)
        io1 = await conn.fetchval("SELECT inventory_status FROM orders WHERE id=$1", oid)
        io2 = await conn.fetchval("SELECT inventory_status FROM orders WHERE id=$1", oid2)
        bal = await conn.fetchrow("SELECT on_hand, reserved FROM inventory_balances WHERE location_id=$1 AND product_id=$2", loc, pid)
        # on_hand: opening 2 + 20 = 22; reserved: 5+3=8; available 14
        check(b1 == "reserved" and b2 == "reserved" and io1 == "reserved" and io2 == "reserved",
              f"cả 2 backorder auto-reserved sau topup (b1={b1} b2={b2} io1={io1} io2={io2})")
        check(bal["on_hand"] == 22 and bal["reserved"] == 8,
              f"balance on_hand=22 reserved=8 sau topup+drain ({dict(bal)})")
        nres = await conn.fetchval("SELECT count(*) FROM inventory_reservations WHERE status='active'")
        check(nres == 2, f"2 reservation active ({nres})")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — backorder never-drop-order + escalation + auto-reserve FIFO on topup proven")


if __name__ == "__main__":
    asyncio.run(main())
