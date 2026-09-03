"""M5 — Test deactivate/rollback-to-NULL control (CA G-A-137-05). DB throwaway synthetic.

Positive: first version activate -> deactivate -> active_version NULL, status rolled_back.
Negative: deactivate khi khong active (idempotent double), sai version, SoD deactivator==ingester.
"""
import asyncio
import os
import pathlib

import asyncpg

from app.services.address import acceptance_gate as gate
from app.services.address import dataset_registry as reg

DB = os.environ["DATABASE_URL"].replace("+asyncpg", "")
BOOT = """
CREATE TABLE IF NOT EXISTS audit_log (id BIGSERIAL PRIMARY KEY, actor_type TEXT, actor_ref TEXT,
  actor_staff_id BIGINT, action TEXT, entity_type TEXT, entity_id TEXT, before JSONB, after JSONB, reason TEXT,
  request_id TEXT, correlation_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS permissions (key TEXT PRIMARY KEY, description TEXT);
"""
PASS, FAIL = [], []


def ok(n, c, e=""):
    (PASS if c else FAIL).append(n)
    print(f"  [{'PASS' if c else 'FAIL'}] {n} {e}")


async def err(n, coro, exc=reg.RegistryError):
    try:
        await coro
        ok(n, False, "(khong raise)")
    except exc as e:
        ok(n, True, f"({str(e)[:44]}…)")


async def main():
    conn = await asyncpg.connect(DB)
    try:
        await conn.execute(BOOT)
        await conn.execute(pathlib.Path("migrations/052_m5_admin_dataset.sql").read_text(encoding="utf-8"))
        units = [{"level": "province", "code": "01", "name": "Ha Noi", "parent_code": None},
                 {"level": "ward", "code": "W1", "name": "Ba Dinh", "parent_code": "01"}]
        aliases = []
        prov = {"source_url": "x", "source_kind": "authoritative", "downloaded_at": "2025-07-01",
                "license": "x", "first_version": True, "expected_counts": {"province": 1, "ward": 1}}
        V = "VN-ADMIN-2025-07-v1"
        AU = dict(reason="deactivate test", ticket="T1")
        ING = dict(version=V, source_url="x", source_kind="authoritative", license="x",
                   sha256=gate.canonical_checksum(units, aliases), provenance=prov, units=units, aliases=aliases)
        await reg.ingest(conn, actor="custodian", apply=True, **ING, **AU)
        await reg.run_gate(conn, version=V, actor="staff-1", **AU)
        await reg.accept(conn, version=V, actor="po-hoai", apply=True, **AU)
        await reg.activate(conn, version=V, actor="po-hoai", apply=True, **AU)
        ok("first version active", (await reg.get_active(conn)) == V)

        # negative: SoD deactivator == custodian ingest
        await err("SoD deactivator!=custodian", reg.deactivate(conn, version=V, actor="custodian", apply=True, **AU))
        # negative: sai version
        await err("deactivate wrong version", reg.deactivate(conn, version="VN-ADMIN-2099-01-v1", actor="po-hoai",
                                                             apply=True, **AU))
        # positive
        await reg.deactivate(conn, version=V, actor="po-hoai", apply=True, **AU)
        active = await reg.get_active(conn)
        st = await conn.fetchval("SELECT status FROM admin_unit_dataset WHERE version=$1", V)
        ok("deactivate -> active_version NULL + rolled_back", active is None and st == "rolled_back",
           f"(active={active}, status={st})")
        # idempotent: double deactivate -> reject (khong con active)
        await err("double deactivate rejected (idempotent)", reg.deactivate(conn, version=V, actor="po-hoai",
                                                                            apply=True, **AU))
        n = await conn.fetchval("SELECT count(*) FROM audit_log WHERE action='address.dataset.deactivate'")
        ok("audit address.dataset.deactivate present", n == 1, f"(rows={n})")

        print(f"\nSUMMARY: {len(PASS)} pass, {len(FAIL)} fail")
        if FAIL:
            raise SystemExit(1)
    finally:
        await conn.close()


asyncio.run(main())
