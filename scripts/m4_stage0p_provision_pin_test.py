#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence cho `scripts/m4_stage0p_provision_pin.py` REV2, dap lai
`PHASE1B-M4-REHEARSAL-READINESS-SNAPSHOT-REVIEW-1-VI.md` F-M4-PIN-R1-01/02/03.

Chay (sandbox RIENG, KHONG production - script TU RESET schema public, migration 040 duoc apply
qua chinh `scripts/migrate.py up` nhu binh thuong):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@<sandbox-db>:5432/alpha3s \
      alpha3s-api-1 python scripts/m4_stage0p_provision_pin_test.py

Kich ban:
  [1] Token BUOC voi staff A KHONG THE dung de dat PIN cho staff B — ve mat cau truc (provision-
      pin KHONG con nhan staff-id tu caller o bat ky dang nao, staff_id luon resolve tu token).
  [2] Round-trip that: issue-token -> provision-pin (token qua stdin) -> row -> `m4_stage0p_
      pin_actor()` THAT chap nhan.
  [3] Token da dung (consumed) -> lan 2 bi tu choi.
  [4] Token het han -> bi tu choi.
  [5] PIN mismatch/qua ngan -> tu choi NHUNG token VAN con dung duoc lai (khong bi tieu thu oan).
  [6] Toan bo stdout/stderr KHONG BAO GIO chua token that, PIN that, hay gia tri bcrypt hash."""

import asyncio
import hashlib
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


def _run_issue_token(staff_id: int, issued_by: int, ttl_minutes: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/m4_stage0p_provision_pin.py", "issue-token",
         "--staff-id", str(staff_id), "--issued-by", str(issued_by),
         "--ttl-minutes", str(ttl_minutes)],
        cwd=str(ROOT), env={**os.environ, "DATABASE_URL": DB_URL},
        capture_output=True, text=True, timeout=30)


def _extract_token(issue_stdout: str) -> str:
    # Token la dong CUOI CUNG khac rong cua stdout (xem issue_token() - in token o dong rieng).
    lines = [ln for ln in issue_stdout.strip().splitlines() if ln.strip()]
    return lines[-1].strip()


def _run_provision_pin(stdin_text: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/m4_stage0p_provision_pin.py", "provision-pin"],
        cwd=str(ROOT), env={**os.environ, "DATABASE_URL": DB_URL},
        input=stdin_text, capture_output=True, text=True, timeout=30)


async def _make_staff(admin, username: str) -> int:
    row = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ($1, 'x', 'x', true) RETURNING id", username)
    return row["id"]


async def scenario_1_no_staff_id_input_surface() -> None:
    print("== [1] provision-pin KHONG con nhan staff-id duoi bat ky dang nao ==")
    help_text = subprocess.run(
        [sys.executable, "scripts/m4_stage0p_provision_pin.py", "provision-pin", "--help"],
        cwd=str(ROOT), capture_output=True, text=True).stdout
    check("--staff-id" not in help_text, "subcommand provision-pin KHONG co --staff-id")
    check("--staff" not in help_text, "subcommand provision-pin KHONG co bat ky bien the --staff nao")


async def scenario_2_round_trip_real_pin_actor() -> None:
    print("== [2] Round-trip that: issue-token -> provision-pin -> pin_actor() THAT chap nhan ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        await _reset_schema(admin)
    finally:
        await admin.close()
    _run_migrations()

    admin = await asyncpg.connect(DB_URL)
    try:
        issuer_id = await _make_staff(admin, "provision-pin-test-issuer")
        target_id = await _make_staff(admin, "provision-pin-test-target")
        await admin.execute(
            "INSERT INTO m4_stage0p_staff_permissions (staff_id, permission, granted_by) "
            "VALUES ($1, 'm4.stage0p.operate', $1)", target_id)
    finally:
        await admin.close()

    r = _run_issue_token(target_id, issuer_id)
    check(r.returncode == 0, f"issue-token exit 0 (thuc te {r.returncode})")
    token = _extract_token(r.stdout)
    check(len(token) > 20, "token trich xuat duoc, do dai hop ly")

    test_pin = "correct-horse-battery-staple-9"
    r2 = _run_provision_pin(f"{token}\n{test_pin}\n{test_pin}\n")
    check(r2.returncode == 0, f"provision-pin exit 0 (thuc te {r2.returncode}); stderr={r2.stderr}")
    check(f"staff_id={target_id}" in r2.stdout,
          "output xac nhan DUNG staff_id duoc resolve tu token (khong phai tu caller)")

    verify_conn = await asyncpg.connect(DB_URL)
    try:
        row = await verify_conn.fetchrow(
            "SELECT staff_id FROM m4_stage0p_actor_credentials WHERE staff_id = $1", target_id)
        check(row is not None, "row THAT SU ton tai cho DUNG target_id")

        matches = await verify_conn.fetchval(
            "SELECT pin_secret_hash = crypt($1, pin_secret_hash) "
            "FROM m4_stage0p_actor_credentials WHERE staff_id = $2", test_pin, target_id)
        check(matches is True, "crypt() xac nhan hash khop PIN da nhap")

        pin_conn = await asyncpg.connect(DB_URL)
        try:
            await pin_conn.execute("SET ROLE alpha3s_m4_actor_binder")
            pinned = await pin_conn.fetchrow(
                "SELECT * FROM m4_stage0p_pin_actor($1, $2)", target_id, test_pin)
            check(pinned is not None and pinned["pinned_staff_id"] == target_id,
                  "m4_stage0p_pin_actor() THAT chap nhan PIN vua provision qua token")
        finally:
            await pin_conn.close()

        consumed_row = await verify_conn.fetchrow(
            "SELECT consumed_at FROM m4_stage0p_pin_bootstrap_tokens WHERE staff_id = $1", target_id)
        check(consumed_row is not None and consumed_row["consumed_at"] is not None,
              "token da duoc danh dau consumed_at sau khi thanh cong")
    finally:
        await verify_conn.close()

    check(token not in r2.stdout and token not in r2.stderr, "output KHONG chua token that")
    check(test_pin not in r.stdout and test_pin not in r2.stdout and test_pin not in r2.stderr,
          "output KHONG chua PIN that")
    check("$2b$" not in r2.stdout and "$2a$" not in r2.stdout,
          "output KHONG chua gia tri bcrypt hash that")


async def scenario_3_token_reuse_rejected() -> None:
    print("== [3] Token da dung (consumed) -> lan 2 bi tu choi ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        issuer_id = await _make_staff(admin, "provision-pin-test-reuse-issuer")
        target_id = await _make_staff(admin, "provision-pin-test-reuse-target")
    finally:
        await admin.close()

    r = _run_issue_token(target_id, issuer_id)
    token = _extract_token(r.stdout)

    pin = "first-use-pin-value-12"
    r1 = _run_provision_pin(f"{token}\n{pin}\n{pin}\n")
    check(r1.returncode == 0, "lan dau dung token thanh cong")

    r2 = _run_provision_pin(f"{token}\nanother-pin-value-99\nanother-pin-value-99\n")
    check(r2.returncode != 0, "lan 2 dung LAI CUNG token bi tu choi (da consumed)")
    check("token khong hop le" in r2.stderr.lower() or "khong hop le" in r2.stderr.lower(),
          "loi neu ro token khong hop le/da dung")


async def scenario_4_expired_token_rejected() -> None:
    print("== [4] Token het han -> bi tu choi ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        issuer_id = await _make_staff(admin, "provision-pin-test-expiry-issuer")
        target_id = await _make_staff(admin, "provision-pin-test-expiry-target")
    finally:
        await admin.close()

    r = _run_issue_token(target_id, issuer_id, ttl_minutes=30)
    token = _extract_token(r.stdout)

    # Gia lap het han: lui expires_at ve qua khu truc tiep qua admin connection (test-only).
    admin2 = await asyncpg.connect(DB_URL)
    try:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        await admin2.execute(
            "UPDATE m4_stage0p_pin_bootstrap_tokens SET "
            "issued_at = now() - interval '2 hours', "
            "expires_at = now() - interval '1 minute' "
            "WHERE token_hash = $1", token_hash)
    finally:
        await admin2.close()

    r2 = _run_provision_pin(f"{token}\nexpired-pin-value-12\nexpired-pin-value-12\n")
    check(r2.returncode != 0, "token het han bi tu choi")

    verify_conn = await asyncpg.connect(DB_URL)
    try:
        row = await verify_conn.fetchrow(
            "SELECT 1 FROM m4_stage0p_actor_credentials WHERE staff_id = $1", target_id)
        check(row is None, "KHONG co credential nao duoc tao tu token het han")
    finally:
        await verify_conn.close()


async def scenario_5_pin_mismatch_does_not_burn_token() -> None:
    print("== [5] PIN mismatch/qua ngan -> tu choi NHUNG token VAN dung duoc lai ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        issuer_id = await _make_staff(admin, "provision-pin-test-retry-issuer")
        target_id = await _make_staff(admin, "provision-pin-test-retry-target")
    finally:
        await admin.close()

    r = _run_issue_token(target_id, issuer_id)
    token = _extract_token(r.stdout)

    r1 = _run_provision_pin(f"{token}\npin-one-value-123\npin-two-value-456\n")
    check(r1.returncode != 0, "mismatch bi tu choi")

    verify_conn = await asyncpg.connect(DB_URL)
    try:
        row = await verify_conn.fetchrow(
            "SELECT consumed_at FROM m4_stage0p_pin_bootstrap_tokens WHERE staff_id = $1", target_id)
        check(row is not None and row["consumed_at"] is None,
              "token VAN CHUA bi consumed sau lan mismatch - con dung duoc lai")
    finally:
        await verify_conn.close()

    good_pin = "retry-succeeds-now-1"
    r2 = _run_provision_pin(f"{token}\n{good_pin}\n{good_pin}\n")
    check(r2.returncode == 0, "dung LAI CUNG token (sau mismatch) thanh cong lan nay")


async def main() -> int:
    await scenario_1_no_staff_id_input_surface()
    await scenario_2_round_trip_real_pin_actor()
    await scenario_3_token_reuse_rejected()
    await scenario_4_expired_token_rejected()
    await scenario_5_pin_mismatch_does_not_burn_token()

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
