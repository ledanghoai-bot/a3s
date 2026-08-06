#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence cho `scripts/m4_stage0p_provision_pin.py`, dap lai
`PHASE1B-M4-REHEARSAL-PRINCIPAL-ASSIGNMENT-REVIEW-1-VI.md` P-M4-PA-02.

Chay (sandbox RIENG, KHONG production - script TU RESET schema public):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@<sandbox-db>:5432/alpha3s \
      alpha3s-api-1 python scripts/m4_stage0p_provision_pin_test.py

Kich ban:
  [1] Argparse KHONG co `--pin`/`--secret`/`--password` - cau truc khong the truyen PIN qua CLI.
  [2] Round-trip that: cap PIN qua stdin (gia lap nguoi go), xac nhan row duoc tao, `crypt()`
      xac minh dung PIN, VA `m4_stage0p_pin_actor()` (ham DB THAT) chap nhan PIN do.
  [3] 2 lan nhap khong khop -> tu choi, khong ghi gi.
  [4] PIN qua ngan -> tu choi, khong ghi gi.
  [5] Toan bo stdout/stderr cua qua trinh KHONG BAO GIO chua PIN THAT (kiem tra chuoi con)."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_URL = os.environ.get("DATABASE_URL") or "postgresql://alpha3s:alpha3s@db:5432/alpha3s"

_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


async def _reset_schema(admin: asyncpg.Connection) -> None:
    await admin.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")


def _run_migrations() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/migrate.py", "up"], cwd=str(ROOT),
        env={**os.environ, "DATABASE_URL": DB_URL}, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise SystemExit("migrate.py up that bai - khong the thiet lap sandbox")


def _run_provision(staff_id: int, stdin_text: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/m4_stage0p_provision_pin.py", "--staff-id", str(staff_id)],
        cwd=str(ROOT), env={**os.environ, "DATABASE_URL": DB_URL},
        input=stdin_text, capture_output=True, text=True, timeout=30)


async def scenario_1_no_cli_pin_argument() -> None:
    print("== [1] argparse KHONG co --pin/--secret/--password ==")
    help_text = subprocess.run(
        [sys.executable, "scripts/m4_stage0p_provision_pin.py", "--help"],
        cwd=str(ROOT), capture_output=True, text=True).stdout
    check("--pin" not in help_text, "--pin KHONG phai argument hop le")
    check("--secret" not in help_text, "--secret KHONG phai argument hop le")
    check("--password" not in help_text, "--password KHONG phai argument hop le")

    rejected = subprocess.run(
        [sys.executable, "scripts/m4_stage0p_provision_pin.py", "--staff-id", "1",
         "--pin", "should-not-work"],
        cwd=str(ROOT), capture_output=True, text=True)
    check(rejected.returncode != 0, "truyen --pin qua CLI bi argparse tu choi ngay (unrecognized)")


