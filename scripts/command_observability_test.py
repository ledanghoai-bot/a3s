#!/usr/bin/env python3
"""Observability evidence (I-B M1 Slice 10). Spec §12.

Seed dieu kien -> command_bus_metrics() dung + evaluate_alerts() fire dung P1/P2. log_event() smoke.

  docker exec -e DATABASE_URL=...m1_itest -e PYTHONPATH=/srv -w /srv api python scripts/command_observability_test.py
"""
import asyncio
import json
import sys

import asyncpg

from app.config import settings
from app.services import auth_service
from app.services.command import observability, order_service
from app.services.command import repository as repo
from app.services.command.envelope import Actor, build_order_create_envelope

C = {"customer_name": "Obs", "phone": "0900000111", "address": "1 Obs", "sku": "3S-100G"}


def _db():
    return settings.database_url.replace("+asyncpg", "")


async def ins_outbox(conn, cid, dedupe, status, available_offset_min=0):
    payload = json.dumps({"order_id": 1, "correlation_id": "c"})
    eid = await conn.fetchval(
        "INSERT INTO outbox_events (id, command_id, event_type, event_version, destination, dedupe_key, "
        "payload, status, available_at, max_attempts) VALUES (gen_random_uuid(),$1,'x',1,'telegram_admin',"
        "$2,$3::jsonb,$4, now() - ($5 * interval '1 minute'), 8) RETURNING id",
        cid, dedupe, payload, status, available_offset_min)
    if status == "dead_lettered":
        await conn.execute("UPDATE outbox_events SET dead_lettered_at=now() WHERE id=$1", eid)
    return eid


async def main() -> int:  # noqa: C901
    conn = await asyncpg.connect(_db())
    fails: list[str] = []
    try:
        await conn.execute("TRUNCATE order_items, orders, command_executions, outbox_events, "
                           "delivery_attempts, price_overrides RESTART IDENTITY CASCADE")
        await conn.execute("UPDATE products SET stock=1000 WHERE sku='3S-100G'")
        st = await auth_service.create_staff_user("obs_staff", "pw12345678", "OB", role_key="admin")

        # 1 order succeeded (command succeeded + outbox pending recent)
        env = build_order_create_envelope(raw_payload=dict(C, quantity=1, unit_price_vnd=150000),
                                          actor=Actor("staff", str(st["id"])), channel="dashboard",
                                          idempotency_key="obs-seed-key-000001")
        await order_service.execute_order_create(env)
        cid = await conn.fetchval("SELECT id FROM command_executions LIMIT 1")

        # dead-letter event
        await ins_outbox(conn, cid, "dl", "dead_lettered")
        # old pending event (20 phut truoc) -> oldest_pending > 15m
        await ins_outbox(conn, cid, "oldpg", "pending", available_offset_min=20)
        # credential error attempt (http_401) recent
        e_c = await ins_outbox(conn, cid, "cred", "dead_lettered")
        await conn.execute(
            "INSERT INTO delivery_attempts (outbox_event_id, attempt_no, worker_id, started_at, "
            "finished_at, outcome, http_status, error_class, correlation_id) "
            "VALUES ($1,1,'w', now(), now(), 'terminal_error', 401, 'http_401', gen_random_uuid())", e_c)
        # stale processing command (started_at 10 phut truoc)
        env2 = build_order_create_envelope(raw_payload=dict(C, quantity=1, unit_price_vnd=150000),
                                          actor=Actor("staff", str(st["id"])), channel="dashboard",
                                          idempotency_key="obs-stale-key-00001")
        await repo.insert_command(conn, env2.as_insert_params(status="processing"))
        await conn.execute("UPDATE command_executions SET started_at=now()-interval '10 minutes' "
                           "WHERE idempotency_key='obs-stale-key-00001'")

        m = await observability.command_bus_metrics(conn)
        if m["commands_by_status"].get("succeeded", 0) < 1:
            fails.append(f"metric: thieu succeeded command: {m['commands_by_status']}")
        if m["outbox_dead_letter_total"] < 2:
            fails.append(f"metric: dead_letter_total sai: {m['outbox_dead_letter_total']}")
        if m["outbox_oldest_pending_age_seconds"] <= 900:
            fails.append(f"metric: oldest_pending sai: {m['outbox_oldest_pending_age_seconds']}")
        if m["credential_error_15m"] < 1:
            fails.append(f"metric: credential_error sai: {m['credential_error_15m']}")
        if m["stale_processing_total"] < 1:
            fails.append(f"metric: stale_processing sai: {m['stale_processing_total']}")

        names = {a["name"] for a in observability.evaluate_alerts(m)}
        for want in ("dead_letter_present", "outbox_oldest_pending", "credential_outage",
                     "stale_command_processing"):
            if want not in names:
                fails.append(f"alert: thieu {want} (co: {names})")

        # log_event smoke (khong raise)
        observability.log_event("test.event", command_id="x", correlation_id="y", resource_id=1)
    finally:
        await conn.close()

    if fails:
        print("OBSERVABILITY FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("OBSERVABILITY PASS: metrics (succeeded/dead_letter/oldest_pending/credential/stale) + "
          "alerts (dead_letter_present, outbox_oldest_pending P1, credential_outage P1, "
          "stale_command_processing P2) + log_event smoke.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
