#!/usr/bin/env python3
"""Price-tier endpoint RBAC + audit test (CA-REVIEW-M0-CLOSURE §3 P0 + §4).

Bao phu 4 evidence CA yeu cau cho endpoint PUT /dashboard/products/{id}/tiers (require_permission price.manage):
  A. Authorized (co price.manage) -> gate pass + mutation thanh cong + audit ghi (actor/entity/before-after).
  B. Unauthorized (active role KHONG co price.manage) -> 403, gia KHONG doi, KHONG audit row moi.
  C. Unauthenticated -> 401.
  D. Audit insert failure -> ROLLBACK gia.
Chay tren throwaway DB 001-018, RBAC_STRICT (posture production).
  docker ... -e DATABASE_URL=... -e PYTHONPATH=/srv -w /srv api python scripts/price_audit_test.py
"""
import asyncio
import sys

import asyncpg

from app.api.auth import require_permission, require_staff_session
from app.config import settings
from app.services import auth_service
from app.services import products as products_service


def _db() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _status(e) -> int | None:
    return getattr(e, "status_code", None)


async def break_audit(conn):
    await conn.execute("ALTER TABLE audit_log ADD CONSTRAINT _forcefail CHECK (false) NOT VALID")


async def fix_audit(conn):
    await conn.execute("ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS _forcefail")


async def tiers_now(conn, pid):
    rows = await conn.fetch(
        "SELECT min_qty, unit_price_vnd FROM price_tiers WHERE product_id=$1 ORDER BY min_qty", pid)
    return [(int(r["min_qty"]), int(r["unit_price_vnd"])) for r in rows]


async def price_audit_count(conn) -> int:
    return await conn.fetchval(
        "SELECT count(*) FROM audit_log WHERE action='product.price_tiers.replace'")


async def main() -> int:
    settings.rbac_strict = True  # posture production (no-degrade)
    conn = await asyncpg.connect(_db())
    fails: list[str] = []
    try:
        pid = await conn.fetchval("SELECT id FROM products ORDER BY id LIMIT 1")
        if pid is None:
            print("SKIP: khong co san pham seed")
            return 2
        admin = await auth_service.create_staff_user("price_admin", "pw12345678", "PA", role_key="admin")
        actor = {"id": admin["id"], "username": "price_admin",
                 "rbac_provisioned": True, "permissions": {"price.manage"}}
        lowpriv = {"id": 999001, "username": "viewer_x",
                   "rbac_provisioned": True, "permissions": {"customer.view"}}
        gate = require_permission("price.manage")

        # === C: Unauthenticated -> 401 ===
        try:
            await require_staff_session(authorization=None)
            fails.append("C: unauthenticated KHONG raise (mong 401)")
        except Exception as e:
            if _status(e) != 401:
                fails.append(f"C: unauthenticated status {_status(e)} (mong 401)")

        # === B: Unauthorized (khong co price.manage) -> 403, khong mutation/audit ===
        t0 = await tiers_now(conn, pid)
        a0 = await price_audit_count(conn)
        try:
            await gate(staff=lowpriv)
            fails.append("B: role khong price.manage KHONG raise (mong 403)")
        except Exception as e:
            if _status(e) != 403:
                fails.append(f"B: status {_status(e)} (mong 403)")
        if await tiers_now(conn, pid) != t0:
            fails.append("B: gia doi du bi 403 (gate phai chan truoc body)")
        if await price_audit_count(conn) != a0:
            fails.append("B: co audit row moi du bi 403")

        # === A: Authorized (price.manage) -> gate pass + mutation + audit ghi ===
        if not await gate(staff=actor):
            fails.append("A: gate khong pass voi price.manage")
        await products_service.replace_price_tiers(
            pid, [{"min_qty": 1, "unit_price_vnd": 99000}], actor=actor)
        if await tiers_now(conn, pid) != [(1, 99000)]:
            fails.append("A: gia khong doi dung")
        a1 = await price_audit_count(conn)
        if a1 != a0 + 1:
            fails.append(f"A: audit khong tang dung ({a0}->{a1})")
        row = await conn.fetchrow(
            "SELECT actor_staff_id, entity_type, entity_id, after FROM audit_log "
            "WHERE action='product.price_tiers.replace' ORDER BY id DESC LIMIT 1")
        if not (row["actor_staff_id"] == admin["id"] and row["entity_type"] == "product"
                and row["entity_id"] == str(pid) and '"unit_price_vnd": 99000' in (row["after"] or "")):
            fails.append(f"A: audit row sai actor/entity/after: {dict(row)}")

        # === D: Audit insert failure -> rollback gia ===
        t_before = await tiers_now(conn, pid)
        await break_audit(conn)
        try:
            await products_service.replace_price_tiers(
                pid, [{"min_qty": 2, "unit_price_vnd": 77000}], actor=actor)
            fails.append("D: KHONG raise khi audit fail")
        except Exception:
            pass
        await fix_audit(conn)
        if await tiers_now(conn, pid) != t_before:
            fails.append("D: gia DA doi (rollback fail)")
    finally:
        await conn.close()

    if fails:
        print("PRICE-AUTHZ-AUDIT FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("PRICE-AUTHZ-AUDIT PASS: A authorized->pass+audit; B no-price.manage->403 no-mutation/no-audit; "
          "C unauthenticated->401; D audit-fail->rollback gia")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
