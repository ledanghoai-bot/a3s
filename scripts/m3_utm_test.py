#!/usr/bin/env python3
"""M3 Slice 2 evidence — UTM attribution (spec A3S-PHASE1B-M3-SPEC-001 §7.3, AC-M3-03).

Chay tren throwaway DB khop DATABASE_URL (an toan: db name phai chua 'test'):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m3s2_itest -e PYTHONPATH=/srv \
    -w /srv alpha3s-api-1 python scripts/m3_utm_test.py

Chung minh:
  1. sanitize_utm (pure, mapping v1): hop le -> giu; unknown key -> drop; empty/None -> {};
     PII guard: SDT/email/space/oversize/non-str -> UTMValidationError; utm_term chi khi co input.
  2. Migration 030 fresh-apply: 5 cot UTM tren orders + conversations.
  3. Backward compat: payload KHONG utm -> normalized khong co key 'utm', request_hash KHONG doi
     so voi truoc S2 (hash input whitelist); order.create chay binh thuong.
  4. Flag OFF (default): utm hop le duoc chap nhan nhung KHONG ghi (cot NULL).
  5. Flag ON: utm ghi dung cot; origin_channel giu nguyen nghia (spec: UTM khong thay the).
  6. utm invalid -> CommandError 422, KHONG tao order.
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
from app.services import attribution, auth_service  # noqa: E402
from app.services.command import errors, order_service, registry  # noqa: E402
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


def env_create(key, qty=1, utm=None):
    payload = dict(customer_name="A", phone="0912345678", address="12 Le Loi", sku="3S-100G",
                   quantity=qty, unit_price_vnd=150000)
    if utm is not None:
        payload["utm"] = utm
    return build_order_create_envelope(raw_payload=payload, actor=Actor("staff", STAFF_ID),
                                       channel="dashboard", idempotency_key=key)


UTM_OK = {"utm_source": "facebook", "utm_medium": "cpc", "utm_campaign": "orbit-2026.07",
          "utm_content": "video-a/b", "utm_term": "ca-phe-say-lanh"}


async def main():  # noqa: C901
    dbname = _db().rsplit("/", 1)[-1]
    if "test" not in dbname:
        print(f"ABORT: DATABASE_URL db='{dbname}' khong chua 'test' — tu choi (an toan).")
        return 2

    print("[1] sanitize_utm (pure, mapping v%d)" % attribution.MAPPING_VERSION)
    check(attribution.sanitize_utm(None) == {}, "None -> {}")
    check(attribution.sanitize_utm({}) == {}, "{} -> {}")
    check(attribution.sanitize_utm(UTM_OK) == UTM_OK, "bo hop le -> giu nguyen")
    check(attribution.sanitize_utm({"utm_source": "web", "junk": "x"}) == {"utm_source": "web"},
          "unknown key -> drop")
    check("utm_term" not in attribution.sanitize_utm({"utm_source": "web"}),
          "utm_term chi khi co input that")
    check(attribution.sanitize_utm({"utm_source": "  web  "}) == {"utm_source": "web"}, "strip whitespace")
    check(attribution.sanitize_utm({"utm_source": ""}) == {}, "empty string -> drop")
    for bad, why in [({"utm_source": "0912345678"}, "SDT"),
                     ({"utm_campaign": "a@b.com"}, "email"),
                     ({"utm_content": "hai tu"}, "space"),
                     ({"utm_source": "x" * 101}, "oversize"),
                     ({"utm_source": 123}, "non-str"),
                     ({"utm_term": "+84912345678"}, "SDT +84"),
                     ("chuoi", "khong phai object")]:
        try:
            attribution.sanitize_utm(bad)
            check(False, f"PII/format guard: {why} should raise")
        except attribution.UTMValidationError:
            check(True, f"PII/format guard: {why} -> UTMValidationError")

    print("[2] request_hash backward compat (pure)")
    n_old = registry.validate_order_create_payload(
        dict(customer_name="A", phone="0912345678", address="12 Le Loi", sku="3S-100G", quantity=1))
    check("utm" not in n_old, "khong utm -> normalized khong co key utm")
    n_new = registry.validate_order_create_payload(
        dict(customer_name="A", phone="0912345678", address="12 Le Loi", sku="3S-100G", quantity=1,
             utm=UTM_OK))
    hi_old = registry.order_create_hash_input(n_old)
    hi_new = registry.order_create_hash_input(n_new)
    check("utm" not in hi_new, "hash input (whitelist) khong chua utm")
    h_old = registry.compute_request_hash(registry.ORDER_CREATE, 1, hi_old)
    h_new = registry.compute_request_hash(registry.ORDER_CREATE, 1, hi_new)
    check(h_old == h_new, "request_hash khong doi khi co/khong utm (attribution ngoai business intent)")

    admin = await asyncpg.connect("postgresql://alpha3s:alpha3s@db:5432/postgres")
    await admin.execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{dbname}' AND pid<>pg_backend_pid()")
    await admin.execute(f"DROP DATABASE IF EXISTS {dbname}")
    await admin.execute(f"CREATE DATABASE {dbname}")
    await admin.close()

    conn = await asyncpg.connect(_db())
    try:
        print("[3] migrations 001..030 fresh apply")
        await migrate(conn)
        for tbl in ("orders", "conversations"):
            n = await conn.fetchval(
                "SELECT count(*) FROM information_schema.columns WHERE table_name=$1 "
                "AND column_name = ANY($2)", tbl,
                ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"])
            check(n == 5, f"030: {tbl} co 5 cot UTM (got {n})")

        await conn.execute("UPDATE products SET stock=100 WHERE sku='3S-100G'")
        plan = await bf.build_plan(conn)
        async with conn.transaction():
            await bf.apply(conn, plan, "00000000-0000-0000-0000-0000000000b2")
        global STAFF_ID
        st = await auth_service.create_staff_user("itest_m3s2", "pw12345678", "IT", role_key="admin")
        STAFF_ID = str(st["id"])
        settings.m2_inventory_ledger = True

        print("[4] flag OFF (default): utm hop le -> khong ghi")
        check(settings.m3_utm_attribution is False, "default m3_utm_attribution=False")
        r1 = await order_service.execute_order_create(env_create("M3S2-OFF-1", utm=UTM_OK))
        o1 = await conn.fetchrow(
            "SELECT utm_source, utm_medium, utm_campaign, utm_content, utm_term, origin_channel "
            "FROM orders WHERE id=$1", r1.resource["id"])
        check(all(o1[k] is None for k in ("utm_source", "utm_medium", "utm_campaign",
                                          "utm_content", "utm_term")),
              f"flag OFF: cot UTM NULL (got {dict(o1)})")

        print("[5] flag ON: ghi dung cot; origin_channel giu nguyen")
        settings.m3_utm_attribution = True
        r2 = await order_service.execute_order_create(env_create("M3S2-ON-1", utm=UTM_OK))
        o2 = await conn.fetchrow(
            "SELECT utm_source, utm_medium, utm_campaign, utm_content, utm_term, origin_channel "
            "FROM orders WHERE id=$1", r2.resource["id"])
        check({k: o2[k] for k in UTM_OK} == UTM_OK, f"flag ON: UTM ghi dung (got {dict(o2)})")
        check(o2["origin_channel"] == "dashboard", "origin_channel = kenh nguon, khong bi UTM thay the")
        r3 = await order_service.execute_order_create(env_create("M3S2-ON-2"))
        o3 = await conn.fetchrow("SELECT utm_source FROM orders WHERE id=$1", r3.resource["id"])
        check(o3["utm_source"] is None, "khong gui utm -> NULL (khong synthesize)")

        print("[6] utm invalid -> 422, khong tao order")
        before = await conn.fetchval("SELECT count(*) FROM orders")
        try:
            env_create("M3S2-BAD-1", utm={"utm_source": "0987654321"})
            check(False, "utm SDT should raise at envelope build")
        except errors.CommandError as e:
            check(e.code == errors.INVALID_ENVELOPE, f"CommandError invalid_envelope (got {e.code})")
        after = await conn.fetchval("SELECT count(*) FROM orders")
        check(before == after, "khong order moi sau utm invalid")
    finally:
        await conn.close()

    print("\n" + ("ALL PASS" if not _fail else f"FAIL: {_fail}"))
    return 0 if not _fail else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
