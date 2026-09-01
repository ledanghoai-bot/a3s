"""M5 Phase 2 — DB rehearsal (synthetic, throwaway Postgres). CA Directive 108.

052+053 applied -> seed dataset synthetic qua registry -> activate -> resolve nhieu case:
 - fail-closed khi CHUA co active dataset;
 - current exact -> auto_verified; accentless -> auto;
 - legacy (Minh Hải) -> needs_customer_confirmation; conflict -> needs_staff_review;
 - idempotency (cung key -> cung id);
 - immutable: UPDATE/DELETE address_resolution bi chan;
 - audit address.resolve present.
KHONG customer data that. Chi chay tren DB throwaway.
"""
import asyncio
import os
import pathlib

import asyncpg

from app.services.address import acceptance_gate as gate
from app.services.address import dataset_registry as reg
from app.services.address import resolver

DB = os.environ["DATABASE_URL"].replace("+asyncpg", "")
BOOT = """
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY, actor_type TEXT, actor_ref TEXT, actor_staff_id BIGINT, action TEXT,
  entity_type TEXT, entity_id TEXT, before JSONB, after JSONB, reason TEXT, request_id TEXT,
  correlation_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS permissions (key TEXT PRIMARY KEY, description TEXT);
"""
PASS, FAIL = [], []


def ok(n, c, e=""):
    (PASS if c else FAIL).append(n)
    print(f"  [{'PASS' if c else 'FAIL'}] {n} {e}")


async def expect_error(n, coro, exc):
    try:
        await coro
        ok(n, False, "(khong raise)")
    except exc as e:
        ok(n, True, f"({str(e)[:44]}…)")


def _dataset():
    units = [
        {"level": "province", "code": "P01", "name": "Cà Mau", "parent_code": None},
        {"level": "province", "code": "P02", "name": "Bạc Liêu", "parent_code": None},
        {"level": "district", "code": "D01", "name": "Đầm Dơi", "parent_code": "P01"},
        {"level": "district", "code": "D02", "name": "Hòa Bình", "parent_code": "P02"},
        {"level": "ward", "code": "W01", "name": "Tân Duyệt", "parent_code": "D01"},
    ]
    aliases = [
        {"unit_code": "P01", "alias_name": "Ca Mau", "alias_kind": "accentless"},
        {"unit_code": "P01", "alias_name": "Minh Hải", "alias_kind": "legacy"},
        {"unit_code": "D01", "alias_name": "Dam Doi", "alias_kind": "accentless"},
    ]
    prov = {"source_url": "https://danhmuchanhchinh.nso.gov.vn/x", "source_kind": "authoritative",
            "downloaded_at": "2025-07-01", "license": "OGL", "first_version": True,
            "expected_counts": {"province": 2, "district": 2, "ward": 1}}
    sha = gate.canonical_checksum(units, aliases)
    return dict(version="VN-ADMIN-2025-07-v1", source_url=prov["source_url"], source_kind="authoritative",
                license="OGL", sha256=sha, provenance=prov, units=units, aliases=aliases)


async def main():
    conn = await asyncpg.connect(DB)
    try:
        await conn.execute(BOOT)
        await conn.execute(pathlib.Path("migrations/052_m5_admin_dataset.sql").read_text(encoding="utf-8"))
        await conn.execute(pathlib.Path("migrations/053_m5_address_resolution.sql").read_text(encoding="utf-8"))
        print("migrations 052+053 applied.")
        AUTH = dict(reason="rehearsal", ticket="M5P2-REH")

        # fail-closed truoc khi co active dataset
        await expect_error("fail-closed no active dataset",
                           resolver.resolve(conn, subject_type="adhoc", province="Cà Mau", actor="op", **AUTH),
                           resolver.ResolveError)

        # seed + activate dataset
        d = _dataset()
        await reg.ingest(conn, actor="custodian", apply=True, **d, **AUTH)
        rep = await reg.run_gate(conn, version=d["version"], actor="reviewer", **AUTH)
        ok("gate passed", rep["passed"], str([c["check"] for c in rep["checks"] if not c["ok"]]))
        await reg.accept(conn, version=d["version"], actor="po", apply=True, **AUTH)
        await reg.activate(conn, version=d["version"], actor="po", apply=True, **AUTH)

        r1 = await resolver.resolve(conn, subject_type="adhoc", province="Cà Mau", district="Đầm Dơi",
                                    ward="Tân Duyệt", actor="op", **AUTH)
        ok("current exact -> auto_verified", r1["status"] == "auto_verified" and r1["ward_code"] == "W01",
           f"({r1['status']},{r1['confidence']})")
        r2 = await resolver.resolve(conn, subject_type="adhoc", province="Ca Mau", actor="op", **AUTH)
        ok("accentless -> auto", r2["status"] == "auto_verified" and r2["province_code"] == "P01")
        r3 = await resolver.resolve(conn, subject_type="adhoc", province="Minh Hải", actor="op", **AUTH)
        ok("legacy -> needs_customer_confirmation",
           r3["status"] == "needs_customer_confirmation" and r3["method"] == "legacy_mapping",
           f"({r3['status']},{r3['confidence']})")
        r4 = await resolver.resolve(conn, subject_type="adhoc", province="Cà Mau", district="Hòa Bình",
                                    actor="op", **AUTH)
        ok("conflict -> needs_staff_review", r4["status"] == "needs_staff_review",
           str(r4["rules_applied"]))

        # idempotency
        k = "IDEMP-1"
        a1 = await resolver.resolve(conn, subject_type="adhoc", province="Cà Mau", actor="op",
                                    idempotency_key=k, **AUTH)
        a2 = await resolver.resolve(conn, subject_type="adhoc", province="Cà Mau", actor="op",
                                    idempotency_key=k, **AUTH)
        ok("idempotency same id", a1["id"] == a2["id"])

        # immutability
        await expect_error("UPDATE resolution blocked",
                           conn.execute("UPDATE address_resolution SET status='failed' WHERE id=$1::uuid",
                                        r1["id"]), asyncpg.PostgresError)
        await expect_error("DELETE resolution blocked",
                           conn.execute("DELETE FROM address_resolution WHERE id=$1::uuid", r1["id"]),
                           asyncpg.PostgresError)

        n = await conn.fetchval("SELECT count(*) FROM audit_log WHERE action='address.resolve'")
        ok("audit address.resolve present", n >= 5, f"(rows={n})")

        print(f"\nSUMMARY: {len(PASS)} pass, {len(FAIL)} fail")
        if FAIL:
            print("FAILED:", FAIL)
            raise SystemExit(1)
    finally:
        await conn.close()


asyncio.run(main())
