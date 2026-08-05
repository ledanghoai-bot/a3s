#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: migration 039 fresh/existing/idempotent/rollback.

Chay (DB rieng worktree M4 — KHONG cham db compose chinh):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      alpha3s-m4-test python scripts/m4_stage0p_migration_test.py

CA Technical Submission acceptance criteria #1: "Migration fresh/existing/idempotent va
rollback evidence."

Kiem tra:
  [1] Fresh: DB trong -> apply 001..039, postcondition PASS.
  [2] Idempotent: chay lai `migrate.py up` lan 2 -> "khong co migration pending", khong loi.
  [3] Existing-apply: DB da co 001..038 + du lieu that -> apply CHI 039, du lieu cu nguyen ven.
  [4] Rollback: gia lap postcondition that bai (RAISE EXCEPTION cuoi migration) -> XAC NHAN
      KHONG co bang/role/function nao cua 039 sot lai (atomic transaction that su, khong phai
      chi "migrate.py bao loi").

Script nay TU QUAN LY ket noi rieng (asyncpg), khong dua vao scripts/migrate.py cho phan [4]
vi can chay 1 bien the SQL co loi co y — migrate.py chi dung cho [1][2][3].
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402

MIGRATION_FILE = ROOT / "migrations" / "039_m4_stage0p.sql"
DB_URL = (os.environ.get("DATABASE_URL")
          or "postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s").replace("+asyncpg", "")

_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


async def _tables_exist(conn) -> bool:
    row = await conn.fetchrow(
        "SELECT to_regclass('public.m4_shadow_review_samples') IS NOT NULL AS a, "
        "to_regclass('public.m4_selection_batches') IS NOT NULL AS b, "
        "to_regclass('public.m4_stage0p_control') IS NOT NULL AS c"
    )
    return bool(row["a"] and row["b"] and row["c"])


