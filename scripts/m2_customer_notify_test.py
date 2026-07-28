#!/usr/bin/env python3
"""M2 CA M2-S1-F06 evidence — customer notification cho transition (AC-M2-15), durable outbox.

  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2cn_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m2_customer_notify_test.py

Chung minh (flags m2_inventory_ledger + m2_order_transitions ON):
  - Don kenh 'messenger' -> confirm/fulfill phat customer outbox event dung kenh, text DETERMINISTIC
    (khong LLM), dedupe theo (order,to_status), co max_attempts (retry/dead-letter M1).
  - Idempotent: chay lai confirm command (duplicate) -> KHONG nhan doi outbox event.
  - Don cancel -> cancelled notification.
  - Don kenh 'dashboard' (staff) -> KHONG phat customer notification.
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
from app.services.command import lifecycle, order_service, registry  # noqa: E402
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


def msgr_env(key, qty, psid):
    payload = dict(customer_name="Khach A", phone="0912345678", address="12 Le Loi", sku="3S-100G",
                   quantity=qty, psid=psid)
    return build_order_create_envelope(raw_payload=payload, actor=Actor("customer", psid),
                                       channel="messenger", idempotency_key=key)


def dash_env(key, qty):
    payload = dict(customer_name="A", phone="0912345678", address="12 Le Loi", sku="3S-100G",
                   quantity=qty, unit_price_vnd=150000)
    return build_order_create_envelope(raw_payload=payload, actor=Actor("staff", STAFF_ID),
                                       channel="dashboard", idempotency_key=key)


def tenv(ct, key, oid):
    return lifecycle.build_lifecycle_envelope(command_type=ct, payload={"order_id": oid},
        actor=Actor("staff", STAFF_ID), channel="dashboard", idempotency_key=key)


async def outbox_count(conn, dedupe):
    return await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key=$1", dedupe)


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
            await bf.apply(conn, plan, "00000000-0000-0000-0000-0000000000f6")
        st = await auth_service.create_staff_user("cn_admin", "pw12345678", "IT", role_key="admin")
        global STAFF_ID
        STAFF_ID = str(st["id"])
        settings.m2_inventory_ledger = True
        settings.m2_order_transitions = True

        print("[1] messenger order -> confirm notification")
        o1 = (await order_service.execute_order_create(msgr_env("CN-O1", 2, "psid-cn-1"))).resource["id"]
        ch = await conn.fetchval("SELECT origin_channel FROM orders WHERE id=$1", o1)
        check(ch == "messenger", f"origin_channel luu = messenger ({ch})")
        await lifecycle.execute_lifecycle(tenv(registry.ORDER_CONFIRM, "CN-CONF", o1))
        row = await conn.fetchrow("SELECT destination, payload FROM outbox_events WHERE dedupe_key=$1",
                                  f"order_status:{o1}:confirmed")
        import json
        pl = json.loads(row["payload"]) if row and isinstance(row["payload"], str) else (row["payload"] if row else None)
        check(row is not None and row["destination"] == "messenger", "confirm -> outbox messenger")
        check(pl and pl.get("text") == f"Đơn #{o1} của bạn đã được xác nhận." and pl.get("customer_ref") == "psid-cn-1",
              f"text deterministic + customer_ref ({pl.get('text') if pl else None})")
        ma = await conn.fetchval("SELECT max_attempts FROM outbox_events WHERE dedupe_key=$1", f"order_status:{o1}:confirmed")
        check(ma and ma > 1, f"co max_attempts (retry/dead-letter) = {ma}")

        print("[2] idempotent: confirm command chay lai -> khong nhan doi")
        await lifecycle.execute_lifecycle(tenv(registry.ORDER_CONFIRM, "CN-CONF", o1))  # duplicate key
        n = await outbox_count(conn, f"order_status:{o1}:confirmed")
        check(n == 1, f"confirm notification van 1 sau retry ({n})")

        print("[3] fulfill notification")
        await lifecycle.execute_lifecycle(tenv(registry.ORDER_START_PROCESSING, "CN-PROC", o1))
        await lifecycle.execute_lifecycle(tenv(registry.ORDER_READY, "CN-READY", o1))
        await lifecycle.execute_lifecycle(tenv(registry.ORDER_FULFILL, "CN-FUL", o1))
        n = await outbox_count(conn, f"order_status:{o1}:fulfilled")
        check(n == 1, f"fulfill -> customer notification ({n})")

        print("[4] cancel notification (đơn messenger khác)")
        o2 = (await order_service.execute_order_create(msgr_env("CN-O2", 1, "psid-cn-2"))).resource["id"]
        await lifecycle.execute_lifecycle(tenv(registry.ORDER_CANCEL, "CN-CAN", o2))
        n = await outbox_count(conn, f"order_status:{o2}:cancelled")
        check(n == 1, f"cancel -> customer notification ({n})")

        print("[5] dashboard order -> KHONG customer notification")
        o3 = (await order_service.execute_order_create(dash_env("CN-O3", 1))).resource["id"]
        await lifecycle.execute_lifecycle(tenv(registry.ORDER_CONFIRM, "CN-CONF3", o3))
        n = await outbox_count(conn, f"order_status:{o3}:confirmed")
        check(n == 0, f"dashboard order khong phat customer notification ({n})")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — customer transition notification deterministic + durable + dedupe + kenh-aware")


if __name__ == "__main__":
    asyncio.run(main())
