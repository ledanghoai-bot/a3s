"""Router login/logout/me/quan ly tai khoan nhan vien (issue #8 Bat 4; I-B M0.4/M0.5 hardening).

Mount tai prefix /dashboard/auth trong app/main.py. /login goi duoc TRUOC khi co token.

I-B M0 (CA-REVIEW-IMPL-M0 §12 + CA-REVIEW-M0-DEV): login throttling da chieu; staff CRUD gate
require_permission('staff.manage') + last-admin guard + no privilege-escalation + audit fail-closed;
doi mat khau (revoke session). Backward-compat: DB truoc 016/017 -> require_permission degrade, audit
bo qua neu chua co bang audit_log.
"""
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import require_permission, require_staff_session
from app.services import audit_service, auth_service, permission_service
from app.security import throttle

router = APIRouter(prefix="/dashboard/auth", tags=["auth"])

_GENERIC_LOGIN_ERR = "Sai username hoac password"  # KHONG tiet lo tai khoan ton tai (CA §12.3)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _audit_exists(conn) -> bool:
    return bool(await conn.fetchval("SELECT to_regclass('public.audit_log') IS NOT NULL"))


@router.post("/login")
async def login(body: dict, request: Request) -> dict:
    username = (body or {}).get("username")
    password = (body or {}).get("password")
    if not username or not password:
        raise HTTPException(status_code=422, detail="Thieu username hoac password")
    uname = throttle.normalize_username(username)
    ip = _client_ip(request)
    if await throttle.is_locked(uname, ip):
        raise HTTPException(status_code=429, detail="Quá nhiều lần thử. Vui lòng thử lại sau ít phút.")
    staff = await auth_service.authenticate(username, password)
    if staff is None:
        await throttle.record_failure(uname, ip)
        await audit_service.record_best_effort(
            "api", "auth.login_failed", actor_ref=uname, reason=f"ip={ip}")
        raise HTTPException(status_code=401, detail=_GENERIC_LOGIN_ERR)
    await throttle.reset_user(uname)
    token = await auth_service.create_session(staff["id"])
    # last_login_at (feature-detect) + audit best-effort (nhom B: login la telemetry)
    try:
        conn = await asyncpg.connect(auth_service._db_url())
        try:
            if await auth_service._has_column(conn, "staff_users", "last_login_at"):
                await conn.execute("UPDATE staff_users SET last_login_at=now() WHERE id=$1", staff["id"])
        finally:
            await conn.close()
    except Exception as e:  # noqa: BLE001
        print(f"[auth] touch last_login loi (bo qua): {e}")
    await audit_service.record_best_effort(
        "staff", "auth.login", actor_staff_id=staff["id"], actor_ref=staff["username"], reason=f"ip={ip}")
    return {"token": token, "username": staff["username"], "name": staff["name"]}


@router.post("/logout")
async def logout(staff: dict = Depends(require_staff_session)) -> dict:
    await auth_service.delete_session(staff["token"])
    return {"logged_out": True}


@router.get("/me")
async def me(staff: dict = Depends(require_staff_session)) -> dict:
    return {
        "id": staff["id"], "username": staff["username"], "name": staff["name"],
        "role_key": staff.get("role_key"),
        "must_change_password": staff.get("must_change_password", False),
    }


@router.post("/password")
async def change_own_password(body: dict, staff: dict = Depends(require_staff_session)) -> dict:
    """Doi mat khau cua chinh minh (can mat khau hien tai). Revoke tat ca session cu -> phai
    dang nhap lai. Cho phep ca khi must_change_password=True (khong dung require_active_session)."""
    current = (body or {}).get("current_password")
    new = (body or {}).get("new_password")
    if not current or not new:
        raise HTTPException(status_code=422, detail="Thieu current_password hoac new_password")
    if len(new) < 6:
        raise HTTPException(status_code=422, detail="Mat khau moi can toi thieu 6 ky tu")
    if not await auth_service.verify_current_password(staff["id"], current):
        raise HTTPException(status_code=401, detail="Mat khau hien tai khong dung")
    await auth_service.change_password(
        staff["id"], new, actor_staff_id=staff["id"], actor_username=staff["username"],
        reason="self change")
    return {"password_changed": True, "sessions_revoked": True}


# --- Quan ly tai khoan nhan vien (gate staff.manage) -------------------------


@router.get("/staff")
async def list_staff(_: dict = Depends(require_permission("staff.manage"))) -> list[dict]:
    return await auth_service.list_staff_users()


