#!/usr/bin/env python3
"""M3 Slice 1 evidence — delivered lifecycle (spec A3S-PHASE1B-M3-SPEC-001 §7.2, AC-M3-02).

Chay tren throwaway DB khop DATABASE_URL (an toan: db name phai chua 'test'):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m3s1_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m3_delivered_lifecycle_test.py

Chung minh:
  1. Matrix (pure): fulfilled--mark_delivered-->delivered; delivered--complete/request_return;
     delivery_failed--retry_delivery-->fulfilled; delivery_failed--cancel-->cancelled
     (perm=order.cancel.exception, EFFECT_NONE); illegal cases -> 409.
  2. Migration 029 fresh-apply PASS (constraint co 'delivered', cot delivered_at).
  3. Flag OFF (default): mark_delivered bi tu choi IllegalTransition — hanh vi M2 nguyen trang;
     chuoi M2 (confirm->processing->ready->fulfill) van chay binh thuong.
  4. Flag ON: execute_lifecycle(order.mark_delivered) qua command bus: status=delivered,
     delivered_at set, DUNG MOT event order.mark_delivered, customer notify outbox
     (origin_channel=messenger, dedupe order_status:{id}:delivered).
  5. Effective-once: resend cung envelope -> khong double event, delivered_at KHONG doi.
  6. delivered--complete--> completed; delivered_at giu nguyen sau complete.
  7. delivery_failed: retry_delivery -> fulfilled; roi mark_delivery_failed -> cancel ->
     cancelled; balances KHONG doi boi cac transition EFFECT_NONE (khong am, stock==available).
  8. RBAC F02: viewer goi truc tiep execute_lifecycle(mark_delivered) -> forbidden, khong mutation.
"""
import asyncio
import importlib.util
import sys
import uuid
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services import auth_service  # noqa: E402
from app.services.command import lifecycle, order_service  # noqa: E402
from app.services.command.envelope import (  # noqa: E402
    Actor,
    build_order_create_envelope,
)
from app.services.order import transition_service as txn  # noqa: E402
from app.services.order import transitions  # noqa: E402
from app.services.order.events import append_order_event  # noqa: E402

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


def env_create(key, qty):
    payload = dict(customer_name="A", phone="0912345678", address="12 Le Loi", sku="3S-100G",
                   quantity=qty, unit_price_vnd=150000)
    return build_order_create_envelope(raw_payload=payload, actor=Actor("staff", STAFF_ID),
                                       channel="dashboard", idempotency_key=key)


def env_tr(key, ctype, oid, actor_id=None):
    return lifecycle.build_lifecycle_envelope(
        command_type=ctype, payload={"order_id": oid},
        actor=Actor("staff", actor_id or STAFF_ID), channel="dashboard", idempotency_key=key)


STAFF_ID = "1"
VIEWER_ID = "2"


async def walk_to_fulfilled(conn, oid):
    corr = uuid.uuid4()
    for act in ("confirm", "start_processing", "ready_for_fulfillment", "fulfill"):
        async with conn.transaction():
            await txn.apply_transition(conn, order_id=oid, action=act, actor_type="staff",
                                       actor_id=STAFF_ID, correlation_id=corr,
                                       idem_prefix=f"m3s1:{oid}:{act}")


async def bal(conn, sku="3S-100G"):
    return await conn.fetchrow(
        "SELECT b.on_hand, b.reserved, b.on_hand-b.reserved AS available, p.stock "
        "FROM inventory_balances b JOIN products p ON p.id=b.product_id WHERE p.sku=$1", sku)


