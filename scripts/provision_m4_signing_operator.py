"""Provision / revoke role operator ky Tier A (M4-9, hardened — Directive 70 + 70A).

Role `m4_signing_operator` (5 quyen m4.signing.run.*) do MIGRATION 048 dinh nghia (version-controlled);
script nay CHI GAN role co dinh do cho mot staff chuyen biet (khong tao/grant quyen -> khong
escalation). Moi lan provision/revoke ghi AUDIT bat bien (audit_log). Bat buoc --actor/--reason/
--ticket (fail-closed). Ho tro --dry-run (plan truoc), --revoke (thu hoi ve dormant), --yes (xac nhan).

BAO MAT: mat khau nhap AN tu terminal (getpass, 2 lan) — khong qua lenh/env/history.
Chay trong container api (KHONG -T de co TTY):
    docker compose -f docker-compose.prod.yml exec api python scripts/provision_m4_signing_operator.py \
        <username> --actor "hoai" --ticket "M4-9-OPS-001" --reason "cap operator Tier A" --dry-run
Bo --dry-run + them --yes de thuc thi. Thu hoi: them --revoke (khong can mat khau).
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
        pw = getpass.getpass("Mat khau operator moi (go, khong hien): ")
        if pw != getpass.getpass("Nhap lai de xac nhan: "):
            print("Loi: hai lan nhap khong khop."); return None
        return pw
    pw = os.environ.get("NEW_OPERATOR_PASSWORD", "")
    if not pw:
        print("Loi: khong co TTY. Chay KHONG kem -T, hoac dat NEW_OPERATOR_PASSWORD (automation).")
    return pw or None


def _print_plan(plan: dict) -> None:
    print("--- PLAN ---")
    for k in ("action", "username", "role", "grants", "will_create", "delegated_by", "ticket",
              "existing", "dry_run", "applied", "result", "staff_id"):
        if k in plan:
            print(f"  {k}: {plan[k]}")


async def main() -> int:
    p = argparse.ArgumentParser(description="Provision/revoke operator ky Tier A")
    p.add_argument("username")
    p.add_argument("name", nargs="?", default=None)
    p.add_argument("--actor", required=True, help="nguoi thuc hien (dinh danh khong bi mat)")
    p.add_argument("--ticket", required=True, help="change ticket / authorization reference")
    p.add_argument("--reason", required=True)
    p.add_argument("--delegated-by", default=None, help="neu operator lam thay PO uy quyen")
    p.add_argument("--revoke", action="store_true", help="thu hoi role ve dormant (khong mat khau)")
    p.add_argument("--dry-run", action="store_true", help="chi in plan, khong mutation")
    p.add_argument("--yes", action="store_true", help="xac nhan apply (bat buoc khi khong dry-run)")
    args = p.parse_args()
    name = args.name or args.username

    conn = await asyncpg.connect(_db_url())
    try:
        if args.revoke:
            try:
                plan = await rp.revoke_operator(
                    conn, username=args.username, actor=args.actor, reason=args.reason,
                    ticket=args.ticket, apply=(not args.dry_run and args.yes))
            except rp.ProvisioningError as e:
                print(f"Loi: {e}"); return 2
            _print_plan(plan)
            if not args.dry_run and not args.yes:
                print("Chua apply: them --yes de xac nhan thu hoi."); return 3
            return 0

        # provision: can mat khau (tru dry-run)
        password_hash = salt = None
        if not args.dry_run:
            if not args.yes:
                # plan truoc, khong doi mat khau
                try:
                    plan = await rp.provision_operator(
                        conn, username=args.username, name=name, password_hash="x", salt="x",
                        actor=args.actor, delegated_by=args.delegated_by, reason=args.reason,
                        ticket=args.ticket, apply=False)
                except rp.ProvisioningError as e:
                    print(f"Loi: {e}"); return 2
                _print_plan(plan)
                print("Chua apply: them --yes de xac nhan (se hoi mat khau).")
                return 3
            pw = _read_password()
            if pw is None:
                return 2
            if len(pw) < 8:
                print("Loi: mat khau can toi thieu 8 ky tu."); return 2
            password_hash, salt = auth_service._hash_password(pw)  # noqa: SLF001
        try:
            plan = await rp.provision_operator(
                conn, username=args.username, name=name,
                password_hash=password_hash or "x", salt=salt or "x",
                actor=args.actor, delegated_by=args.delegated_by, reason=args.reason,
                ticket=args.ticket, apply=(not args.dry_run and args.yes))
        except rp.ProvisioningError as e:
            print(f"Loi: {e}"); return 2
        _print_plan(plan)
        if plan.get("applied"):
            print(f"OK: role {rp.OPERATOR_ROLE} gan cho '{args.username}' ({plan['result']}). "
                  "Audit da ghi. Dang nhap /login -> 'Ky transcript' (Tier A).")
            print("Luu y: assignment != activation — Execute/signing van cho Activation Gate rieng.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
