"""M4-9 — Service provisioning RBAC operator (ratification & hardening, Directive 70 + 70A).

Cung cap logic dung chung cho CLI break-glass provision/revoke operator ky + reset admin, voi cac
control CA yeu cau:
- authorization bat buoc: actor + reason + ticket (fail-closed neu thieu);
- allowlist: role CO DINH `m4_signing_operator` (khong nhan role/grant tuy y tu input); grants do
  migration 048 chot (script CHI GAN role, khong tao/grant quyen -> khong the escalation);
- idempotent + dry-run (plan truoc apply);
- immutable AUDIT qua audit_service.record (audit_log, redact secret) — bat buoc, fail-closed neu
  audit_log chua provision; TUYET DOI khong ghi password/PIN/token;
- fail-closed neu user/role/scope bat thuong.

KHONG start signer, khong cap quyen production signing/KMS/WIF. Assignment != activation.
"""
from __future__ import annotations

from app.services import audit_service

OPERATOR_ROLE = "m4_signing_operator"
OPERATOR_PERMS = (
    "m4.signing.run.view", "m4.signing.run.start", "m4.signing.run.operate",
    "m4.signing.run.approve", "m4.signing.run.abort",
)


class ProvisioningError(Exception):
    """Loi provisioning (fail-closed). Khong leak secret."""


def _require_auth(actor: str | None, reason: str | None, ticket: str | None) -> None:
    if not (actor and actor.strip()):
        raise ProvisioningError("thieu --actor (nguoi thuc hien, dinh danh khong bi mat)")
    if not (reason and reason.strip()):
        raise ProvisioningError("thieu --reason")
    if not (ticket and ticket.strip()):
        raise ProvisioningError("thieu --ticket (change ticket / authorization reference)")


async def _assert_audit_ready(conn) -> None:
    if not await audit_service.audit_exists(conn):
        raise ProvisioningError("audit_log chua provision (migration 015) — tu choi RBAC change "
                                "khong co audit (fail-closed)")


async def _role_ready(conn) -> None:
    ok = await conn.fetchval("SELECT 1 FROM roles WHERE key=$1", OPERATOR_ROLE)
    if not ok:
        raise ProvisioningError(
            f"role '{OPERATOR_ROLE}' chua ton tai — chay migration 048 truoc (role/grants phai "
            "version-controlled, khong tao tay o day)")


async def _staff_state(conn, username: str) -> dict | None:
    row = await conn.fetchrow(
        "SELECT id, role_key, is_active FROM staff_users WHERE username=$1", username)
    return dict(row) if row else None


async def provision_operator(
    conn, *, username: str, name: str, password_hash: str, salt: str,
    actor: str, delegated_by: str | None, reason: str, ticket: str, apply: bool,
) -> dict:
    """Gan role operator (co dinh) cho staff (create-or-update). Dry-run neu apply=False.

    Fail-closed neu username da ton tai voi role KHAC (khong dam vao tai khoan nghiep vu).
    """
    _require_auth(actor, reason, ticket)
    await _assert_audit_ready(conn)
    await _role_ready(conn)
    has_mcp = await _has_col(conn, "must_change_password")

    existing = await _staff_state(conn, username)
    if existing and existing["role_key"] not in (None, OPERATOR_ROLE):
        raise ProvisioningError(
            f"username '{username}' dang co role '{existing['role_key']}' — tu choi ghi de "
            f"(dung username MOI cho operator chuyen biet)")

    plan = {
        "action": "provision_operator",
        "username": username, "role": OPERATOR_ROLE, "grants": list(OPERATOR_PERMS),
        "existing": existing, "will_create": existing is None,
        "delegated_by": delegated_by, "ticket": ticket,
    }
    if not apply:
        plan["dry_run"] = True
        return plan

    async with conn.transaction():
        if existing is None:
            staff_id = await conn.fetchval(
                "INSERT INTO staff_users (username,password_hash,password_salt,name,role_key,"
                "is_active) VALUES ($1,$2,$3,$4,$5,true) RETURNING id",
                username, password_hash, salt, name, OPERATOR_ROLE)
            result = "created"
        else:
            staff_id = existing["id"]
            sets = ["password_hash=$2", "password_salt=$3", "name=$4", "role_key=$5", "is_active=true"]
            if has_mcp:
                sets.append("must_change_password=false")
            await conn.execute(f"UPDATE staff_users SET {', '.join(sets)} WHERE id=$1",
                               staff_id, password_hash, salt, name, OPERATOR_ROLE)
            await conn.execute("DELETE FROM staff_sessions WHERE staff_id=$1", staff_id)
            result = "reassigned"
        # AUDIT bat buoc trong CUNG transaction (fail-closed). KHONG ghi password/salt.
        await audit_service.record(
            conn, actor_type="cli", action="rbac.provision_operator",
            actor_ref=actor, actor_staff_id=staff_id, entity_type="staff_users",
            entity_id=username,
            before={"role": (existing or {}).get("role_key")} if existing else None,
            after={"role": OPERATOR_ROLE, "grants": list(OPERATOR_PERMS),
                   "delegated_by": delegated_by, "ticket": ticket, "result": result},
            reason=reason)
    plan.update({"applied": True, "staff_id": staff_id, "result": result})
    return plan


