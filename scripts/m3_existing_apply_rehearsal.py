#!/usr/bin/env python3
"""M3 Slice 7 evidence — EXISTING-APPLY migration rehearsal 028 -> 033 (Directive §6, AC-M3 DoD).

Chung minh migration M3 (029..033) apply an toan tren DB DA TON TAI o moc M2 accepted (028) voi du
lieu dai dien (orders nhieu status ke ca legacy + balances tu backfill M2). Kiem tra du lieu hien
huu bao toan (checksum), schema moi hien dien, khong PII trong output.

  docker exec alpha3s-api-1 python scripts/m3_existing_apply_rehearsal.py
"""
import asyncio
import hashlib
import importlib.util
import sys
import time
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
sys.path.insert(0, str(ROOT))
from app.services.inventory import reconcile as recon  # noqa: E402

_bf_spec = importlib.util.spec_from_file_location("m2_backfill", ROOT / "scripts" / "m2_backfill.py")
bf = importlib.util.module_from_spec(_bf_spec)
_bf_spec.loader.exec_module(bf)
ADMIN = "postgresql://alpha3s:alpha3s@db:5432/postgres"
TEST_DB = "m3exist_itest"
URL = "postgresql://alpha3s:alpha3s@db:5432/" + TEST_DB
EXISTING_THROUGH = 28  # DB "hien huu" = M2 accepted (migration head 028)

_fail = []


def check(cond, label):
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        _fail.append(label)


def _num(p):
    return int(p.name[:3])


async def _apply(conn, files):
    for p in files:
        sql = p.read_text(encoding="utf-8")
        async with conn.transaction():
            await conn.execute(sql)
        await conn.execute(
            "INSERT INTO schema_migrations(version,checksum,applied_by) VALUES ($1,$2,'rehearsal') "
            "ON CONFLICT (version) DO NOTHING",
            p.stem, hashlib.sha256(sql.encode()).hexdigest())


async def _data_checksum(conn):
    orders = await conn.fetch("SELECT id, status FROM orders ORDER BY id")
    prods = await conn.fetch("SELECT id, stock FROM products ORDER BY id")
    blob = ";".join(f"{r['id']}:{r['status']}" for r in orders) + "|" + \
           ";".join(f"{r['id']}:{r['stock']}" for r in prods)
    return hashlib.sha256(blob.encode()).hexdigest(), len(orders), len(prods)


