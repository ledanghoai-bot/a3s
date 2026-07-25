"""Tao tai khoan nhan vien dau tien (issue #8, Bat 4) - can chay 1 lan de
"bootstrap" vi khong the tao tai khoan qua trang /staff khi CHUA co ai dang
nhap duoc (con ga con trung - trang /staff yeu cau dang nhap moi vao duoc).

Sau khi co it nhat 1 tai khoan, cac tai khoan tiep theo tao thang qua trang
/staff tren dashboard (dang nhap roi vao muc "Nhan vien" > "+ Them nhan vien"),
khong can chay lai script nay.

Cach dung (chay trong container api):
    docker compose exec api python scripts/create_staff_user.py <username> <password> [ten hien thi] [--role <role_key>]

Vi du (bootstrap admin dau tien sau khi migration 016 RBAC da ap):
    docker compose exec api python scripts/create_staff_user.py hoai "MatKhauManh123" "Anh Hoai" --role admin

--role chi co tac dung khi DB da co cot staff_users.role_key (migration 016). Neu chua co, role bi bo qua.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import auth_service  # noqa: E402


async def main() -> None:
    if len(sys.argv) < 3:
        print("Dung dung cu phap: python scripts/create_staff_user.py <username> <password> [ten hien thi]")
        print('Vi du: python scripts/create_staff_user.py hoai "MatKhauManh123" "Anh Hoai"')
        return

    args = sys.argv[1:]
    role_key = None
    if "--role" in args:
        i = args.index("--role")
        role_key = args[i + 1] if i + 1 < len(args) else None
        args = args[:i] + args[i + 2:]

    username = args[0]
    password = args[1]
    name = args[2] if len(args) > 2 else username

    if len(password) < 6:
        print("Loi: mat khau can toi thieu 6 ky tu.")
        return

    try:
        staff = await auth_service.create_staff_user(username, password, name, role_key=role_key)
    except ValueError as e:
        print(f"Loi: {e}")
        return

    print(f"Da tao tai khoan nhan vien: username='{staff['username']}', id={staff['id']}")
    print("Dang nhap thu tai /login tren dashboard voi tai khoan nay.")


if __name__ == "__main__":
    asyncio.run(main())
