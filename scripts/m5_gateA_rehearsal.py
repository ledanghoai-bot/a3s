"""M5 Gate A — Staging rehearsal (throwaway DB, isolated). CA Directive 135.

Chay TREN DB throwaway TACH production. Load dataset THAT (562be789/836b07ab) chi de exercise lifecycle controls.
Sequence: isolation preflight -> ingest(custodian) -> gate(staff-1) -> accept(po-hoai) -> activate -> verify
(34/3321/10560, 2404 collisions, topology 2-tier, audit) -> negatives/SoD -> rollback -> cleanup.
KHONG production write. Actors la CLI string cho rehearsal; production path dung session-derived (runbook).
"""
import asyncio
import hashlib
import json
import os
import pathlib

import asyncpg

from app.services.address import acceptance_gate as gate
from app.services.address import dataset_registry as reg

DB = os.environ["DATABASE_URL"].replace("+asyncpg", "")
DATASET = os.environ.get("DATASET", "/data/dataset_VN-ADMIN-2025-07-v2.json")
LOCK_ARTIFACT = "6f0f4781a23617c106e110ad9251d09e702a4a4f2eb193a3dd988264baca5ae5"
LOCK_CANONICAL = "dc505a2425b0552ccee57230d4f953faacb702c36f62445048f1a42dbafb2cde"
BOOT = """
CREATE TABLE IF NOT EXISTS audit_log (id BIGSERIAL PRIMARY KEY, actor_type TEXT, actor_ref TEXT,
  actor_staff_id BIGINT, action TEXT, entity_type TEXT, entity_id TEXT, before JSONB, after JSONB, reason TEXT,
  request_id TEXT, correlation_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS permissions (key TEXT PRIMARY KEY, description TEXT);
"""
PASS, FAIL, FIND = [], [], []


def ok(n, c, e=""):
    (PASS if c else FAIL).append(n)
    print(f"  [{'PASS' if c else 'FAIL'}] {n} {e}")


async def err(n, coro, exc=Exception):
    try:
        await coro
        ok(n, False, "(khong raise)")
    except exc as e:
        ok(n, True, f"({str(e)[:44]}…)")


def load():
    raw = pathlib.Path(DATASET).read_bytes()
    art = hashlib.sha256(raw).hexdigest()
    d = json.loads(raw)
    canon = gate.canonical_checksum(d["units"], d["aliases"])
    return d, art, canon


