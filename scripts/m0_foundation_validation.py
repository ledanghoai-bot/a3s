#!/usr/bin/env python3
"""M0 foundation validation (I-B M0.3/M0.4) — audit fail-closed + redaction + permission model.

Chay tren DB da ap 001-017 + seed rbac_seed_proposed.sql. Exit != 0 neu bat ky assertion fail.
  docker exec -e DATABASE_URL=... -e PYTHONPATH=/srv -w /srv api python scripts/m0_foundation_validation.py
"""
import asyncio
import json
import sys

import asyncpg

from app.config import settings
from app.services import audit_service, permission_service


def _db() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def main() -> int:
    conn = await asyncpg.connect(_db())
    fails: list[str] = []
    try:
        # --- Permission model (M0.4) ---
        if not await permission_service.rbac_provisioned(conn):
            fails.append("RBAC chua provisioned (thieu 016)")
        admin = await permission_service.permissions_for_role(conn, "admin")
        sales = await permission_service.permissions_for_role(conn, "sales")
        if "staff.manage" not in admin:
            fails.append("admin thieu staff.manage")
        if "staff.manage" in sales:
            fails.append("sales CO staff.manage (escalation risk)")
        if "inventory.adjust" in sales:
            fails.append("sales CO inventory.adjust (sai least-privilege)")
        if not sales:
            fails.append("sales rong (seed chua chay?)")

        # --- Audit fail-closed: rollback -> KHONG ghi (M0.3) ---
        before = await conn.fetchval("SELECT count(*) FROM audit_log")
        try:
            async with conn.transaction():
                await audit_service.record(
                    conn, "staff", "test.should_rollback", actor_ref="tester", reason="simulate fail")
                raise RuntimeError("simulate mutation failure")
        except RuntimeError:
            pass
        after_rb = await conn.fetchval("SELECT count(*) FROM audit_log")
        if after_rb != before:
            fails.append(f"audit KHONG rollback cung mutation ({before}->{after_rb})")

        # --- Audit committed on success + REDACTION ---
        async with conn.transaction():
            await audit_service.record(
                conn, "staff", "test.ok", actor_ref="tester",
                after={"password": "secret123", "name": "X"})
        row = await conn.fetchrow(
            "SELECT after FROM audit_log WHERE action='test.ok' ORDER BY id DESC LIMIT 1")
        after_json = json.loads(row["after"])
        if after_json.get("password") != "***REDACTED***":
            fails.append("password KHONG duoc redact trong audit")
        if after_json.get("name") != "X":
            fails.append("audit mat field khong nhay cam")
    finally:
        await conn.close()

    if fails:
        print("M0 FOUNDATION FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("M0 FOUNDATION PASS: RBAC provisioned; admin⊇staff.manage; sales KHONG staff.manage/"
          "inventory.adjust; audit fail-closed rollback OK; secret redaction OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
