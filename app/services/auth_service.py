"""Xac thuc + quan ly tai khoan nhan vien (issue #8, Bat 4) - thay the hoan
toan ADMIN_API_TOKEN tinh dung chung bang dang nhap that (username/password) +
session token rieng cho tung nhan vien.

Hash mat khau bang PBKDF2-HMAC-SHA256 (Python stdlib `hashlib`) - KHONG dung
bcrypt/passlib de tranh them dependency moi vao requirements.txt (them thu
vien moi = phai rebuild lai Docker image `api`, khac restart thuong - da gap
kho khan voi viec nay o cac Bat truoc, xem ISSUES-VI.md).

Session token la chuoi ngau nhien luu trong bang `staff_sessions` (KHONG dung
JWT) - don gian hon, de revoke (chi can xoa dong DB), khong can them PyJWT.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import asyncpg

from app.config import settings
from app.db_pool import acquire, release
from app.services import permission_service

SESSION_TTL_HOURS = 24 * 7  # 7 ngay
PBKDF2_ITERATIONS = 200_000


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Tra ve (hash_hex, salt_hex). Tu sinh salt ngau nhien neu chua co."""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return dk.hex(), salt


def _verify_password(password: str, password_hash: str, salt: str) -> bool:
    computed, _ = _hash_password(password, salt)
    # So sanh constant-time, tranh timing attack
    return secrets.compare_digest(computed, password_hash)


async def create_staff_user(
    username: str, password: str, name: str = "", role_key: str | None = None
) -> dict:
    password_hash, salt = _hash_password(password)
    conn = await acquire()
    try:
        has_role = await _has_column(conn, "staff_users", "role_key")
        try:
            if has_role and role_key:
                staff_id = await conn.fetchval(
                    "INSERT INTO staff_users (username, password_hash, password_salt, name, role_key) "
                    "VALUES ($1,$2,$3,$4,$5) RETURNING id",
                    username, password_hash, salt, name, role_key,
                )
            else:
                staff_id = await conn.fetchval(
                    "INSERT INTO staff_users (username, password_hash, password_salt, name) "
                    "VALUES ($1,$2,$3,$4) RETURNING id",
                    username, password_hash, salt, name,
                )
        except asyncpg.UniqueViolationError:
            raise ValueError(f"Username '{username}' da ton tai, dung ten khac.")
        return {"id": staff_id, "username": username, "name": name,
                "role_key": role_key if has_role else None}
    finally:
        await release(conn)


async def authenticate(username: str, password: str) -> dict | None:
    """Tra ve thong tin staff neu dung username+password VA tai khoan dang
    active, nguoc lai tra ve None (khong phan biet 'sai username' voi 'sai
    password' trong thong bao loi - tranh lo thong tin tai khoan nao ton tai)."""
    conn = await acquire()
    try:
        row = await conn.fetchrow(
            "SELECT id, username, password_hash, password_salt, name, is_active "
            "FROM staff_users WHERE username = $1",
            username,
        )
        if row is None or not row["is_active"]:
            return None
        if not _verify_password(password, row["password_hash"], row["password_salt"]):
            return None
        return {"id": row["id"], "username": row["username"], "name": row["name"]}
    finally:
        await release(conn)


async def create_session(staff_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
    conn = await acquire()
    try:
        await conn.execute(
            "INSERT INTO staff_sessions (staff_id, token, expires_at) VALUES ($1, $2, $3)",
            staff_id,
            token,
            expires_at,
        )
        return token
    finally:
        await release(conn)


async def _has_column(conn, table: str, col: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
        "WHERE table_name=$1 AND column_name=$2)", table, col))


async def validate_session(token: str) -> dict | None:
    """Tra ve {id, username, name, token, role_key, permissions, rbac_provisioned,
    must_change_password} neu token con hop le, None neu khong.

    role_key/permissions query MOI request (khong cache — CA §6). Feature-detect: DB truoc
    migration 016/017 van chay (rbac_provisioned=False, permissions rong) -> require_permission
    degrade ve hanh vi require_staff_session (khong lam vo dashboard o moi truong 012)."""
    conn = await acquire()
    try:
        row = await conn.fetchrow(
            """
            SELECT s.staff_id, s.expires_at, u.username, u.name, u.is_active
            FROM staff_sessions s
            JOIN staff_users u ON u.id = s.staff_id
            WHERE s.token = $1
            """,
            token,
        )
        if row is None or not row["is_active"]:
            return None
        if row["expires_at"] < datetime.now(timezone.utc):
            return None
        staff_id = row["staff_id"]
        authz = await permission_service.load_staff_authz(conn, staff_id)
        must_change = False
        if await _has_column(conn, "staff_users", "must_change_password"):
            must_change = bool(await conn.fetchval(
                "SELECT must_change_password FROM staff_users WHERE id=$1", staff_id))
        return {
            "id": staff_id, "username": row["username"], "name": row["name"], "token": token,
            "role_key": authz["role_key"], "permissions": authz["permissions"],
            "rbac_provisioned": authz["rbac_provisioned"], "must_change_password": must_change,
        }
    finally:
        await release(conn)