async def main():  # noqa: C901
    dbname = _db().rsplit("/", 1)[-1]
    if "test" not in dbname:
        print(f"ABORT: DATABASE_URL db='{dbname}' khong chua 'test' — tu choi (an toan).")
        return 2

    print("[1] matrix guard (pure)")
    check(transitions.resolve("fulfilled", "mark_delivered").to_status == "delivered",
          "fulfilled--mark_delivered-->delivered")
    check(transitions.resolve("fulfilled", "mark_delivered").inventory_effect == transitions.EFFECT_NONE,
          "mark_delivered EFFECT_NONE")
    check(transitions.resolve("delivered", "complete").to_status == "completed",
          "delivered--complete-->completed")
    check(transitions.resolve("delivered", "request_return").to_status == "return_requested",
          "delivered--request_return-->return_requested")
    check(transitions.resolve("delivery_failed", "retry_delivery").to_status == "fulfilled",
          "delivery_failed--retry_delivery-->fulfilled")
    spec_c = transitions.resolve("delivery_failed", "cancel")
    check(spec_c.to_status == "cancelled" and spec_c.permission == "order.cancel.exception"
          and spec_c.inventory_effect == transitions.EFFECT_NONE,
          "delivery_failed--cancel-->cancelled (perm=cancel.exception, EFFECT_NONE)")
    for frm, act in [("new", "mark_delivered"), ("delivered", "fulfill"),
                     ("completed", "mark_delivered"), ("delivered", "mark_delivered")]:
        try:
            transitions.resolve(frm, act)
            check(False, f"{frm}--{act} should be illegal")
        except transitions.IllegalTransition:
            check(True, f"{frm}--{act}--> illegal (409)")

    admin = await asyncpg.connect("postgresql://alpha3s:alpha3s@db:5432/postgres")
    await admin.execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{dbname}' AND pid<>pg_backend_pid()")
    await admin.execute(f"DROP DATABASE IF EXISTS {dbname}")
    await admin.execute(f"CREATE DATABASE {dbname}")
    await admin.close()

    conn = await asyncpg.connect(_db())
    try:
        print("[2] migrations 001..029 fresh apply")
        await migrate(conn)
        cdef = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='orders_status_check'")
        check("'delivered'" in cdef, "029: constraint co 'delivered'")
        check(await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='orders' AND column_name='delivered_at'") == 1, "029: cot delivered_at")

        await conn.execute("UPDATE products SET stock=100 WHERE sku='3S-100G'")
        plan = await bf.build_plan(conn)
        async with conn.transaction():
            await bf.apply(conn, plan, "00000000-0000-0000-0000-0000000000b1")
        global STAFF_ID, VIEWER_ID
        st = await auth_service.create_staff_user("itest_m3s1", "pw12345678", "IT", role_key="admin")
        STAFF_ID = str(st["id"])
        vw = await auth_service.create_staff_user("itest_m3s1_v", "pw12345678", "V", role_key="viewer")
        VIEWER_ID = str(vw["id"])
        settings.m2_inventory_ledger = True

        r1 = await order_service.execute_order_create(env_create("M3S1-CREATE-1", qty=2))
        oid = r1.resource["id"]
        # origin_channel + psid de test customer notify
        await conn.execute("UPDATE orders SET origin_channel='messenger' WHERE id=$1", oid)

        print("[3] flag OFF = hanh vi M2 nguyen trang")
        check(settings.m3_delivered_lifecycle is False, "default m3_delivered_lifecycle=False")
        await walk_to_fulfilled(conn, oid)  # chuoi M2 chay binh thuong voi flag off
        check((await conn.fetchval("SELECT status FROM orders WHERE id=$1", oid)) == "fulfilled",
              "chuoi M2 -> fulfilled (flag off khong anh huong)")
        try:
            async with conn.transaction():
                await txn.apply_transition(conn, order_id=oid, action="mark_delivered",
                                           actor_type="staff", actor_id=STAFF_ID,
                                           correlation_id=uuid.uuid4(), idem_prefix="m3s1:off")
            check(False, "mark_delivered flag off should fail")
        except transitions.IllegalTransition:
            check(True, "flag OFF: mark_delivered -> IllegalTransition (M2 nguyen trang)")

        print("[4] flag ON: mark_delivered qua command bus")
        settings.m3_delivered_lifecycle = True
        e1 = env_tr("M3S1-DELIVERED-1", "order.mark_delivered", oid)
        rc = await lifecycle.execute_lifecycle(e1)
        check(rc.outcome == "succeeded", f"receipt succeeded (got {rc.outcome})")
        o = await conn.fetchrow("SELECT status, delivered_at FROM orders WHERE id=$1", oid)
        check(o["status"] == "delivered" and o["delivered_at"] is not None,
              f"status=delivered + delivered_at set (got {dict(o)})")
        nev = await conn.fetchval(
            "SELECT count(*) FROM order_events WHERE order_id=$1 AND event_type='order.mark_delivered'", oid)
        check(nev == 1, f"DUNG 1 event order.mark_delivered (got {nev})")
        ob = await conn.fetchrow(
            "SELECT destination, payload FROM outbox_events WHERE dedupe_key=$1",
            f"order_status:{oid}:delivered")
        check(ob is not None and ob["destination"] == "messenger",
              "customer notify outbox delivered (messenger)")

        print("[5] effective-once: resend envelope moi cung idempotency key")
        t0 = o["delivered_at"]
        rc2 = await lifecycle.execute_lifecycle(env_tr("M3S1-DELIVERED-1", "order.mark_delivered", oid))
        check(rc2.outcome == "succeeded" and rc2.duplicate, "resend -> duplicate receipt succeeded")
        nev2 = await conn.fetchval(
            "SELECT count(*) FROM order_events WHERE order_id=$1 AND event_type='order.mark_delivered'", oid)
        check(nev2 == 1, "khong double event")
        t1 = await conn.fetchval("SELECT delivered_at FROM orders WHERE id=$1", oid)
        check(t1 == t0, "delivered_at khong doi (COALESCE)")
        # idempotent event primitive: re-append cung key -> van 1
        async with conn.transaction():
            await append_order_event(conn, order_id=oid, event_type="order.mark_delivered",
                                     to_status="delivered", from_status="fulfilled",
                                     inventory_status_before="fulfilled", inventory_status_after="fulfilled",
                                     actor_type="staff", actor_id=STAFF_ID, correlation_id=uuid.uuid4(),
                                     command_id=None,
                                     idempotency_key=f"cmd:{e1.command_id}:event:{oid}:mark_delivered")
        nev3 = await conn.fetchval(
            "SELECT count(*) FROM order_events WHERE order_id=$1 AND event_type='order.mark_delivered'", oid)
        check(nev3 == 1, "append idempotent theo key -> van 1 event")

        print("[6] delivered -> complete; delivered_at giu nguyen")
        rc3 = await lifecycle.execute_lifecycle(env_tr("M3S1-COMPLETE-1", "order.complete", oid))
        check(rc3.outcome == "succeeded", "complete succeeded")
        o2 = await conn.fetchrow("SELECT status, delivered_at FROM orders WHERE id=$1", oid)
        check(o2["status"] == "completed" and o2["delivered_at"] == t0,
              "completed + delivered_at khong doi")

        print("[7] delivery_failed: retry + cancel, khong dong den ton kho")
        r2 = await order_service.execute_order_create(env_create("M3S1-CREATE-2", qty=3))
        oid2 = r2.resource["id"]
        await walk_to_fulfilled(conn, oid2)
        rcf = await lifecycle.execute_lifecycle(env_tr("M3S1-DF-1", "order.mark_delivery_failed", oid2))
        check(rcf.outcome == "succeeded", "mark_delivery_failed succeeded")
        b0 = await bal(conn)
        rcr = await lifecycle.execute_lifecycle(env_tr("M3S1-RETRY-1", "order.retry_delivery", oid2))
        check(rcr.outcome == "succeeded"
              and (await conn.fetchval("SELECT status FROM orders WHERE id=$1", oid2)) == "fulfilled",
              "retry_delivery -> fulfilled")
        rcf2 = await lifecycle.execute_lifecycle(env_tr("M3S1-DF-2", "order.mark_delivery_failed", oid2))
        check(rcf2.outcome == "succeeded", "mark_delivery_failed lan 2 succeeded")
        rcc = await lifecycle.execute_lifecycle(env_tr("M3S1-CANCEL-1", "order.cancel", oid2))
        check(rcc.outcome == "succeeded"
              and (await conn.fetchval("SELECT status FROM orders WHERE id=$1", oid2)) == "cancelled",
              "delivery_failed--cancel-->cancelled")
        b1 = await bal(conn)
        check(dict(b0) == dict(b1), f"balances khong doi qua retry/df/cancel (got {dict(b0)} vs {dict(b1)})")
        check(b1["on_hand"] >= 0 and b1["reserved"] >= 0 and b1["stock"] == b1["available"],
              "khong am + stock==available (mirror contract)")

        print("[8] RBAC F02: viewer direct-call mark_delivered -> forbidden, khong mutation")
        r3 = await order_service.execute_order_create(env_create("M3S1-CREATE-3", qty=1))
        oid3 = r3.resource["id"]
        await walk_to_fulfilled(conn, oid3)
        rv = await lifecycle.execute_lifecycle(env_tr("M3S1-VIEWER-1", "order.mark_delivered", oid3, VIEWER_ID))
        check(rv.outcome == "rejected" and rv.error_code == "forbidden",
              f"viewer -> forbidden (got {rv.outcome}/{rv.error_code})")
        st3 = await conn.fetchrow("SELECT status, delivered_at FROM orders WHERE id=$1", oid3)
        check(st3["status"] == "fulfilled" and st3["delivered_at"] is None,
              "khong mutation (van fulfilled, delivered_at NULL)")
    finally:
        await conn.close()

    print("\n" + ("ALL PASS" if not _fail else f"FAIL: {_fail}"))
    return 0 if not _fail else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
