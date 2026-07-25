#!/usr/bin/env python3
"""E9 — strict RBAC positive + negative (executable, exit code). CA-REVIEW-M0-DEV-004 §7. Không cần DB.
  docker exec -e PYTHONPATH=/srv -w /srv api python scripts/rbac_strict_test.py
"""
import asyncio
import sys

from app.api.auth import require_permission
from app.config import settings


async def main() -> int:
    fails: list[str] = []
    settings.rbac_strict = True
    # NEG: unprovisioned + strict -> 403 (không degrade sau cutover)
    try:
        await require_permission("inventory.adjust")(
            staff={"rbac_provisioned": False, "permissions": set()})
        fails.append("unprovisioned+strict: KHÔNG raise (mong đợi 403)")
    except Exception as e:
        if getattr(e, "status_code", None) != 403:
            fails.append(f"unprovisioned+strict: status {getattr(e, 'status_code', None)} (mong đợi 403)")
    # POS: provisioned + có quyền -> pass
    r = await require_permission("x.y")(staff={"rbac_provisioned": True, "permissions": {"x.y"}})
    if not r:
        fails.append("provisioned+có quyền: không pass")
    # provisioned + thiếu quyền -> 403
    try:
        await require_permission("x.y")(staff={"rbac_provisioned": True, "permissions": set()})
        fails.append("provisioned+thiếu quyền: KHÔNG raise (mong đợi 403)")
    except Exception as e:
        if getattr(e, "status_code", None) != 403:
            fails.append(f"thiếu quyền: status {getattr(e, 'status_code', None)}")

    if fails:
        print("RBAC-STRICT FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("RBAC-STRICT PASS: unprovisioned+strict->403; có quyền->pass; thiếu quyền->403")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
