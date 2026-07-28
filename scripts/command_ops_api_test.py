#!/usr/bin/env python3
"""Ops API e2e (I-B M1 Slice 8/9 hardening). Spec §10.3, §11.

In-process ASGI (real routing + require_permission), override require_staff_session = staff có đủ
quyền. Bao phủ: GET /dashboard/commands, /outbox, /outbox/{id} (detail+attempts), /ops/metrics
(+alert dead_letter), POST /outbox/{id}/retry (200 + reason required 422). Đây là e2e cho trang /ops.

  docker exec -e DATABASE_URL=...m1_itest -e PYTHONPATH=/srv -w /srv api python scripts/command_ops_api_test.py
"""
import asyncio
import json
import sys

import asyncpg

from app.config import settings

settings.m1_reliable_order_command = True

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.api.auth import require_staff_session  # noqa: E402
from app.main import app  # noqa: E402
from app.services import auth_service  # noqa: E402
from app.services.command import order_service  # noqa: E402
from app.services.command.envelope import (  # noqa: E402
    Actor,
    build_order_create_envelope,
)

PERMS = {"commands.view", "outbox.view", "outbox.retry", "outbox.replay", "outbox.cancel"}
STAFF = {"id": None, "username": "ops_staff", "name": "OPS", "rbac_provisioned": True,
         "permissions": PERMS, "must_change_password": False}
C = {"customer_name": "Ops", "phone": "0900333555", "address": "8 Ops", "sku": "3S-100G"}


def _db():
    return settings.database_url.replace("+asyncpg", "")


async def main() -> int:  # noqa: C901
    conn = await asyncpg.connect(_db())
    fails: list[str] = []
    try:
        await conn.execute("TRUNCATE order_items, orders, command_executions, outbox_events, "
                           "delivery_attempts, price_overrides RESTART IDENTITY CASCADE")
        await conn.execute("UPDATE products SET stock=1000 WHERE sku='3S-100G'")
        st = await auth_service.create_staff_user("ops_staff", "pw12345678", "OPS", role_key="admin")
        STAFF["id"] = st["id"]
        # 1 command succeeded + 1 outbox pending
        env = build_order_create_envelope(raw_payload=dict(C, quantity=1, unit_price_vnd=150000),
                                          actor=Actor("staff", str(st["id"])), channel="dashboard",
                                          idempotency_key="ops-seed-key-000001")
        await order_service.execute_order_create(env)
        cid = await conn.fetchval("SELECT id FROM command_executions LIMIT 1")
        # dead-letter event + 1 attempt (cho detail + retry)
        dl = await conn.fetchval(
            "INSERT INTO outbox_events (id, command_id, event_type, event_version, destination, "
            "dedupe_key, payload, status, available_at, max_attempts, dead_lettered_at, last_error_code) "
            "VALUES (gen_random_uuid(),$1,'order.created.notify',1,'telegram_admin','dl-ops',"
            "$2::jsonb,'dead_lettered',now(),8,now(),'http_500') RETURNING id",
            cid, json.dumps({"order_id": 1, "phone_masked": "***555"}))
        await conn.execute(
            "INSERT INTO delivery_attempts (outbox_event_id, attempt_no, worker_id, started_at, "
            "finished_at, outcome, http_status, error_class, correlation_id) VALUES "
            "($1,1,'w',now(),now(),'retryable_error',500,'http_500',gen_random_uuid())", dl)

        app.dependency_overrides[require_staff_session] = lambda: STAFF
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/dashboard/commands")
            if r.status_code != 200 or len(r.json()) < 1:
                fails.append(f"commands list: {r.status_code} n={len(r.json()) if r.status_code==200 else '?'}")

            r = await c.get("/dashboard/outbox")
            if r.status_code != 200 or not any(e["dedupe_key"] == "dl-ops" for e in r.json()):
                fails.append(f"outbox list: {r.status_code}")

            r = await c.get(f"/dashboard/outbox/{dl}")
            if r.status_code != 200 or len(r.json().get("attempts", [])) != 1:
                fails.append(f"outbox detail: {r.status_code} {r.text[:120]}")

            r = await c.get("/dashboard/ops/metrics")
            body = r.json() if r.status_code == 200 else {}
            if r.status_code != 200 or body.get("metrics", {}).get("outbox_dead_letter_total", 0) < 1:
                fails.append(f"metrics: {r.status_code} {r.text[:120]}")
            if not any(a["name"] == "dead_letter_present" for a in body.get("alerts", [])):
                fails.append("metrics: thiếu alert dead_letter_present")

            r = await c.post(f"/dashboard/outbox/{dl}/retry", json={})  # reason required
            if r.status_code != 422:
                fails.append(f"retry no-reason: {r.status_code} (mong 422)")

            r = await c.post(f"/dashboard/outbox/{dl}/retry", json={"reason": "ops e2e retry"})
            if r.status_code != 200 or r.json().get("status") != "retry_scheduled":
                fails.append(f"retry: {r.status_code} {r.text[:120]}")
        # audit ghi cho retry
        if await conn.fetchval("SELECT count(*) FROM audit_log WHERE action='outbox.retry'") != 1:
            fails.append("retry không audit")

    finally:
        await conn.close()

    if fails:
        print("OPS-API FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("OPS-API PASS: GET commands/outbox/detail+attempts/metrics(+alert dead_letter) / "
          "POST retry 200+audit + reason-required 422 — e2e trang /ops qua RBAC thật.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
