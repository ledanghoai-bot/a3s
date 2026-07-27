#!/usr/bin/env python3
"""M2 Slice 2 — backfill DRY-RUN tren PRODUCTION SNAPSHOT (read-only, PO-approved 27/7).

Seed throwaway DB mirror ĐÚNG production snapshot (export read-only tu VPS 27/7, PII-free):
  products : id=1 sku=3S-100G stock=998
  orders   : id=1 status=new ; id=2 status=new
  items    : (o1->p1 x1) , (o2->p1 x1)
Chay `m2_backfill.py audit` + `plan` -> in report + checksum (KHONG ghi balance, dry-run).

  docker exec alpha3s-api-1 python scripts/m2_backfill_prod_dryrun.py
"""
import asyncio
import importlib.util
import json
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
ADMIN_DB = "postgresql://alpha3s:alpha3s@db:5432/postgres"
TEST_DB = "m2_prodsnap"
TEST_URL = "postgresql://alpha3s:alpha3s@db:5432/" + TEST_DB

_spec = importlib.util.spec_from_file_location("m2_backfill", ROOT / "scripts" / "m2_backfill.py")
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)


async def main():
    admin = await asyncpg.connect(ADMIN_DB)
    await admin.execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{TEST_DB}' AND pid<>pg_backend_pid()")
    await admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    await admin.execute(f"CREATE DATABASE {TEST_DB}")
    await admin.close()

    conn = await asyncpg.connect(TEST_URL)
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT, transactional BOOLEAN NOT NULL DEFAULT true)")
        for p in sorted(x for x in MIG.glob("*.sql") if x.name[:3].isdigit()):
            async with conn.transaction():
                await conn.execute(p.read_text(encoding="utf-8"))

        # --- mirror production snapshot exactly (1 product, 2 new orders) ---
        # migration 001 da seed 1 product; ep no ve dung production: sku=3S-100G stock=998
        await conn.execute("DELETE FROM order_items"); await conn.execute("DELETE FROM orders")
        await conn.execute("DELETE FROM price_tiers"); await conn.execute("DELETE FROM products")
        await conn.execute("INSERT INTO products (id,sku,name,price_vnd,stock) VALUES (1,'3S-100G','3S 100g',170000,998)")
        await conn.execute("INSERT INTO orders (id,status) VALUES (1,'new'),(2,'new')")
        await conn.execute("INSERT INTO order_items (order_id,product_id,quantity,unit_price_vnd) "
                           "VALUES (1,1,1,170000),(2,1,1,170000)")

        audit = await bf.audit(conn)
        plan = await bf.build_plan(conn)
        report = {"source": "production snapshot 2026-07-27 (read-only, PO-approved)",
                  "audit": audit, "plan": plan}
        out = Path("/tmp/m2_backfill_prod_plan_report.json")
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"audit_ok": audit["ok"], "anomalies": audit["anomalies"],
                          "checksum": plan["checksum"],
                          "balances": plan["balances"],
                          "reservations": [[r["order_item_id"], r["order_id"], r["product_id"], r["quantity"]]
                                           for r in plan["reservations"]]},
                         ensure_ascii=False, indent=2))
        print(f"\nreport -> {out}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
