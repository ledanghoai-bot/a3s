"""M5 Phase 3 — DB rehearsal (synthetic, throwaway Postgres). CA Directive 112.

052+053+054 applied -> seed+activate dataset -> tao resolution needs_customer_confirmation / needs_staff_review
-> chay confirmation + review queue voi cac case bat buoc:
 confirmation: issue -> respond happy (customer_confirmed); replay (respond lai -> loi); stale code -> loi;
   binding mismatch -> loi; expiry -> loi; duplicate/idempotent issue.
 review queue: enqueue -> assign -> resolve happy (staff_confirmed); override no approver -> loi;
   self-approval -> loi; stale code -> loi; replay resolve -> loi.
 immutability: UPDATE candidate_snapshot / DELETE bi chan (ca hai bang).
KHONG customer data that. Chi throwaway DB.
"""
import asyncio
import os
import pathlib

import asyncpg

from app.services.address import acceptance_gate as gate
from app.services.address import confirmation as conf
from app.services.address import dataset_registry as reg
from app.services.address import resolver
from app.services.address import review_queue as rq

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


async def err(n, coro, exc=Exception):
    try:
        await coro
        ok(n, False, "(khong raise)")
    except exc as e:
        ok(n, True, f"({str(e)[:40]}…)")


def _seed():
    units = [
        {"level": "province", "code": "P01", "name": "Cà Mau", "parent_code": None},
        {"level": "province", "code": "P02", "name": "Bạc Liêu", "parent_code": None},
        {"level": "district", "code": "D01", "name": "Đầm Dơi", "parent_code": "P01"},
        {"level": "district", "code": "D02", "name": "Hòa Bình", "parent_code": "P02"},
        {"level": "ward", "code": "W01", "name": "Tân Duyệt", "parent_code": "D01"},
    ]
    aliases = [{"unit_code": "P01", "alias_name": "Minh Hải", "alias_kind": "legacy"}]
    prov = {"source_url": "https://danhmuchanhchinh.nso.gov.vn/x", "source_kind": "authoritative",
            "downloaded_at": "2025-07-01", "license": "OGL", "first_version": True,
            "expected_counts": {"province": 2, "district": 2, "ward": 1}}
    return dict(version="VN-ADMIN-2025-07-v1", source_url=prov["source_url"], source_kind="authoritative",
                license="OGL", sha256=gate.canonical_checksum(units, aliases), provenance=prov,
                units=units, aliases=aliases)


