"""CA Directive 396 F1 — rehearsal migration 074 (up / idempotent / down / up lai) tren DB SCRATCH rieng.

  docker run --rm --network m5lab -e PYTHONPATH=/srv -e ADMIN_DSN=postgresql://alpha3s:alpha3s@m5lab-db:5432/postgres \
    -v D:/alpha3s:/srv -w /srv alpha3s-api:latest python scripts/d396_migration_rehearsal.py

Chung minh (KHONG dung DB that/prod):
  1. Fresh DB 001..073 -> 074 OK; chay lai 074 idempotent.
  2. staff_attention nhan reason 'eta_question'; reason ngoai allowlist van bi CHECK chan; 1 OPEN/(order, reason).
  3. Down (khoi ROLLBACK cuoi file, sau precheck = 0) -> CHECK ve trang thai 073 (chan eta_question); Up lai OK.
"""
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
DBNAME = "d396_rehearsal"
_fail: list[str] = []

DOWN = """
ALTER TABLE staff_attention DROP CONSTRAINT IF EXISTS staff_attention_reason_check;
ALTER TABLE staff_attention ADD CONSTRAINT staff_attention_reason_check CHECK (reason IN
    ('address', 'quote', 'account', 'method', 'payment_mismatch', 'unmatched_webhook', 'payment_timeout',
     'large_order_review', 'quantity_unit_review', 'provider_error', 'other',
     'refund_required', 'order_cancel_exception', 'shipment_create'));
"""
PRECHECK = "SELECT count(*) FROM staff_attention WHERE reason='eta_question'"


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
        m074 = next(p for p in migs if p.name.startswith("074_")).read_text(encoding="utf-8")
        for p in migs:
            if p.name[:3] < "074":
                await apply(conn, p.read_text(encoding="utf-8"))
        await apply(conn, m074)
        await apply(conn, m074)
        check(True, "[1] 074 up + re-apply idempotent")

        cid = await conn.fetchval("INSERT INTO customers (psid, channel, external_chat_id, name, phone) "
                                  "VALUES ('tg:d396','telegram_customer','tg:d396','R','0900000000') RETURNING id")
        oid = await conn.fetchval("INSERT INTO orders (customer_id, status, total_vnd, origin_channel) "
                                  "VALUES ($1,'confirmed',170000,'telegram_customer') RETURNING id", cid)
        ins = "INSERT INTO staff_attention (order_id, reason, detail, created_by) VALUES ($1,$2,'{}'::jsonb,'r')"
        await conn.execute(ins, oid, "eta_question")
        check(await conn.fetchval(PRECHECK) == 1, "[2] reason eta_question duoc chap nhan")
        await expect(conn, ins, (oid, "eta_bogus"), asyncpg.CheckViolationError, "[2] reason ngoai allowlist bi chan")
        await expect(conn, ins, (oid, "eta_question"), asyncpg.UniqueViolationError,
                     "[2] 1 OPEN / (order, eta_question)")

        check(await conn.fetchval(PRECHECK) > 0, "[3] precheck phat hien du lieu -> runbook DUNG (khong down)")
        await conn.execute("DELETE FROM staff_attention WHERE reason='eta_question'")   # scratch DB
        check(await conn.fetchval(PRECHECK) == 0, "[3] precheck = 0")
        await apply(conn, DOWN)
        await expect(conn, ins, (oid, "eta_question"), asyncpg.CheckViolationError,
                     "[3] down: CHECK ve 073 (chan eta_question)")
        await apply(conn, m074)
        await conn.execute(ins, oid, "eta_question")
        check(True, "[3] up lai sau down OK")
    finally:
        await conn.close()
        admin = await asyncpg.connect(admin_dsn)
        await admin.execute(f"DROP DATABASE IF EXISTS {DBNAME}")
        await admin.close()
    print("RESULT:", "ALL PASS" if not _fail else f"{len(_fail)} FAIL: {_fail}")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    asyncio.run(main())
