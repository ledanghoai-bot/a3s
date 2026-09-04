"""M5 Gate A — dataset SoD role provisioning (assign-only bootstrap, mirror M4-9 rbac_provisioning).

VI SAO CAN: staff-update API (`PATCH /dashboard/auth/staff/{id}`) co self-escalation guard chan bootstrap
(khong account nao co `address.dataset.*` de cap holder DAU TIEN cua 3 role M5 tu migration 056). Service nay la
duong provisioning chuyen biet, co kiem soat.

TRUST BOUNDARY (G-A-158-01): day la **privileged operational CLI** — attested boi external execution boundary
(chi chay duoc bang `docker compose exec api ...` = quyen truy cap container production, da kiem soat). Service
KHONG the authenticate caller, nen:
  - claimed operator (`--actor`) la CLAIMED identity, ghi lam PROVENANCE, KHONG ghi lam authenticated actor
    (`actor_staff_id=NULL`); tach claimed username khoi verified executor.
  - Guardrail authority bootstrap: claimed operator phai resolve toi account active CO quyen `staff.manage`
    (khong chi active), va KHAC target.

Kiem soat khac:
  - **allowlist CO DINH** 3 role <-> 3 quyen (056); **restore CHI ve NULL** (prior_role_key phai None, chong
    escalation — G-A-157-01); **immutable id BAT BUOC** (G-A-157-03).
  - **149-06** assign chi khi role_key NULL; capture prior.
  - **G-A-158-02**: MOI validation (role def, target active, operator authority, role_key) chay TRONG transaction;
    target va operator row `SELECT ... FOR UPDATE` (revalidate + lock tai thoi diem mutation) -> khong race.
  - immutable AUDIT in-tx (fail-closed neu audit chua ready); TUYET DOI khong ghi secret.
"""
from __future__ import annotations

from app.services import audit_service

ROLE_PERM = {
    "m5_dataset_custodian": "address.dataset.ingest",
    "m5_dataset_reviewer": "address.dataset.review",
    "m5_dataset_owner": "address.dataset.manage",
}
BOOTSTRAP_PERM = "staff.manage"  # authority bootstrap: claimed operator phai co quyen quan ly staff


class ProvisioningError(Exception):
    """Loi provisioning (fail-closed). Khong leak secret."""


def _require_auth(actor: str | None, reason: str | None, ticket: str | None) -> None:
    if not (actor and actor.strip()):
        raise ProvisioningError("thieu --actor (claimed operator)")
    if not (reason and reason.strip()):
        raise ProvisioningError("thieu --reason")
    if not (ticket and ticket.strip()):
        raise ProvisioningError("thieu --ticket (change ticket / authorization reference)")


async def _assert_audit_ready(conn) -> None:
    if not await audit_service.audit_exists(conn):
        raise ProvisioningError("audit_log chua provision — tu choi RBAC change khong co audit (fail-closed)")


async def _role_def_ok(conn, role: str) -> None:
    """Role dung managed-state (056): is_system=false, is_active=true, DUNG 1 quyen allowlist. Goi TRONG tx."""
    row = await conn.fetchrow("SELECT is_system, is_active FROM roles WHERE key=$1", role)
    if row is None:
        raise ProvisioningError(f"role '{role}' chua ton tai — chay migration 056 truoc")
    if row["is_system"] is not False or row["is_active"] is not True:
        raise ProvisioningError(f"role '{role}' state bat thuong (is_system={row['is_system']}, "
                                f"is_active={row['is_active']}) — tu choi")
    perms = [r["permission_key"] for r in await conn.fetch(
        "SELECT permission_key FROM role_permissions WHERE role_key=$1 ORDER BY permission_key", role)]
    if perms != [ROLE_PERM[role]]:
        raise ProvisioningError(f"role '{role}' grants {perms} != ['{ROLE_PERM[role]}'] — tu choi")


async def _lock_target(conn, *, username: str, expect_id: int):
    """Lock + revalidate target trong tx (G-A-158-02). expect_id BAT BUOC (G-A-157-03)."""
    if expect_id is None:
        raise ProvisioningError("thieu expect_id (immutable staff id BAT BUOC — G-A-157-03)")
    row = await conn.fetchrow(
        "SELECT id, username, role_key, is_active FROM staff_users WHERE username=$1 FOR UPDATE", username)
    if row is None:
        raise ProvisioningError(f"username '{username}' khong ton tai (fail-closed)")
    if row["id"] != expect_id:
        raise ProvisioningError(f"immutable ID mismatch: '{username}' id={row['id']} != expect {expect_id}")
    if not row["is_active"]:
        raise ProvisioningError(f"target '{username}' (id={row['id']}) khong active tai mutation — tu choi")
    return row


