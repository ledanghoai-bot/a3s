#!/usr/bin/env python3
"""M3 Slice 6 evidence — retention executor (spec §7.7, AC-M3-07).

Chay tren throwaway DB khop DATABASE_URL (an toan: db name phai chua 'test'):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m3s6r_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m3_retention_test.py

Chung minh:
  1. Migration 033 fresh: policies seed DRAFT (PO chua duyet), run log, legal_holds.
  2. Dry-run raw_chat: dem dung conversation qua han, DB KHONG doi.
  3. Apply voi policy draft -> RetentionError policy_not_approved (khong xoa).
  4. Approve (version moi) -> apply xoa DUNG chat qua han (messages+escalations+conversations);
     chat moi giu nguyen; run log ghi counts KHONG PII.
  5. Legal hold: customer hold active -> chat qua han van GIU (skipped_hold dem dung);
     release hold -> lan chay sau xoa.
  6. Restore-non-resurrection: re-insert du lieu da xoa (mo phong restore backup) -> run lai ->
     bi xoa lai (policy hoi tu theo cutoff).
  7. deletion_requests qua han bi xoa (RET-09).
  8. Flag OFF: run_all_approved(dry_run=False) -> [{'skipped':'flag_off'}] (cron no-op).
"""
import asyncio
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services import retention  # noqa: E402

_fail = []


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


async def mk_chat(conn, psid: str, days_old: int) -> tuple[int, int]:
    cid = await conn.fetchval(
        "INSERT INTO customers (psid, name) VALUES ($1, 'K') RETURNING id", psid)
    conv = await conn.fetchval(
        "INSERT INTO conversations (customer_id, created_at) "
        "VALUES ($1, now() - ($2 || ' days')::interval) RETURNING id", cid, str(days_old))
    await conn.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) "
        "VALUES ($1, 'customer', 'xin chao', now() - ($2 || ' days')::interval)",
        conv, str(days_old))
    return cid, conv


