"""M4-9 — Integration test EVIDENCE cho RBAC Ratification & Hardening (Directive 70 + 70A).

Chay voi DATABASE_URL sandbox rieng. Kiem:
  [1] migration 048: role m4_signing_operator + 5 grants (least privilege).
  [2] allowlist trigger: cap quyen NGOAI 5 -> DB tu choi (chong escalation).
  [3] provision dry-run -> plan, KHONG mutation.
  [4] fail-closed: thieu actor/reason/ticket -> ProvisioningError.
  [5] provision apply -> staff gan role + AUDIT ghi audit_log; audit KHONG chua password.
  [6] refuse: username co role KHAC -> tu choi.
  [7] idempotent: provision lai -> reassigned, khong nhan doi.
  [8] revoke -> role_key NULL + audit; SoD: admin van chi view.
In "M4_9_RBAC_ALL_PASS" neu dat het.
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB_URL = os.environ.get("DATABASE_URL") or "postgresql://alpha3s:alpha3s@db:5432/alpha3s"


def _plain(u): return u.replace("+asyncpg", "")
def _check(c, n):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}")
    if not c: raise SystemExit(f"FAIL: {n}")


async def main() -> int:
    from app.services import auth_service
    from app.services.m4_signing import rbac_provisioning as rp

    admin = await asyncpg.connect(_plain(DB_URL))
    try:
        await admin.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await admin.close()
    r = subprocess.run([sys.executable, "scripts/migrate.py", "up"], cwd=str(ROOT),
                       env={**os.environ, "DATABASE_URL": DB_URL}, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout); print(r.stderr); raise SystemExit("migrate FAIL")

    c = await asyncpg.connect(_plain(DB_URL))
    try:
        # [1] role + 5 grants
        perms = sorted([x["permission_key"] for x in await c.fetch(
            "SELECT permission_key FROM role_permissions WHERE role_key='m4_signing_operator'")])
        _check(perms == sorted(rp.OPERATOR_PERMS), "1 role co dung 5 quyen (least privilege)")

        # [2] allowlist trigger chan quyen ngoai 5
        await c.execute("INSERT INTO permissions(key,description) VALUES('price.manage','x') "
                        "ON CONFLICT DO NOTHING")
        blocked = False
        try:
            await c.execute("INSERT INTO role_permissions(role_key,permission_key) "
                            "VALUES('m4_signing_operator','price.manage')")
        except asyncpg.PostgresError:
            blocked = True
        _check(blocked, "2 allowlist trigger chan cap quyen ngoai 5 (chong escalation)")

        ph, salt = auth_service._hash_password("OperatorPass123")

        # [3] dry-run khong mutation
        plan = await rp.provision_operator(c, username="signerX", name="NV", password_hash=ph,
                                           salt=salt, actor="hoai", delegated_by=None,
                                           reason="test", ticket="T-1", apply=False)
        exists = await c.fetchval("SELECT 1 FROM staff_users WHERE username='signerX'")
        _check(plan.get("dry_run") and exists is None, "3 dry-run tra plan, khong tao staff")

        # [4] fail-closed thieu authorization
        for bad in [dict(actor="", reason="r", ticket="t"), dict(actor="a", reason="", ticket="t"),
                    dict(actor="a", reason="r", ticket="")]:
            try:
                await rp.provision_operator(c, username="s", name="s", password_hash=ph, salt=salt,
                                            delegated_by=None, apply=False, **bad)
                _check(False, "4 fail-closed phai chan thieu authz")
            except rp.ProvisioningError:
                pass
        _check(True, "4 fail-closed chan thieu actor/reason/ticket")

        # [5] apply + audit
        res = await rp.provision_operator(c, username="signerX", name="NV", password_hash=ph,
                                          salt=salt, actor="hoai", delegated_by="PO",
                                          reason="cap operator", ticket="M4-9-OPS-1", apply=True)
        _check(res.get("applied") and res["result"] == "created", "5a provision apply -> created")
        srole = await c.fetchval("SELECT role_key FROM staff_users WHERE username='signerX'")
        _check(srole == "m4_signing_operator", "5b staff gan role operator")
        arow = await c.fetchrow("SELECT action,actor_ref,after::text AS a FROM audit_log "
                                "WHERE action='rbac.provision_operator' ORDER BY id DESC LIMIT 1")
        _check(arow is not None and arow["actor_ref"] == "hoai", "5c audit_log ghi provision")
        _check("OperatorPass123" not in (arow["a"] or "") and ph not in (arow["a"] or ""),
               "5d audit KHONG chua password/hash")

        # [6] refuse username co role khac
        await c.execute("INSERT INTO staff_users(username,password_hash,password_salt,name,role_key)"
                        " VALUES('bizuser','x','x','Biz','admin')")
        try:
            await rp.provision_operator(c, username="bizuser", name="Biz", password_hash=ph,
                                        salt=salt, actor="hoai", delegated_by=None, reason="r",
                                        ticket="t", apply=True)
            _check(False, "6 phai tu choi user co role khac")
        except rp.ProvisioningError:
            _check(True, "6 tu choi ghi de user co role khac (fail-closed)")

        # [7] idempotent
        res2 = await rp.provision_operator(c, username="signerX", name="NV2", password_hash=ph,
                                           salt=salt, actor="hoai", delegated_by=None,
                                           reason="lai", ticket="T-2", apply=True)
        n = await c.fetchval("SELECT count(*) FROM staff_users WHERE username='signerX'")
        _check(res2["result"] == "reassigned" and n == 1, "7 idempotent -> reassigned, khong nhan doi")

        # [8] revoke + SoD admin chi view
        rv = await rp.revoke_operator(c, username="signerX", actor="hoai", reason="thu hoi",
                                      ticket="T-3", apply=True)
        srole2 = await c.fetchval("SELECT role_key FROM staff_users WHERE username='signerX'")
        _check(rv.get("applied") and srole2 is None, "8a revoke -> role_key NULL (dormant)")
        arow2 = await c.fetchval("SELECT count(*) FROM audit_log WHERE action='rbac.revoke_operator'")
        _check(arow2 >= 1, "8b audit ghi revoke")
        adm = sorted([x["permission_key"] for x in await c.fetch(
            "SELECT permission_key FROM role_permissions WHERE role_key='admin' "
            "AND permission_key LIKE 'm4.signing.%'")])
        _check(adm == ["m4.signing.run.view"], "8c SoD: admin CHI m4.signing.run.view")
    finally:
        await c.close()
    print("M4_9_RBAC_ALL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
