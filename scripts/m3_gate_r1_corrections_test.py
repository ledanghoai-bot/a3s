#!/usr/bin/env python3
"""M3 CA Merge/Release Gate Review R1 corrections evidence — F-M3-GATE-R1-01..02.

Chay tren throwaway DB khop DATABASE_URL (an toan: db name phai chua 'test'):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m3g1_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m3_gate_r1_corrections_test.py

Chung minh (negative drift evidence tren EXISTING-DB path):
  F-GATE-01 (retention policy drift + immutability):
    a. DB o moc 034, draft RET-04 v1 bi sua period 730->999 -> apply 035 RAISE (khong approve drift).
    b. drift action delete->anonymize -> 035 RAISE.
    c. drift data_category -> 035 RAISE.
    d. m3_contract_validation phat hien approved-policy drift (tamper ngoai luong khi disable trigger).
    e. 037 immutability: UPDATE period/action cua approved -> reject; approved->draft -> reject;
       approved->retired OK; retired bat bien; DELETE approved -> reject; draft sua/xoa duoc.
  F-GATE-02 (template v2 drift):
    a. DB o moc 035, pre-insert fulfilled v2 body SAI -> apply 036 RAISE (ON CONFLICT khong nuot drift).
    b. pre-insert v2 purpose SAI -> 036 RAISE.
    c. m3_contract_validation phat hien v2 drift (exact tuple) + seed v1 content drift (md5).
  Sanity: fresh 001..037 PASS + validation PASS tren DB dung contract.
"""
import asyncio
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

_fail = []


def check(cond, label):
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        _fail.append(label)


def _db():
    return settings.database_url.replace("+asyncpg", "")


def _files(through):
    return [p for p in sorted(MIG.glob("*.sql")) if p.name[:3].isdigit() and int(p.name[:3]) <= through]


async def migrate(conn, through=99):
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
        "applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT, transactional BOOLEAN NOT NULL DEFAULT true)")
    for p in _files(through):
        async with conn.transaction():
            await conn.execute(p.read_text(encoding="utf-8"))


async def mkdb(name):
    admin = await asyncpg.connect("postgresql://alpha3s:alpha3s@db:5432/postgres")
    await admin.execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{name}' AND pid<>pg_backend_pid()")
    await admin.execute(f"DROP DATABASE IF EXISTS {name}")
    await admin.execute(f"CREATE DATABASE {name}")
    await admin.close()
    return await asyncpg.connect(_db().rsplit("/", 1)[0] + "/" + name)


async def apply_one(conn, num):
    p = next(x for x in MIG.glob(f"{num}_*.sql"))
    async with conn.transaction():
        await conn.execute(p.read_text(encoding="utf-8"))


async def expect_raise(conn, num, needle, label):
    try:
        await apply_one(conn, num)
        check(False, label + " (khong RAISE)")
    except asyncpg.RaiseError as e:
        check(needle in str(e), f"{label} ({str(e)[:70]})")