async def main():  # noqa: C901
    t0 = time.monotonic()
    admin = await asyncpg.connect(ADMIN)
    await admin.execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{TEST_DB}' AND pid<>pg_backend_pid()")
    await admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    await admin.execute(f"CREATE DATABASE {TEST_DB}")
    await admin.close()

    files = sorted((p for p in MIG.glob("*.sql") if p.name[:3].isdigit()), key=_num)
    existing = [p for p in files if _num(p) <= EXISTING_THROUGH]
    m3 = [p for p in files if _num(p) > EXISTING_THROUGH]
    print(f"[setup] existing=001..{EXISTING_THROUGH:03d} ({len(existing)} files); apply={[p.stem[:3] for p in m3]}")

    conn = await asyncpg.connect(URL)
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT, transactional BOOLEAN NOT NULL DEFAULT true)")

        print("[1] dung DB hien huu o moc 028 + seed du lieu dai dien + backfill M2")
        await _apply(conn, existing)
        cust = await conn.fetchval(
            "INSERT INTO customers (psid,name,phone,address) VALUES ('psid-ex','C','0912345678','addr') RETURNING id")
        await conn.execute("UPDATE products SET stock=500 WHERE sku='3S-100G'")
        pid = await conn.fetchval("SELECT id FROM products WHERE sku='3S-100G'")
        for stt in ["new", "confirmed", "shipped", "done", "cancelled", "fulfilled", "delivery_failed"]:
            oid = await conn.fetchval(
                "INSERT INTO orders (customer_id,status,total_vnd) VALUES ($1,$2,1000) RETURNING id", cust, stt)
            await conn.execute(
                "INSERT INTO order_items (order_id,product_id,quantity,unit_price_vnd) VALUES ($1,$2,1,1000)", oid, pid)
        plan = await bf.build_plan(conn)
        async with conn.transaction():
            await bf.apply(conn, plan, "00000000-0000-0000-0000-0000000000e3")
        pre_ck, pre_orders, pre_prods = await _data_checksum(conn)
        print(f"[pre] orders={pre_orders} products={pre_prods} checksum={pre_ck[:12]}")

        print("[2] EXISTING-APPLY: migration 029..033 tren DB da co du lieu")
        try:
            await _apply(conn, m3)
            check(True, f"apply 029..{m3[-1].stem[:3]} thanh cong (postcondition moi migration PASS)")
        except Exception as e:  # noqa: BLE001
            check(False, f"existing-apply FAIL: {e}")
            raise

        print("[3] POST integrity")
        post_ck, post_orders, post_prods = await _data_checksum(conn)
        check(post_ck == pre_ck, f"du lieu hien huu KHONG doi (checksum {pre_ck[:12]} == {post_ck[:12]})")
        check(post_orders == pre_orders and post_prods == pre_prods, "orders/products count giu nguyen")
        cdef = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='orders_status_check'")
        check("'delivered'" in cdef and "shipped" in cdef,
              "029: constraint co delivered + van chap nhan legacy status hien huu")
        da_null = await conn.fetchval("SELECT count(*) FROM orders WHERE delivered_at IS NULL")
        check(da_null == pre_orders, f"delivered_at NULL cho existing rows ({da_null})")
        utm_null = await conn.fetchval("SELECT count(*) FROM orders WHERE utm_source IS NULL")
        check(utm_null == pre_orders, f"utm_* NULL cho existing rows ({utm_null})")
        for t in ["consent_records", "outbound_templates", "retention_policies", "legal_holds",
                  "retention_run_log"]:
            ok = await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{t}")
            check(ok, f"new table {t} hien dien sau existing-apply")
        n_tmpl = await conn.fetchval("SELECT count(*) FROM outbound_templates WHERE status='approved'")
        check(n_tmpl == 7, f"032+036 seed 6 v1 + fulfilled v2 approved ({n_tmpl})")
        n_appr = await conn.fetchval(
            "SELECT count(*) FROM retention_policies WHERE status='approved' "
            "AND (rule_id, version) IN (('RET-04',1),('RET-09',1))")
        check(n_appr == 2, f"033 seed -> 035 PO approved RET-04/09 v1 ({n_appr})")
        n_mig = await conn.fetchval("SELECT count(*) FROM schema_migrations")
        n_ck = await conn.fetchval("SELECT count(DISTINCT checksum) FROM schema_migrations")
        check(n_mig == 37 and n_ck == 37, f"schema_migrations 37 rows/37 checksums ({n_mig}/{n_ck})")
        check(await conn.fetchval(
            "SELECT count(*) FROM pg_trigger WHERE tgname='retention_policies_guard_trg'") == 1,
            "037: retention policy immutability trigger hien dien sau existing-apply")
        check(await conn.fetchval(
            "SELECT count(*) FROM pg_trigger WHERE tgname='outbound_templates_guard_trg'") == 1,
            "034: template immutability trigger hien dien sau existing-apply")

        print("[4] reconcile M2 van OK sau M3 (khong pha invariant)")
        rep = await recon.reconcile_inventory(conn, check_stock_compat=True)
        check(rep.ok, f"reconcile OK (mismatches={rep.mismatches})")
        bad = await conn.fetchval(
            "SELECT count(*) FROM inventory_balances WHERE reserved>on_hand OR on_hand<0 OR reserved<0")
        check(bad == 0, f"balance invariants hold ({bad} vi pham)")

        print("[caveat] Production hien o M0-era; M1/M2 CHUA deploy -> rehearsal dung schema 001-028 +")
        print("         representative data. Re-baseline sau M2 merge main la gate rieng (Directive §2.2).")
        print(f"[duration] {round(time.monotonic() - t0, 2)}s")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — existing-apply 028->033 an toan; du lieu hien huu bao toan; no PII in output")


if __name__ == "__main__":
    asyncio.run(main())