async def _verify_operator_claim(conn, actor: str, *, target_id: int) -> int:
    """CLAIMED operator (attested-CLI, KHONG authenticate caller). Guardrail: active + co quyen staff.manage +
    KHAC target. Lock operator row trong tx. Tra ve claimed id de ghi PROVENANCE (khong lam authenticated actor)."""
    row = await conn.fetchrow("SELECT id, is_active, role_key FROM staff_users WHERE username=$1 FOR UPDATE", actor)
    if row is None or not row["is_active"]:
        raise ProvisioningError(f"claimed operator '{actor}' khong phai account active — tu choi")
    if row["id"] == target_id:
        raise ProvisioningError(f"claimed operator '{actor}' trung target (id={target_id}) — tu choi self-mutation")
    can = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM role_permissions WHERE role_key=$1 AND permission_key=$2)",
        row["role_key"], BOOTSTRAP_PERM)
    if not can:
        raise ProvisioningError(f"claimed operator '{actor}' thieu quyen '{BOOTSTRAP_PERM}' "
                                "(authority bootstrap) — tu choi")
    return row["id"]


def _audit_after(role_or_none, *, target_id, actor, op_id, ticket, perm=None) -> dict:
    a = {"role_key": role_or_none, "target_id": target_id, "claimed_operator": actor,
         "claimed_operator_id": op_id, "attested_via": "privileged-cli", "ticket": ticket}
    if perm is not None:
        a["permission"] = perm
    return a


async def assign_dataset_role(
    conn, *, username: str, role: str, expect_id: int,
    actor: str, reason: str, ticket: str, apply: bool,
) -> dict:
    """Gan 1 trong 3 role dataset (precondition role_key IS NULL). Moi kiem tra + mutation trong 1 transaction."""
    _require_auth(actor, reason, ticket)
    if role not in ROLE_PERM:
        raise ProvisioningError(f"role '{role}' khong thuoc allowlist {sorted(ROLE_PERM)} — tu choi")
    await _assert_audit_ready(conn)
    plan = {"action": "assign_dataset_role", "username": username, "id": expect_id, "role": role,
            "permission": ROLE_PERM[role], "prior_role_key": None, "operator": actor, "ticket": ticket}
    if not apply:
        plan["dry_run"] = True
        return plan
    async with conn.transaction():
        await _role_def_ok(conn, role)
        st = await _lock_target(conn, username=username, expect_id=expect_id)
        op_id = await _verify_operator_claim(conn, actor, target_id=st["id"])
        if st["role_key"] is not None:
            raise ProvisioningError(
                f"'{username}' (id={st['id']}) role_key hien='{st['role_key']}' (ky vong NULL) — tu choi ghi de")
        res = await conn.execute(
            "UPDATE staff_users SET role_key=$1 WHERE id=$2 AND username=$3 AND role_key IS NULL",
            role, st["id"], username)
        if res != "UPDATE 1":
            raise ProvisioningError(f"race: khong con NULL/khop cho id={st['id']} — abort")
        await conn.execute("DELETE FROM staff_sessions WHERE staff_id=$1", st["id"])
        await audit_service.record(
            conn, actor_type="cli", action="address.dataset.role.assign", actor_ref=f"claimed-cli:{actor}",
            actor_staff_id=None, entity_type="staff_users", entity_id=username, before={"role_key": None},
            after=_audit_after(role, target_id=st["id"], actor=actor, op_id=op_id, ticket=ticket,
                               perm=ROLE_PERM[role]), reason=reason)
    plan.update({"applied": True, "result": "assigned", "id": st["id"], "operator_id_claimed": op_id})
    return plan


async def restore_dataset_role(
    conn, *, username: str, expect_id: int, prior_role_key: str | None,
    actor: str, reason: str, ticket: str, apply: bool,
) -> dict:
    """Khoi phuc role_key ve NULL. prior_role_key BAT BUOC = None (G-A-157-01). Kiem tra + mutation trong 1 tx."""
    _require_auth(actor, reason, ticket)
    if prior_role_key is not None:
        raise ProvisioningError(
            "prior_role_key phai la None — restore Gate A CHI ve NULL (khong nhan role target, chong escalation)")
    await _assert_audit_ready(conn)
    plan = {"action": "restore_dataset_role", "username": username, "id": expect_id,
            "to_role_key": None, "operator": actor, "ticket": ticket}
    if not apply:
        plan["dry_run"] = True
        return plan
    async with conn.transaction():
        st = await _lock_target(conn, username=username, expect_id=expect_id)
        op_id = await _verify_operator_claim(conn, actor, target_id=st["id"])
        cur = st["role_key"]
        if cur not in ROLE_PERM:
            raise ProvisioningError(
                f"'{username}' (id={st['id']}) role_key hien='{cur}' khong phai M5 dataset role — tu choi restore")
        res = await conn.execute(
            "UPDATE staff_users SET role_key=NULL WHERE id=$1 AND username=$2 AND role_key=$3",
            st["id"], username, cur)
        if res != "UPDATE 1":
            raise ProvisioningError(f"race: role_key khong con '{cur}'/khop cho id={st['id']} — abort")
        await conn.execute("DELETE FROM staff_sessions WHERE staff_id=$1", st["id"])
        await audit_service.record(
            conn, actor_type="cli", action="address.dataset.role.restore", actor_ref=f"claimed-cli:{actor}",
            actor_staff_id=None, entity_type="staff_users", entity_id=username, before={"role_key": cur},
            after=_audit_after(None, target_id=st["id"], actor=actor, op_id=op_id, ticket=ticket), reason=reason)
    plan.update({"applied": True, "result": "restored", "id": st["id"], "from_role": cur, "operator_id_claimed": op_id})
    return plan
