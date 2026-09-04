"""M5 Gate A — dataset SoD role provisioning (assign-only bootstrap, mirror M4-9 rbac_provisioning).

VI SAO CAN: staff-update API (`PATCH /dashboard/auth/staff/{id}`) co self-escalation guard
(`target_perms ⊄ actor.permissions -> 403`). Khong account nao co `address.dataset.*` (chi 3 role dormant tu
migration 056 co), nen KHONG ai gan duoc holder DAU TIEN cua 3 role M5 qua API do (deadlock bootstrap).
Service nay la duong provisioning chuyen biet, co kiem soat (nhu M4 `provision_m4_signing_operator`):

- **assign-only**: KHONG dung toi password/credential (3 account da ton tai).
- **allowlist CO DINH**: dung 3 role <-> 3 quyen do migration 056 chot; input khong the chon role/quyen tuy y.
- **restore CHI VE NULL** (Gate A): prior_role_key BAT BUOC = None; moi gia tri khac bi tu choi (G-A-157-01: khong
  cho user-controlled restore target -> khong the escalation qua restore).
- **actor = operator that** (G-A-157-02): actor phai resolve toi mot account active, KHAC target; audit
  `actor_staff_id` = operator id (KHONG bao gio la target id).
- **immutable id BAT BUOC** (G-A-157-03): expect_id required; conditional UPDATE bind id + username + role-state.
- **149-06 precondition**: assign chi khi `role_key IS NULL`; capture prior; conditional affected-row check.
- **immutable AUDIT** in-transaction (fail-closed neu audit_log chua ready); TUYET DOI khong ghi secret.

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
        raise ProvisioningError("thieu --actor (operator dinh danh)")
    if not (reason and reason.strip()):
        raise ProvisioningError("thieu --reason")
    if not (ticket and ticket.strip()):
        raise ProvisioningError("thieu --ticket (change ticket / authorization reference)")


async def _assert_audit_ready(conn) -> None:
    if not await audit_service.audit_exists(conn):
        raise ProvisioningError("audit_log chua provision — tu choi RBAC change khong co audit (fail-closed)")


async def _assert_role_ready(conn, role: str) -> None:
    """Role phai ton tai dung managed-state (056): is_system=false, is_active=true, va DUNG 1 quyen allowlist."""
    row = await conn.fetchrow("SELECT is_system, is_active FROM roles WHERE key=$1", role)
    if row is None:
        raise ProvisioningError(f"role '{role}' chua ton tai — chay migration 056 truoc (khong tao role o day)")
    if row["is_system"] is not False or row["is_active"] is not True:
        raise ProvisioningError(f"role '{role}' state bat thuong (is_system={row['is_system']}, "
                                f"is_active={row['is_active']}) — tu choi (fail-closed)")
    perms = [r["permission_key"] for r in await conn.fetch(
        "SELECT permission_key FROM role_permissions WHERE role_key=$1 ORDER BY permission_key", role)]
    if perms != [ROLE_PERM[role]]:
        raise ProvisioningError(f"role '{role}' grants {perms} != allowlist ['{ROLE_PERM[role]}'] — tu choi")


async def _resolve_operator(conn, actor: str, *, target_id: int) -> int:
    """Operator (actor) phai la mot account active, va KHAC target (khong self-assign/self-restore).
    Bind actor_staff_id ve dung operator (G-A-157-02); KHONG suy tu target."""
    row = await conn.fetchrow("SELECT id, is_active FROM staff_users WHERE username=$1", actor)
    if row is None or not row["is_active"]:
        raise ProvisioningError(f"operator '{actor}' khong phai account active — tu choi (khong xac dinh actor)")
    if row["id"] == target_id:
        raise ProvisioningError(f"operator '{actor}' trung target (id={target_id}) — tu choi self-mutation")
    return row["id"]


async def _staff(conn, *, username: str, expect_id: int):
    if expect_id is None:
        raise ProvisioningError("thieu expect_id (immutable staff id BAT BUOC — G-A-157-03)")
    row = await conn.fetchrow(
        "SELECT id, username, role_key, is_active FROM staff_users WHERE username=$1", username)
    if row is None:
        raise ProvisioningError(f"username '{username}' khong ton tai (fail-closed)")
    if row["id"] != expect_id:
        raise ProvisioningError(
            f"immutable ID mismatch: username '{username}' co id={row['id']} != expect {expect_id} — tu choi")
    if not row["is_active"]:
        raise ProvisioningError(f"username '{username}' (id={row['id']}) khong active — tu choi")
    return row


async def assign_dataset_role(
    conn, *, username: str, role: str, expect_id: int,
    actor: str, reason: str, ticket: str, apply: bool,
) -> dict:
    """Gan 1 trong 3 role dataset cho account (precondition role_key IS NULL). Dry-run neu apply=False."""
    _require_auth(actor, reason, ticket)
    if role not in ROLE_PERM:
        raise ProvisioningError(f"role '{role}' khong thuoc allowlist {sorted(ROLE_PERM)} — tu choi")
    await _assert_audit_ready(conn)
    await _assert_role_ready(conn, role)
    st = await _staff(conn, username=username, expect_id=expect_id)
    operator_id = await _resolve_operator(conn, actor, target_id=st["id"])
    if st["role_key"] is not None:  # 149-06: chi gan khi dang NULL
        raise ProvisioningError(
            f"'{username}' (id={st['id']}) role_key hien='{st['role_key']}' (ky vong NULL) — tu choi ghi de")
    plan = {"action": "assign_dataset_role", "username": username, "id": st["id"], "role": role,
            "permission": ROLE_PERM[role], "prior_role_key": None, "operator": actor,
            "operator_id": operator_id, "ticket": ticket}
    if not apply:
        plan["dry_run"] = True
        return plan
    async with conn.transaction():
        res = await conn.execute(
            "UPDATE staff_users SET role_key=$1 WHERE id=$2 AND username=$3 AND role_key IS NULL",
            role, st["id"], username)
        if res != "UPDATE 1":
            raise ProvisioningError(f"race/precondition: khong con NULL/khop cho id={st['id']} — abort")
        await conn.execute("DELETE FROM staff_sessions WHERE staff_id=$1", st["id"])
        await audit_service.record(
            conn, actor_type="cli", action="address.dataset.role.assign", actor_ref=actor,
            actor_staff_id=operator_id, entity_type="staff_users", entity_id=username,
            before={"role_key": None}, after={"role_key": role, "permission": ROLE_PERM[role],
                                              "target_id": st["id"], "ticket": ticket}, reason=reason)
    plan.update({"applied": True, "result": "assigned"})
    return plan


async def restore_dataset_role(
    conn, *, username: str, expect_id: int, prior_role_key: str | None,
    actor: str, reason: str, ticket: str, apply: bool,
) -> dict:
    """Khoi phuc role_key ve NULL (Gate A). prior_role_key BAT BUOC = None (G-A-157-01: khong nhan role target)."""
    _require_auth(actor, reason, ticket)
    if prior_role_key is not None:
        raise ProvisioningError(
            "prior_role_key phai la None — restore Gate A CHI ve NULL (khong nhan role target, chong escalation)")
    await _assert_audit_ready(conn)
    st = await _staff(conn, username=username, expect_id=expect_id)
    operator_id = await _resolve_operator(conn, actor, target_id=st["id"])
    cur = st["role_key"]
    if cur not in ROLE_PERM:
        raise ProvisioningError(
            f"'{username}' (id={st['id']}) role_key hien='{cur}' khong phai M5 dataset role — tu choi restore")
    plan = {"action": "restore_dataset_role", "username": username, "id": st["id"],
            "from_role": cur, "to_role_key": None, "operator": actor, "operator_id": operator_id, "ticket": ticket}
    if not apply:
        plan["dry_run"] = True
        return plan
    async with conn.transaction():
        res = await conn.execute(
            "UPDATE staff_users SET role_key=NULL WHERE id=$1 AND username=$2 AND role_key=$3",
            st["id"], username, cur)
        if res != "UPDATE 1":
            raise ProvisioningError(f"race: role_key khong con '{cur}'/khop cho id={st['id']} — abort")
        await conn.execute("DELETE FROM staff_sessions WHERE staff_id=$1", st["id"])
        await audit_service.record(
            conn, actor_type="cli", action="address.dataset.role.restore", actor_ref=actor,
            actor_staff_id=operator_id, entity_type="staff_users", entity_id=username,
            before={"role_key": cur}, after={"role_key": None, "target_id": st["id"], "ticket": ticket},
            reason=reason)
    plan.update({"applied": True, "result": "restored"})
    return plan
