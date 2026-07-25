#!/usr/bin/env python3
"""Endpoint-level audit rollback test (CA-REVIEW-M0-DEV-003 §9).

Chứng minh mutation ROLLBACK khi audit insert THẤT BẠI, cho từng endpoint nhóm A:
  - staff.create (auth_router.create_staff)
  - auth.password_change (auth_service.change_password)
Chạy trên throwaway DB 001-018 + bootstrap admin.
Force audit-insert fail = thêm CONSTRAINT CHECK(false) NOT VALID vào audit_log (existing rows bỏ qua,
mọi INSERT mới bị chặn) -> audit_log VẪN tồn tại (nên _audit_exists=True, code KHÔNG skip audit).
  docker exec -e DATABASE_URL=... -e PYTHONPATH=/srv -w /srv api python scripts/audit_rollback_endpoint_test.py
"""
import asyncio
import sys

import asyncpg

from app.api import auth_router
from app.config import settings
from app.services import auth_service


def _db() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def break_audit(conn):
    await conn.execute("ALTER TABLE audit_log ADD CONSTRAINT _forcefail CHECK (false) NOT VALID")


async def fix_audit(conn):
    await conn.execute("ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS _forcefail")


async def main() -> int:
    conn = await asyncpg.connect(_db())
    fails: list[str] = []
    try:
        admin = await auth_service.create_staff_user("admin_boot", "adminpass", "Boot", role_key="admin")
        all_perms = {r["key"] for r in await conn.fetch("SELECT key FROM permissions")}
        actor = {"id": admin["id"], "username": "admin_boot",
                 "permissions": all_perms, "rbac_provisioned": True}

        # === TEST 1: create_staff ROLLBACK khi audit fail ===
        await break_audit(conn)
        n_before = await conn.fetchval("SELECT count(*) FROM staff_users")
        try:
            await auth_router.create_staff(
                {"username": "u_rollback", "password": "secret1", "role_key": "sales"}, actor=actor)
            fails.append("create_staff: KHÔNG raise khi audit fail")
        except Exception:
            pass
        await fix_audit(conn)
        if await conn.fetchval("SELECT count(*) FROM staff_users") != n_before:
            fails.append("create_staff: KHÔNG rollback (staff count đổi)")
        if await conn.fetchval("SELECT count(*) FROM staff_users WHERE username='u_rollback'"):
            fails.append("create_staff: staff vẫn được tạo (rollback fail)")

        # === TEST 1b: create_staff THÀNH CÔNG khi audit ok (+ ghi audit) ===
        r = await auth_router.create_staff(
            {"username": "u_ok", "password": "secret1", "role_key": "sales"}, actor=actor)
        if not r.get("id"):
            fails.append("create_staff: audit ok nhưng không tạo")
        if not await conn.fetchval("SELECT count(*) FROM audit_log WHERE action='staff.create'"):
            fails.append("create_staff: audit ok nhưng không ghi audit_log")

        # === TEST 2: change_password ROLLBACK khi audit fail ===
        target = await auth_service.create_staff_user("u_pw", "oldpass1", "PW", role_key="sales")
        await break_audit(conn)
        try:
            await auth_service.change_password(
                target["id"], "newpass1", actor_staff_id=admin["id"], actor_username="admin_boot")
            fails.append("change_password: KHÔNG raise khi audit fail")
        except Exception:
            pass
        await fix_audit(conn)
        if not await auth_service.verify_current_password(target["id"], "oldpass1"):
            fails.append("change_password: mật khẩu ĐÃ đổi (rollback fail)")
    finally:
        await conn.close()

    if fails:
        print("AUDIT-ROLLBACK ENDPOINT FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("AUDIT-ROLLBACK ENDPOINT PASS: staff.create + password_change ROLLBACK mutation khi audit "
          "insert fail; audit-ok path ghi audit_log")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