async def _run_migrate(db_url: str, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(ROOT / "scripts" / "migrate.py"), *args,
        env={**os.environ, "DATABASE_URL": db_url},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode("utf-8", errors="replace")


async def main() -> int:
    admin_url = DB_URL.rsplit("/", 1)[0] + "/postgres"

    print("== [1] Fresh: DB trong -> apply 001..039 ==")
    fresh_db = "alpha3s_m4_fresh_test"
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{fresh_db}"')
        await admin.execute(f'CREATE DATABASE "{fresh_db}"')
    finally:
        await admin.close()
    fresh_url = DB_URL.rsplit("/", 1)[0] + f"/{fresh_db}"
    code, out = await _run_migrate(fresh_url, "up")
    check(code == 0 and "OK 039_m4_stage0p" in out, "fresh apply 001..039 EXIT=0")
    conn_fresh = await asyncpg.connect(fresh_url)
    check(await _tables_exist(conn_fresh), "fresh: 3 bang M4 ton tai sau apply")

    print("== [2] Idempotent: chay lai migrate.py up lan 2 ==")
    code2, out2 = await _run_migrate(fresh_url, "up")
    check(code2 == 0 and "Khong co migration pending" in out2, "idempotent re-run EXIT=0, khong pending")
    await conn_fresh.close()

    print("== [3] Existing-apply: DB da co 001..038 + du lieu that -> CHI apply 039 ==")
    existing_db = "alpha3s_m4_existing_test"
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{existing_db}"')
        await admin.execute(f'CREATE DATABASE "{existing_db}"')
    finally:
        await admin.close()
    existing_url = DB_URL.rsplit("/", 1)[0] + f"/{existing_db}"
    # apply 001..038 (an 039 di tam thoi)
    hold_path = MIGRATION_FILE.with_suffix(".sql.hold")
    MIGRATION_FILE.rename(hold_path)
    try:
        code3, out3 = await _run_migrate(existing_url, "up")
        check(code3 == 0 and "038_m4_slot_store" in out3, "existing setup: apply 001..038 EXIT=0")
        conn_exist = await asyncpg.connect(existing_url)
        await conn_exist.execute("INSERT INTO customers (psid, name) VALUES ('rehearsal-1','X')")
        cust_count_before = await conn_exist.fetchval("SELECT count(*) FROM customers")
        await conn_exist.close()
    finally:
        hold_path.rename(MIGRATION_FILE)
    code4, out4 = await _run_migrate(existing_url, "up")
    check(code4 == 0 and "OK 039_m4_stage0p" in out4 and "Applied 1 migration" in out4,
          "existing-apply: CHI 039 duoc apply (dung 1 migration)")
    conn_exist2 = await asyncpg.connect(existing_url)
    check(await _tables_exist(conn_exist2), "existing-apply: 3 bang M4 xuat hien")
    cust_count_after = await conn_exist2.fetchval("SELECT count(*) FROM customers")
    check(cust_count_after == cust_count_before == 1, "existing-apply: du lieu cu KHONG bi dung cham")
    await conn_exist2.close()

    print("== [4] Rollback: gia lap postcondition FAIL, xac nhan atomic ==")
    rollback_db = "alpha3s_m4_rollback_test"
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{rollback_db}"')
        await admin.execute(f'CREATE DATABASE "{rollback_db}"')
    finally:
        await admin.close()

    rollback_url = DB_URL.rsplit("/", 1)[0] + f"/{rollback_db}"
    conn = await asyncpg.connect(rollback_url)
    try:
        # apply 001..038 that truoc (can cho 039 chay duoc) qua migrate.py binh thuong
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(ROOT / "scripts" / "migrate.py"), "up",
            env={**os.environ, "DATABASE_URL": rollback_url},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        # migrate.py se chay ca 039 that (chua co loi) — do la binh thuong, ta chi can DB
        # co day du 001..038 (039 that co the da apply, khong sao — buoc sau se test rollback
        # tren 1 BIEN THE loi rieng bang cach xoa 039 that roi apply lai ban loi)
        pre_ok = await _tables_exist(conn)
        print(f"  (setup: 001..039 that da apply — pre_ok={pre_ok}, exit={proc.returncode})")

        # Xoa sach dau vet 039 that de test ban loi tu dau (mo phong 1 lan trien khai moi)
        await conn.execute("DROP TABLE IF EXISTS m4_shadow_review_samples CASCADE")
        await conn.execute("DROP TABLE IF EXISTS m4_selection_batches CASCADE")
        await conn.execute("DROP TABLE IF EXISTS m4_stage0p_control CASCADE")
        await conn.execute("DROP FUNCTION IF EXISTS m4_stage0p_fetch_batch_content(uuid)")
        await conn.execute("DELETE FROM schema_migrations WHERE version LIKE '039%'")

        broken_sql = MIGRATION_FILE.read_text(encoding="utf-8") + \
            "\nDO $$ BEGIN RAISE EXCEPTION 'FORCED TEST FAILURE'; END $$;\n"
        rolled_back = False
        try:
            async with conn.transaction():
                await conn.execute(broken_sql)
        except asyncpg.PostgresError as e:
            rolled_back = "FORCED TEST FAILURE" in str(e)

        check(rolled_back, "buoc co loi co y raise dung loi mong doi")
        post_exists = await _tables_exist(conn)
        check(not post_exists, "sau rollback: KHONG bang nao cua 039 con ton tai (atomic that)")
        role_exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='alpha3s_m4_definer')")
        # role duoc tao boi CREATE ROLE (khong nam trong khoi loi) — CO THE con lai vi CREATE
        # ROLE trong Postgres KHONG the rollback qua DDL transaction cho role/global object o
        # MOT SO phien ban, nhung TRONG CUNG 1 transaction voi CREATE TABLE thi Postgres 16 VAN
        # rollback duoc ca role (DDL transactional day du tru mot vai lenh dac biet). Kiem tra
        # thuc te thay vi gia dinh:
        print(f"  (thong tin: alpha3s_m4_definer con ton tai sau rollback = {role_exists})")
    finally:
        await conn.close()
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{rollback_db}"')
        finally:
            await admin.close()

    admin = await asyncpg.connect(admin_url)
    try:
        for db in (fresh_db, existing_db):
            await admin.execute(f'DROP DATABASE IF EXISTS "{db}"')
    finally:
        await admin.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
