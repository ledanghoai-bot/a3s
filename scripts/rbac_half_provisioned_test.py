#!/usr/bin/env python3
"""E10 — half-provisioned detect (executable, exit code). CA-REVIEW-M0-DEV-004 §7.

Chạy trên DB đã áp 016 (tables/columns/permissions) NHƯNG chưa seed role_permissions (018)
-> rbac_provisioned=True, rbac_ready=False (half-provisioned). Chứng minh readiness KHÔNG cho
boot lên trạng thái nửa vời (đúng fail-closed).
  docker exec -e DATABASE_URL=<001-016 DB> -e PYTHONPATH=/srv -w /srv api \
      python scripts/rbac_half_provisioned_test.py

Exit: 0 = đúng half-provisioned (ready=False); 1 = SAI (ready=True); 2 = DB chưa provisioned (skip).
"""
import asyncio
import sys

import asyncpg

from app.config import settings
from app.services import permission_service


def _db() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def main() -> int:
    conn = await asyncpg.connect(_db())
    try:
        provisioned = await permission_service.rbac_provisioned(conn)
        ready, reason = await permission_service.rbac_ready(conn)
    finally:
        await conn.close()

    if not provisioned:
        print("HALF-PROVISIONED SKIP: DB chưa provisioned (cần áp 001-016 rồi chạy lại)")
        return 2
    if ready:
        print(f"HALF-PROVISIONED FAIL: rbac_ready=True (mong đợi False khi chưa seed 018): {reason}")
        return 1
    print(f"HALF-PROVISIONED PASS: provisioned=True nhưng rbac_ready=False ({reason}) "
          f"-> readiness fail-closed, không boot trạng thái nửa vời")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