async def main():
    conn = await asyncpg.connect(DB)
    try:
        await conn.execute(BOOT)
        for mig in ("052_m5_admin_dataset.sql", "053_m5_address_resolution.sql", "054_m5_confirmation_queue.sql"):
            await conn.execute(pathlib.Path(f"migrations/{mig}").read_text(encoding="utf-8"))
        print("migrations 052+053+054 applied.")
        AUTH = dict(reason="reh", ticket="M5P3")

        d = _seed()
        await reg.ingest(conn, actor="cust", apply=True, **d, **AUTH)
        await reg.run_gate(conn, version=d["version"], actor="rev", **AUTH)
        await reg.accept(conn, version=d["version"], actor="po", apply=True, **AUTH)
        await reg.activate(conn, version=d["version"], actor="po", apply=True, **AUTH)

        # resolution needs_customer_confirmation (legacy)
        rc = await resolver.resolve(conn, subject_type="adhoc", province="Minh Hải", actor="op", **AUTH)
        ok("resolution legacy -> needs_customer_confirmation", rc["status"] == "needs_customer_confirmation")
        # resolution needs_staff_review (conflict)
        rs = await resolver.resolve(conn, subject_type="adhoc", province="Cà Mau", district="Hòa Bình",
                                    actor="op", **AUTH)
        ok("resolution conflict -> needs_staff_review", rs["status"] == "needs_staff_review")

        # ---- confirmation ----
        cr = await conf.issue(conn, resolution_id=rc["id"], channel="web", bound_ref="cust-sess-1",
                              expiry_minutes=60, actor="staff", **AUTH)
        ok("issue confirmation", cr["state"] == "issued")
        await err("respond binding mismatch",
                  conf.respond(conn, request_id=cr["id"], chosen_code="P01", responder_ref="attacker"),
                  conf.ConfirmationError)
        await err("respond stale code",
                  conf.respond(conn, request_id=cr["id"], chosen_code="ZZZ", responder_ref="cust-sess-1"),
                  conf.ConfirmationError)
        done = await conf.respond(conn, request_id=cr["id"], chosen_code="P01", responder_ref="cust-sess-1")
        ok("respond happy -> confirmed", done["state"] == "confirmed" and done["result_resolution_id"])
        newstatus = await conn.fetchval("SELECT status FROM address_resolution WHERE id=$1::uuid",
                                        done["result_resolution_id"])
        ok("result resolution customer_confirmed", newstatus == "customer_confirmed")
        await err("respond replay blocked",
                  conf.respond(conn, request_id=cr["id"], chosen_code="P01", responder_ref="cust-sess-1"),
                  conf.ConfirmationError)
        # idempotent issue
        i1 = await conf.issue(conn, resolution_id=rc["id"], channel="web", bound_ref="c2", expiry_minutes=60,
                              actor="staff", idempotency_key="K1", **AUTH)
        i2 = await conf.issue(conn, resolution_id=rc["id"], channel="web", bound_ref="c2", expiry_minutes=60,
                              actor="staff", idempotency_key="K1", **AUTH)
        ok("issue idempotent", i1["id"] == i2["id"])
        # expiry
        exp = await conf.issue(conn, resolution_id=rc["id"], channel="web", bound_ref="c3", expiry_minutes=60,
                               actor="staff", idempotency_key="K2", **AUTH)
        await conn.execute("UPDATE address_confirmation_request SET expiry=now()-interval '1 min' WHERE id=$1::uuid",
                           exp["id"])
        await err("respond expired blocked",
                  conf.respond(conn, request_id=exp["id"], chosen_code="P01", responder_ref="c3"),
                  conf.ConfirmationError)

        # ---- review queue ----
        q = await rq.enqueue(conn, resolution_id=rs["id"], actor="staff", **AUTH)
        ok("enqueue staff review", q["state"] == "open")
        await rq.assign(conn, queue_id=q["id"], assignee="staffA", actor="staff")
        await err("override no approver",
                  rq.resolve(conn, queue_id=q["id"], chosen_code="P01", actor="staffA", is_override=True,
                             **AUTH), rq.ReviewQueueError)
        await err("self-approval blocked",
                  rq.resolve(conn, queue_id=q["id"], chosen_code="P01", actor="staffA", is_override=True,
                             approver="staffA", **AUTH), rq.ReviewQueueError)
        await err("stale code blocked",
                  rq.resolve(conn, queue_id=q["id"], chosen_code="ZZZ", actor="staffA", **AUTH),
                  rq.ReviewQueueError)
        rr = await rq.resolve(conn, queue_id=q["id"], chosen_code="P01", actor="staffA",
                              is_override=True, approver="poB", affects_fulfillment=True, **AUTH)
        ok("resolve override ok -> staff_confirmed", rr["state"] == "resolved")
        st = await conn.fetchval("SELECT status FROM address_resolution WHERE id=$1::uuid",
                                 rr["result_resolution_id"])
        ok("result resolution staff_confirmed", st == "staff_confirmed")
        await err("resolve replay blocked",
                  rq.resolve(conn, queue_id=q["id"], chosen_code="P01", actor="staffA", **AUTH),
                  rq.ReviewQueueError)

        # ---- immutability ----
        await err("UPDATE snapshot (confirmation) blocked",
                  conn.execute("UPDATE address_confirmation_request SET candidate_snapshot='[]'::jsonb "
                               "WHERE id=$1::uuid", cr["id"]), asyncpg.PostgresError)
        await err("DELETE confirmation blocked",
                  conn.execute("DELETE FROM address_confirmation_request WHERE id=$1::uuid", cr["id"]),
                  asyncpg.PostgresError)
        await err("DELETE queue blocked",
                  conn.execute("DELETE FROM address_review_queue WHERE id=$1::uuid", q["id"]),
                  asyncpg.PostgresError)

        n = await conn.fetchval("SELECT count(*) FROM audit_log WHERE action LIKE 'address.confirm.%' "
                                "OR action LIKE 'address.review.%'")
        ok("audit rows present", n >= 6, f"(rows={n})")

        print(f"\nSUMMARY: {len(PASS)} pass, {len(FAIL)} fail")
        if FAIL:
            print("FAILED:", FAIL)
            raise SystemExit(1)
    finally:
        await conn.close()


asyncio.run(main())
