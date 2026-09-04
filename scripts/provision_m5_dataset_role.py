"""Gan / khoi phuc role dataset SoD M5 (Gate A bootstrap) — mirror provision_m4_signing_operator.

3 role (`m5_dataset_custodian`/`reviewer`/`owner`) + grants do MIGRATION 056 chot (version-controlled).
Script nay CHI GAN 1 trong 3 role co dinh cho 1 account da ton tai (assign-only, khong password, khong
tao/grant quyen -> khong escalation). Can vi staff-update API co self-escalation guard chan bootstrap.

Fail-closed: --actor/--reason/--ticket bat buoc; precondition role_key IS NULL (149-06); audit bat bien.
Ho tro --dry-run (plan truoc), --yes (xac nhan apply), --restore (ve dormant: role_key -> NULL).

Chay trong container api (deployed control, actor tuong minh):
    docker compose -f docker-compose.prod.yml exec -T api python scripts/provision_m5_dataset_role.py \
        po-hoai --role m5_dataset_owner --id 10 --actor hoai --ticket GATEA-XXX \
        --reason "M5 Gate A grant" --dry-run
Bo --dry-run + --yes de thuc thi. Restore: them --restore (bo --role; role hien phai la M5 dataset role).
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.address import dataset_rbac_provisioning as rp  # noqa: E402


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _print_plan(plan: dict) -> None:
    print("--- PLAN ---")
    for k in ("action", "username", "id", "role", "permission", "prior_role_key", "from_role",
              "to_role_key", "ticket", "dry_run", "applied", "result"):
        if k in plan:
            print(f"  {k}: {plan[k]}")


async def main() -> int:
    p = argparse.ArgumentParser(description="Gan/khoi phuc role dataset SoD M5 (Gate A bootstrap)")
    p.add_argument("username")
    p.add_argument("--role", choices=sorted(rp.ROLE_PERM), help="role can gan (bo qua khi --restore)")
    p.add_argument("--id", type=int, default=None, help="immutable staff id de doi chieu (khuyen nghi)")
    p.add_argument("--actor", required=True, help="nguoi thuc hien (dinh danh khong bi mat)")
    p.add_argument("--ticket", required=True, help="change ticket / authorization reference")
    p.add_argument("--reason", required=True)
    p.add_argument("--restore", action="store_true", help="khoi phuc role_key ve NULL (revoke)")
    p.add_argument("--prior-role-key", default=None, help="captured prior role_key de restore (mac dinh NULL)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true", help="xac nhan apply (bat buoc neu khong --dry-run)")
    a = p.parse_args()

    apply = not a.dry_run
    if apply and not a.yes:
        print("Loi: thieu --yes de xac nhan apply (hoac dung --dry-run).")
        return 2
    if not a.restore and not a.role:
        print("Loi: thieu --role (hoac dung --restore).")
        return 2

    conn = await asyncpg.connect(_db_url())
    try:
        if a.restore:
            plan = await rp.restore_dataset_role(
                conn, username=a.username, expect_id=a.id, prior_role_key=a.prior_role_key,
                actor=a.actor, reason=a.reason, ticket=a.ticket, apply=apply)
        else:
            plan = await rp.assign_dataset_role(
                conn, username=a.username, role=a.role, expect_id=a.id,
                actor=a.actor, reason=a.reason, ticket=a.ticket, apply=apply)
        _print_plan(plan)
        return 0
    except rp.ProvisioningError as e:
        print(f"FAIL (fail-closed): {e}")
        return 1
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