async def revoke_operator(
    conn, *, username: str, actor: str, reason: str, ticket: str, apply: bool,
) -> dict:
    """Thu hoi role operator khoi staff -> ve dormant (role_key=NULL). Dry-run neu apply=False."""
    _require_auth(actor, reason, ticket)
    await _assert_audit_ready(conn)
    existing = await _staff_state(conn, username)
    if existing is None:
        raise ProvisioningError(f"username '{username}' khong ton tai")
    if existing["role_key"] != OPERATOR_ROLE:
        raise ProvisioningError(
            f"username '{username}' khong giu role '{OPERATOR_ROLE}' (dang '{existing['role_key']}') "
            "— tu choi revoke (fail-closed)")
    plan = {"action": "revoke_operator", "username": username, "existing": existing, "ticket": ticket}
    if not apply:
        plan["dry_run"] = True
        return plan
    async with conn.transaction():
        await conn.execute("UPDATE staff_users SET role_key=NULL WHERE id=$1", existing["id"])
        await conn.execute("DELETE FROM staff_sessions WHERE staff_id=$1", existing["id"])
        await audit_service.record(
            conn, actor_type="cli", action="rbac.revoke_operator",
            actor_ref=actor, actor_staff_id=existing["id"], entity_type="staff_users",
            entity_id=username, before={"role": OPERATOR_ROLE},
            after={"role": None, "ticket": ticket, "result": "revoked"}, reason=reason)
    plan.update({"applied": True, "result": "revoked"})
    return plan


async def reset_admin(
    conn, *, username: str, name: str, password_hash: str, salt: str,
    actor: str, reason: str, ticket: str, apply: bool,
) -> dict:
    """Break-glass create-or-reset admin + audit. Dry-run neu apply=False."""
    _require_auth(actor, reason, ticket)
    await _assert_audit_ready(conn)
    has_role = await _has_col(conn, "role_key")
    has_mcp = await _has_col(conn, "must_change_password")
    if has_role:
        if not await conn.fetchval("SELECT 1 FROM roles WHERE key='admin'"):
            has_role = False  # DB chua co RBAC day du -> bo qua gan role
    existing = await _staff_state(conn, username)
    plan = {"action": "reset_admin", "username": username, "existing": existing,
            "will_create": existing is None, "ticket": ticket}
    if not apply:
        plan["dry_run"] = True
        return plan
    async with conn.transaction():
        if existing is None:
            cols = "username,password_hash,password_salt,name"
            vals = "$1,$2,$3,$4"
            params = [username, password_hash, salt, name]
            if has_role:
                cols += ",role_key"
                vals += ",$5"
                params.append("admin")
            staff_id = await conn.fetchval(
                f"INSERT INTO staff_users ({cols},is_active) VALUES ({vals},true) RETURNING id",
                *params)
            result = "created"
        else:
            staff_id = existing["id"]
            sets = ["password_hash=$2", "password_salt=$3", "name=$4", "is_active=true"]
            params = [staff_id, password_hash, salt, name]
            if has_role:
                sets.append("role_key='admin'")
            if has_mcp:
                sets.append("must_change_password=false")
            await conn.execute(f"UPDATE staff_users SET {', '.join(sets)} WHERE id=$1", *params)
            await conn.execute("DELETE FROM staff_sessions WHERE staff_id=$1", staff_id)
            result = "reset"
        await audit_service.record(
            conn, actor_type="cli", action="rbac.reset_admin",
            actor_ref=actor, actor_staff_id=staff_id, entity_type="staff_users",
            entity_id=username, before={"existed": existing is not None},
            after={"role": "admin" if has_role else None, "ticket": ticket, "result": result},
            reason=reason)
    plan.update({"applied": True, "staff_id": staff_id, "result": result})
    return plan


async def _has_col(conn, col: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_name='staff_users' AND column_name=$1",
        col))
