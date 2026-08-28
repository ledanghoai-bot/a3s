"""Reset / bootstrap tai khoan ADMIN cho dashboard (break-glass, khong can mat khau cu).

Dung khi: quen mat khau admin, khoa ngoai, hoac can dat lai tai khoan admin dau tien.
Khac `create_staff_user.py` (chi TAO moi, loi neu username da ton tai) — script nay CREATE-OR-RESET:
- Neu username da ton tai: dat lai password + role='admin' + is_active=true + xoa co
  must_change_password + REVOKE moi session cu (buoc dang nhap lai).
- Neu chua ton tai: tao moi voi role admin.

Hash dung PBKDF2-HMAC-SHA256 200k iterations (khop `auth_service._hash_password` — login verify duoc).

BAO MAT: mat khau doc tu BIEN MOI TRUONG `NEW_ADMIN_PASSWORD` (khong hien trong process list /
shell history). Neu chua set, script bao loi va huong dan — KHONG nhan qua CLI arg.

Cach dung (chay trong container api tren VPS):
    docker compose -f docker-compose.prod.yml exec -T -e NEW_ADMIN_PASSWORD='MatKhauManh...' \
        api python scripts/reset_admin_user.py <username> ["Ten hien thi"]

Vi du:
    docker compose -f docker-compose.prod.yml exec -T -e NEW_ADMIN_PASSWORD='...' \
        api python scripts/reset_admin_user.py hoai "Anh Hoai"
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.config import settings  # noqa: E402
from app.services import auth_service  # noqa: E402


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def main() -> int:
    if len(sys.argv) < 2:
        print("Dung: python scripts/reset_admin_user.py <username> [\"Ten hien thi\"]")
        print("Mat khau moi PHAI truyen qua bien moi truong NEW_ADMIN_PASSWORD (khong qua CLI).")
        return 2

    username = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else username
    password = os.environ.get("NEW_ADMIN_PASSWORD", "")

    if len(password) < 8:
        print("Loi: dat NEW_ADMIN_PASSWORD (toi thieu 8 ky tu) qua bien moi truong, vd:")
        print("  docker compose -f docker-compose.prod.yml exec -T -e NEW_ADMIN_PASSWORD='...' \\")
        print("     api python scripts/reset_admin_user.py " + username)
        return 2

    password_hash, salt = auth_service._hash_password(password)  # noqa: SLF001 - dung chung thuat toan

    conn = await asyncpg.connect(_db_url())
    try:
        has_role = await auth_service._has_column(conn, "staff_users", "role_key")  # noqa: SLF001
        has_mcp = await auth_service._has_column(conn, "staff_users", "must_change_password")  # noqa: SLF001

        # Dam bao role 'admin' ton tai (migration 016/018 da seed; phong khi chua).
        if has_role:
            role_exists = await conn.fetchval("SELECT 1 FROM roles WHERE key='admin'")
            if not role_exists:
                print("Canh bao: role 'admin' chua co trong bang roles — bo qua gan role "
                      "(chay migration 016/018 truoc de co RBAC day du).")
                has_role = False

        row = await conn.fetchrow("SELECT id FROM staff_users WHERE username=$1", username)

        async with conn.transaction():
            if row is None:
                # tao moi
                cols = "username, password_hash, password_salt, name"
                vals = "$1,$2,$3,$4"
                params = [username, password_hash, salt, name]
                if has_role:
                    cols += ", role_key"; vals += ",$5"; params.append("admin")
                staff_id = await conn.fetchval(
                    f"INSERT INTO staff_users ({cols}, is_active) VALUES ({vals}, true) RETURNING id",
                    *params)
                action = "TAO MOI"
            else:
                staff_id = row["id"]
                sets = ["password_hash=$2", "password_salt=$3", "name=$4", "is_active=true"]
                params = [staff_id, password_hash, salt, name]
                nxt = 5
                if has_role:
                    sets.append(f"role_key=${nxt}"); params.append("admin"); nxt += 1
                if has_mcp:
                    sets.append("must_change_password=false")
                await conn.execute(
                    f"UPDATE staff_users SET {', '.join(sets)} WHERE id=$1", *params)
                # REVOKE moi session cu -> buoc dang nhap lai voi mat khau moi
                await conn.execute("DELETE FROM staff_sessions WHERE staff_id=$1", staff_id)
                action = "DAT LAI (revoke session cu)"
    finally:
        await conn.close()

    print(f"OK: {action} tai khoan admin username='{username}' id={staff_id}"
          + (" role=admin" if has_role else " (khong gan role — DB chua co RBAC)"))
    print("Dang nhap tai /login tren dashboard voi mat khau moi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
