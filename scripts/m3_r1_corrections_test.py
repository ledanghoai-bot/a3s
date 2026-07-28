#!/usr/bin/env python3
"""M3 CA Substantive Review R1 corrections evidence — F-M3-R1-01..03.

Chay tren throwaway DB khop DATABASE_URL (an toan: db name phai chua 'test'):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m3r1_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m3_r1_corrections_test.py

Chung minh:
  F01 (consent precedence — khong so sanh revision cheo sequence):
    a. channel-specific grant revision CAO (5) + global withdrawal MOI hon nhung revision thap (1)
       -> deny (global withdrawal phu channel).
    b. global denial revision cao + channel-specific grant moi hon (sequence rieng)
       -> deny (precedence 1 deterministic).
    c. khong global denial: channel-specific denial thang global grant (precedence 2).
    d. chi co global grant -> channel bat ky allow (precedence 3).
  F02 (retention action + hold + transaction):
    a. policy approved action='anonymize' -> RetentionError action_not_implemented, KHONG mutation.
    b. action='archive' tuong tu.
    c. deletion_requests: counts khai bao legal_hold_semantics=not_applicable_no_customer_link
       (khong con skipped_hold=0 gay hieu nham).
    d. transaction boundary: run-log INSERT loi (actor=None NOT NULL) -> mutation ROLLBACK
       (khong xoa thanh cong ma mat audit).
  F03 (template immutability tai DB boundary — migration 034):
    a. UPDATE body cua approved -> exception immutable_template.
    b. UPDATE purpose_code cua approved -> exception.
    c. approved -> draft (un-approve) -> exception; approved -> retired OK; retired -> approved -> exception.
    d. DELETE approved -> exception; draft duoc sua body + DELETE.
    e. seed drift: tat trigger (superuser mo phong out-of-band edit) + sua seed -> re-apply 034 RAISE.
"""
import asyncio
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services import consent, retention  # noqa: E402

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


PV, NV = "policy-v1.2", "notice-v1.1"


