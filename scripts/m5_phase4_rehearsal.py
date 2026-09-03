"""M5 Phase 4 — DB rehearsal (synthetic, throwaway Postgres). CA Directive 116.

052..055 applied -> dataset active -> verified resolution -> bind order snapshot + quote contract:
 quote(None) tu choi; quote(verified) shadow ok; bind happy + snapshot; idempotent; conflict (resolution khac);
 wrong-customer tu choi; unverified tu choi; stale (dataset rolled_back) tu choi; snapshot UPDATE/DELETE chan;
 dataset version preservation (activate v2 -> snapshot van v1); change_log append + immutable; retention_due; audit.
KHONG customer data that.
"""
import asyncio
import os
import pathlib

import asyncpg

from app.services.address import acceptance_gate as gate
from app.services.address import dataset_registry as reg
from app.services.address import order_binding as ob
from app.services.address import resolver

DB = os.environ["DATABASE_URL"].replace("+asyncpg", "")
BOOT = """
CREATE TABLE IF NOT EXISTS audit_log (id BIGSERIAL PRIMARY KEY, actor_type TEXT, actor_ref TEXT,
  actor_staff_id BIGINT, action TEXT, entity_type TEXT, entity_id TEXT, before JSONB, after JSONB, reason TEXT,
  request_id TEXT, correlation_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS permissions (key TEXT PRIMARY KEY, description TEXT);
CREATE TABLE IF NOT EXISTS customers (id BIGSERIAL PRIMARY KEY, address TEXT);
CREATE TABLE IF NOT EXISTS orders (id BIGSERIAL PRIMARY KEY, customer_id BIGINT, shipping_address TEXT);
INSERT INTO customers (address) VALUES ('freetext') ON CONFLICT DO NOTHING;
INSERT INTO orders (customer_id) SELECT 1 FROM generate_series(1,5);
"""
PASS, FAIL = [], []


def ok(n, c, e=""):
    (PASS if c else FAIL).append(n)
    print(f"  [{'PASS' if c else 'FAIL'}] {n} {e}")


async def err(n, coro, exc=Exception):
    try:
        await coro
        ok(n, False, "(khong raise)")
    except exc as e:
        ok(n, True, f"({str(e)[:40]}…)")


def _ds(ver, first=True):
    units = [
        {"level": "province", "code": "P01", "name": "Cà Mau", "parent_code": None},
        {"level": "province", "code": "P02", "name": "Bạc Liêu", "parent_code": None},
        {"level": "district", "code": "D01", "name": "Đầm Dơi", "parent_code": "P01"},
        {"level": "district", "code": "D02", "name": "Hòa Bình", "parent_code": "P02"},
        {"level": "ward", "code": "W01", "name": "Tân Duyệt", "parent_code": "D01"},
    ]
    aliases = [{"unit_code": "P01", "alias_name": "Minh Hải", "alias_kind": "legacy"}]
    prov = {"source_url": "https://danhmuchanhchinh.nso.gov.vn/x", "source_kind": "authoritative",
            "downloaded_at": "2025-07-01", "license": "OGL", "first_version": first,
            "expected_counts": {"province": 2, "district": 2, "ward": 1}}
    return dict(version=ver, source_url=prov["source_url"], source_kind="authoritative", license="OGL",
                sha256=gate.canonical_checksum(units, aliases), provenance=prov, units=units, aliases=aliases)