async def main():  # noqa: C901
    dbname = _db().rsplit("/", 1)[-1]
    if "test" not in dbname:
        print(f"ABORT: DATABASE_URL db='{dbname}' khong chua 'test' — tu choi (an toan).")
        return 2

    admin = await asyncpg.connect("postgresql://alpha3s:alpha3s@db:5432/postgres")
    await admin.execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{dbname}' AND pid<>pg_backend_pid()")
    await admin.execute(f"DROP DATABASE IF EXISTS {dbname}")
    await admin.execute(f"CREATE DATABASE {dbname}")
    await admin.close()

    conn = await asyncpg.connect(_db())
    try:
        print("[1] migrations 001..033 fresh apply")
        await migrate(conn)
        st = await conn.fetchval(
            "SELECT status FROM retention_policies WHERE rule_id='RET-04' AND version=1")
        # 033 seed draft -> 035 (PO Decision Record M3 #1) nang approved
        check(st == "approved", f"RET-04 v1 = approved sau 035 (PO da duyet) (got {st})")
        # tao policy draft rieng de test refusal (v1 gio da approved)
        await conn.execute(
            "INSERT INTO retention_policies (rule_id, version, data_category, action, "
            "retention_period_days, status) VALUES ('RET-04', 90, 'raw_chat', 'delete', 730, 'draft')")

        _, conv_old = await mk_chat(conn, "ret-old", 800)
        _, conv_new = await mk_chat(conn, "ret-new", 5)

        print("[2] dry-run: dem dung, khong mutation")
        rep = await retention.run_retention(conn, rule_id="RET-04", version=1, dry_run=True)
        check(rep["counts"]["candidates"] == 1, f"dry-run candidates=1 (got {rep['counts']})")
        n = await conn.fetchval("SELECT count(*) FROM conversations")
        check(n == 2, "dry-run khong xoa gi")

        print("[3] apply policy draft -> tu choi")
        try:
            await retention.run_retention(conn, rule_id="RET-04", version=90, dry_run=False)
            check(False, "apply draft should raise")
        except retention.RetentionError as e:
            check("policy_not_approved" in str(e), f"policy_not_approved (got {e})")

        print("[4] approve -> apply xoa dung chat qua han")
        await conn.execute(
            "INSERT INTO retention_policies (rule_id, version, data_category, action, "
            "retention_period_days, status) VALUES ('RET-04', 2, 'raw_chat', 'delete', 730, 'approved')")
        rep2 = await retention.run_retention(conn, rule_id="RET-04", version=2, dry_run=False)
        check(rep2["counts"].get("conversations_deleted") == 1
              and rep2["counts"].get("messages_deleted") == 1,
              f"xoa 1 conv + 1 msg (got {rep2['counts']})")
        left = [r["id"] for r in await conn.fetch("SELECT id FROM conversations")]
        check(left == [conv_new], f"chat moi giu nguyen (left={left})")
        log = await conn.fetchrow(
            "SELECT counts::text AS c, dry_run FROM retention_run_log WHERE rule_id='RET-04' "
            "AND dry_run=false ORDER BY started_at DESC LIMIT 1")
        check(log is not None and "xin chao" not in log["c"] and "ret-old" not in log["c"],
              "run log chi so lieu, khong PII")

        print("[5] legal hold: giu du lieu, dem skipped_hold")
        cid_h, conv_h = await mk_chat(conn, "ret-hold", 900)
        await conn.execute(
            "INSERT INTO legal_holds (customer_id, reason_ref) VALUES ($1, 'ticket:op-77')", cid_h)
        rep3 = await retention.run_retention(conn, rule_id="RET-04", version=2, dry_run=False)
        check(rep3["counts"]["candidates"] == 0 and rep3["counts"]["skipped_hold"] == 1,
              f"hold active -> skip (got {rep3['counts']})")
        check(await conn.fetchval("SELECT count(*) FROM conversations WHERE id=$1", conv_h) == 1,
              "chat cua customer hold van con")
        await conn.execute("UPDATE legal_holds SET active=false, released_at=now() WHERE customer_id=$1", cid_h)
        rep4 = await retention.run_retention(conn, rule_id="RET-04", version=2, dry_run=False)
        check(rep4["counts"].get("conversations_deleted") == 1, "release hold -> lan sau xoa")

        print("[6] restore-non-resurrection")
        # mo phong restore backup: re-insert chat qua han da xoa
        await conn.execute(
            "INSERT INTO conversations (id, customer_id, created_at) "
            "SELECT $1, id, now() - interval '800 days' FROM customers WHERE psid='ret-old'", conv_old)
        await conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES ($1, 'customer', 'restored', now() - interval '800 days')", conv_old)
        rep5 = await retention.run_retention(conn, rule_id="RET-04", version=2, dry_run=False)
        check(rep5["counts"].get("conversations_deleted") == 1
              and await conn.fetchval("SELECT count(*) FROM conversations WHERE id=$1", conv_old) == 0,
              "du lieu restore qua han bi xoa lai (khong tai sinh)")

        print("[7] deletion_requests qua han (RET-09)")
        await conn.execute(
            "INSERT INTO data_deletion_requests (confirmation_code, requested_at) "
            "VALUES ('OLDCODE1', now() - interval '800 days'), ('NEWCODE1', now())")
        await conn.execute(
            "INSERT INTO retention_policies (rule_id, version, data_category, action, "
            "retention_period_days, status) VALUES ('RET-09', 2, 'deletion_requests', 'delete', 730, 'approved')")
        rep6 = await retention.run_retention(conn, rule_id="RET-09", version=2, dry_run=False)
        left = await conn.fetchval("SELECT count(*) FROM data_deletion_requests")
        check(rep6["counts"].get("deleted") == 1 and left == 1,
              f"xoa 1 request qua han, giu request moi (got {rep6['counts']}, left={left})")

        print("[8] flag OFF -> cron no-op")
        check(settings.m3_retention_executor is False, "default m3_retention_executor=False")
        out = await retention.run_all_approved(conn, dry_run=False)
        check(out == [{"skipped": "flag_off"}], f"apply qua run_all khi flag OFF -> skipped (got {out})")
        out2 = await retention.run_all_approved(conn, dry_run=True)
        check(isinstance(out2, list) and all("counts" in r for r in out2),
              "dry-run van chay duoc khi flag OFF (chuan bi cho PO duyet)")
    finally:
        await conn.close()

    print("\n" + ("ALL PASS" if not _fail else f"FAIL: {_fail}"))
    return 0 if not _fail else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