@router.post("/staff")
async def create_staff(
    body: dict, actor: dict = Depends(require_permission("staff.manage"))
) -> dict:
    username = (body or {}).get("username")
    password = (body or {}).get("password")
    name = (body or {}).get("name", "")
    role_key = (body or {}).get("role_key")
    if not username or not password:
        raise HTTPException(status_code=422, detail="Thieu username hoac password")
    if len(password) < 6:
        raise HTTPException(status_code=422, detail="Mat khau can toi thieu 6 ky tu")

    conn = await asyncpg.connect(auth_service._db_url())
    try:
        has_role = await auth_service._has_column(conn, "staff_users", "role_key")
        # no privilege-escalation (CA §5.7): role gan phai co quyen ⊆ quyen actor
        if has_role and role_key and actor.get("rbac_provisioned"):
            target_perms = await permission_service.permissions_for_role(conn, role_key)
            if not target_perms.issubset(actor.get("permissions", set())):
                raise HTTPException(
                    status_code=403, detail="Khong the gan role co quyen vuot qua quyen cua ban")
        ph, salt = auth_service._hash_password(password)
        try:
            async with conn.transaction():
                if has_role and role_key:
                    staff_id = await conn.fetchval(
                        "INSERT INTO staff_users (username,password_hash,password_salt,name,role_key) "
                        "VALUES ($1,$2,$3,$4,$5) RETURNING id", username, ph, salt, name, role_key)
                else:
                    staff_id = await conn.fetchval(
                        "INSERT INTO staff_users (username,password_hash,password_salt,name) "
                        "VALUES ($1,$2,$3,$4) RETURNING id", username, ph, salt, name)
                if await _audit_exists(conn):  # fail-closed: mutation + audit cung transaction
                    await audit_service.record(
                        conn, "staff", "staff.create", actor_staff_id=actor["id"],
                        actor_ref=actor["username"], entity_type="staff_user",
                        entity_id=str(staff_id),
                        after={"username": username, "name": name, "role_key": role_key})
        except asyncpg.UniqueViolationError:
            raise HTTPException(status_code=409, detail=f"Username '{username}' da ton tai")
        return {"id": staff_id, "username": username, "name": name,
                "role_key": role_key if has_role else None}
    finally:
        await conn.close()


@router.patch("/staff/{staff_id}")
async def update_staff(
    staff_id: int, body: dict, actor: dict = Depends(require_permission("staff.manage"))
) -> dict:
    """Doi is_active va/hoac role_key. Guard: last active admin + no self-escalation + audit fail-closed."""
    is_active = (body or {}).get("is_active")
    role_key = (body or {}).get("role_key")
    if is_active is None and role_key is None:
        raise HTTPException(status_code=422, detail="Thieu 'is_active' hoac 'role_key'")

    conn = await asyncpg.connect(auth_service._db_url())
    try:
        state = await auth_service.get_staff_admin_state(conn, staff_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Khong tim thay staff id={staff_id}")
        has_role = await auth_service._has_column(conn, "staff_users", "role_key")

        # last-admin guard: khong vo hieu hoa / ha quyen admin cuoi cung
        removing_admin = (
            state.get("role_key") == "admin" and state.get("is_active")
            and ((is_active is False) or (role_key is not None and role_key != "admin"))
        )
        if removing_admin and await auth_service.count_active_admins(conn) <= 1:
            raise HTTPException(status_code=409, detail="Khong the vo hieu hoa/ha quyen admin cuoi cung")

        # no self-escalation: khong tu doi role cua CHINH minh; role gan phai ⊆ quyen actor
        if role_key is not None and has_role:
            if staff_id == actor["id"]:
                raise HTTPException(status_code=403, detail="Khong the tu doi role cua chinh minh")
            if actor.get("rbac_provisioned"):
                target_perms = await permission_service.permissions_for_role(conn, role_key)
                if not target_perms.issubset(actor.get("permissions", set())):
                    raise HTTPException(
                        status_code=403, detail="Khong the gan role co quyen vuot qua quyen cua ban")

        async with conn.transaction():
            if is_active is not None:
                await conn.execute(
                    "UPDATE staff_users SET is_active=$1 WHERE id=$2", bool(is_active), staff_id)
            if role_key is not None and has_role:
                await conn.execute(
                    "UPDATE staff_users SET role_key=$1 WHERE id=$2", role_key, staff_id)
            if is_active is False:  # deactivate -> revoke session (CA §12)
                await conn.execute("DELETE FROM staff_sessions WHERE staff_id=$1", staff_id)
            if await _audit_exists(conn):
                await audit_service.record(
                    conn, "staff", "staff.update", actor_staff_id=actor["id"],
                    actor_ref=actor["username"], entity_type="staff_user", entity_id=str(staff_id),
                    before={"is_active": state.get("is_active"), "role_key": state.get("role_key")},
                    after={"is_active": is_active, "role_key": role_key})
        return {"id": staff_id, "is_active": is_active, "role_key": role_key}
    finally:
        await conn.close()
