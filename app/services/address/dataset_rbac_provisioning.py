"""M5 Gate A — dataset SoD role provisioning (assign-only bootstrap, mirror M4-9 rbac_provisioning).

VI SAO CAN: staff-update API (`PATCH /dashboard/auth/staff/{id}`) co self-escalation guard
(`target_perms ⊄ actor.permissions -> 403`). Khong account nao co `address.dataset.*` (chi 3 role dormant
tu migration 056 co), nen KHONG ai gan duoc holder DAU TIEN cua 3 role M5 qua API do (deadlock bootstrap).
Service nay la duong provisioning chuyen biet, co kiem soat (nhu M4 `provision_m4_signing_operator`):

- **assign-only**: KHONG dung toi password/credential (3 account da ton tai).
- **allowlist CO DINH**: dung 3 role <-> 3 quyen do migration 056 chot; input khong the chon role/quyen tuy y
  -> khong the escalation.
- **authorization fail-closed**: actor + reason + ticket bat buoc.
- **149-06 precondition**: `role_key IS NULL` truoc khi gan (khong ghi de role khac); capture prior state;
  conditional UPDATE (exact affected-row) chong race.
- **immutable AUDIT** in-transaction (fail-closed neu audit_log chua ready); TUYET DOI khong ghi secret.
- **restore**: role_key -> captured prior (= NULL) — revoke ve dormant.

Assignment != activation. Khong ingest/gate/accept/activate o day.
"""
from __future__ import annotations

from app.services import audit_service

# Allowlist CO DINH: role <-> exact permission (khop migration 056). Khong nhan role ngoai day.
ROLE_PERM = {
    "m5_dataset_custodian": "address.dataset.ingest",
    "m5_dataset_reviewer": "address.dataset.review",
    "m5_dataset_owner": "address.dataset.manage",
}


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
        raise ProvisioningError("audit_log chua provision — tu choi RBAC change khong co audit (fail-closed)")


async def _assert_role_ready(conn, role: str) -> None:
    """Role phai ton tai dung managed-state (056): is_system=false, is_active=true, va DUNG 1 quyen allowlist."""
    row = await conn.fetchrow(
        "SELECT is_system, is_active FROM roles WHERE key=$1", role)
    if row is None:
        raise ProvisioningError(f"role '{role}' chua ton tai — chay migration 056 truoc (khong tao role o day)")
    if row["is_system"] is not False or row["is_active"] is not True:
        raise ProvisioningError(f"role '{role}' state bat thuong (is_system={row['is_system']}, "
                                f"is_active={row['is_active']}) — tu choi (fail-closed)")
    perms = [r["permission_key"] for r in await conn.fetch(
        "SELECT permission_key FROM role_permissions WHERE role_key=$1", role)]
    if perms != [ROLE_PERM[role]]:
        raise ProvisioningError(f"role '{role}' grants {perms} != allowlist ['{ROLE_PERM[role]}'] — tu choi")


async def _staff(conn, *, username: str, expect_id: int | None):
    row = await conn.fetchrow(
        "SELECT id, username, role_key, is_active FROM staff_users WHERE username=$1", username)
    if row is None:
        raise ProvisioningError(f"username '{username}' khong ton tai (fail-closed)")
    if expect_id is not None and row["id"] != expect_id:
        raise ProvisioningError(
            f"immutable ID mismatch: username '{username}' co id={row['id']} != expect {expect_id} — tu choi")
    if not row["is_active"]:
        raise ProvisioningError(f"username '{username}' (id={row['id']}) khong active — tu choi")
    return row


async def assign_dataset_role(
    conn, *, username: str, role: str, expect_id: int | None,
    actor: str, reason: str, ticket: str, apply: bool,
) -> dict:
    """Gan 1 trong 3 role dataset cho account (precondition role_key IS NULL). Dry-run neu apply=False."""
    _require_auth(actor, reason, ticket)
    if role not in ROLE_PERM:
        raise ProvisioningError(f"role '{role}' khong thuoc allowlist {sorted(ROLE_PERM)} — tu choi")
    await _assert_audit_ready(conn)
    await _assert_role_ready(conn, role)
    st = await _staff(conn, username=username, expect_id=expect_id)
    if st["role_key"] is not None:  # 149-06: chi gan khi dang NULL
        raise ProvisioningError(
            f"'{username}' (id={st['id']}) role_key hien='{st['role_key']}' (ky vong NULL) — tu choi ghi de")
    plan = {"action": "assign_dataset_role", "username": username, "id": st["id"], "role": role,
            "permission": ROLE_PERM[role], "prior_role_key": None, "ticket": ticket}
    if not apply:
        plan["dry_run"] = True
        return plan
    async with conn.transaction():
        res = await conn.execute(
            "UPDATE staff_users SET role_key=$1 WHERE id=$2 AND role_key IS NULL", role, st["id"])
        if res != "UPDATE 1":
            raise ProvisioningError(f"race/precondition: role_key khong con NULL cho id={st['id']} — abort")
        await conn.execute("DELETE FROM staff_sessions WHERE staff_id=$1", st["id"])
        await audit_service.record(
            conn, actor_type="cli", action="address.dataset.role.assign", actor_ref=actor,
            actor_staff_id=st["id"], entity_type="staff_users", entity_id=username,
            before={"role_key": None}, after={"role_key": role, "permission": ROLE_PERM[role], "ticket": ticket},
            reason=reason)
    plan.update({"applied": True, "result": "assigned"})
    return plan


async def restore_dataset_role(
    conn, *, username: str, expect_id: int | None, prior_role_key: str | None,
    actor: str, reason: str, ticket: str, apply: bool,
) -> dict:
    """Khoi phuc role_key ve captured prior (149-06; = NULL). Chi khi hien dang giu 1 role M5 dataset."""
    _require_auth(actor, reason, ticket)
    if prior_role_key is not None and prior_role_key in ROLE_PERM:
        raise ProvisioningError("prior_role_key khong duoc la mot M5 dataset role (restore ve trang thai truoc)")
    await _assert_audit_ready(conn)
    st = await _staff(conn, username=username, expect_id=expect_id)
    cur = st["role_key"]
    if cur not in ROLE_PERM:
        raise ProvisioningError(
            f"'{username}' (id={st['id']}) role_key hien='{cur}' khong phai M5 dataset role — tu choi restore")
    plan = {"action": "restore_dataset_role", "username": username, "id": st["id"],
            "from_role": cur, "to_role_key": prior_role_key, "ticket": ticket}
    if not apply:
        plan["dry_run"] = True
        return plan
    async with conn.transaction():
        res = await conn.execute(
            "UPDATE staff_users SET role_key=$1 WHERE id=$2 AND role_key=$3", prior_role_key, st["id"], cur)
        if res != "UPDATE 1":
            raise ProvisioningError(f"race: role_key khong con '{cur}' cho id={st['id']} — abort")
        await conn.execute("DELETE FROM staff_sessions WHERE staff_id=$1", st["id"])
        await audit_service.record(
            conn, actor_type="cli", action="address.dataset.role.restore", actor_ref=actor,
            actor_staff_id=st["id"], entity_type="staff_users", entity_id=username,
            before={"role_key": cur}, after={"role_key": prior_role_key, "ticket": ticket}, reason=reason)
    plan.update({"applied": True, "result": "restored"})
    return plan