async def main():  # noqa: C901
    dbname = _db().rsplit("/", 1)[-1]
    if "test" not in dbname:
        print(f"ABORT: DATABASE_URL db='{dbname}' khong chua 'test' — tu choi (an toan).")
        return 2

    vsql = (ROOT / "scripts" / "m3_contract_validation.sql").read_text(encoding="utf-8")

    print("[0] sanity: fresh 001..037 + validation PASS")
    conn = await mkdb(dbname)
    try:
        await migrate(conn)
        await conn.execute(vsql)
        check(True, "fresh chain + validation PASS tren DB dung contract")

        print("[F-GATE-01.e] 037 immutability cho approved policy")
        for stmt, label in [
            ("UPDATE retention_policies SET retention_period_days=9 WHERE rule_id='RET-04' AND version=1",
             "UPDATE period approved -> reject"),
            ("UPDATE retention_policies SET action='anonymize' WHERE rule_id='RET-04' AND version=1",
             "UPDATE action approved -> reject"),
            ("UPDATE retention_policies SET status='draft' WHERE rule_id='RET-04' AND version=1",
             "approved -> draft (un-approve) -> reject"),
            ("DELETE FROM retention_policies WHERE rule_id='RET-04' AND version=1",
             "DELETE approved -> reject"),
        ]:
            try:
                await conn.execute(stmt)
                check(False, label + " (khong raise)")
            except asyncpg.RaiseError as e:
                check("immutable_retention_policy" in str(e), label)
        await conn.execute(
            "INSERT INTO retention_policies (rule_id, version, data_category, action, "
            "retention_period_days, status) VALUES ('G1', 1, 'raw_chat', 'delete', 100, 'draft')")
        await conn.execute("UPDATE retention_policies SET retention_period_days=200 WHERE rule_id='G1'")
        await conn.execute("UPDATE retention_policies SET status='approved' WHERE rule_id='G1'")
        await conn.execute("UPDATE retention_policies SET status='retired' WHERE rule_id='G1'")
        check(True, "lifecycle draft(sua ok)->approved->retired OK")
        try:
            await conn.execute("UPDATE retention_policies SET status='approved' WHERE rule_id='G1'")
            check(False, "retired -> approved should reject")
        except asyncpg.RaiseError:
            check(True, "retired bat bien (khong un-retire)")

        print("[F-GATE-01.d] validation detect approved-policy drift (tamper ngoai luong)")
        async with conn.transaction():
            await conn.execute("ALTER TABLE retention_policies DISABLE TRIGGER retention_policies_guard_trg")
            await conn.execute(
                "UPDATE retention_policies SET retention_period_days=999 WHERE rule_id='RET-04' AND version=1")
            await conn.execute("ALTER TABLE retention_policies ENABLE TRIGGER retention_policies_guard_trg")
        try:
            await conn.execute(vsql)
            check(False, "validation should RAISE tren policy drift")
        except asyncpg.RaiseError as e:
            check("RET-04" in str(e), f"validation detect RET-04 drift ({str(e)[:60]})")

        print("[F-GATE-02.c] validation detect template v2 drift + seed v1 drift")
        conn2 = await mkdb("m3g1b_itest")
        try:
            await migrate(conn2)
            async with conn2.transaction():
                await conn2.execute("ALTER TABLE outbound_templates DISABLE TRIGGER outbound_templates_guard_trg")
                await conn2.execute(
                    "UPDATE outbound_templates SET body='WRONG' WHERE template_key='order_status_fulfilled' AND version=2")
                await conn2.execute("ALTER TABLE outbound_templates ENABLE TRIGGER outbound_templates_guard_trg")
            try:
                await conn2.execute(vsql)
                check(False, "validation should RAISE tren v2 drift")
            except asyncpg.RaiseError as e:
                check("v2" in str(e), f"validation detect v2 drift ({str(e)[:60]})")
        finally:
            await conn2.close()
    finally:
        await conn.close()

    print("[F-GATE-01.a/b/c] existing-DB drift -> 035 RAISE, khong approve")
    for field, stmt in [
        ("period 999", "UPDATE retention_policies SET retention_period_days=999 WHERE rule_id='RET-04' AND version=1"),
        ("action anonymize", "UPDATE retention_policies SET action='anonymize' WHERE rule_id='RET-04' AND version=1"),
        ("category deletion_requests", "UPDATE retention_policies SET data_category='deletion_requests' WHERE rule_id='RET-04' AND version=1"),
    ]:
        cdb = await mkdb("m3g1c_itest")
        try:
            await migrate(cdb, through=34)  # truoc 035; draft van sua duoc (chua co 037? 037>035 -> chua ap)
            await cdb.execute(stmt)  # drift tren draft (hop le: draft mutable)
            await asyncio.sleep(0)
            try:
                await apply_one(cdb, "035")
                check(False, f"035 should RAISE voi drift {field}")
            except asyncpg.RaiseError as e:
                ok = "khong khop exact tuple" in str(e)
                check(ok, f"035 fail-closed voi drift {field} ({str(e)[:60]})")
                st = await cdb.fetchval(
                    "SELECT status FROM retention_policies WHERE rule_id='RET-04' AND version=1")
                check(st == "draft", f"drift {field}: policy KHONG duoc approve (van draft)")
        finally:
            await cdb.close()

    print("[F-GATE-02.a/b] existing-DB template v2 drift -> 036 RAISE")
    for field, ins in [
        ("body sai", "INSERT INTO outbound_templates (template_key, version, purpose_code, body, status) "
                     "VALUES ('order_status_fulfilled', 2, 'P03_TRANSACTIONAL', 'BODY SAI {id}', 'approved')"),
        ("purpose sai", "INSERT INTO outbound_templates (template_key, version, purpose_code, body, status) "
                        "VALUES ('order_status_fulfilled', 2, 'P06_MARKETING', "
                        "'Đơn #{id} của bạn đã được bàn giao cho đơn vị vận chuyển.', 'approved')"),
    ]:
        cdb = await mkdb("m3g1d_itest")
        try:
            await migrate(cdb, through=35)  # truoc 036
            await cdb.execute(ins)  # existing row cung (key,version) noi dung sai
            try:
                await apply_one(cdb, "036")
                check(False, f"036 should RAISE voi v2 {field}")
            except asyncpg.RaiseError as e:
                check("EXACT tuple" in str(e), f"036 fail-closed voi v2 {field} ({str(e)[:60]})")
        finally:
            await cdb.close()

    print("\n" + ("ALL PASS" if not _fail else f"FAIL: {_fail}"))
    return 0 if not _fail else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
