#!/usr/bin/env python3
"""Outbox delivery worker evidence (I-B M1 Slice 5). Spec §9, §8.2.

Inject send_fn gia (khong cham Telegram that). Bao phu:
  T1 delivered     : 2xx -> delivered + provider_message_id + 1 attempt(delivered).
  T2 retry->dead   : 5xx, max_attempts=2 -> attempt1 retry_scheduled, attempt2 dead_lettered.
  T3 terminal 4xx  : 400 -> dead_lettered ngay (1 attempt terminal_error).
  T4 timeout       : timeout -> UNKNOWN, retry_scheduled (khong failed ngay, §8.2).
  T5 lease reclaim : 'delivering' lease het han -> reclaim -> delivered (crash recovery).

  docker exec -e DATABASE_URL=...m1_itest -e PYTHONPATH=/srv -w /srv api python scripts/command_outbox_worker_test.py
"""
import asyncio
import json
import sys

import asyncpg

from app.config import settings
from app.services import auth_service
from app.services.command import order_service, outbox_worker
from app.services.command.envelope import Actor, build_order_create_envelope
from app.services.command.outbox_worker import SendResult

C = {"customer_name": "Pham C", "phone": "0901122334", "address": "9 Ba Trieu, HN"}


def _db() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def ok_send(dest, payload):
    return SendResult(ok=True, http_status=200, provider_message_id="tg-msg-1")


async def err500(dest, payload):
    return SendResult(ok=False, http_status=500, error_class="http_500")


async def err400(dest, payload):
    return SendResult(ok=False, http_status=400, error_class="http_400")


async def timeout_send(dest, payload):
    return SendResult(ok=False, is_timeout=True, error_class="timeout")


async def clear_outbox(conn):
    await conn.execute("TRUNCATE outbox_events, delivery_attempts RESTART IDENTITY CASCADE")


async def insert_event(conn, command_id, correlation, dedupe, max_attempts):
    payload = json.dumps({"order_id": 1, "correlation_id": str(correlation), "sku": "3S-100G",
                          "quantity": 1, "unit_price_vnd": 150000, "total_vnd": 150000,
                          "customer_name": "Pham C", "phone_masked": "***334", "status": "new"})
    return await conn.fetchval(
        "INSERT INTO outbox_events (id, command_id, event_type, event_version, destination, "
        "dedupe_key, payload, status, available_at, max_attempts) "
        "VALUES (gen_random_uuid(), $1, 'order.created.notify', 1, 'telegram_admin', $2, $3::jsonb, "
        "'pending', now(), $4) RETURNING id", command_id, dedupe, payload, max_attempts)


async def ev(conn, dedupe):
    return await conn.fetchrow("SELECT status, attempt_count, provider_message_id, delivered_at, "
                               "dead_lettered_at, last_error_code FROM outbox_events WHERE dedupe_key=$1",
                               dedupe)


async def att_count(conn, dedupe):
    return await conn.fetchval(
        "SELECT count(*) FROM delivery_attempts da JOIN outbox_events o ON o.id=da.outbox_event_id "
        "WHERE o.dedupe_key=$1", dedupe)


