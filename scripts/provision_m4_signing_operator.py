"""Provision role + staff CHUYEN BIET de van hanh Tier A ky transcript (M4-9).

Tao/dam bao role `m4_signing_operator` ("Van hanh ky transcript") CHI co 5 quyen m4.signing.run.*
(view/start/operate/approve/abort) — KHONG kem quyen nghiep vu khac, TACH khoi admin va staff hang
ngay. Roi tao/gan MOT staff chuyen biet vao role do (mat khau nhap AN tu terminal).

Vi sao can script (khong lam qua /staff UI): endpoint /staff co "subset check" — admin chi gan
duoc role ma admin CUNG co quyen. Admin mac dinh chi co m4.signing.run.view, nen KHONG gan duoc
role nay qua UI. Script ghi DB truc tiep (break-glass, boundary = SSH key custody).

BAO MAT: mat khau nhap AN tu terminal (getpass, 2 lan xac nhan) — khong qua lenh/env/history.
(Fallback bien NEW_OPERATOR_PASSWORD khi khong co TTY, cho automation.)

Cach dung (container api tren VPS, KHONG dung -T de co TTY):
    docker compose -f docker-compose.prod.yml exec api \
        python scripts/provision_m4_signing_operator.py <username_moi> ["Ten hien thi"]

Vi du: python scripts/provision_m4_signing_operator.py signer1 "Nhan vien ky transcript"
"""
import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.config import settings  # noqa: E402
from app.services import auth_service  # noqa: E402

ROLE_KEY = "m4_signing_operator"
ROLE_NAME = "Van hanh ky transcript (Tier A)"
PERMS = [
    "m4.signing.run.view", "m4.signing.run.start", "m4.signing.run.operate",
    "m4.signing.run.approve", "m4.signing.run.abort",
]


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _read_password() -> str | None:
    if sys.stdin.isatty():
        pw = getpass.getpass("Mat khau operator moi (go, khong hien): ")
        c = getpass.getpass("Nhap lai de xac nhan: ")
        if pw != c:
            print("Loi: hai lan nhap khong khop.")
            return None
        return pw
    pw = os.environ.get("NEW_OPERATOR_PASSWORD", "")
    if not pw:
        print("Loi: khong co TTY. Chay KHONG kem `-T` de nhap mat khau, hoac dat "
              "NEW_OPERATOR_PASSWORD cho automation.")
    return pw or None


async def main() -> int:
    if len(sys.argv) < 2:
        print("Dung: python scripts/provision_m4_signing_operator.py <username> [\"Ten\"]")
        return 2
    username = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else username

    password = _read_password()
    if password is None:
        return 2
    if len(password) < 8:
        print("Loi: mat khau can toi thieu 8 ky tu.")
        return 2

    password_hash, salt = auth_service._hash_password(password)  # noqa: SLF001

    conn = await asyncpg.connect(_db_url())
    try:
        if not await auth_service._has_column(conn, "staff_users", "role_key"):  # noqa: SLF001
            print("Loi: DB chua co RBAC (staff_users.role_key) — chay migration 016/018 truoc.")
            return 2
        has_mcp = await auth_service._has_column(conn, "staff_users", "must_change_password")  # noqa: SLF001

        async with conn.transaction():
            # 1. role chuyen biet
            await conn.execute(
                "INSERT INTO roles (key, name, is_system, is_active) VALUES ($1,$2,false,true) "
                "ON CONFLICT (key) DO UPDATE SET name=EXCLUDED.name, is_active=true",
                ROLE_KEY, ROLE_NAME)
            # 2. grant dung 5 quyen m4.signing.run.* (idempotent)
            granted = 0
            for p in PERMS:
                r = await conn.execute(
                    "INSERT INTO role_permissions (role_key, permission_key) "
                    "SELECT $1,$2 WHERE EXISTS (SELECT 1 FROM permissions WHERE key=$2) "
                    "ON CONFLICT DO NOTHING", ROLE_KEY, p)
                if r.endswith("1"):
                    granted += 1
            nperm = await conn.fetchval(
                "SELECT count(*) FROM role_permissions WHERE role_key=$1 "
                "AND permission_key LIKE 'm4.signing.%'", ROLE_KEY)

            # 3. tao/gan staff chuyen biet vao role
            row = await conn.fetchrow("SELECT id, role_key FROM staff_users WHERE username=$1",
                                      username)
            if row is None:
                staff_id = await conn.fetchval(
                    "INSERT INTO staff_users (username,password_hash,password_salt,name,role_key,"
                    "is_active) VALUES ($1,$2,$3,$4,$5,true) RETURNING id",
                    username, password_hash, salt, name, ROLE_KEY)
                action = "TAO MOI staff"
            else:
                if row["role_key"] not in (None, ROLE_KEY):
                    print(f"Canh bao: '{username}' dang co role '{row['role_key']}' — se DOI sang "
                          f"'{ROLE_KEY}' (mat cac quyen role cu). Dung username MOI cho staff "
                          f"chuyen biet neu khong muon vay.")
                staff_id = row["id"]
                sets = ["password_hash=$2", "password_salt=$3", "name=$4",
                        "role_key=$5", "is_active=true"]
                if has_mcp:
                    sets.append("must_change_password=false")
                await conn.execute(f"UPDATE staff_users SET {', '.join(sets)} WHERE id=$1",
                                   staff_id, password_hash, salt, name, ROLE_KEY)
                await conn.execute("DELETE FROM staff_sessions WHERE staff_id=$1", staff_id)
                action = "GAN LAI staff (revoke session cu)"
    finally:
        await conn.close()

    print(f"OK: role '{ROLE_KEY}' co {nperm}/5 quyen m4.signing.run.*; {action} "
          f"username='{username}' id={staff_id} role={ROLE_KEY}.")
    print("Dang nhap /login voi tai khoan nay -> vao 'Ky transcript' chay Tier A.")
    print("Luu y: admin KHAC van chi co quyen 'view' (giam sat), khong van hanh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
