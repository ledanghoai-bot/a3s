#!/usr/bin/env python3
"""Price-tier mutation audit test (PO scope-change M0, CA-REVIEW-M0-CUTOVER §5.1).

Chứng minh `products.replace_price_tiers(..., actor=)`:
  1. POSITIVE: audit row `product.price_tiers.replace` (actor/entity/before-after) khi có actor + audit ok.
  2. FAIL-CLOSED: audit insert fail -> ROLLBACK cả thay đổi giá (giá KHÔNG đổi).
  3. BACKWARD-COMPAT: actor=None -> đổi giá, KHÔNG audit (không vỡ caller cũ).
Chạy trên throwaway DB 001-018.
  docker exec -e DATABASE_URL=... -e PYTHONPATH=/srv -w /srv api python scripts/price_audit_test.py
"""
import asyncio
import sys

import asyncpg

from app.config import settings
from app.services import auth_service
from app.services import products as products_service


def _db() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def break_audit(conn):
    await conn.execute("ALTER TABLE audit_log ADD CONSTRAINT _forcefail CHECK (false) NOT VALID")


async def fix_audit(conn):
    await conn.execute("ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS _forcefail")


async def tiers_now(conn, pid):
    rows = await conn.fetch(
        "SELECT min_qty, unit_price_vnd FROM price_tiers WHERE product_id=$1 ORDER BY min_qty", pid)
    return [(int(r["min_qty"]), int(r["unit_price_vnd"])) for r in rows]


async def main() -> int:
    conn = await asyncpg.connect(_db())
    fails: list[str] = []
    try:
        pid = await conn.fetchval("SELECT id FROM products ORDER BY id LIMIT 1")
        if pid is None:
            print("SKIP: khong co san pham seed")
            return 2
        admin = await auth_service.create_staff_user("price_tester", "pw12345678", "PT", role_key="admin")
        actor = {"id": admin["id"], "username": "price_tester"}

        # === TEST 1: POSITIVE — audit ghi đúng actor/action/entity/before-after ===
        n0 = await conn.fetchval(
            "SELECT count(*) FROM audit_log WHERE action='product.price_tiers.replace'")
        await products_service.replace_price_tiers(
            pid, [{"min_qty": 1, "unit_price_vnd": 99000}, {"min_qty": 10, "unit_price_vnd": 88000}],
            actor=actor)
        if await tiers_now(conn, pid) != [(1, 99000), (10, 88000)]:
            fails.append("positive: gia KHONG doi dung")
        row = await conn.fetchrow(
            "SELECT actor_type,actor_staff_id,actor_ref,action,entity_type,entity_id,before,after "
            "FROM audit_log WHERE action='product.price_tiers.replace' ORDER BY id DESC LIMIT 1")
        n1 = await conn.fetchval(
            "SELECT count(*) FROM audit_log WHERE action='product.price_tiers.replace'")
        if n1 != n0 + 1:
            fails.append(f"positive: audit khong tang dung ({n0}->{n1})")
        elif not (row["actor_staff_id"] == admin["id"] and row["actor_type"] == "staff"
                  and row["entity_type"] == "product" and row["entity_id"] == str(pid)
                  and '"unit_price_vnd": 88000' in (row["after"] or "")
                  and '"tiers"' in (row["before"] or "")):
            fails.append(f"positive: audit row sai actor/entity/before-after: {dict(row)}")

        # === TEST 2: FAIL-CLOSED — audit fail -> rollback ca gia ===
        t_before = await tiers_now(conn, pid)
        await break_audit(conn)
        try:
            await products_service.replace_price_tiers(
                pid, [{"min_qty": 2, "unit_price_vnd": 77000}], actor=actor)
            fails.append("fail-closed: KHONG raise khi audit fail")
        except Exception:
            pass
        await fix_audit(conn)
        if await tiers_now(conn, pid) != t_before:
            fails.append("fail-closed: gia DA doi (rollback fail)")

        # === TEST 3: BACKWARD-COMPAT — actor=None -> doi gia, KHONG audit ===
        n_before = await conn.fetchval(
            "SELECT count(*) FROM audit_log WHERE action='product.price_tiers.replace'")
        await products_service.replace_price_tiers(
            pid, [{"min_qty": 3, "unit_price_vnd": 66000}], actor=None)
        if await tiers_now(conn, pid) != [(3, 66000)]:
            fails.append("backward-compat: gia KHONG doi khi actor=None")
        if await conn.fetchval(
                "SELECT count(*) FROM audit_log WHERE action='product.price_tiers.replace'") != n_before:
            fails.append("backward-compat: van ghi audit du actor=None")
    finally:
        await conn.close()

    if fails:
        print("PRICE-AUDIT FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("PRICE-AUDIT PASS: positive (actor/entity/before-after) + fail-closed rollback gia + "
          "backward-compat actor=None khong audit")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
