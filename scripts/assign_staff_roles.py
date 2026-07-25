#!/usr/bin/env python3
"""Gán role cho staff hiện hữu (I-B M0.4, CA-REVIEW-M0-DEV-003 §5) — TRANSACTIONAL, IDEMPOTENT,
FAIL-CLOSED. Đọc mapping từ FILE NGOÀI repo (không PII/username trong repository).

Mapping file (--mapping <path>): mỗi dòng `staff_id=role_key`; bỏ qua dòng trống / bắt đầu bằng `#`.
  # staff role mapping (PO điền, giữ ở nơi kiểm soát truy cập)
  1=admin
  2=sales

Chạy (SAU khi PO duyệt ma trận + CA release approval, trong maintenance window):
  docker compose -f docker-compose.prod.yml exec -T api python scripts/assign_staff_roles.py --mapping /path/staff_roles.txt

Fail-closed: TẤT CẢ trong 1 transaction; nếu có role không hợp lệ / staff không tồn tại / <1 active admin /
còn active staff thiếu role -> RAISE -> ROLLBACK (không gán một phần). Idempotent (chạy lại an toàn).
"""
import asyncio
import sys

import asyncpg

from app.config import settings


def _db() -> str:
    return settings.database_url.replace("+asyncpg", "")


def parse_mapping(path: str) -> dict[int, str]:
    m: dict[int, str] = {}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise SystemExit(f"FAIL: dòng mapping sai định dạng: {line!r}")
            sid, role = line.split("=", 1)
            m[int(sid.strip())] = role.strip()
    return m


async def main() -> int:
    if "--mapping" not in sys.argv:
        print("Dùng: assign_staff_roles.py --mapping <file>")
        return 2
    path = sys.argv[sys.argv.index("--mapping") + 1]
    mapping = parse_mapping(path)
    if not mapping:
        print("Mapping RỖNG -> không làm gì (fail-closed).")
        return 2

    conn = await asyncpg.connect(_db())
    try:
        async with conn.transaction():
            valid_roles = {r["key"] for r in await conn.fetch("SELECT key FROM roles")}
            for sid, role in mapping.items():
                if role not in valid_roles:
                    raise SystemExit(f"FAIL: role '{role}' không hợp lệ (staff {sid}) -> ROLLBACK")
                res = await conn.execute(
                    "UPDATE staff_users SET role_key=$1 WHERE id=$2", role, sid)
                if res == "UPDATE 0":
                    raise SystemExit(f"FAIL: không tìm thấy staff id={sid} -> ROLLBACK")
            n_admin = await conn.fetchval(
                "SELECT count(*) FROM staff_users WHERE role_key='admin' AND is_active=TRUE")
            if n_admin < 1:
                raise SystemExit("FAIL: không có active admin nào sau khi gán -> ROLLBACK")
            n_null = await conn.fetchval(
                "SELECT count(*) FROM staff_users WHERE is_active=TRUE AND role_key IS NULL")
            if n_null:
                raise SystemExit(f"FAIL: còn {n_null} active staff chưa có role -> ROLLBACK")
        print(f"OK: gán role {len(mapping)} staff; active_admin={n_admin}; active_staff_thiếu_role=0.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
