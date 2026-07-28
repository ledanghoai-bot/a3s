#!/usr/bin/env python3
"""M3 Slice 5 evidence — Outbound Dispatcher (spec §7.6, AC-M3-06).

Chay tren throwaway DB khop DATABASE_URL (an toan: db name phai chua 'test'):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m3s5d_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m3_dispatcher_test.py

Chung minh:
  1. Migration 032 fresh: template registry seed 6 approved (text = M2 nguyen van).
  2. Flag OFF: customer notify = payload legacy {text} (M2 byte-mot-byte, khong dispatch marker).
  3. Flag ON: notify enqueue qua dispatcher (marker, purpose P03, template ref, KHONG raw text);
     CUNG dedupe_key nhu M2 -> dedupe/at-least-once giu nguyen (insert lai -> None).
  4. deliver_outbound (fake adapter): render text = DUNG BANG legacy text; adapter nhan
     customer_ref + text + decision_ref.
  5. Suppression: P03 bi denial tuong minh -> ok=True error_class='suppressed:...' + adapter
     KHONG duoc goi (khong gui).
  6. Fail-closed: P06 khong consent -> suppressed(no_consent); consent 'unavailable' voi P06 ->
     retryable consent_unavailable (KHONG gui); voi P03 -> van gui (transactional khong bi chan
     boi outage consent-infra).
  7. Template khong approved / thieu param -> terminal 400 (khong gui mu).
  8. Zalo ZNS stub -> vendor_not_approved (terminal) khi chua duyet.
  9. outbox_worker.run_once end-to-end voi dispatcher payload -> delivered + delivery_attempts ghi
     outcome; dedupe key khong tao event trung.
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services import auth_service, consent  # noqa: E402
from app.services.command import (  # noqa: E402
    dispatcher,
    lifecycle,
    order_service,
    outbox_worker,
)
from app.services.command.envelope import (  # noqa: E402
    Actor,
    build_order_create_envelope,
)

bf_spec = importlib.util.spec_from_file_location("m2_backfill", ROOT / "scripts" / "m2_backfill.py")
bf = importlib.util.module_from_spec(bf_spec)
bf_spec.loader.exec_module(bf)

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


STAFF_ID = "1"
PV, NV = "policy-v1.2", "notice-v1.1"


def env_create(key):
    payload = dict(customer_name="A", phone="0912345678", address="12 Le Loi", sku="3S-100G",
                   quantity=1, unit_price_vnd=150000)
    return build_order_create_envelope(raw_payload=payload, actor=Actor("staff", STAFF_ID),
                                       channel="dashboard", idempotency_key=key)


def env_tr(key, ctype, oid):
    return lifecycle.build_lifecycle_envelope(
        command_type=ctype, payload={"order_id": oid},
        actor=Actor("staff", STAFF_ID), channel="dashboard", idempotency_key=key)


class FakeAdapter:
    def __init__(self):
        self.calls = []

    async def __call__(self, destination, payload):
        self.calls.append((destination, payload))
        return outbox_worker.SendResult(ok=True, http_status=200, provider_message_id="fake-1")


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
        print("[1] migrations 001..032 fresh apply + seed template")
        await migrate(conn)
        n = await conn.fetchval("SELECT count(*) FROM outbound_templates WHERE status='approved'")
        check(n == 7, f"seed 6 v1 + fulfilled v2 (036) approved (got {n})")
        body = await conn.fetchval(
            "SELECT body FROM outbound_templates WHERE template_key='order_status_confirmed' AND version=1")
        check(body == "Đơn #{id} của bạn đã được xác nhận.", "text template = M2 nguyen van")

        await conn.execute("UPDATE products SET stock=100 WHERE sku='3S-100G'")
        plan = await bf.build_plan(conn)
        async with conn.transaction():
            await bf.apply(conn, plan, "00000000-0000-0000-0000-0000000000b5")
        global STAFF_ID
        st = await auth_service.create_staff_user("itest_m3s5", "pw12345678", "IT", role_key="admin")
        STAFF_ID = str(st["id"])
        settings.m2_inventory_ledger = True

        print("[2] flag OFF: notify legacy (M2 nguyen trang)")
        check(settings.m3_outbound_dispatcher is False, "default m3_outbound_dispatcher=False")
        r1 = await order_service.execute_order_create(env_create("M3S5-OFF-1"))
        oid1 = r1.resource["id"]
        await conn.execute("UPDATE orders SET origin_channel='messenger' WHERE id=$1", oid1)
        await lifecycle.execute_lifecycle(env_tr("M3S5-OFF-CONF", "order.confirm", oid1))
        ev1 = await conn.fetchrow(
            "SELECT event_type, payload FROM outbox_events WHERE dedupe_key=$1",
            f"order_status:{oid1}:confirmed")
        import json as _json
        p1 = _json.loads(ev1["payload"])
        check(ev1["event_type"] == "order.status.customer" and "dispatch" not in p1
              and p1.get("text") == f"Đơn #{oid1} của bạn đã được xác nhận.",
              f"flag OFF: payload legacy text (got {p1})")

        print("[3] flag ON: enqueue qua dispatcher, cung dedupe_key")
        settings.m3_outbound_dispatcher = True
        r2 = await order_service.execute_order_create(env_create("M3S5-ON-1"))
        oid2 = r2.resource["id"]
        await conn.execute("UPDATE orders SET origin_channel='messenger' WHERE id=$1", oid2)
        await lifecycle.execute_lifecycle(env_tr("M3S5-ON-CONF", "order.confirm", oid2))
        ev2 = await conn.fetchrow(
            "SELECT event_type, payload, command_id FROM outbox_events WHERE dedupe_key=$1",
            f"order_status:{oid2}:confirmed")
        p2 = _json.loads(ev2["payload"])
        check(ev2["event_type"] == "outbound.message" and p2.get("dispatch") == "outbound.message"
              and p2.get("purpose_code") == "P03_TRANSACTIONAL" and "text" not in p2
              and p2.get("template_key") == "order_status_confirmed",
              f"flag ON: dispatcher payload, khong raw text (got {p2})")
        dup = await dispatcher.enqueue_outbound(
            conn, command_id=ev2["command_id"], customer_id=p2["customer_id"],
            customer_ref=p2["customer_ref"], destination="messenger",
            purpose_code="P03_TRANSACTIONAL", template_key="order_status_confirmed",
            template_version=1, params={"id": oid2},
            dedupe_key=f"order_status:{oid2}:confirmed", max_attempts=5)
        check(dup is None, "dedupe key trung -> khong tao event moi (M1 dedupe giu nguyen)")

        print("[4] deliver_outbound render = legacy text")
        fake = FakeAdapter()
        sr = await dispatcher.deliver_outbound("messenger", p2, send_adapter=fake)
        check(sr.ok and len(fake.calls) == 1, "deliver ok qua adapter")
        dest, sent = fake.calls[0]
        check(sent["text"] == f"Đơn #{oid2} của bạn đã được xác nhận." and sent["customer_ref"] == p2["customer_ref"]
              and sent.get("decision_ref"), f"text render = M2 nguyen van + decision_ref (got {sent})")

        print("[5] suppression: P03 denial tuong minh -> khong gui")
        cid2 = p2["customer_id"]
        await consent.record_consent(conn, customer_id=cid2, purpose_code="P03_TRANSACTIONAL",
                                     status="denied", captured_via="staff_manual",
                                     policy_version=PV, notice_version=NV)
        fake2 = FakeAdapter()
        sr2 = await dispatcher.deliver_outbound("messenger", p2, send_adapter=fake2)
        check(sr2.ok and (sr2.error_class or "").startswith("suppressed:explicit_denial:")
              and not fake2.calls,
              f"suppressed + adapter khong goi (got {sr2.error_class}, calls={len(fake2.calls)})")

        print("[6] fail-closed P06/unavailable")
        p6 = dict(p2, purpose_code="P06_MARKETING")
        fake3 = FakeAdapter()
        sr3 = await dispatcher.deliver_outbound("messenger", p6, send_adapter=fake3)
        check(sr3.ok and (sr3.error_class or "").startswith("suppressed:")
              and not fake3.calls, f"P06 khong consent -> suppressed (got {sr3.error_class})")

        async def check_unavailable(conn2, **kw):
            return consent.PermissionDecision("unavailable", "infrastructure_error", "ref-x")
        fake4 = FakeAdapter()
        sr4 = await dispatcher.deliver_outbound("messenger", p6, send_adapter=fake4,
                                                check_fn=check_unavailable)
        check(not sr4.ok and sr4.error_class == "consent_unavailable" and not fake4.calls,
              f"P06 unavailable -> retryable, khong gui (got {sr4.error_class})")
        fake5 = FakeAdapter()
        p3 = dict(p2)  # P03
        sr5 = await dispatcher.deliver_outbound("messenger", p3, send_adapter=fake5,
                                                check_fn=check_unavailable)
        check(sr5.ok and len(fake5.calls) == 1,
              "P03 unavailable -> VAN gui (transactional khong bi chan boi outage)")

        # go denial [5] de cac buoc sau di toi duoc tang template/adapter
        await consent.record_consent(conn, customer_id=cid2, purpose_code="P03_TRANSACTIONAL",
                                     status="granted", captured_via="staff_manual",
                                     policy_version=PV, notice_version=NV)

        print("[7] template khong approved / thieu param -> terminal")
        await conn.execute(
            "INSERT INTO outbound_templates (template_key, version, purpose_code, body, status) "
            "VALUES ('order_status_confirmed', 2, 'P03_TRANSACTIONAL', 'x {id}', 'draft')")
        bad1 = dict(p3, template_version=2)
        srt = await dispatcher.deliver_outbound("messenger", bad1, send_adapter=FakeAdapter())
        check(not srt.ok and srt.http_status == 400 and srt.error_class == "template_not_approved",
              f"draft version -> terminal (got {srt.error_class})")
        bad2 = dict(p3, params={})
        srp = await dispatcher.deliver_outbound("messenger", bad2, send_adapter=FakeAdapter())
        check(not srp.ok and srp.error_class == "template_params_missing",
              f"thieu param -> terminal (got {srp.error_class})")

        print("[8] zalo_zns stub -> vendor_not_approved")
        srz = await dispatcher.deliver_outbound("zalo_zns", dict(p3))
        check(not srz.ok and srz.http_status == 403 and srz.error_class == "vendor_not_approved",
              f"zalo stub terminal (got {srz.error_class})")

        print("[9] end-to-end run_once voi dispatcher payload")
        # deny lai P03 de chung minh suppression audit persist vao delivery_attempts qua worker
        await consent.record_consent(conn, customer_id=cid2, purpose_code="P03_TRANSACTIONAL",
                                     status="denied", captured_via="staff_manual",
                                     policy_version=PV, notice_version=NV)
        fake9 = FakeAdapter()

        async def send_fn(destination, payload):
            if payload.get("dispatch") == "outbound.message":
                return await dispatcher.deliver_outbound(destination, payload, send_adapter=fake9)
            return outbox_worker.SendResult(ok=True, http_status=200)
        stats = await outbox_worker.run_once(send_fn=send_fn)
        st2 = await conn.fetchval(
            "SELECT status FROM outbox_events WHERE dedupe_key=$1", f"order_status:{oid2}:confirmed")
        att = await conn.fetchval(
            "SELECT count(*) FROM delivery_attempts da JOIN outbox_events oe ON oe.id=da.outbox_event_id "
            "WHERE oe.dedupe_key=$1", f"order_status:{oid2}:confirmed")
        # cid2 da bi denial P03 o buoc [5] -> event nay gio SUPPRESSED khi gui (van delivered + audit)
        check(stats["claimed"] >= 1 and st2 == "delivered" and att >= 1,
              f"run_once xu ly event dispatcher (stats={stats}, status={st2}, attempts={att})")
        supp = await conn.fetchval(
            "SELECT error_class FROM delivery_attempts da JOIN outbox_events oe ON oe.id=da.outbox_event_id "
            "WHERE oe.dedupe_key=$1 ORDER BY da.attempt_no DESC LIMIT 1",
            f"order_status:{oid2}:confirmed")
        check(supp is not None and supp.startswith("suppressed:"),
              f"delivery_attempts luu outbound audit decision_ref (got {supp})")
    finally:
        await conn.close()

    print("\n" + ("ALL PASS" if not _fail else f"FAIL: {_fail}"))
    return 0 if not _fail else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
