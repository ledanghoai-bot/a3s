#!/usr/bin/env python3
"""M2 CA M2-S1-F03 evidence — negative RBAC: read-only KHONG mutate duoc.

  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2rbac_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m2_rbac_test.py

Chung minh (ASGI in-process, flag M2_ORDER_TRANSITIONS on):
  - Tai khoan mang DUNG bo quyen role 'viewer' (read-only) -> MOI mutation lifecycle + adjustment -> 403.
    Bao gom complete/mark_delivery_failed/request_return (truoc day map nham order.transition.view).
  - Tai khoan admin (du quyen) -> mutation hop le KHONG bi 403 (positive control).
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
from app.services.command import lifecycle, order_service, registry  # noqa: E402
from app.services.command.envelope import (  # noqa: E402
    Actor,
    build_order_create_envelope,
)

bf_spec = importlib.util.spec_from_file_location("m2_backfill", ROOT / "scripts" / "m2_backfill.py")
bf = importlib.util.module_from_spec(bf_spec)
bf_spec.loader.exec_module(bf)

_fail = []
STAFF = {"id": 0, "rbac_provisioned": True, "permissions": set()}

# Mọi mutation lifecycle (action -> quyền write bắt buộc). viewer KHÔNG có quyền nào trong số này.
MUTATIONS = ["confirm", "start_processing", "ready_for_fulfillment", "fulfill", "cancel",
             "complete", "mark_delivery_failed", "request_return"]


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
            await bf.apply(conn, plan, "00000000-0000-0000-0000-0000000000c7")
        st = await auth_service.create_staff_user("rbac_s", "pw12345678", "IT", role_key="admin")
        STAFF["id"] = st["id"]
        settings.m2_inventory_ledger = True
        settings.m2_order_transitions = True

        # tạo 1 đơn (admin) để target
        STAFF["permissions"] = {r["permission_key"] for r in await conn.fetch(
            "SELECT permission_key FROM role_permissions WHERE role_key='admin'")}
        oid = (await order_service.execute_order_create(build_order_create_envelope(
            raw_payload=dict(customer_name="A", phone="0912345678", address="12 Le Loi", sku="3S-100G",
                             quantity=2, unit_price_vnd=150000),
            actor=Actor("staff", str(STAFF["id"])), channel="dashboard", idempotency_key="RBAC-O1"))).resource["id"]

        # bộ quyền THỰC của role 'viewer' (read-only)
        viewer_perms = {r["permission_key"] for r in await conn.fetch(
            "SELECT permission_key FROM role_permissions WHERE role_key='viewer'")}
        print(f"[viewer perms] {sorted(viewer_perms)}")

        app.dependency_overrides[require_staff_session] = lambda: STAFF
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            print("[1] viewer -> MỌI mutation 403")
            STAFF["permissions"] = set(viewer_perms)
            for i, act in enumerate(MUTATIONS):
                r = await c.post(f"/dashboard/orders/{oid}/transitions", json={"action": act},
                                 headers={"Idempotency-Key": f"rbac-neg-{i}"})
                check(r.status_code == 403, f"viewer '{act}' -> 403 (got {r.status_code})")
            # adjustment request + approve
            r = await c.post("/dashboard/inventory/adjustments",
                             json={"location_id": 1, "product_id": 1, "quantity_delta": 3, "reason": "x"},
                             headers={"Idempotency-Key": "rbac-adj"})
            check(r.status_code == 403, f"viewer adjustment.request -> 403 (got {r.status_code})")
            r = await c.post("/dashboard/inventory/adjustments/00000000-0000-0000-0000-000000000000/approve",
                             headers={"Idempotency-Key": "rbac-apr"})
            check(r.status_code == 403, f"viewer adjustment.approve -> 403 (got {r.status_code})")

            print("[2] admin -> mutation hợp lệ KHÔNG bị 403 (positive control)")
            STAFF["permissions"] = {r["permission_key"] for r in await conn.fetch(
                "SELECT permission_key FROM role_permissions WHERE role_key='admin'")}
            r = await c.post(f"/dashboard/orders/{oid}/transitions", json={"action": "confirm"},
                             headers={"Idempotency-Key": "rbac-pos-confirm"})
            check(r.status_code != 403 and r.status_code == 200, f"admin confirm -> 200 ({r.status_code})")
            # complete từ new là illegal (409) NHƯNG không được là 403 -> chứng minh perm pass, chỉ state chặn
            r = await c.post(f"/dashboard/orders/{oid}/transitions", json={"action": "complete"},
                             headers={"Idempotency-Key": "rbac-pos-complete"})
            check(r.status_code != 403, f"admin complete -> not 403 (perm ok, state 409) (got {r.status_code})")
        app.dependency_overrides.clear()

        print("[3] DIRECT command-boundary (F02): viewer gọi execute_lifecycle trực tiếp -> forbidden, no mutation")
        # order MỚI để transition hợp lệ (chỉ quyền chặn, không phải state)
        od = (await order_service.execute_order_create(build_order_create_envelope(
            raw_payload=dict(customer_name="A", phone="0912345678", address="12 Le Loi", sku="3S-100G",
                             quantity=1, unit_price_vnd=150000),
            actor=Actor("staff", str(STAFF["id"])), channel="dashboard", idempotency_key="RBAC-OD"))).resource["id"]
        viewer = await auth_service.create_staff_user("rbac_viewer", "pw12345678", "IT", role_key="viewer")
        # viewer gọi thẳng command service (bypass HTTP) -> _enforce chặn fail-closed
        for ct, key in [(registry.ORDER_CONFIRM, "DIRECT-CONF"), (registry.ADJUST_REQUEST, "DIRECT-ADJ")]:
            pl = {"order_id": od} if ct == registry.ORDER_CONFIRM else \
                 {"location_id": 1, "product_id": 1, "quantity_delta": 3, "reason": "x"}
            env = lifecycle.build_lifecycle_envelope(command_type=ct, payload=pl,
                actor=Actor("staff", str(viewer["id"])), channel="dashboard", idempotency_key=key)
            r = await lifecycle.execute_lifecycle(env)
            check(r.outcome == "rejected" and r.error_code == "forbidden",
                  f"viewer direct {ct} -> forbidden ({r.outcome}/{r.error_code})")
        # KHÔNG mutation: order od chưa confirmed, không order_event confirm, không adjustment row
        ost = await conn.fetchval("SELECT status FROM orders WHERE id=$1", od)
        nev = await conn.fetchval("SELECT count(*) FROM order_events WHERE order_id=$1 AND event_type='order.confirm'", od)
        nadj = await conn.fetchval("SELECT count(*) FROM inventory_adjustment_requests")
        check(ost == "new" and nev == 0 and nadj == 0,
              f"no mutation sau direct-call forbidden (status={ost} confirm_events={nev} adj={nadj})")
        # positive: admin gọi trực tiếp -> KHÔNG forbidden
        adm = await auth_service.create_staff_user("rbac_adm2", "pw12345678", "IT", role_key="admin")
        env = lifecycle.build_lifecycle_envelope(command_type=registry.ORDER_CONFIRM, payload={"order_id": od},
            actor=Actor("staff", str(adm["id"])), channel="dashboard", idempotency_key="DIRECT-CONF-OK")
        r = await lifecycle.execute_lifecycle(env)
        check(r.outcome == "succeeded", f"admin direct confirm -> succeeded ({r.outcome}/{r.error_code})")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — read-only KHONG mutate duoc (F03); mutation perms tach khoi .view")


if __name__ == "__main__":
    asyncio.run(main())