async def scenario_2_round_trip_real_pin_actor() -> None:
    print("== [2] Round-trip that: PIN qua stdin -> row -> pin_actor() THAT chap nhan ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        await _reset_schema(admin)
    finally:
        await admin.close()
    _run_migrations()

    admin = await asyncpg.connect(DB_URL)
    try:
        staff = await admin.fetchrow(
            "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
            "VALUES ('provision-pin-test-staff', 'x', 'x', true) RETURNING id")
        staff_id = staff["id"]
        for perm in ("m4.stage0p.operate",):
            await admin.execute(
                "INSERT INTO m4_stage0p_staff_permissions (staff_id, permission, granted_by) "
                "VALUES ($1, $2, $1)", staff_id, perm)
    finally:
        await admin.close()

    test_pin = "correct-horse-battery-staple-9"
    r = _run_provision(staff_id, f"{test_pin}\n{test_pin}\n")
    check(r.returncode == 0, f"provision script exit 0 (thuc te {r.returncode})")
    check("OK - credential row ton tai" in r.stdout, "output xac nhan row ton tai")
    # Chi kiem tra KHONG lo GIA TRI hash that (dang bcrypt "$2b$..."/"$2a$...") - nhac TEN cot
    # trong 1 dong tu giai thich ("khong in X") la binh thuong, khong phai lo bi mat.
    check("$2b$" not in r.stdout and "$2a$" not in r.stdout
          and "$2b$" not in r.stderr and "$2a$" not in r.stderr,
          "output KHONG bao gio chua GIA TRI bcrypt hash that (chi ten cot trong loi giai thich la OK)")

    verify_conn = await asyncpg.connect(DB_URL)
    try:
        row = await verify_conn.fetchrow(
            "SELECT staff_id, provisioned_at FROM m4_stage0p_actor_credentials WHERE staff_id = $1",
            staff_id)
        check(row is not None, "row THAT SU ton tai trong m4_stage0p_actor_credentials")

        # crypt() tu Postgres xac minh dung PIN (khong doan mo, doc lap voi script).
        matches = await verify_conn.fetchval(
            "SELECT pin_secret_hash = crypt($1, pin_secret_hash) "
            "FROM m4_stage0p_actor_credentials WHERE staff_id = $2", test_pin, staff_id)
        check(matches is True, "crypt() xac nhan hash THAT SU khop voi PIN da nhap (khong phai gia)")

        # pin_actor() - ham DB THAT dung trong toan bo rehearsal - chap nhan PIN nay.
        pin_conn = await asyncpg.connect(DB_URL)
        try:
            await pin_conn.execute("SET ROLE alpha3s_m4_actor_binder")
            pinned = await pin_conn.fetchrow(
                "SELECT * FROM m4_stage0p_pin_actor($1, $2)", staff_id, test_pin)
            check(pinned is not None and pinned["pinned_staff_id"] == staff_id,
                  "m4_stage0p_pin_actor() THAT chap nhan PIN vua provision - credential dung duoc "
                  "cho rehearsal that, khong chi 'trong hash'")
        finally:
            await pin_conn.close()
    finally:
        await verify_conn.close()

    check(test_pin not in r.stdout and test_pin not in r.stderr,
          "stdout/stderr cua lan chay THANH CONG KHONG chua PIN that")


async def scenario_3_mismatch_rejected() -> None:
    print("== [3] 2 lan nhap khong khop -> tu choi, khong ghi gi ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        staff = await admin.fetchrow(
            "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
            "VALUES ('provision-pin-test-mismatch', 'x', 'x', true) RETURNING id")
        staff_id = staff["id"]
    finally:
        await admin.close()

    r = _run_provision(staff_id, "pin-value-one-12345\npin-value-two-67890\n")
    check(r.returncode != 0, "exit != 0 khi 2 lan nhap khac nhau")

    verify_conn = await asyncpg.connect(DB_URL)
    try:
        row = await verify_conn.fetchrow(
            "SELECT 1 FROM m4_stage0p_actor_credentials WHERE staff_id = $1", staff_id)
        check(row is None, "KHONG co row nao duoc tao khi mismatch")
    finally:
        await verify_conn.close()
    check("pin-value-one-12345" not in r.stdout and "pin-value-one-12345" not in r.stderr,
          "stdout/stderr khong chua PIN du that bai")


async def scenario_4_too_short_rejected() -> None:
    print("== [4] PIN qua ngan -> tu choi, khong ghi gi ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        staff = await admin.fetchrow(
            "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
            "VALUES ('provision-pin-test-short', 'x', 'x', true) RETURNING id")
        staff_id = staff["id"]
    finally:
        await admin.close()

    r = _run_provision(staff_id, "abc12\nabc12\n")
    check(r.returncode != 0, "exit != 0 khi PIN < 8 ky tu")

    verify_conn = await asyncpg.connect(DB_URL)
    try:
        row = await verify_conn.fetchrow(
            "SELECT 1 FROM m4_stage0p_actor_credentials WHERE staff_id = $1", staff_id)
        check(row is None, "KHONG co row nao duoc tao khi PIN qua ngan")
    finally:
        await verify_conn.close()


async def main() -> int:
    await scenario_1_no_cli_pin_argument()
    await scenario_2_round_trip_real_pin_actor()
    await scenario_3_mismatch_rejected()
    await scenario_4_too_short_rejected()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)} kich ban that bai)")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
