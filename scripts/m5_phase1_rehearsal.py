"""M5 Phase 1 — DB rehearsal (synthetic, throwaway Postgres). CA Directive 104.

Chung minh migration 052 + trigger + registry control chay dung tren du lieu GIA LAP:
 - ingest -> gate(pass) -> accept -> activate; active_version = v1.
 - ingest v2 -> gate -> accept -> activate; v1 RETIRED, v2 ACTIVE.
 - rollback ve v1; v2 ROLLED_BACK, v1 ACTIVE.
 - SoD: reviewer==custodian bi tu choi; accepter==reviewer bi tu choi.
 - gate FAIL (orphan) -> accept bi tu choi.
 - Trigger: DELETE dataset bi chan; UPDATE sha256 sau draft bi chan; INSERT unit vao dataset ACTIVE bi chan.

KHONG customer data. Chi chay tren DB throwaway (DATABASE_URL tro toi Postgres tam).
"""
import asyncio
import os
import pathlib

import asyncpg

from app.services.address import acceptance_gate as gate
from app.services.address import dataset_registry as reg

DB = os.environ["DATABASE_URL"].replace("+asyncpg", "")
MIG = pathlib.Path("migrations/052_m5_admin_dataset.sql").read_text(encoding="utf-8")

BOOT = """
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY, actor_type TEXT, actor_ref TEXT, actor_staff_id BIGINT,
  action TEXT, entity_type TEXT, entity_id TEXT, before JSONB, after JSONB, reason TEXT,
  request_id TEXT, correlation_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS permissions (key TEXT PRIMARY KEY, description TEXT);
"""

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {extra}")


def dataset(ver, first=True):
    units = [
        {"level": "province", "code": "P01", "name": "Cà Mau", "parent_code": None},
        {"level": "district", "code": "D01", "name": "Đầm Dơi", "parent_code": "P01"},
        {"level": "ward", "code": "W01", "name": "Tân Duyệt", "parent_code": "D01"},
    ]
    aliases = [{"unit_code": "P01", "alias_name": "Ca Mau", "alias_kind": "accentless"}]
    prov = {"source_url": "https://danhmuchanhchinh.nso.gov.vn/x", "source_kind": "authoritative",
            "downloaded_at": "2025-07-01", "license": "OGL", "first_version": first,
            "expected_counts": {"province": 1, "district": 1, "ward": 1}}
    sha = gate.canonical_checksum(units, aliases)
    return dict(version=ver, source_url=prov["source_url"], source_kind="authoritative",
                license="OGL", sha256=sha, provenance=prov, units=units, aliases=aliases)


async def expect_error(name, coro):
    try:
        await coro
        ok(name, False, "(khong raise)")
    except reg.RegistryError as e:
        ok(name, True, f"({str(e)[:40]}…)")


async def expect_pgerror(name, coro):
    try:
        await coro
        ok(name, False, "(khong raise)")
    except asyncpg.PostgresError as e:
        ok(name, True, f"({str(e)[:40]}…)")


