#!/usr/bin/env python3
"""M3 release-prep delta evidence — PO Decision Record M3 muc 1/4/5 (migration 035/036,
template version map, m3_contract_validation trong manifest).

Chay tren throwaway DB khop DATABASE_URL (an toan: db name phai chua 'test'):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m3rp_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m3_release_prep_test.py

Chung minh:
  1. Fresh 001..036: RET-04/09 v1 approved (035); fulfilled v2 approved + v1 NGUYEN VEN (036).
  2. m3_contract_validation.sql: PASS tren DB du contract (fresh 036); RAISES khi thieu contract
     (chay tren DB moc 028 -> detect) — validation co gia tri that, khong vacuous.
  3. Manifest: ca 2 baseline_manifest*.json da dang ky m3_contract_validation trong
     post_migration_validations.
  4. Flag dispatcher ON: notify fulfilled enqueue template_version=2, render text v2
     "ban giao cho don vi van chuyen"; confirmed van v1 text cu.
  5. Flag OFF: notify fulfilled = legacy text M2 "da duoc giao." (khong doi behavior truoc release).
  6. Retention: run_all_approved dry-run phu RET-04+RET-09 v1; apply van bi flag OFF chan.
"""
import asyncio
import importlib.util
import json as _json
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services import auth_service, retention  # noqa: E402
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


async def migrate(conn, through=99):
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
        "applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT, transactional BOOLEAN NOT NULL DEFAULT true)")
    for p in sorted(x for x in MIG.glob("*.sql") if x.name[:3].isdigit()):
        if int(p.name[:3]) > through:
            break
        async with conn.transaction():
            await conn.execute(p.read_text(encoding="utf-8"))


STAFF_ID = "1"


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
        return outbox_worker.SendResult(ok=True, http_status=200, provider_message_id="fake")


async def mkdb(name):
    admin = await asyncpg.connect("postgresql://alpha3s:alpha3s@db:5432/postgres")
    await admin.execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{name}' AND pid<>pg_backend_pid()")
    await admin.execute(f"DROP DATABASE IF EXISTS {name}")
    await admin.execute(f"CREATE DATABASE {name}")
    await admin.close()