async def rec(conn, cid, purpose, status, channel="any", via="chat"):
    return await consent.record_consent(conn, customer_id=cid, purpose_code=purpose, status=status,
                                        captured_via=via, policy_version=PV, notice_version=NV,
                                        channel=channel)


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
        print("[0] migrations 001..034 fresh apply (034 trigger + seed drift check PASS khi seed dung)")
        await migrate(conn)
        check(await conn.fetchval(
            "SELECT count(*) FROM pg_trigger WHERE tgname='outbound_templates_guard_trg'") == 1,
            "034: trigger guard ton tai")

        print("[F01] consent precedence deterministic")
        c1 = await conn.fetchval("INSERT INTO customers (psid, name) VALUES ('r1-c1','K') RETURNING id")
        # a) channel-specific grant, day revision len 5 trong sequence messenger
        for st in ["granted", "denied", "granted", "denied", "granted"]:
            await rec(conn, c1, "P06_MARKETING", st, channel="messenger")
        # global withdrawal MOI NHAT nhung revision=1 (sequence any rieng)
        await rec(conn, c1, "P06_MARKETING", "withdrawn", channel="any", via="chat_optout")
        d = await consent.check_permission(conn, customer_id=c1, purpose_code="P06_MARKETING",
                                           channel="messenger")
        check(d.decision == "deny",
              f"a) global withdrawal (rev thap, moi hon) phu channel grant rev cao (got {d.decision}/{d.reason_code})")

        c2 = await conn.fetchval("INSERT INTO customers (psid, name) VALUES ('r1-c2','K') RETURNING id")
        # b) global denial rev cao truoc, channel-specific grant moi hon (rev 1 sequence rieng)
        for st in ["granted", "denied", "denied"]:
            await rec(conn, c2, "P06_MARKETING", st, channel="any")
        await rec(conn, c2, "P06_MARKETING", "granted", channel="messenger")
        d2 = await consent.check_permission(conn, customer_id=c2, purpose_code="P06_MARKETING",
                                            channel="messenger")
        check(d2.decision == "deny",
              f"b) global denial thang channel grant moi hon (precedence 1) (got {d2.decision})")

        c3 = await conn.fetchval("INSERT INTO customers (psid, name) VALUES ('r1-c3','K') RETURNING id")
        await rec(conn, c3, "P06_MARKETING", "granted", channel="any")
        await rec(conn, c3, "P06_MARKETING", "denied", channel="messenger")
        d3 = await consent.check_permission(conn, customer_id=c3, purpose_code="P06_MARKETING",
                                            channel="messenger")
        check(d3.decision == "deny", f"c) channel denial thang global grant (precedence 2) (got {d3.decision})")
        d3b = await consent.check_permission(conn, customer_id=c3, purpose_code="P06_MARKETING",
                                             channel="zalo_zns")
        check(d3b.decision == "allow", f"d) channel khac khong bi anh huong -> global grant (got {d3b.decision})")

        print("[F02] retention action fail-closed + hold semantics + transaction")
        cid = await conn.fetchval("INSERT INTO customers (psid, name) VALUES ('r1-ret','K') RETURNING id")
        conv = await conn.fetchval(
            "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now() - interval '900 days') RETURNING id", cid)
        await conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES ($1,'customer','old','now'::timestamptz - interval '900 days')", conv)
        await conn.execute(
            "INSERT INTO retention_policies (rule_id, version, data_category, action, retention_period_days, status) "
            "VALUES ('RET-04', 9, 'raw_chat', 'anonymize', 730, 'approved'), "
            "('RET-04', 10, 'raw_chat', 'archive', 730, 'approved'), "
            "('RET-04', 11, 'raw_chat', 'delete', 730, 'approved'), "
            "('RET-09', 9, 'deletion_requests', 'delete', 730, 'approved')")
        for ver, act in [(9, "anonymize"), (10, "archive")]:
            try:
                await retention.run_retention(conn, rule_id="RET-04", version=ver, dry_run=False)
                check(False, f"a/b) action {act} should fail-closed")
            except retention.RetentionError as e:
                check("action_not_implemented" in str(e), f"a/b) {act} -> action_not_implemented (got {e})")
        n = await conn.fetchval("SELECT count(*) FROM conversations WHERE id=$1", conv)
        check(n == 1, "a/b) KHONG mutation nao xay ra truoc fail-closed")

        await conn.execute(
            "INSERT INTO data_deletion_requests (confirmation_code, requested_at) "
            "VALUES ('R1OLD', now() - interval '800 days')")
        rep = await retention.run_retention(conn, rule_id="RET-09", version=9, dry_run=False)
        check(rep["counts"].get("legal_hold_semantics") == "not_applicable_no_customer_link"
              and "skipped_hold" not in rep["counts"],
              f"c) deletion_requests khai bao hold semantics tuong minh (got {rep['counts']})")

        # d) transaction boundary: actor=None -> run_log INSERT vi pham NOT NULL -> mutation rollback
        pre = await conn.fetchval("SELECT count(*) FROM conversations WHERE id=$1", conv)
        try:
            await retention.run_retention(conn, rule_id="RET-04", version=11, dry_run=False, actor=None)
            check(False, "d) run-log loi should raise")
        except Exception:  # noqa: BLE001 — NotNullViolation
            pass
        post = await conn.fetchval("SELECT count(*) FROM conversations WHERE id=$1", conv)
        nlog = await conn.fetchval(
            "SELECT count(*) FROM retention_run_log WHERE rule_id='RET-04' AND version=11")
        check(pre == 1 and post == 1 and nlog == 0,
              f"d) log loi -> mutation ROLLBACK, khong mat audit (pre={pre} post={post} log={nlog})")
        rep2 = await retention.run_retention(conn, rule_id="RET-04", version=11, dry_run=False)
        check(rep2["counts"].get("conversations_deleted") == 1, "d) chay lai hop le -> xoa + log atomic")

        print("[F03] template immutability tai DB boundary")
        for stmt, label in [
            ("UPDATE outbound_templates SET body='HACKED' WHERE template_key='order_status_confirmed' AND version=1",
             "a) UPDATE body approved -> reject"),
            ("UPDATE outbound_templates SET purpose_code='P06_MARKETING' WHERE template_key='order_status_confirmed' AND version=1",
             "b) UPDATE purpose_code approved -> reject"),
            ("UPDATE outbound_templates SET status='draft' WHERE template_key='order_status_confirmed' AND version=1",
             "c) approved -> draft (un-approve) -> reject"),
            ("DELETE FROM outbound_templates WHERE template_key='order_status_confirmed' AND version=1",
             "d) DELETE approved -> reject"),
        ]:
            try:
                await conn.execute(stmt)
                check(False, label + " (khong raise)")
            except asyncpg.RaiseError as e:
                check("immutable_template" in str(e), label)
        body = await conn.fetchval(
            "SELECT body FROM outbound_templates WHERE template_key='order_status_confirmed' AND version=1")
        check(body == "Đơn #{id} của bạn đã được xác nhận.", "approved body nguyen ven sau moi attempt")

        # lifecycle hop le: draft sua duoc + approve; approved -> retired; retired bat bien
        await conn.execute(
            "INSERT INTO outbound_templates (template_key, version, purpose_code, body, status) "
            "VALUES ('r1_test', 1, 'P03_TRANSACTIONAL', 'draft body {id}', 'draft')")
        await conn.execute("UPDATE outbound_templates SET body='draft body v2 {id}' WHERE template_key='r1_test'")
        await conn.execute("UPDATE outbound_templates SET status='approved' WHERE template_key='r1_test'")
        await conn.execute("UPDATE outbound_templates SET status='retired' WHERE template_key='r1_test'")
        check(True, "e) lifecycle draft(sua ok)->approved->retired OK")
        try:
            await conn.execute("UPDATE outbound_templates SET status='approved' WHERE template_key='r1_test'")
            check(False, "f) retired -> approved should reject")
        except asyncpg.RaiseError:
            check(True, "f) retired bat bien (khong un-retire)")
        await conn.execute(
            "INSERT INTO outbound_templates (template_key, version, purpose_code, body, status) "
            "VALUES ('r1_draft_del', 1, 'P03_TRANSACTIONAL', 'x {id}', 'draft')")
        await conn.execute("DELETE FROM outbound_templates WHERE template_key='r1_draft_del'")
        check(True, "g) draft DELETE duoc")

        print("[F03-e] seed drift detection khi re-apply 034")
        async with conn.transaction():
            await conn.execute("ALTER TABLE outbound_templates DISABLE TRIGGER outbound_templates_guard_trg")
            await conn.execute(
                "UPDATE outbound_templates SET body='DRIFTED' WHERE template_key='order_status_completed' AND version=1")
            await conn.execute("ALTER TABLE outbound_templates ENABLE TRIGGER outbound_templates_guard_trg")
        try:
            async with conn.transaction():
                await conn.execute((MIG / "034_template_immutability.sql").read_text(encoding="utf-8"))
            check(False, "seed drift should RAISE on re-apply")
        except asyncpg.RaiseError as e:
            check("drift" in str(e), f"re-apply 034 phat hien seed drift (got {str(e)[:80]})")
    finally:
        await conn.close()

    print("\n" + ("ALL PASS" if not _fail else f"FAIL: {_fail}"))
    return 0 if not _fail else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