async def delete_session(token: str) -> None:
    """Dung khi logout - xoa dung 1 session, khong anh huong session khac
    (vd staff dang dang nhap tren nhieu thiet bi)."""
    conn = await acquire()
    try:
        await conn.execute("DELETE FROM staff_sessions WHERE token = $1", token)
    finally:
        await release(conn)


async def list_staff_users() -> list[dict]:
    conn = await acquire()
    try:
        rows = await conn.fetch(
            "SELECT id, username, name, is_active, created_at FROM staff_users ORDER BY id"
        )
        return [dict(r) for r in rows]
    finally:
        await release(conn)


async def set_staff_active(staff_id: int, is_active: bool) -> None:
    """Vo hieu hoa/kich hoat lai 1 tai khoan - KHONG xoa han, giu lich su.
    Vo hieu hoa se lam tat ca session hien tai cua staff do bi tu choi ngay
    o lan goi API tiep theo (validate_session check is_active)."""
    conn = await acquire()
    try:
        result = await conn.execute(
            "UPDATE staff_users SET is_active = $1 WHERE id = $2", is_active, staff_id
        )
        if result == "UPDATE 0":
            raise LookupError(f"Khong tim thay staff id={staff_id}")
    finally:
        await release(conn)


# --- RBAC / hardening helpers (I-B M0.4/M0.5) --------------------------------

async def count_active_admins(conn) -> int:
    """So admin dang active (0 neu RBAC chua provisioned). Dung cho last-admin guard."""
    if not await permission_service.rbac_provisioned(conn):
        return 0
    return await conn.fetchval(
        "SELECT count(*) FROM staff_users WHERE role_key='admin' AND is_active=TRUE")


async def get_staff_admin_state(conn, staff_id: int) -> dict | None:
    """{is_active, role_key} cho guard (role_key None neu chua co cot 016)."""
    if await _has_column(conn, "staff_users", "role_key"):
        r = await conn.fetchrow("SELECT is_active, role_key FROM staff_users WHERE id=$1", staff_id)
    else:
        r = await conn.fetchrow(
            "SELECT is_active, NULL::text AS role_key FROM staff_users WHERE id=$1", staff_id)
    return dict(r) if r else None


async def verify_current_password(staff_id: int, password: str) -> bool:
    conn = await acquire()
    try:
        r = await conn.fetchrow(
            "SELECT password_hash, password_salt FROM staff_users WHERE id=$1", staff_id)
        return bool(r) and _verify_password(password, r["password_hash"], r["password_salt"])
    finally:
        await release(conn)


async def change_password(
    staff_id: int, new_password: str, *, actor_staff_id: int, actor_username: str,
    reason: str = "password change",
) -> None:
    """Doi mat khau + xoa co must_change_password + REVOKE tat ca session cu + audit fail-closed.
    Tat ca trong 1 transaction (mutation + audit commit/rollback cung nhau)."""
    ph, salt = _hash_password(new_password)
    conn = await acquire()
    try:
        async with conn.transaction():
            if await _has_column(conn, "staff_users", "must_change_password"):
                await conn.execute(
                    "UPDATE staff_users SET password_hash=$1, password_salt=$2, "
                    "must_change_password=FALSE, temporary_password_expires_at=NULL WHERE id=$3",
                    ph, salt, staff_id)
            else:
                await conn.execute(
                    "UPDATE staff_users SET password_hash=$1, password_salt=$2 WHERE id=$3",
                    ph, salt, staff_id)
            await conn.execute("DELETE FROM staff_sessions WHERE staff_id=$1", staff_id)
            if await conn.fetchval("SELECT to_regclass('public.audit_log') IS NOT NULL"):
                from app.services import audit_service
                await audit_service.record(
                    conn, "staff", "auth.password_change",
                    actor_staff_id=actor_staff_id, actor_ref=actor_username,
                    entity_type="staff_user", entity_id=str(staff_id), reason=reason)
    finally:
        await release(conn)