async def main():  # noqa: C901
    dbname = _db().rsplit("/", 1)[-1]
    if "test" not in dbname:
        print(f"ABORT: DATABASE_URL db='{dbname}' khong chua 'test' — tu choi (an toan).")
        return 2

    await mkdb(dbname)
    conn = await asyncpg.connect(_db())
    try:
        print("[1] fresh 001..036: 035 approve + 036 template v2")
        await migrate(conn)
        n = await conn.fetchval(
            "SELECT count(*) FROM retention_policies WHERE (rule_id,version) IN (('RET-04',1),('RET-09',1)) "
            "AND status='approved'")
        check(n == 2, f"035: RET-04/09 v1 approved ({n}/2)")
        v1 = await conn.fetchval(
            "SELECT body FROM outbound_templates WHERE template_key='order_status_fulfilled' AND version=1")
        v2 = await conn.fetchval(
            "SELECT body FROM outbound_templates WHERE template_key='order_status_fulfilled' AND version=2")
        check(v1 == "Đơn #{id} của bạn đã được giao.", "036: v1 NGUYEN VEN (immutable)")
        check(v2 == "Đơn #{id} của bạn đã được bàn giao cho đơn vị vận chuyển.", "036: v2 dung text PO duyet")

        print("[2] m3_contract_validation: PASS tren 036, RAISES tren 028")
        vsql = (ROOT / "scripts" / "m3_contract_validation.sql").read_text(encoding="utf-8")
        await conn.execute(vsql)
        check(True, "validation PASS tren DB du contract")
        await mkdb("m3rp28_itest")
        c28 = await asyncpg.connect(_db().rsplit("/", 1)[0] + "/m3rp28_itest")
        try:
            await migrate(c28, through=28)
            try:
                await c28.execute(vsql)
                check(False, "validation should RAISE tren DB 028")
            except asyncpg.RaiseError as e:
                check("M3 FAIL" in str(e), f"validation detect thieu contract ({str(e)[:60]})")
        finally:
            await c28.close()

        print("[3] manifest da dang ky validation")
        for mf in ("baseline_manifest.json", "baseline_manifest_13.json"):
            data = _json.loads((ROOT / "scripts" / mf).read_text(encoding="utf-8"))
            check("scripts/m3_contract_validation.sql" in data.get("post_migration_validations", []),
                  f"{mf}: co m3_contract_validation")

        await conn.execute("UPDATE products SET stock=100 WHERE sku='3S-100G'")
        plan = await bf.build_plan(conn)
        async with conn.transaction():
            await bf.apply(conn, plan, "00000000-0000-0000-0000-0000000000b6")
        global STAFF_ID
        st = await auth_service.create_staff_user("itest_m3rp", "pw12345678", "IT", role_key="admin")
        STAFF_ID = str(st["id"])
        settings.m2_inventory_ledger = True

        print("[4] flag ON: fulfilled -> template v2; confirmed van v1")
        settings.m3_outbound_dispatcher = True
        r1 = await order_service.execute_order_create(env_create("M3RP-1"))
        oid = r1.resource["id"]
        await conn.execute("UPDATE orders SET origin_channel='messenger' WHERE id=$1", oid)
        await lifecycle.execute_lifecycle(env_tr("M3RP-CONF", "order.confirm", oid))
        await lifecycle.execute_lifecycle(env_tr("M3RP-PROC", "order.start_processing", oid))
        await lifecycle.execute_lifecycle(env_tr("M3RP-READY", "order.ready_for_fulfillment", oid))
        await lifecycle.execute_lifecycle(env_tr("M3RP-FUL", "order.fulfill", oid))
        pconf = _json.loads(await conn.fetchval(
            "SELECT payload FROM outbox_events WHERE dedupe_key=$1", f"order_status:{oid}:confirmed"))
        pful = _json.loads(await conn.fetchval(
            "SELECT payload FROM outbox_events WHERE dedupe_key=$1", f"order_status:{oid}:fulfilled"))
        check(pconf.get("template_version") == 1, f"confirmed -> v1 (got {pconf.get('template_version')})")
        check(pful.get("template_version") == 2, f"fulfilled -> v2 (got {pful.get('template_version')})")
        fake = FakeAdapter()
        sr = await dispatcher.deliver_outbound("messenger", pful, send_adapter=fake)
        check(sr.ok and fake.calls[0][1]["text"] == f"Đơn #{oid} của bạn đã được bàn giao cho đơn vị vận chuyển.",
              f"render v2 dung text (got {fake.calls[0][1]['text'] if fake.calls else 'none'})")

        print("[5] flag OFF: legacy text M2 khong doi")
        settings.m3_outbound_dispatcher = False
        r2 = await order_service.execute_order_create(env_create("M3RP-2"))
        oid2 = r2.resource["id"]
        await conn.execute("UPDATE orders SET origin_channel='messenger' WHERE id=$1", oid2)
        await lifecycle.execute_lifecycle(env_tr("M3RP2-CONF", "order.confirm", oid2))
        await lifecycle.execute_lifecycle(env_tr("M3RP2-PROC", "order.start_processing", oid2))
        await lifecycle.execute_lifecycle(env_tr("M3RP2-READY", "order.ready_for_fulfillment", oid2))
        await lifecycle.execute_lifecycle(env_tr("M3RP2-FUL", "order.fulfill", oid2))
        pleg = _json.loads(await conn.fetchval(
            "SELECT payload FROM outbox_events WHERE dedupe_key=$1", f"order_status:{oid2}:fulfilled"))
        check(pleg.get("text") == f"Đơn #{oid2} của bạn đã được giao." and "dispatch" not in pleg,
              f"flag OFF: legacy fulfilled text M2 nguyen trang (got {pleg.get('text')})")

        print("[6] retention: dry-run phu policy approved; apply van bi flag chan")
        check(settings.m3_retention_executor is False, "flag m3_retention_executor OFF")
        out = await retention.run_all_approved(conn, dry_run=True)
        rules = {r["rule_id"] for r in out if "rule_id" in r}
        check(rules == {"RET-04", "RET-09"}, f"dry-run phu RET-04+RET-09 ({rules})")
        outa = await retention.run_all_approved(conn, dry_run=False)
        check(outa == [{"skipped": "flag_off"}], "apply flag OFF -> skipped (dieu kien PO: dry-run + report truoc)")
    finally:
        await conn.close()

    print("\n" + ("ALL PASS" if not _fail else f"FAIL: {_fail}"))
    return 0 if not _fail else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
