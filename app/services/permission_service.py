"""Permission service (I-B M0.4).

- KHONG cache permission (CA-REVIEW-IMPL-M0 §6): query role_permissions moi request -> revoke co
  hieu luc ngay tren moi API process, tranh "admin thu hoi quyen nhung process giu cache cu".
- Backward-compat: neu RBAC CHUA provisioned (DB truoc migration 016) -> `rbac_provisioned=False`;
  require_permission se degrade ve hanh vi require_staff_session (khong lam vo dashboard hien tai o
  moi truong 012). Sau khi 016 + seed + gan role -> enforce that.
"""


async def rbac_provisioned(conn) -> bool:
    """True neu co bang role_permissions VA cot staff_users.role_key (>= migration 016)."""
    return bool(await conn.fetchval(
        "SELECT (to_regclass('public.role_permissions') IS NOT NULL) "
        "AND EXISTS(SELECT 1 FROM information_schema.columns "
        "          WHERE table_name='staff_users' AND column_name='role_key')"
    ))


async def permissions_for_role(conn, role_key: str | None) -> set[str]:
    if not role_key:
        return set()
    rows = await conn.fetch(
        "SELECT permission_key FROM role_permissions WHERE role_key=$1", role_key)
    return {r["permission_key"] for r in rows}


async def load_staff_authz(conn, staff_id: int) -> dict:
    """Tra ve {role_key, permissions, rbac_provisioned} cho 1 staff. Feature-detect an toan."""
    if not await rbac_provisioned(conn):
        return {"role_key": None, "permissions": set(), "rbac_provisioned": False}
    role_key = await conn.fetchval("SELECT role_key FROM staff_users WHERE id=$1", staff_id)
    perms = await permissions_for_role(conn, role_key)
    return {"role_key": role_key, "permissions": perms, "rbac_provisioned": True}


async def rbac_ready(conn) -> tuple[bool, str]:
    """Startup readiness (CA-REVIEW-M0-DEV-002 §7.7): nếu RBAC ĐÃ provision (bảng+cột 016) NHƯNG
    permissions catalog hoặc role_permissions mapping RỖNG -> chưa sẵn sàng (half-provisioned) ->
    startup phải fail. Nếu chưa provision (dev/pre-016) -> ready=True (degrade hợp lệ)."""
    if not await rbac_provisioned(conn):
        return True, "RBAC chưa provision (dev/pre-016) — readiness bỏ qua"
    n_perm = await conn.fetchval("SELECT count(*) FROM permissions")
    n_map = await conn.fetchval("SELECT count(*) FROM role_permissions")
    if not n_perm:
        return False, "RBAC provisioned nhưng permissions catalog RỖNG (half-provisioned)"
    if not n_map:
        return False, "RBAC provisioned nhưng role_permissions mapping RỖNG (half-provisioned)"
    return True, f"RBAC ready (permissions={n_perm}, mappings={n_map})"
