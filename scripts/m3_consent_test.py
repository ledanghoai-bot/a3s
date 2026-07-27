#!/usr/bin/env python3
"""M3 Slice 3 evidence — consent ledger + check_permission + suppression (AC-M3-04; §13.19 #1,#2,#3,#13).

Chay tren throwaway DB khop DATABASE_URL (an toan: db name phai chua 'test'):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m3s3_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m3_consent_test.py

Chung minh:
  1. Migration 031 fresh-apply: bang + unique revision index.
  2. Ledger append-only + authority_revision monotonic (1,2,3...); conflict revision -> unique violation.
  3. #1: opt-out P06 KHONG chan P03 transactional (allow service_default).
  4. #2: granted P05 -> allow; withdraw P05 -> deny (chan follow-up).
  5. #3: complaint -> suppress P06 ke ca dang granted; complaint_resolved -> het suppress.
  6. #13: policy/notice version truy xuat duoc tu record hieu luc.
  7. unavailable fail-closed: loi ha tang (bang bien mat) -> 'unavailable', khong allow.
  8. Denial tuong minh P03 -> deny (explicit_denial) — khac voi opt-out marketing.
"""
import asyncio
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services import consent  # noqa: E402

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
        print("[1] migrations 001..031 fresh apply")
        await migrate(conn)
        check(await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_name='consent_records'") == 1,
            "031: bang consent_records")
        check(await conn.fetchval(
            "SELECT count(*) FROM pg_indexes WHERE indexname='consent_records_rev_uq'") == 1,
            "031: unique revision index")

        cid = await conn.fetchval(
            "INSERT INTO customers (psid, name) VALUES ('m3s3-test-psid', 'K') RETURNING id")

        print("[2] ledger append-only + revision monotonic")
        r1 = await consent.record_consent(conn, customer_id=cid, purpose_code="P06_MARKETING",
                                          status="granted", captured_via="chat_optin",
                                          policy_version=PV, notice_version=NV)
        r2 = await consent.record_consent(conn, customer_id=cid, purpose_code="P06_MARKETING",
                                          status="denied", captured_via="chat_optout",
                                          policy_version=PV, notice_version=NV)
        check(r1["authority_revision"] == 1 and r2["authority_revision"] == 2,
              f"revision monotonic 1->2 (got {r1['authority_revision']},{r2['authority_revision']})")
        try:
            await conn.execute(
                "INSERT INTO consent_records (customer_id, purpose_code, channel, policy_version, "
                "notice_version, status, captured_via, authority_revision) "
                "VALUES ($1,'P06_MARKETING','any',$2,$3,'granted','dup',2)", cid, PV, NV)
            check(False, "duplicate revision should violate unique")
        except asyncpg.UniqueViolationError:
            check(True, "duplicate revision -> UniqueViolation (khong ghi de)")

        print("[3] #1 opt-out marketing KHONG chan transactional")
        d = await consent.check_permission(conn, customer_id=cid, purpose_code="P03_TRANSACTIONAL")
        check(d.decision == "allow" and d.reason_code == "service_default",
              f"P03 allow service_default (got {d.decision}/{d.reason_code})")
        dm = await consent.check_permission(conn, customer_id=cid, purpose_code="P06_MARKETING")
        check(dm.decision == "deny", f"P06 deny sau opt-out (got {dm.decision}/{dm.reason_code})")

        print("[4] #2 rut lifecycle consent chan follow-up")
        await consent.record_consent(conn, customer_id=cid, purpose_code="P05_LIFECYCLE",
                                     status="granted", captured_via="chat_optin",
                                     policy_version=PV, notice_version=NV)
        d5 = await consent.check_permission(conn, customer_id=cid, purpose_code="P05_LIFECYCLE")
        check(d5.decision == "allow" and d5.reason_code == "granted", "P05 granted -> allow")
        await consent.record_consent(conn, customer_id=cid, purpose_code="P05_LIFECYCLE",
                                     status="withdrawn", captured_via="chat_optout",
                                     policy_version=PV, notice_version=NV)
        d5b = await consent.check_permission(conn, customer_id=cid, purpose_code="P05_LIFECYCLE")
        check(d5b.decision == "deny" and d5b.reason_code == "status_withdrawn",
              f"P05 withdraw -> deny (got {d5b.decision}/{d5b.reason_code})")
        wa = await conn.fetchval(
            "SELECT withdrawn_at FROM consent_records WHERE customer_id=$1 AND purpose_code='P05_LIFECYCLE' "
            "ORDER BY authority_revision DESC LIMIT 1", cid)
        check(wa is not None, "withdrawn_at duoc set")

        print("[5] #3 complaint suppress promotion (ke ca granted)")
        cid2 = await conn.fetchval(
            "INSERT INTO customers (psid, name) VALUES ('m3s3-test-psid2', 'K2') RETURNING id")
        await consent.record_consent(conn, customer_id=cid2, purpose_code="P06_MARKETING",
                                     status="granted", captured_via="chat_optin",
                                     policy_version=PV, notice_version=NV)
        g = await consent.check_permission(conn, customer_id=cid2, purpose_code="P06_MARKETING")
        check(g.decision == "allow", "P06 granted -> allow (truoc complaint)")
        await consent.record_complaint(conn, customer_id=cid2, evidence_ref="esc:123",
                                       policy_version=PV, notice_version=NV)
        s = await consent.check_permission(conn, customer_id=cid2, purpose_code="P06_MARKETING")
        check(s.decision == "deny" and s.reason_code == "complaint_suppression",
              f"complaint -> suppress P06 (got {s.decision}/{s.reason_code})")
        st = await consent.check_permission(conn, customer_id=cid2, purpose_code="P03_TRANSACTIONAL")
        check(st.decision == "allow", "complaint KHONG chan transactional")
        await consent.record_consent(conn, customer_id=cid2, purpose_code="P06_MARKETING",
                                     status="granted", captured_via="complaint_resolved",
                                     policy_version=PV, notice_version=NV)
        rs = await consent.check_permission(conn, customer_id=cid2, purpose_code="P06_MARKETING")
        check(rs.decision == "allow", f"complaint_resolved -> het suppress (got {rs.decision}/{rs.reason_code})")

        print("[6] #13 consent version truy xuat duoc")
        v = await consent.consent_versions(conn, customer_id=cid2, purpose_code="P06_MARKETING")
        check(v is not None and v["policy_version"] == PV and v["notice_version"] == NV,
              f"policy/notice version (got {v})")

        print("[7] unavailable fail-closed khi loi ha tang")
        broken = await asyncpg.connect(_db())
        await broken.close()  # conn dong -> query nem exception
        u = await consent.check_permission(broken, customer_id=cid, purpose_code="P06_MARKETING")
        check(u.decision == "unavailable" and u.reason_code == "infrastructure_error",
              f"loi ha tang -> unavailable (got {u.decision}/{u.reason_code})")

        print("[8] denial tuong minh P03 -> deny (khac opt-out marketing)")
        await consent.record_consent(conn, customer_id=cid2, purpose_code="P03_TRANSACTIONAL",
                                     status="denied", captured_via="staff_manual",
                                     policy_version=PV, notice_version=NV)
        d3 = await consent.check_permission(conn, customer_id=cid2, purpose_code="P03_TRANSACTIONAL")
        check(d3.decision == "deny" and d3.reason_code == "explicit_denial",
              f"P03 explicit denial -> deny (got {d3.decision}/{d3.reason_code})")
        check(len({d.decision_ref, dm.decision_ref, d5.decision_ref}) == 3,
              "decision_ref opaque per-decision (audit)")
    finally:
        await conn.close()

    print("\n" + ("ALL PASS" if not _fail else f"FAIL: {_fail}"))
    return 0 if not _fail else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
