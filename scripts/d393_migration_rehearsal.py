"""CA Directive 393 §8 — rehearsal migration 073 (up / idempotent / down / up lai) tren DB SCRATCH rieng.

  docker run --rm --network m5lab -e PYTHONPATH=/srv -e ADMIN_DSN=postgresql://alpha3s:alpha3s@m5lab-db:5432/postgres \
    -v D:/alpha3s:/srv -w /srv alpha3s-api:latest python scripts/d393_migration_rehearsal.py

Chung minh (KHONG dung DB that/prod):
  1. Fresh DB 001..072 -> 073 OK; chay lai 073 idempotent.
  2. Rang buoc: 1 operation active/order; UNIQUE (source, command_key); initiator theo source; succeeded bat buoc
     provider_order_code; snapshot/identity bat bien; state terminal khong doi; attempts append-only; DELETE bi cam.
  3. Down (khoi ROLLBACK cuoi file, sau precheck = 0) -> bang/quyen/CHECK ve trang thai 072; Up lai OK.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
DBNAME = "d393_rehearsal"
_fail: list[str] = []

DOWN = """
DELETE FROM role_permissions WHERE permission_key='shipment.ghn.create';
DELETE FROM permissions WHERE key='shipment.ghn.create';
DROP TABLE ghn_shipment_create_attempts; DROP TABLE ghn_shipment_create_operations;
DROP FUNCTION ghn_shipment_create_attempts_no_mutate(); DROP FUNCTION ghn_shipment_create_operations_freeze();
ALTER TABLE fulfillment_conversations DROP CONSTRAINT IF EXISTS fulfillment_conversations_step_check;
ALTER TABLE fulfillment_conversations ADD CONSTRAINT fulfillment_conversations_step_check CHECK (step IN
    ('routing', 'awaiting_method', 'cod_handoff', 'awaiting_transfer', 'staff_attention', 'completed', 'cancelled'));
ALTER TABLE staff_attention DROP CONSTRAINT IF EXISTS staff_attention_reason_check;
ALTER TABLE staff_attention ADD CONSTRAINT staff_attention_reason_check CHECK (reason IN
    ('address', 'quote', 'account', 'method', 'payment_mismatch', 'unmatched_webhook', 'payment_timeout',
     'large_order_review', 'quantity_unit_review', 'provider_error', 'other',
     'refund_required', 'order_cancel_exception'));
ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS outbox_command_id_required_unless_escalation;
ALTER TABLE outbox_events ADD CONSTRAINT outbox_command_id_required_unless_escalation CHECK (command_id IS NOT NULL
    OR event_type IN ('order.escalated.notify', 'handoff.escalated.notify', 'shipment.handover.notify',
    'shipment.delivered.notify', 'shipment.failed.notify', 'payment.check_request.notify', 'payment.confirmed.notify',
    'fulfillment.prompt.notify', 'fulfillment.instruction.notify', 'fulfillment.reminder.notify',
    'fulfillment.staff.notify', 'fulfillment.cod.notify'));
