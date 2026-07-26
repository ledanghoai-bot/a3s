#!/usr/bin/env python3
"""Crash / fault-injection evidence (I-B M1, spec §13.1 / §8.2). Bổ sung cho hardening.

  C1  Lỗi TRƯỚC commit (inject insert_outbox raise) -> full rollback: KHÔNG order, KHÔNG command
      row, stock KHÔNG đổi (transaction nguyên tử).
  C2  "Crash sau commit trước response" -> retry cùng idempotency key đọc lại ĐÚNG receipt cũ,
      KHÔNG tạo order thứ hai, stock KHÔNG đổi thêm.
  C3  "Worker crash sau claim (đã/ chưa gửi) trước finalize" -> event kẹt 'delivering' + lease hết
      hạn -> reclaim -> gửi lại (at-least-once) -> delivered; số lần send quan sát được.

  docker exec -e DATABASE_URL=...m1_itest -e PYTHONPATH=/srv -w /srv api python scripts/command_crash_recovery_test.py
"""
import asyncio
import sys

import asyncpg

from app.config import settings
from app.services import auth_service
from app.services.command import order_service as osvc
from app.services.command import outbox_worker
from app.services.command.envelope import Actor, build_order_create_envelope
from app.services.command.outbox_worker import SendResult

C = {"customer_name": "Crash", "phone": "0900222444", "address": "7 Crash", "sku": "3S-100G"}


def _db():
    return settings.database_url.replace("+asyncpg", "")


async def orders_n(conn):
    return await conn.fetchval("SELECT count(*) FROM orders")


async def stock(conn):
    return await conn.fetchval("SELECT stock FROM products WHERE sku='3S-100G'")


async def cmd_n(conn, key):
    return await conn.fetchval("SELECT count(*) FROM command_executions WHERE idempotency_key=$1", key)


async def main() -> int:  # noqa: C901
    conn = await asyncpg.connect(_db())
    fails: list[str] = []
    try:
        await conn.execute("TRUNCATE order_items, orders, command_executions, outbox_events, "
                           "delivery_attempts, price_overrides RESTART IDENTITY CASCADE")
        await conn.execute("UPDATE products SET stock=1000 WHERE sku='3S-100G'")
        st = await auth_service.create_staff_user("crash_staff", "pw12345678", "CR", role_key="admin")

        def env(key):
            return build_order_create_envelope(raw_payload=dict(C, quantity=1, unit_price_vnd=150000),
                                               actor=Actor("staff", str(st["id"])), channel="dashboard",
                                               idempotency_key=key)

        # C1: fail BEFORE commit -> full rollback
        s0 = await stock(conn)
        orig_outbox = osvc.repo.insert_outbox

        async def boom(*a, **k):
            raise RuntimeError("injected crash before commit")

        osvc.repo.insert_outbox = boom
        raised = False
        try:
            await osvc.execute_order_create(env("crash-c1-key-000001"))
        except Exception:
            raised = True
        finally:
            osvc.repo.insert_outbox = orig_outbox
        if not raised:
            fails.append("C1: inject fail KHÔNG raise")
        if await orders_n(conn) != 0:
            fails.append("C1: có order sau rollback (phải 0)")
        if await cmd_n(conn, "crash-c1-key-000001") != 0:
            fails.append("C1: command row còn sau rollback (phải 0)")
        if await stock(conn) != s0:
            fails.append(f"C1: stock đổi sau rollback {s0}->{await stock(conn)}")

        # C2: commit ok -> retry same key -> same receipt, no 2nd order
        r1 = await osvc.execute_order_create(env("crash-c2-key-000001"))
        oid, s_after = r1.resource["id"], await stock(conn)
        r2 = await osvc.execute_order_create(env("crash-c2-key-000001"))  # "retry sau khi mất response"
        if not (r2.duplicate and r2.resource["id"] == oid):
            fails.append(f"C2: retry không trả receipt cũ: {r2.to_dict()}")
        if await orders_n(conn) != 1:
            fails.append(f"C2: có {await orders_n(conn)} order (phải 1)")
        if await stock(conn) != s_after:
            fails.append("C2: retry trừ stock lần hai")

        # C3: worker crash sau claim -> lease hết hạn -> reclaim -> re-send at-least-once
        eid = await conn.fetchval("SELECT id FROM outbox_events LIMIT 1")
        await conn.execute("UPDATE outbox_events SET status='delivering', lease_owner='dead', "
                           "lease_expires_at=now()-interval '2 minutes' WHERE id=$1", eid)
        calls = {"n": 0}

        async def counting_send(dest, payload):
            calls["n"] += 1
            return SendResult(ok=True, http_status=200, provider_message_id="tg-recover")

        s = await outbox_worker.run_once(send_fn=counting_send)
        ev = await conn.fetchrow("SELECT status FROM outbox_events WHERE id=$1", eid)
        if not (s["reclaimed"] >= 1 and ev["status"] == "delivered" and calls["n"] == 1):
            fails.append(f"C3: reclaim+resend sai: stats={s} status={ev['status']} sends={calls['n']}")
    finally:
        await conn.close()

    if fails:
        print("CRASH-RECOVERY FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("CRASH-RECOVERY PASS: C1 fail-before-commit->full rollback (0 order/0 command/stock giữ); "
          "C2 retry-after-commit->receipt cũ, 1 order; C3 worker-crash->lease reclaim->re-send delivered.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