async def main():
    d, art, canon = load()
    print("=== ISOLATION / HASH PREFLIGHT ===")
    ok("artifact_file_sha256 khop lock 562be789", art == LOCK_ARTIFACT, art[:16])
    ok("canonical recompute khop lock 836b07ab", canon == LOCK_CANONICAL and d["sha256"] == LOCK_CANONICAL, canon[:16])
    print(f"  target DB = {DB.split('@')[-1]}  (throwaway; KHONG production)")

    conn = await asyncpg.connect(DB)
    try:
        # zero-row + schema baseline
        await conn.execute(BOOT)
        # Gate A lifecycle chi dung migration 052 (dataset registry) — baseline dung pham vi.
        # 053-055 (resolution/confirmation/order) khong duoc exercise o Gate A.
        await conn.execute(pathlib.Path("migrations/052_m5_admin_dataset.sql").read_text(encoding="utf-8"))
        n0 = await conn.fetchval("SELECT count(*) FROM admin_unit_dataset")
        ok("target start zero M5 rows", n0 == 0)
        AU = dict(reason="Gate A rehearsal", ticket="M5-GATEA-REH")
        V = d["version"]
        ING = dict(version=V, source_url=d["source_url"], source_kind=d["source_kind"], license=d["license"],
                   sha256=d["sha256"], provenance=d["provenance"], units=d["units"], aliases=d["aliases"])

        print("=== LIFECYCLE (custodian -> staff-1 -> po-hoai) ===")
        await reg.ingest(conn, actor="custodian", apply=True, **ING, **AU)
        nu = await conn.fetchval("SELECT count(*) FROM admin_unit WHERE dataset_version=$1", V)
        na = await conn.fetchval("SELECT count(*) FROM admin_unit_alias WHERE dataset_version=$1", V)
        np = await conn.fetchval("SELECT count(*) FROM admin_unit WHERE dataset_version=$1 AND level='province'", V)
        nw = await conn.fetchval("SELECT count(*) FROM admin_unit WHERE dataset_version=$1 AND level='ward'", V)
        ok("ingest draft counts 3355/34/3321/10560", nu == 3355 and np == 34 and nw == 3321 and na == 10560,
           f"(units={nu} prov={np} ward={nw} alias={na})")
        # SoD: reviewer != ingester
        await err("SoD reviewer!=custodian", reg.run_gate(conn, version=V, actor="custodian", **AU),
                  reg.RegistryError)
        rep = await reg.run_gate(conn, version=V, actor="staff-1", **AU)
        ok("gate(staff-1) 8/8 topology=2-tier collisions=2404",
           rep["passed"] and rep["topology"] == "2-tier" and rep["legacy_name_collisions"]["count"] == 2404,
           f"(passed={rep['passed']} topo={rep['topology']} coll={rep['legacy_name_collisions']['count']})")
        # SoD: accepter != ingester / reviewer
        await err("SoD accepter!=custodian", reg.accept(conn, version=V, actor="custodian", apply=True, **AU),
                  reg.RegistryError)
        await err("SoD accepter!=reviewer(staff-1)", reg.accept(conn, version=V, actor="staff-1", apply=True, **AU),
                  reg.RegistryError)
        await reg.accept(conn, version=V, actor="po-hoai", apply=True, **AU)
        await reg.activate(conn, version=V, actor="po-hoai", apply=True, **AU)
        active = await reg.get_active(conn)
        ok("activate -> one ACTIVE = version", active == V, f"(active={active})")
        nact = await conn.fetchval("SELECT count(*) FROM admin_unit_dataset WHERE status='active'")
        ok("exactly one ACTIVE", nact == 1, f"(active_count={nact})")
        na_audit = await conn.fetchval(
            "SELECT count(DISTINCT action) FROM audit_log WHERE action IN "
            "('address.dataset.ingest','address.dataset.review','address.dataset.accept','address.dataset.activate')")
        ok("audit 4 lifecycle actions", na_audit == 4, f"(distinct={na_audit})")

        print("=== NEGATIVE / SoD / fail-closed ===")
        await err("duplicate activation blocked", reg.activate(conn, version=V, actor="po-hoai", apply=True, **AU),
                  reg.RegistryError)
        # wrong hash -> gate checksum fail
        await reg.ingest(conn, actor="custodian", apply=True, version="VN-ADMIN-2099-01-v1",
                         source_url=d["source_url"], source_kind="authoritative", license=d["license"],
                         sha256="0" * 64, provenance={**d["provenance"], "first_version": False},
                         units=d["units"][:3], aliases=[], **AU)
        rbad = await reg.run_gate(conn, version="VN-ADMIN-2099-01-v1", actor="staff-1", **AU)
        ok("wrong-hash -> gate checksum FAIL",
           not rbad["passed"] and not next(c for c in rbad["checks"] if c["check"] == "checksum")["ok"])
        # gate failure (orphan) -> accept rejected
        bad_units = [{"level": "province", "code": "P9", "name": "X", "parent_code": None},
                     {"level": "ward", "code": "W9", "name": "Y", "parent_code": "NOPE"}]
        await reg.ingest(conn, actor="custodian", apply=True, version="VN-ADMIN-2099-02-v1",
                         source_url=d["source_url"], source_kind="authoritative", license=d["license"],
                         sha256=gate.canonical_checksum(bad_units, []),
                         provenance={"source_url": "x", "source_kind": "authoritative", "downloaded_at": "2025-07-01",
                                     "license": "x", "first_version": False, "expected_counts": {"province": 1, "ward": 1}},
                         units=bad_units, aliases=[], **AU)
        await reg.run_gate(conn, version="VN-ADMIN-2099-02-v1", actor="staff-1", **AU)
        await err("gate-failed dataset -> accept refused",
                  reg.accept(conn, version="VN-ADMIN-2099-02-v1", actor="po-hoai", apply=True, **AU),
                  reg.RegistryError)
        # idempotency: re-ingest same version rejected
        await err("re-ingest same version rejected",
                  reg.ingest(conn, actor="custodian", apply=True, **ING, **AU), reg.RegistryError)

        print("=== ROLLBACK ===")
        # normal rollback: v2 activate then rollback to v1
        d2 = dict(ING); d2["version"] = "VN-ADMIN-2025-07-v2"
        d2["provenance"] = {**d["provenance"], "first_version": False}
        await reg.ingest(conn, actor="custodian", apply=True, **d2, **AU)
        await reg.run_gate(conn, version="VN-ADMIN-2025-07-v2", actor="staff-1", **AU)
        await reg.accept(conn, version="VN-ADMIN-2025-07-v2", actor="po-hoai", apply=True, **AU)
        await reg.activate(conn, version="VN-ADMIN-2025-07-v2", actor="po-hoai", apply=True, **AU)
        st_v1 = await conn.fetchval("SELECT status FROM admin_unit_dataset WHERE version=$1", V)
        ok("v2 active + v1 retired", (await reg.get_active(conn)) == "VN-ADMIN-2025-07-v2" and st_v1 == "retired")
        await reg.rollback(conn, to_version=V, actor="po-hoai", apply=True, **AU)
        ok("rollback v2->v1 (active=v1, v2 rolled_back)",
           (await reg.get_active(conn)) == V
           and (await conn.fetchval("SELECT status FROM admin_unit_dataset WHERE version='VN-ADMIN-2025-07-v2'")) == "rolled_back")
        # FIRST-VERSION deactivate to NULL: kiem tra control co ho tro khong
        try:
            await reg.rollback(conn, to_version=None, actor="po-hoai", apply=True, **AU)
            still = await reg.get_active(conn)
            if still is None:
                ok("first-version rollback -> active_version NULL", True)
            else:
                ok("first-version rollback -> active_version NULL", False, f"(active={still})")
        except Exception as e:  # noqa: BLE001
            FIND.append("G-A-135-01: control deployed KHONG co deactivate/rollback-to-NULL cho first version "
                        f"(reg.rollback yeu cau to_version ton tai). Chi tiet: {str(e)[:60]}")
            print("  [FINDING] first-version deactivate-to-NULL: control deployed chua ho tro -> G-A-135-01")

        print(f"\nSUMMARY: {len(PASS)} pass, {len(FAIL)} fail, {len(FIND)} finding")
        for f in FIND:
            print("  FINDING:", f)
        if FAIL:
            print("FAILED:", FAIL)
            raise SystemExit(1)
    finally:
        await conn.close()


asyncio.run(main())