async def main() -> int:  # noqa: C901
    conn = await asyncpg.connect(_db())
    fails: list[str] = []
    try:
        await conn.execute("TRUNCATE order_items, orders, command_executions, outbox_events, "
                           "delivery_attempts, price_overrides RESTART IDENTITY CASCADE")
        await conn.execute("UPDATE products SET stock=1000 WHERE sku='3S-100G'")
        st = await auth_service.create_staff_user("ob_staff", "pw12345678", "OB", role_key="admin")
        env = build_order_create_envelope(raw_payload=dict(C, sku="3S-100G", quantity=1,
                                          unit_price_vnd=150000), actor=Actor("staff", str(st["id"])),
                                          channel="dashboard", idempotency_key="ob-seed-key-0001")
        await order_service.execute_order_create(env)
        crow = await conn.fetchrow("SELECT id, correlation_id FROM command_executions LIMIT 1")
        cid, corr = crow["id"], crow["correlation_id"]

        # T1 delivered
        await clear_outbox(conn)
        await insert_event(conn, cid, corr, "d1", 8)
        s = await outbox_worker.run_once(send_fn=ok_send)
        e = await ev(conn, "d1")
        if not (s["delivered"] == 1 and e["status"] == "delivered"
                and e["provider_message_id"] == "tg-msg-1" and e["delivered_at"] is not None):
            fails.append(f"T1: delivered sai: stats={s} ev={dict(e)}")
        if await att_count(conn, "d1") != 1:
            fails.append("T1: khong dung 1 delivery_attempt")

        # T2 retry -> dead-letter (max_attempts=2)
        await clear_outbox(conn)
        await insert_event(conn, cid, corr, "r1", 2)
        await outbox_worker.run_once(send_fn=err500)
        e1 = await ev(conn, "r1")
        if not (e1["status"] == "retry_scheduled" and e1["attempt_count"] == 1):
            fails.append(f"T2: attempt1 phai retry_scheduled: {dict(e1)}")
        await conn.execute("UPDATE outbox_events SET available_at=now() WHERE dedupe_key='r1'")
        await outbox_worker.run_once(send_fn=err500)
        e2 = await ev(conn, "r1")
        if not (e2["status"] == "dead_lettered" and e2["attempt_count"] == 2
                and e2["dead_lettered_at"] is not None and e2["last_error_code"] == "http_500"):
            fails.append(f"T2: attempt2 phai dead_lettered: {dict(e2)}")
        if await att_count(conn, "r1") != 2:
            fails.append("T2: phai co 2 delivery_attempts")

        # T3 terminal 400 -> dead-letter ngay
        await clear_outbox(conn)
        await insert_event(conn, cid, corr, "t1", 8)
        await outbox_worker.run_once(send_fn=err400)
        e = await ev(conn, "t1")
        if not (e["status"] == "dead_lettered" and e["attempt_count"] == 1):
            fails.append(f"T3: 400 phai dead_lettered ngay: {dict(e)}")
        row = await conn.fetchrow("SELECT da.outcome FROM delivery_attempts da JOIN outbox_events o "
                                  "ON o.id=da.outbox_event_id WHERE o.dedupe_key='t1'")
        if row["outcome"] != "terminal_error":
            fails.append(f"T3: attempt outcome phai terminal_error: {row['outcome']}")

        # T4 timeout -> unknown, retry
        await clear_outbox(conn)
        await insert_event(conn, cid, corr, "to1", 8)
        await outbox_worker.run_once(send_fn=timeout_send)
        e = await ev(conn, "to1")
        row = await conn.fetchrow("SELECT da.outcome FROM delivery_attempts da JOIN outbox_events o "
                                  "ON o.id=da.outbox_event_id WHERE o.dedupe_key='to1'")
        if not (e["status"] == "retry_scheduled" and row["outcome"] == "unknown"):
            fails.append(f"T4: timeout phai unknown+retry: {dict(e)} outcome={row['outcome']}")

        # T5 lease reclaim (crash sau claim)
        await clear_outbox(conn)
        await insert_event(conn, cid, corr, "l1", 8)
        await conn.execute("UPDATE outbox_events SET status='delivering', lease_owner='dead-worker', "
                           "lease_expires_at=now() - interval '2 minutes' WHERE dedupe_key='l1'")
        s = await outbox_worker.run_once(send_fn=ok_send)
        e = await ev(conn, "l1")
        if not (s["reclaimed"] >= 1 and e["status"] == "delivered"):
            fails.append(f"T5: reclaim+deliver sai: stats={s} ev={dict(e)}")
    finally:
        await conn.close()

    if fails:
        print("OUTBOX-WORKER FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("OUTBOX-WORKER PASS: T1 delivered+provider_id; T2 retry->dead-letter(max2); "
          "T3 400 terminal dead-letter; T4 timeout->unknown retry; T5 lease reclaim->deliver")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
