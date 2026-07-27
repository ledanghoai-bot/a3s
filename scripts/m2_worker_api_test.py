#!/usr/bin/env python3
"""M2 Slice 6 evidence — expiry worker + HTTP API (transitions/inventory/adjustments).

  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2s6_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m2_worker_api_test.py

Part A worker: reservation đến hạn -> sweep -> order cancelled + stock restore; chạy lại -> noop.
Part B API (ASGI in-process): flag gate 409, thiếu Idempotency-Key 400, thiếu quyền 403, confirm 200,
  illegal 409, timeline/balances/reconciliation reads, adjustment request 200 + approve non-unit-head 403.
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
sys.path.insert(0, str(ROOT))

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.api.auth import require_staff_session  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services import auth_service  # noqa: E402
from app.services.command import (  # noqa: E402
    expiry_worker,
    order_service,
)
from app.services.command.envelope import (  # noqa: E402
    Actor,
    build_order_create_envelope,
)

bf_spec = importlib.util.spec_from_file_location("m2_backfill", ROOT / "scripts" / "m2_backfill.py")
bf = importlib.util.module_from_spec(bf_spec)
bf_spec.loader.exec_module(bf)

_fail = []
STAFF = {"id": 0, "rbac_provisioned": True, "permissions": set()}
ALL_PERMS = {
    "order.transition.view", "order.confirm", "order.process", "order.fulfillment.prepare",
    "order.fulfill", "order.cancel", "order.cancel.exception", "inventory.view",
    "inventory.movement.view", "inventory.adjust", "inventory.adjust.approve", "inventory.reconcile",
}


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
    return build_order_create_envelope(raw_payload=payload, actor=Actor("staff", str(STAFF["id"])),
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
            await bf.apply(conn, plan, "00000000-0000-0000-0000-0000000000a6")
        st = await auth_service.create_staff_user("s6_admin", "pw12345678", "IT", role_key="admin")
        STAFF["id"] = st["id"]
        STAFF["permissions"] = set(ALL_PERMS)
        settings.m2_inventory_ledger = True
        pid = await conn.fetchval("SELECT id FROM products WHERE sku='3S-100G'")
        loc = await conn.fetchval("SELECT id FROM inventory_locations WHERE is_default")

        print("[A] expiry worker sweep")
        oid = (await order_service.execute_order_create(cenv("S6-EXP", 2))).resource["id"]
        rid = await conn.fetchval("SELECT id FROM inventory_reservations WHERE order_id=$1", oid)
        await conn.execute("UPDATE inventory_reservations SET expires_at = now() - interval '1 hour' WHERE id=$1", rid)
        stock_pre = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
        stats = await expiry_worker.run_once()
        ostat = await conn.fetchval("SELECT status FROM orders WHERE id=$1", oid)
        rstat = await conn.fetchval("SELECT status FROM inventory_reservations WHERE id=$1", rid)
        stock_post = await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)
        check(stats["expired"] == 1 and ostat == "cancelled" and rstat == "expired" and stock_post == stock_pre + 2,
              f"sweep expired 1, order cancelled, stock+2 (stats={stats} o={ostat} stock {stock_pre}->{stock_post})")
        stats2 = await expiry_worker.run_once()
        check(stats2["claimed"] == 0, f"2nd sweep claims nothing (idempotent) ({stats2})")

        print("[B] HTTP API")
        app.dependency_overrides[require_staff_session] = lambda: STAFF
        o_api = (await order_service.execute_order_create(cenv("S6-API", 3))).resource["id"]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            # flag off -> 409
            settings.m2_order_transitions = False
            r = await c.post(f"/dashboard/orders/{o_api}/transitions", json={"action": "confirm"},
                             headers={"Idempotency-Key": "s6-c1"})
            check(r.status_code == 409, f"flag off -> 409 ({r.status_code})")
            settings.m2_order_transitions = True
            # missing key -> 400
            r = await c.post(f"/dashboard/orders/{o_api}/transitions", json={"action": "confirm"})
            check(r.status_code == 400, f"no Idempotency-Key -> 400 ({r.status_code})")
            # missing perm -> 403
            STAFF["permissions"] = ALL_PERMS - {"order.confirm"}
            r = await c.post(f"/dashboard/orders/{o_api}/transitions", json={"action": "confirm"},
                             headers={"Idempotency-Key": "s6-c2"})
            check(r.status_code == 403, f"missing order.confirm -> 403 ({r.status_code})")
            STAFF["permissions"] = set(ALL_PERMS)
            # valid confirm -> 200
            r = await c.post(f"/dashboard/orders/{o_api}/transitions", json={"action": "confirm"},
                             headers={"Idempotency-Key": "s6-c3"})
            check(r.status_code == 200 and r.json()["outcome"] == "succeeded" and r.json()["result"]["to_status"] == "confirmed",
                  f"confirm 200 succeeded ({r.status_code} {r.text[:120]})")
            # illegal (fulfill from confirmed) -> 409
            r = await c.post(f"/dashboard/orders/{o_api}/transitions", json={"action": "fulfill"},
                             headers={"Idempotency-Key": "s6-c4"})
            check(r.status_code == 409, f"illegal transition -> 409 ({r.status_code})")
            # timeline
            r = await c.get(f"/dashboard/orders/{o_api}/timeline")
            check(r.status_code == 200 and any(e["event_type"] == "order.confirm" for e in r.json()),
                  f"timeline has confirm event ({r.status_code})")
            # balances + reconciliation
            r = await c.get("/dashboard/inventory/balances")
            check(r.status_code == 200 and len(r.json()) >= 1, f"balances 200 ({r.status_code})")
            r = await c.get("/dashboard/inventory/reconciliation")
            check(r.status_code == 200 and r.json()["ok"], f"reconciliation ok ({r.status_code} {r.text[:120]})")
            # adjustment request (small) -> 200 applied
            r = await c.post("/dashboard/inventory/adjustments",
                             json={"location_id": loc, "product_id": pid, "quantity_delta": 3, "reason": "fix"},
                             headers={"Idempotency-Key": "s6-adj1"})
            check(r.status_code == 200 and r.json()["result"]["status"] == "applied",
                  f"small adjustment applied ({r.status_code} {r.text[:140]})")
            # large adjustment -> pending, approve by non-unit-head -> 403
            r = await c.post("/dashboard/inventory/adjustments",
                             json={"location_id": loc, "product_id": pid, "quantity_delta": 40, "reason": "big"},
                             headers={"Idempotency-Key": "s6-adj2"})
            req_id = r.json()["result"]["request_id"]
            r2 = await c.post(f"/dashboard/inventory/adjustments/{req_id}/approve",
                              headers={"Idempotency-Key": "s6-apr2"})
            check(r2.status_code == 403, f"approve by non-unit-head -> 403 ({r2.status_code} {r2.text[:120]})")
            # escalation queue (PO change): endpoint 200 + có key + pending adjustment đếm được
            r = await c.get("/dashboard/inventory/escalations")
            j = r.json()
            check(r.status_code == 200 and "backorders_waiting_topup" in j and j["adjustments_pending_approval"] >= 1,
                  f"escalations queue 200 (pending_adj={j.get('adjustments_pending_approval')})")
        app.dependency_overrides.clear()
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — expiry worker + HTTP API (RBAC/flag/idempotency/domain-reject) proven")


if __name__ == "__main__":
    asyncio.run(main())
