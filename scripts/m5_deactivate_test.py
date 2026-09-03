"""M5 — Test deactivate/rollback-to-NULL control (CA G-A-137-05 + corrections 138-01/02/03). DB throwaway.

Cover: positive first-version->NULL; replay-safe REJECT (khong idempotent-success); SoD deactivator!=custodian;
wrong/non-existent version; dry-run (khong mutate); thieu reason/ticket; stale-deactivate rejected;
CONCURRENCY (deactivate vs activate song song -> KHONG torn state); audit-readiness fail-closed.
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
        ok(n, True, f"({str(e)[:40]}…)")


def _units():
    return [{"level": "province", "code": "01", "name": "Ha Noi", "parent_code": None},
            {"level": "ward", "code": "W1", "name": "Ba Dinh", "parent_code": "01"}]


def _ing(version):
    u = _units()
    prov = {"source_url": "x", "source_kind": "authoritative", "downloaded_at": "2025-07-01",
            "license": "x", "first_version": True, "expected_counts": {"province": 1, "ward": 1}}
    return dict(version=version, source_url="x", source_kind="authoritative", license="x",
                sha256=gate.canonical_checksum(u, []), provenance=prov, units=u, aliases=[])


async def _seed_active(conn, version, ingester="custodian"):
    AU = dict(reason="t", ticket="T")
    await reg.ingest(conn, actor=ingester, apply=True, **_ing(version), **AU)
    await reg.run_gate(conn, version=version, actor="staff-1", **AU)
    await reg.accept(conn, version=version, actor="po-hoai", apply=True, **AU)
    await reg.activate(conn, version=version, actor="po-hoai", apply=True, **AU)


async def main():
    conn = await asyncpg.connect(DB)
    try:
        await conn.execute(BOOT)
        await conn.execute(pathlib.Path("migrations/052_m5_admin_dataset.sql").read_text(encoding="utf-8"))
        AU = dict(reason="deactivate test", ticket="T1")
        V = "VN-ADMIN-2025-07-v1"
        await _seed_active(conn, V)
        ok("first version active", (await reg.get_active(conn)) == V)

        # dry-run: khong mutate
        pl = await reg.deactivate(conn, version=V, actor="po-hoai", apply=False, **AU)
        ok("dry-run khong mutate", pl.get("dry_run") and (await reg.get_active(conn)) == V)
        # thieu reason/ticket
        await err("thieu reason -> reject", reg.deactivate(conn, version=V, actor="po-hoai", reason="", ticket="T"))
        await err("thieu ticket -> reject", reg.deactivate(conn, version=V, actor="po-hoai", reason="r", ticket=""))
        # SoD + wrong version
        await err("SoD deactivator!=custodian", reg.deactivate(conn, version=V, actor="custodian", apply=True, **AU))
        await err("wrong version", reg.deactivate(conn, version="VN-ADMIN-2099-01-v1", actor="po-hoai",
                                                  apply=True, **AU))
        # positive
        await reg.deactivate(conn, version=V, actor="po-hoai", apply=True, **AU)
        ok("deactivate -> active NULL + rolled_back",
           (await reg.get_active(conn)) is None
           and (await conn.fetchval("SELECT status FROM admin_unit_dataset WHERE version=$1", V)) == "rolled_back")
        # replay-safe reject
        await err("replay-safe reject (double)", reg.deactivate(conn, version=V, actor="po-hoai", apply=True, **AU))
        ok("audit deactivate = 1", (await conn.fetchval(
            "SELECT count(*) FROM audit_log WHERE action='address.dataset.deactivate'")) == 1)

        # stale-deactivate: activate v2 over v1(moi), deactivate(v1) rejected (version label khac, khong reset)
        au = dict(reason="t", ticket="T")
        await _seed_active(conn, "VN-ADMIN-2025-08-v1")  # active (v1 cu da rolled_back, ton tai song song)
        d2 = _ing("VN-ADMIN-2025-08-v2")
        d2["provenance"] = {**d2["provenance"], "first_version": False}
        await reg.ingest(conn, actor="custodian", apply=True, **d2, **au)
        await reg.run_gate(conn, version="VN-ADMIN-2025-08-v2", actor="staff-1", **au)
        await reg.accept(conn, version="VN-ADMIN-2025-08-v2", actor="po-hoai", apply=True, **au)
        await reg.activate(conn, version="VN-ADMIN-2025-08-v2", actor="po-hoai", apply=True, **au)
        await err("stale deactivate(v1 retired) rejected — khong clear v2",
                  reg.deactivate(conn, version="VN-ADMIN-2025-08-v1", actor="po-hoai", apply=True, **au))
        ok("v2 van active sau stale deactivate", (await reg.get_active(conn)) == "VN-ADMIN-2025-08-v2")

        # CONCURRENCY: deactivate(active) vs activate(v-next) song song -> khong torn state
        await _seed_active(conn, "VN-ADMIN-2025-09-v1")
        dn = _ing("VN-ADMIN-2025-09-v2")
        dn["provenance"] = {**dn["provenance"], "first_version": False}
        await reg.ingest(conn, actor="custodian", apply=True, **dn, **au)
        await reg.run_gate(conn, version="VN-ADMIN-2025-09-v2", actor="staff-1", **au)
        await reg.accept(conn, version="VN-ADMIN-2025-09-v2", actor="po-hoai", apply=True, **au)
        cA = await asyncpg.connect(DB)
        cB = await asyncpg.connect(DB)
        try:
            res = await asyncio.gather(
                reg.deactivate(cA, version="VN-ADMIN-2025-09-v1", actor="po-hoai", apply=True, **au),
                reg.activate(cB, version="VN-ADMIN-2025-09-v2", actor="po-hoai", apply=True, **au),
                return_exceptions=True)
        finally:
            await cA.close()
            await cB.close()
        active = await reg.get_active(conn)
        act_rows = [r["version"] for r in
                    await conn.fetch("SELECT version FROM admin_unit_dataset WHERE status='active'")]
        deact_res, act_res = res  # deactivate(v1), activate(v2)
        # CA Review 139/141: siet — EXPECTED final active = v2 (activate luon apply duoc trong ca 2 thu tu);
        # phan loai tung ket qua; loai truong hop "ca hai fail, v1 con active".
        deact_ok = isinstance(deact_res, dict) and deact_res.get("applied")
        deact_rejected = isinstance(deact_res, reg.RegistryError)
        act_ok = isinstance(act_res, dict) and act_res.get("applied")
        # dung 1 trong 2 kich ban hop le:
        #  A) deactivate truoc (NULL) roi activate v2 -> deact_ok & act_ok
        #  B) activate v2 truoc (v1 retired) roi deactivate(v1) bi tu choi -> deact_rejected & act_ok
        classified = (deact_ok and act_ok) or (deact_rejected and act_ok)
        v1_not_active = "VN-ADMIN-2025-09-v1" not in act_rows
        expected_final = (active == "VN-ADMIN-2025-09-v2" and act_rows == ["VN-ADMIN-2025-09-v2"])
        ok("concurrency: EXPECTED final active=v2 + classified + v1 khong active + no-torn",
           classified and v1_not_active and expected_final and act_ok,
           f"(active={active}, active_rows={act_rows}, deact={type(deact_res).__name__}"
           f"/{'ok' if deact_ok else 'reject' if deact_rejected else '?'}, act={'ok' if act_ok else '?'})")

        print(f"\nSUMMARY: {len(PASS)} pass, {len(FAIL)} fail")
        if FAIL:
            print("FAILED:", FAIL)
            raise SystemExit(1)
    finally:
        await conn.close()


asyncio.run(main())