async def main():
    conn = await asyncpg.connect(DB)
    try:
        await conn.execute(BOOT)
        for m in ("052_m5_admin_dataset.sql", "053_m5_address_resolution.sql",
                  "054_m5_confirmation_queue.sql", "055_m5_order_snapshot_wiring.sql"):
            await conn.execute(pathlib.Path(f"migrations/{m}").read_text(encoding="utf-8"))
        print("migrations 052..055 applied.")
        AUTH = dict(reason="reh", ticket="M5P4")

        d = _ds("VN-ADMIN-2025-07-v1", first=True)
        await reg.ingest(conn, actor="cust", apply=True, **d, **AUTH)
        await reg.run_gate(conn, version=d["version"], actor="rev", **AUTH)
        await reg.accept(conn, version=d["version"], actor="po", apply=True, **AUTH)
        await reg.activate(conn, version=d["version"], actor="po", apply=True, **AUTH)

        # verified resolution (auto) cho customer C1
        R = await resolver.resolve(conn, subject_type="customer", subject_id="C1", province="Cà Mau",
                                   district="Đầm Dơi", ward="Tân Duyệt", actor="op", **AUTH)
        ok("resolution auto_verified", R["status"] == "auto_verified")
        R2 = await resolver.resolve(conn, subject_type="customer", subject_id="C1", province="Bạc Liêu",
                                    actor="op", **AUTH)
        U = await resolver.resolve(conn, subject_type="customer", subject_id="C1", province="Cà Mau",
                                   district="Hòa Bình", actor="op", **AUTH)  # conflict -> needs_staff_review

        # quote contract
        await err("quote reject unverified/free-text",
                  ob.quote_shipping(conn, verified_address_id=None), ob.BindingError)
        q = await ob.quote_shipping(conn, verified_address_id=R["id"])
        ok("quote verified -> shadow", q["ok"] and q["mode"] == "shadow")

        # bind happy
        b = await ob.bind_order(conn, order_id=1, resolution_id=R["id"], actor="staff",
                                expected_customer_ref="C1", apply=True, **AUTH)
        ovid = await conn.fetchval("SELECT verified_address_id FROM orders WHERE id=1")
        ok("bind order -> snapshot + order.verified_address_id", b["order_id"] == 1 and str(ovid) == R["id"])
        # idempotent
        b2 = await ob.bind_order(conn, order_id=1, resolution_id=R["id"], actor="staff",
                                 expected_customer_ref="C1", apply=True, **AUTH)
        ok("bind idempotent", b2["id"] == b["id"])
        # conflict different resolution
        await err("bind conflict (resolution khac)",
                  ob.bind_order(conn, order_id=1, resolution_id=R2["id"], actor="staff", apply=True, **AUTH),
                  ob.BindingError)
        # wrong customer
        await err("wrong-customer binding rejected",
                  ob.bind_order(conn, order_id=2, resolution_id=R["id"], actor="staff",
                                expected_customer_ref="C999", apply=True, **AUTH), ob.BindingError)
        # unverified
        await err("unverified rejected",
                  ob.bind_order(conn, order_id=3, resolution_id=U["id"], actor="staff", apply=True, **AUTH),
                  ob.BindingError)
        # stale (dataset rolled_back)
        await conn.execute("UPDATE admin_unit_dataset SET status='rolled_back' WHERE version=$1", d["version"])
        await err("stale dataset rejected",
                  ob.bind_order(conn, order_id=4, resolution_id=R["id"], actor="staff", apply=True, **AUTH),
                  ob.BindingError)
        await conn.execute("UPDATE admin_unit_dataset SET status='active' WHERE version=$1", d["version"])

        # snapshot immutability
        await err("snapshot UPDATE blocked",
                  conn.execute("UPDATE order_address_snapshot SET street_text='x' WHERE order_id=1"),
                  asyncpg.PostgresError)
        await err("snapshot DELETE blocked",
                  conn.execute("DELETE FROM order_address_snapshot WHERE order_id=1"), asyncpg.PostgresError)

        # dataset version preservation: activate v2 -> snapshot van giu v1
        d2 = _ds("VN-ADMIN-2025-08-v2", first=False)
        await reg.ingest(conn, actor="cust", apply=True, **d2, **AUTH)
        await reg.run_gate(conn, version=d2["version"], actor="rev", **AUTH)
        await reg.accept(conn, version=d2["version"], actor="po", apply=True, **AUTH)
        await reg.activate(conn, version=d2["version"], actor="po", apply=True, **AUTH)
        snap_ver = await conn.fetchval("SELECT dataset_version FROM order_address_snapshot WHERE order_id=1")
        ok("dataset version preserved in snapshot", snap_ver == "VN-ADMIN-2025-07-v1", f"({snap_ver})")

        # change_log append + immutable
        clid = await ob.log_address_change(conn, customer_ref="C1", old_value="a", new_value="b", actor="staff",
                                           **AUTH)
        await err("change_log UPDATE blocked",
                  conn.execute("UPDATE address_change_log SET new_value='z' WHERE id=$1::uuid", clid),
                  asyncpg.PostgresError)
        rc = await ob.retention_due(conn, days=400)
        ok("retention_due read-only", rc == 0, f"(count={rc})")

        n = await conn.fetchval("SELECT count(*) FROM audit_log WHERE action='address.bind'")
        ok("audit address.bind present", n >= 1, f"(rows={n})")

        print(f"\nSUMMARY: {len(PASS)} pass, {len(FAIL)} fail")
        if FAIL:
            print("FAILED:", FAIL)
            raise SystemExit(1)
    finally:
        await conn.close()


asyncio.run(main())