"""
PRECHECK = ("SELECT (SELECT count(*) FROM ghn_shipment_create_operations) + "
            "(SELECT count(*) FROM fulfillment_conversations WHERE step='ship_confirm') + "
            "(SELECT count(*) FROM staff_attention WHERE reason='shipment_create') + "
            "(SELECT count(*) FROM outbox_events WHERE event_type='shipment.ghn_created.notify')")


def check(cond, label):
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        _fail.append(label)


async def apply(conn, sql: str):
    async with conn.transaction():
        await conn.execute(sql)


async def expect(conn, sql, args, exc, label):
    try:
        async with conn.transaction():
            await conn.execute(sql, *args)
        check(False, label)
    except exc:
        check(True, label)


async def main():
    admin_dsn = os.environ.get("ADMIN_DSN", "postgresql://alpha3s:alpha3s@m5lab-db:5432/postgres")
    admin = await asyncpg.connect(admin_dsn)
    await admin.execute(f"DROP DATABASE IF EXISTS {DBNAME}")
    await admin.execute(f"CREATE DATABASE {DBNAME}")
    await admin.close()
    conn = await asyncpg.connect(admin_dsn.rsplit("/", 1)[0] + "/" + DBNAME)
    try:
        migs = sorted(p for p in MIG.glob("*.sql") if p.name[:3].isdigit())
        m073 = next(p for p in migs if p.name.startswith("073_")).read_text(encoding="utf-8")
        for p in migs:
            if p.name < "073_":
                await apply(conn, p.read_text(encoding="utf-8"))
        await apply(conn, m073)
        await apply(conn, m073)
        check(await conn.fetchval("SELECT to_regclass('ghn_shipment_create_operations') IS NOT NULL"),
              "[1] 073 up + re-apply idempotent")
        check(await conn.fetchval("SELECT count(*) FROM role_permissions WHERE permission_key='shipment.ghn.create'")
              == 1, "[1] quyen shipment.ghn.create chi gan admin")

        cid = await conn.fetchval("INSERT INTO customers (psid, channel, external_chat_id) VALUES "
                                  "('tg:1','telegram_customer','1') RETURNING id")
        oid = await conn.fetchval("INSERT INTO orders (customer_id,status,total_vnd,origin_channel) "
                                  "VALUES ($1,'confirmed',1,'telegram_customer') RETURNING id", cid)
        sid = await conn.fetchval("INSERT INTO staff_users (username,password_hash,password_salt,role_key) "
                                  "VALUES ('r393','x','x','admin') RETURNING id")
        ins = ("INSERT INTO ghn_shipment_create_operations (order_id, source, initiator_staff_id, initiator_customer_id, "
               "command_key, request_fingerprint, mode, config_revision, client_order_code, policy_version, "
               "request_snapshot, state, provider_order_code) VALUES ($1,$2,$3,$4,$5,'fp','staging',1,$6,'v1',"
               "'{}'::jsonb,$7,$8) RETURNING id")
        op1 = await conn.fetchval(ins, oid, "dashboard", sid, None, "k1", "A3S-1-1", "prepared", None)
        await expect(conn, ins, (oid, "dashboard", sid, None, "k2", "A3S-1-2", "prepared", None),
                     asyncpg.UniqueViolationError, "[2] 1 operation active / order")
        await expect(conn, ins, (oid, "dashboard", sid, None, "k1", "A3S-1-3", "failed_terminal", None),
                     asyncpg.UniqueViolationError, "[2] UNIQUE (source, command_key)")
        await expect(conn, ins, (oid, "bot", None, None, "k3", "A3S-1-4", "failed_terminal", None),
                     asyncpg.CheckViolationError, "[2] initiator bat buoc theo source")
        await expect(conn, "UPDATE ghn_shipment_create_operations SET state='succeeded' WHERE id=$1", (op1,),
                     asyncpg.CheckViolationError, "[2] succeeded bat buoc provider_order_code")
        await expect(conn, "UPDATE ghn_shipment_create_operations SET request_snapshot='{\"x\":1}'::jsonb WHERE id=$1",
                     (op1,), asyncpg.RaiseError, "[2] request_snapshot bat bien")
        await expect(conn, "DELETE FROM ghn_shipment_create_operations WHERE id=$1", (op1,), asyncpg.RaiseError,
                     "[2] DELETE operation bi cam")
        await conn.execute("UPDATE ghn_shipment_create_operations SET state='cancelled_before_dispatch' WHERE id=$1", op1)
        await expect(conn, "UPDATE ghn_shipment_create_operations SET state='prepared' WHERE id=$1", (op1,),
                     asyncpg.RaiseError, "[2] state terminal khong doi")
        await conn.execute("INSERT INTO ghn_shipment_create_attempts (operation_id, attempt_no, kind, outcome, actor) "
                           "VALUES ($1,1,'create','retryable','t')", op1)
        await expect(conn, "UPDATE ghn_shipment_create_attempts SET outcome='created' WHERE operation_id=$1", (op1,),
                     asyncpg.RaiseError, "[2] attempts append-only")
        op2 = await conn.fetchval(ins, oid, "dashboard", sid, None, "k4", "A3S-1-5", "prepared", None)
        check(op2 is not None, "[2] tao lai duoc sau khi operation cu terminal")
        await conn.execute("INSERT INTO outbox_events (id, command_id, event_type, event_version, destination, "
                           "dedupe_key, payload, status, max_attempts) VALUES (gen_random_uuid(), NULL, "
                           "'shipment.ghn_created.notify', 1, 'telegram_customer', 'd393', $1::jsonb, 'pending', 8)",
                           json.dumps({"text": "x"}))
        check(True, "[2] outbox cho phep shipment.ghn_created.notify khong command")

        check(await conn.fetchval(PRECHECK) > 0, "[3] precheck phat hien du lieu -> runbook DUNG (khong down)")
        # mo phong DB chua co du lieu 393 (scratch) -> down duoc
        await conn.execute("ALTER TABLE ghn_shipment_create_operations DISABLE TRIGGER gsco_freeze")
        await conn.execute("ALTER TABLE ghn_shipment_create_attempts DISABLE TRIGGER gsca_no_mutate")
        await conn.execute("DELETE FROM ghn_shipment_create_attempts; DELETE FROM ghn_shipment_create_operations; "
                           "DELETE FROM outbox_events WHERE dedupe_key='d393'")
        check(await conn.fetchval(PRECHECK) == 0, "[3] precheck = 0")
        await apply(conn, DOWN)
        check(await conn.fetchval("SELECT to_regclass('ghn_shipment_create_operations') IS NULL AND "
                                  "(SELECT count(*) FROM permissions WHERE key='shipment.ghn.create') = 0"),
              "[3] down: bang + quyen da go")
        await apply(conn, m073)
        check(await conn.fetchval("SELECT to_regclass('ghn_shipment_create_operations') IS NOT NULL"),
              "[3] up lai sau down OK")
    finally:
        await conn.close()
        admin = await asyncpg.connect(admin_dsn)
        await admin.execute(f"DROP DATABASE IF EXISTS {DBNAME}")
        await admin.close()
    print("RESULT:", "ALL PASS" if not _fail else f"{len(_fail)} FAIL: {_fail}")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    asyncio.run(main())
