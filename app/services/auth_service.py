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


async def create_staff_user(username: str, password: str, name: str = "") -> dict:
    password_hash, salt = _hash_password(password)
    conn = await asyncpg.connect(_db_url())
    try:
        try:
            staff_id = await conn.fetchval(
                """
                INSERT INTO staff_users (username, password_hash, password_salt, name)
                VALUES ($1, $2, $3, $4) RETURNING id
                """,
                username,
                password_hash,
                salt,
                name,
            )
        except asyncpg.UniqueViolationError:
            raise ValueError(f"Username '{username}' da ton tai, dung ten khac.")
        return {"id": staff_id, "username": username, "name": name}
    finally:
        await conn.close()


async def authenticate(username: str, password: str) -> dict | None:
    """Tra ve thong tin staff neu dung username+password VA tai khoan dang
    active, nguoc lai tra ve None (khong phan biet 'sai username' voi 'sai
    password' trong thong bao loi - tranh lo thong tin tai khoan nao ton tai)."""
    conn = await asyncpg.connect(_db_url())
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
        await conn.close()


async def create_session(staff_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
    conn = await asyncpg.connect(_db_url())
    try:
        await conn.execute(
            "INSERT INTO staff_sessions (staff_id, token, expires_at) VALUES ($1, $2, $3)",
            staff_id,
            token,
            expires_at,
        )
        return token
    finally:
        await conn.close()


async def validate_session(token: str) -> dict | None:
    """Tra ve {id, username, name, token} neu token con hop le (chua het han,
    tai khoan van active), None neu khong."""
    conn = await asyncpg.connect(_db_url())
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
        return {"id": row["staff_id"], "username": row["username"], "name": row["name"], "token": token}
    finally:
        await conn.close()


async def delete_session(token: str) -> None:
    """Dung khi logout - xoa dung 1 session, khong anh huong session khac
    (vd staff dang dang nhap tren nhieu thiet bi)."""
    conn = await asyncpg.connect(_db_url())
    try:
        await conn.execute("DELETE FROM staff_sessions WHERE token = $1", token)
    finally:
        await conn.close()


async def list_staff_users() -> list[dict]:
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            "SELECT id, username, name, is_active, created_at FROM staff_users ORDER BY id"
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def set_staff_active(staff_id: int, is_active: bool) -> None:
    """Vo hieu hoa/kich hoat lai 1 tai khoan - KHONG xoa han, giu lich su.
    Vo hieu hoa se lam tat ca session hien tai cua staff do bi tu choi ngay
    o lan goi API tiep theo (validate_session check is_active)."""
    conn = await asyncpg.connect(_db_url())
    try:
        result = await conn.execute(
            "UPDATE staff_users SET is_active = $1 WHERE id = $2", is_active, staff_id
        )
        if result == "UPDATE 0":
            raise LookupError(f"Khong tim thay staff id={staff_id}")
    finally:
        await conn.close()