async def main():
    conn = await asyncpg.connect(DB)
    try:
        await conn.execute(BOOT)
        await conn.execute(MIG)
        print("migration 052 applied.")

        AUTH = dict(reason="rehearsal", ticket="M5-REH-1")
        v1 = dataset("VN-ADMIN-2025-07-v1", first=True)

        # lifecycle v1
        await reg.ingest(conn, actor="custodian", apply=True, **v1, **AUTH)
        rep = await reg.run_gate(conn, version=v1["version"], actor="reviewer", **AUTH)
        ok("gate v1 passed", rep["passed"], str([c["check"] for c in rep["checks"] if not c["ok"]]))
        await reg.accept(conn, version=v1["version"], actor="po_owner", apply=True, **AUTH)
        await reg.activate(conn, version=v1["version"], actor="po_owner", apply=True, **AUTH)
        active = await reg.get_active(conn)
        ok("v1 active_version set", active == v1["version"], f"(active={active})")

        # SoD
        await reg.ingest(conn, actor="custodian", apply=True, **dataset("VN-ADMIN-2025-08-v2", first=False), **AUTH)
        await expect_error("SoD reviewer!=custodian",
                           reg.run_gate(conn, version="VN-ADMIN-2025-08-v2", actor="custodian", **AUTH))
        rep2 = await reg.run_gate(conn, version="VN-ADMIN-2025-08-v2", actor="reviewer", **AUTH)
        ok("gate v2 passed", rep2["passed"])
        await expect_error("SoD accepter!=reviewer",
                           reg.accept(conn, version="VN-ADMIN-2025-08-v2", actor="reviewer", apply=True, **AUTH))
        await reg.accept(conn, version="VN-ADMIN-2025-08-v2", actor="po_owner", apply=True, **AUTH)
        await reg.activate(conn, version="VN-ADMIN-2025-08-v2", actor="po_owner", apply=True, **AUTH)
        st_v1 = await conn.fetchval("SELECT status FROM admin_unit_dataset WHERE version='VN-ADMIN-2025-07-v1'")
        active = await reg.get_active(conn)
        ok("v2 active + v1 retired", active == "VN-ADMIN-2025-08-v2" and st_v1 == "retired",
           f"(active={active}, v1={st_v1})")

        # rollback
        await reg.rollback(conn, to_version="VN-ADMIN-2025-07-v1", actor="po_owner", apply=True, **AUTH)
        active = await reg.get_active(conn)
        st_v2 = await conn.fetchval("SELECT status FROM admin_unit_dataset WHERE version='VN-ADMIN-2025-08-v2'")
        ok("rollback -> v1 active, v2 rolled_back", active == "VN-ADMIN-2025-07-v1" and st_v2 == "rolled_back",
           f"(active={active}, v2={st_v2})")

        # gate FAIL -> accept refused
        bad = dataset("VN-ADMIN-2025-09-v3", first=False)
        bad["units"][2]["parent_code"] = "D99"  # orphan ward
        bad["sha256"] = gate.canonical_checksum(bad["units"], bad["aliases"])
        await reg.ingest(conn, actor="custodian", apply=True, **bad, **AUTH)
        repbad = await reg.run_gate(conn, version="VN-ADMIN-2025-09-v3", actor="reviewer", **AUTH)
        ok("gate v3 FAIL (orphan)", not repbad["passed"],
           str([c["check"] for c in repbad["checks"] if not c["ok"]]))
        await expect_error("accept refused when gate failed",
                           reg.accept(conn, version="VN-ADMIN-2025-09-v3", actor="po_owner", apply=True, **AUTH))

        # triggers
        await expect_pgerror("DELETE dataset blocked",
                             conn.execute("DELETE FROM admin_unit_dataset WHERE version='VN-ADMIN-2025-07-v1'"))
        await expect_pgerror("UPDATE sha256 after draft blocked",
                             conn.execute("UPDATE admin_unit_dataset SET sha256=repeat('a',64) "
                                          "WHERE version='VN-ADMIN-2025-07-v1'"))
        await expect_pgerror("INSERT unit into ACTIVE dataset blocked",
                             conn.execute("INSERT INTO admin_unit(dataset_version,level,code,name,name_normalized)"
                                          " VALUES('VN-ADMIN-2025-07-v1','ward','WZZ','x','x')"))

        # audit trail present
        n_audit = await conn.fetchval("SELECT count(*) FROM audit_log WHERE action LIKE 'address.dataset.%'")
        ok("audit trail written", n_audit >= 8, f"(rows={n_audit})")

        print(f"\nSUMMARY: {len(PASS)} pass, {len(FAIL)} fail")
        if FAIL:
            print("FAILED:", FAIL)
            raise SystemExit(1)
    finally:
        await conn.close()


asyncio.run(main())
