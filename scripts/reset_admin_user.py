"""Reset / bootstrap admin dashboard (break-glass, hardened — Directive 70).

Create-or-reset admin (khong can mat khau cu). Moi lan ghi AUDIT bat bien (audit_log). Bat buoc
--actor/--reason/--ticket (fail-closed). Ho tro --dry-run + --yes (xac nhan). Hash PBKDF2 200k khop
auth_service. Mat khau nhap AN tu terminal (getpass) — khong qua lenh/env/history.

Chay trong container api (KHONG -T de co TTY):
    docker compose -f docker-compose.prod.yml exec api python scripts/reset_admin_user.py \
        <username> --actor "hoai" --ticket "M4-9-OPS-002" --reason "reset admin" --dry-run
Bo --dry-run + them --yes de thuc thi (se hoi mat khau).
"""
import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.config import settings  # noqa: E402
from app.services import auth_service  # noqa: E402
from app.services.m4_signing import rbac_provisioning as rp  # noqa: E402


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _read_password() -> str | None:
    if sys.stdin.isatty():
        pw = getpass.getpass("Mat khau admin moi (go, khong hien): ")
        if pw != getpass.getpass("Nhap lai de xac nhan: "):
            print("Loi: hai lan nhap khong khop."); return None
        return pw
    pw = os.environ.get("NEW_ADMIN_PASSWORD", "")
    if not pw:
        print("Loi: khong co TTY. Chay KHONG kem -T, hoac dat NEW_ADMIN_PASSWORD (automation).")
    return pw or None


async def main() -> int:
    p = argparse.ArgumentParser(description="Break-glass create-or-reset admin dashboard")
    p.add_argument("username")
    p.add_argument("name", nargs="?", default=None)
    p.add_argument("--actor", required=True)
    p.add_argument("--ticket", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true")
    args = p.parse_args()
    name = args.name or args.username

    conn = await asyncpg.connect(_db_url())
    try:
        if not args.dry_run and not args.yes:
            try:
                plan = await rp.reset_admin(conn, username=args.username, name=name,
                                            password_hash="x", salt="x", actor=args.actor,
                                            reason=args.reason, ticket=args.ticket, apply=False)
            except rp.ProvisioningError as e:
                print(f"Loi: {e}"); return 2
            print("--- PLAN ---")
            for k, v in plan.items():
                print(f"  {k}: {v}")
            print("Chua apply: them --yes de xac nhan (se hoi mat khau).")
            return 3

        password_hash = salt = None
        if not args.dry_run:
            pw = _read_password()
            if pw is None:
                return 2
            if len(pw) < 8:
                print("Loi: mat khau can toi thieu 8 ky tu."); return 2
            password_hash, salt = auth_service._hash_password(pw)  # noqa: SLF001

        try:
            plan = await rp.reset_admin(
                conn, username=args.username, name=name,
                password_hash=password_hash or "x", salt=salt or "x",
                actor=args.actor, reason=args.reason, ticket=args.ticket,
                apply=(not args.dry_run and args.yes))
        except rp.ProvisioningError as e:
            print(f"Loi: {e}"); return 2
        print("--- PLAN ---")
        for k, v in plan.items():
            print(f"  {k}: {v}")
        if plan.get("applied"):
            print(f"OK: admin '{args.username}' ({plan['result']}). Audit da ghi. Dang nhap /login.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
