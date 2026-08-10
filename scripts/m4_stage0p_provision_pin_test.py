#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence cho `scripts/m4_stage0p_provision_pin.py` REV4, dap lai
`PHASE1B-M4-REHEARSAL-PIN-TOOL-REVIEW-3-VI.md` F-M4-PIN-R3-01 (REV2/REV3 evidence van con o git
history cua branch nay cho F-M4-PIN-R1-01/03 va F-M4-PIN-R2-01/02/03).

Chay (sandbox RIENG, KHONG production - script TU RESET schema public, migration 040+041+042
duoc apply qua chinh `scripts/migrate.py up` nhu binh thuong):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@<sandbox-db>:5432/alpha3s \
      alpha3s-api-1 python scripts/m4_stage0p_provision_pin_test.py

Kich ban:
  [1] provision-pin KHONG nhan staff-id duoi bat ky dang nao (cau truc, tu REV1 giu nguyen).
  [2] generate-token chay HOAN TOAN cuc bo (khong DATABASE_URL van chay duoc) - sinh 2 gia tri
      TACH BIET: raw token + sha256 hash.
  [3] Round-trip that day du: generate-token (cuc bo) -> record-bind-approval -> bind-token (CHI
      nhan hash) -> provision-pin (token qua stdin) -> row -> `m4_stage0p_pin_actor()` THAT chap
      nhan. Xac nhan bind-token KHONG BAO GIO nhan/in raw token, va toan bo output KHONG chua
      token/PIN/bcrypt hash that o bat ky buoc nao.
  [4] bind-token voi approval-id BUOC target khac (staff B) khi tu goi voi target-staff-id cua
      A -> tu choi cau truc (validate ca approval_id VA target_staff_id cung luc).
  [5] bind-token khong co approval nao khop (approval-id gia/khong ton tai) -> tu choi, khong
      tao token row.
  [6] Approval bi thu hoi TRUOC KHI bind (revoke-bind-approval) -> bind-token sau do bi tu choi
      ngay.
  [7] Approval het han (valid_until qua khu) TRUOC KHI bind -> bind-token bi tu choi.
  [8] bind-token ttl-minutes ngoai [1,30] -> tu choi TRUOC KHI cham DB (ca 2 bien: qua thap/qua
      cao), token-hash sai dinh dang cung vay.
  [9] Token da dung (consumed) -> lan 2 bi tu choi.
  [10] Token het han -> bi tu choi.
  [11] PIN mismatch/qua ngan -> tu choi NHUNG token VAN con dung duoc lai (khong bi tieu thu
       oan).
  [12] F-M4-PIN-R3-01: bind THANH CONG truoc, SAU DO moi revoke approval -> provision-pin (voi
       token da bind, van con "hop le" theo rieng no) van bi tu choi dung, khong credential nao
       duoc tao — chung minh vong doi token gan voi approval XUYEN SUOT, khong chi luc bind.
  [13] F-M4-PIN-R3-01: bind THANH CONG truoc, SAU DO approval moi het han (valid_until bi day ve
       qua khu, token.expires_at cua rieng no VAN con trong tuong lai) -> provision-pin van bi
       tu choi dung.
  [14] F-M4-PIN-R3-01: approval con hieu luc ngan hon ttl-minutes yeu cau -> token.expires_at
       THAT SU bi cap theo approval.valid_until (khong theo ttl yeu cau); approval sap het han
       duoi 1 phut -> bind-token tu choi hoan toan (khong tao token row).
  [15] F-M4-PIN-R3-01: race that giua revoke va consume qua 2 ket noi Postgres dong thoi — dung
       CHINH XAC cau lenh JOIN+FOR UPDATE ma `provision_pin()` dung (khong hand-copy sai lech) de
       chung minh revoke tu 1 connection khac THAT SU bi Postgres row-level lock CHAN toi khi
       connection dang giu lock (dang "consume") commit/rollback — khong co trang thai vua-
       revoked-vua-provisioned, va sau khi lock duoc nha, revoke hoan tat + provision-pin sau do
       bi tu choi dung.
  [16] F-EX-B1-01/02 (Amendment 06 Execution Blocker 1): `_db_url()` normalize dung
       `postgresql+asyncpg://` (SQLAlchemy async, dang production THAT dang dung) thanh
       `postgresql://` cho asyncpg; `postgres://`/`postgresql://` giu nguyen 100%; scheme la
       (vd `mysql://`) bi tu choi bang SystemExit TRUOC khi goi asyncpg.connect — kiem tra unit-
       level qua import truc tiep module (khong subprocess, chi rieng kich ban nay).
  [17] F-EX-B1-01/02: qua CLI THAT (subprocess), DATABASE_URL scheme la bi tu choi SACH (khong
       traceback), khong lo mat khau/DSN goc ra stdout/stderr, va KHONG tao partial write nao.
  [18] F-EX-B1-02 muc 5: integration THAT — DATABASE_URL dang production
       (`postgresql+asyncpg://...`) di qua toan bo duong `record-bind-approval` tren sandbox,
       xac nhan row THAT SU duoc ghi dung du DSN da duoc normalize.
  [19] F-DSN-R1-01 (PIN Tool DSN Compat Review 1): DATABASE_URL malformed ma phan truoc "://"
       dau tien tinh co chua fake secret VA ky tu dieu khien/xuong dong (\\n\\r\\t) - xac nhan
       thong bao loi la HANG SO CO DINH, khong phan chieu BAT KY phan nao cua input goc (khac
       [17] chi test 1 ten scheme "sach" nhu tu dien), khong traceback, khong log injection qua
       nhieu dong, va khong tao partial write.
  [20] F-EX-B2-02 (Amendment 07 Execution Blocker 1): regression - PIN tool._db_url la CHINH
       m4_dsn_utils.normalized_db_url (identity check), khong phai ban sao rieng co the lech voi
       runner trong tuong lai.
  [21] F-EX-B2-03: `revoke-credential` xoa hang credential that su, khong in pin_secret_hash/PIN
       that trong output, va `m4_stage0p_pin_actor()` tu choi dung ngay lap tuc voi PIN cu sau
       revoke (RAISE EXCEPTION that, khong phai gia lap).
  [22] F-EX-B2-03: goi `revoke-credential` lan 2 tren staff_id da revoke van exit 0 - idempotent.
  [23] F-EX-B2-03/04: `revoke-credential` voi actor-staff-id hoac target-staff-id khong ton tai
       bi tu choi TRUOC khi dung DB, va KHONG anh huong toi credential hop le khac.
  [24] F-RCR-R1-01 (Runner DSN/Credential Revocation Review 1): actor ACTIVE nhung KHONG co
       quyen `m4.stage0p.approve` bi tu choi (khac [23] la actor khong ton tai) - credential/
       audit_log khong doi.
  [25] F-RCR-R1-01: actor co dung quyen THANH CONG; target DA deactivate van revoke duoc (staff
       da deactivate cang can duoc cleanup, khong phai truong hop loai tru).
  [26] F-RCR-R1-04: `--reason` rong/toan khoang trang/qua 500 ky tu bi tu choi TRUOC khi cham DB
       - khong xoa credential, khong ghi audit_log; reason hop le (co khoang trang thua) van
       thanh cong sau trim.
  [27] F-RCR-R1-02: DATABASE_URL duoc SET nhung rong/toan khoang trang phai bi tu choi (KHONG
       am tham dung default) - phan biet ABSENT (dung default, khong regression) voi
       PRESENT-BUT-EMPTY (fail-closed) - ca unit-level lan qua CLI that.
  [28] F-RCR-R1-03: static scan machine-verifiable tren toan repo (`scripts/`, `app/`) - MOI file
       goi `asyncpg.connect`/`create_pool` phai co trong manifest tuong minh voi disposition
       (`shared_helper`/`bounded_legacy_replace`/`parameter_only`/`hardcoded_constant`) VA
       disposition do phai khop pattern that trong source - fail neu xuat hien entry point moi
       chua phan loai hoac manifest bi loi thoi.
  [29] F-RCR-R1-01 (Runner DSN/Credential Revocation Review 2): race THAT qua 2 ket noi Postgres
       dong thoi, dung CHINH XAC cau lenh FOR UPDATE ma `revoke_credential()` dung (khong hand-
       copy sai lech) - chung minh 1 thao tac deactivate actor dong thoi THAT SU bi Postgres row-
       level lock chan toi khi transaction cua revoke_credential() ket thuc, khong con khoang ho
       TOCTOU giua luc kiem quyen va luc thuc su xoa credential."""

import asyncio
import hashlib
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
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


def _run_generate_token() -> subprocess.CompletedProcess:
    # Co tinh KHONG truyen DATABASE_URL - generate-token phai chay cuc bo, khong can DB.
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    return subprocess.run(
        [sys.executable, "scripts/m4_stage0p_provision_pin.py", "generate-token"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30)


def _extract_field(text: str, prefix: str) -> str:
    for ln in text.splitlines():
        if ln.startswith(prefix):
            return ln[len(prefix):].strip()
    raise AssertionError(f"khong tim thay dong bat dau bang {prefix!r} trong output")


def _run_record_bind_approval(target_staff_id: int, recorded_by: int, approval_ref: str,
                               valid_minutes: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/m4_stage0p_provision_pin.py", "record-bind-approval",
         "--target-staff-id", str(target_staff_id), "--recorded-by", str(recorded_by),
         "--approval-ref", approval_ref, "--valid-minutes", str(valid_minutes)],
        cwd=str(ROOT), env={**os.environ, "DATABASE_URL": DB_URL},
        capture_output=True, text=True, timeout=30)


def _extract_approval_id(stdout: str) -> int:
    m = re.search(r"Approval id=(\d+)", stdout)
    if not m:
        raise AssertionError(f"khong trich xuat duoc approval id tu: {stdout!r}")
    return int(m.group(1))


def _run_revoke_bind_approval(approval_id: int, reason: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/m4_stage0p_provision_pin.py", "revoke-bind-approval",
         "--approval-id", str(approval_id), "--reason", reason],
        cwd=str(ROOT), env={**os.environ, "DATABASE_URL": DB_URL},
        capture_output=True, text=True, timeout=30)


def _run_bind_token(token_hash: str, target_staff_id: int, approval_id: int,
                     ttl_minutes: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/m4_stage0p_provision_pin.py", "bind-token",
         "--token-hash", token_hash, "--target-staff-id", str(target_staff_id),
         "--approval-id", str(approval_id), "--ttl-minutes", str(ttl_minutes)],
        cwd=str(ROOT), env={**os.environ, "DATABASE_URL": DB_URL},
        capture_output=True, text=True, timeout=30)


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


async def _grant_permission(admin, *, staff_id: int, permission: str) -> None:
    await admin.execute(
        "INSERT INTO m4_stage0p_staff_permissions (staff_id, permission, granted_by) "
        "VALUES ($1, $2, $1) ON CONFLICT DO NOTHING", staff_id, permission)


async def _provision_pin_secret_directly(admin, *, staff_id: int, pin_secret: str) -> None:
    """Test-only setup helper (dung truc tiep ket noi admin cua bo test, KHONG phai tool CLI) -
    tao san 1 credential de cac kich ban revoke-credential co gi de thu hoi, khong can lap lai
    toan bo ceremony 4 buoc (da duoc chung minh rieng o kich ban [3])."""
    await admin.execute(
        "INSERT INTO m4_stage0p_actor_credentials (staff_id, pin_secret_hash, provisioned_by) "
        "VALUES ($1, crypt($2, gen_salt('bf')), $1) "
        "ON CONFLICT (staff_id) DO UPDATE SET pin_secret_hash=crypt($2, gen_salt('bf')), "
        "failed_attempts=0, locked_until=NULL", staff_id, pin_secret)


def _run_revoke_credential(target_staff_id: int, actor_staff_id: int,
                            reason: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/m4_stage0p_provision_pin.py", "revoke-credential",
         "--target-staff-id", str(target_staff_id), "--actor-staff-id", str(actor_staff_id),
         "--reason", reason],
        cwd=str(ROOT), env={**os.environ, "DATABASE_URL": DB_URL},
        capture_output=True, text=True, timeout=30)


async def scenario_1_no_staff_id_input_surface() -> None:
    print("== [1] provision-pin KHONG con nhan staff-id duoi bat ky dang nao ==")
    help_text = subprocess.run(
        [sys.executable, "scripts/m4_stage0p_provision_pin.py", "provision-pin", "--help"],
        cwd=str(ROOT), capture_output=True, text=True).stdout
    check("--staff-id" not in help_text, "subcommand provision-pin KHONG co --staff-id")
    check("--staff" not in help_text, "subcommand provision-pin KHONG co bat ky bien the --staff nao")


async def scenario_2_generate_token_local_only() -> None:
    print("== [2] generate-token chay HOAN TOAN cuc bo (khong can DATABASE_URL) ==")
    r = _run_generate_token()
    check(r.returncode == 0, f"generate-token exit 0 khong can DB (thuc te {r.returncode})")
    token = _extract_field(r.stdout, "TOKEN=")
    token_hash = _extract_field(r.stdout, "TOKEN_HASH=")
    check(len(token) > 20, "raw token trich xuat duoc, do dai hop ly")
    check(re.match(r"^[0-9a-f]{64}$", token_hash) is not None,
          "hash trich xuat duoc dung dinh dang sha256 hex")
    check(hashlib.sha256(token.encode()).hexdigest() == token_hash,
          "hash in ra THAT SU la sha256(raw token) - khop tinh toan doc lap")


async def scenario_3_round_trip_real_pin_actor() -> None:
    print("== [3] Round-trip that: generate-token -> record-bind-approval -> bind-token (chi "
          "hash) -> provision-pin -> pin_actor() THAT chap nhan ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        await _reset_schema(admin)
    finally:
        await admin.close()
    _run_migrations()

    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-approver")
        target_id = await _make_staff(admin, "provision-pin-test-target")
        await admin.execute(
            "INSERT INTO m4_stage0p_staff_permissions (staff_id, permission, granted_by) "
            "VALUES ($1, 'm4.stage0p.operate', $1)", target_id)
    finally:
        await admin.close()

    gen = _run_generate_token()
    token = _extract_field(gen.stdout, "TOKEN=")
    token_hash = _extract_field(gen.stdout, "TOKEN_HASH=")

    approve = _run_record_bind_approval(target_id, approver_id, "test-approval-round-trip")
    check(approve.returncode == 0, f"record-bind-approval exit 0 (thuc te {approve.returncode})")
    approval_id = _extract_approval_id(approve.stdout)

    bind = _run_bind_token(token_hash, target_id, approval_id)
    check(bind.returncode == 0, f"bind-token exit 0 (thuc te {bind.returncode}); stderr={bind.stderr}")
    check(token not in bind.stdout and token not in bind.stderr,
          "bind-token KHONG BAO GIO nhan/in raw token - chi lam viec voi hash")

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

        bootstrap_row = await verify_conn.fetchrow(
            "SELECT consumed_at, issued_by FROM m4_stage0p_pin_bootstrap_tokens "
            "WHERE staff_id = $1", target_id)
        check(bootstrap_row is not None and bootstrap_row["consumed_at"] is not None,
              "token da duoc danh dau consumed_at sau khi thanh cong")
        check(bootstrap_row["issued_by"] == approver_id,
              "issued_by duoc SERVER-SIDE resolve tu approval record (khong phai CLI flag rieng)")
    finally:
        await verify_conn.close()

    all_output = gen.stdout + gen.stderr + approve.stdout + approve.stderr + \
        bind.stdout + bind.stderr + r2.stdout + r2.stderr
    check(token not in (bind.stdout + bind.stderr), "output bind-token KHONG chua token that")
    check(token not in r2.stdout and token not in r2.stderr, "output provision-pin KHONG chua token that")
    check(test_pin not in all_output, "khong buoc nao trong output chua PIN that")
    check("$2b$" not in all_output and "$2a$" not in all_output,
          "khong buoc nao trong output chua gia tri bcrypt hash that")


async def scenario_4_cross_principal_approval_mismatch_rejected() -> None:
    print("== [4] Approval cua A KHONG the dung de bind-token cho B ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-cross-approver")
        staff_a = await _make_staff(admin, "provision-pin-test-cross-a")
        staff_b = await _make_staff(admin, "provision-pin-test-cross-b")
    finally:
        await admin.close()

    approve = _run_record_bind_approval(staff_a, approver_id, "test-approval-cross-a")
    approval_id = _extract_approval_id(approve.stdout)

    fake_hash = hashlib.sha256(b"irrelevant-for-this-negative-test").hexdigest()
    bind_wrong_target = _run_bind_token(fake_hash, staff_b, approval_id)
    check(bind_wrong_target.returncode != 0,
          "bind-token cho staff_b bang approval BUOC voi staff_a bi tu choi")

    verify_conn = await asyncpg.connect(DB_URL)
    try:
        row = await verify_conn.fetchrow(
            "SELECT 1 FROM m4_stage0p_pin_bootstrap_tokens WHERE staff_id = $1", staff_b)
        check(row is None, "KHONG co token nao duoc bind cho staff_b tu approval sai target")
    finally:
        await verify_conn.close()


async def scenario_5_bind_without_matching_approval_rejected() -> None:
    print("== [5] bind-token khong co approval khop (approval-id gia) -> tu choi ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        staff_id = await _make_staff(admin, "provision-pin-test-noapproval")
    finally:
        await admin.close()

    fake_hash = hashlib.sha256(b"irrelevant-no-approval-case").hexdigest()
    bind = _run_bind_token(fake_hash, staff_id, approval_id=999999)
    check(bind.returncode != 0, "bind-token voi approval-id khong ton tai bi tu choi")

    verify_conn = await asyncpg.connect(DB_URL)
    try:
        row = await verify_conn.fetchrow(
            "SELECT 1 FROM m4_stage0p_pin_bootstrap_tokens WHERE staff_id = $1", staff_id)
        check(row is None, "KHONG co token nao duoc tao khi khong co approval khop")
    finally:
        await verify_conn.close()


async def scenario_6_revoked_approval_rejected() -> None:
    print("== [6] Approval bi thu hoi -> bind-token bi tu choi ngay ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-revoke-approver")
        target_id = await _make_staff(admin, "provision-pin-test-revoke-target")
    finally:
        await admin.close()

    approve = _run_record_bind_approval(target_id, approver_id, "test-approval-revoke")
    approval_id = _extract_approval_id(approve.stdout)

    revoke = _run_revoke_bind_approval(approval_id, "danh gia lai - chua can thiet")
    check(revoke.returncode == 0, f"revoke-bind-approval exit 0 (thuc te {revoke.returncode})")

    fake_hash = hashlib.sha256(b"irrelevant-revoked-case").hexdigest()
    bind = _run_bind_token(fake_hash, target_id, approval_id)
    check(bind.returncode != 0, "bind-token voi approval DA thu hoi bi tu choi")


async def scenario_7_expired_approval_rejected() -> None:
    print("== [7] Approval het han (valid_until qua khu) -> bind-token bi tu choi ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-expapp-approver")
        target_id = await _make_staff(admin, "provision-pin-test-expapp-target")
    finally:
        await admin.close()

    approve = _run_record_bind_approval(target_id, approver_id, "test-approval-expired")
    approval_id = _extract_approval_id(approve.stdout)

    admin2 = await asyncpg.connect(DB_URL)
    try:
        await admin2.execute(
            "UPDATE m4_stage0p_pin_bind_approvals SET "
            "valid_from = now() - interval '2 hours', valid_until = now() - interval '1 hour' "
            "WHERE id = $1", approval_id)
    finally:
        await admin2.close()

    fake_hash = hashlib.sha256(b"irrelevant-expired-approval-case").hexdigest()
    bind = _run_bind_token(fake_hash, target_id, approval_id)
    check(bind.returncode != 0, "bind-token voi approval DA het han bi tu choi")


async def scenario_8_ttl_out_of_range_rejected() -> None:
    print("== [8] bind-token ttl-minutes ngoai [1,30] -> tu choi TRUOC KHI cham DB ==")
    fake_hash = "0" * 64
    too_low = _run_bind_token(fake_hash, target_staff_id=1, approval_id=1, ttl_minutes=0)
    check(too_low.returncode != 0, "ttl-minutes=0 bi tu choi")
    too_high = _run_bind_token(fake_hash, target_staff_id=1, approval_id=1, ttl_minutes=31)
    check(too_high.returncode != 0, "ttl-minutes=31 bi tu choi (tran cung 30)")

    bad_hash = _run_bind_token("not-a-valid-sha256-hash", target_staff_id=1, approval_id=1)
    check(bad_hash.returncode != 0, "token-hash sai dinh dang bi tu choi truoc khi cham DB")


async def scenario_9_token_reuse_rejected() -> None:
    print("== [9] Token da dung (consumed) -> lan 2 bi tu choi ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-reuse-approver")
        target_id = await _make_staff(admin, "provision-pin-test-reuse-target")
    finally:
        await admin.close()

    gen = _run_generate_token()
    token = _extract_field(gen.stdout, "TOKEN=")
    token_hash = _extract_field(gen.stdout, "TOKEN_HASH=")
    approve = _run_record_bind_approval(target_id, approver_id, "test-approval-reuse")
    approval_id = _extract_approval_id(approve.stdout)
    bind = _run_bind_token(token_hash, target_id, approval_id)
    check(bind.returncode == 0, "bind-token thanh cong (chuan bi cho test reuse)")

    pin = "first-use-pin-value-12"
    r1 = _run_provision_pin(f"{token}\n{pin}\n{pin}\n")
    check(r1.returncode == 0, "lan dau dung token thanh cong")

    r2 = _run_provision_pin(f"{token}\nanother-pin-value-99\nanother-pin-value-99\n")
    check(r2.returncode != 0, "lan 2 dung LAI CUNG token bi tu choi (da consumed)")
    check("token khong hop le" in r2.stderr.lower() or "khong hop le" in r2.stderr.lower(),
          "loi neu ro token khong hop le/da dung")


async def scenario_10_expired_token_rejected() -> None:
    print("== [10] Token het han -> bi tu choi ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-expiry-approver")
        target_id = await _make_staff(admin, "provision-pin-test-expiry-target")
    finally:
        await admin.close()

    gen = _run_generate_token()
    token = _extract_field(gen.stdout, "TOKEN=")
    token_hash = _extract_field(gen.stdout, "TOKEN_HASH=")
    approve = _run_record_bind_approval(target_id, approver_id, "test-approval-expiry")
    approval_id = _extract_approval_id(approve.stdout)
    bind = _run_bind_token(token_hash, target_id, approval_id, ttl_minutes=30)
    check(bind.returncode == 0, "bind-token thanh cong (chuan bi cho test het han)")

    admin2 = await asyncpg.connect(DB_URL)
    try:
        # Gia lap het han nhung VAN thoa man CHECK m4_pin_bootstrap_ttl_bounded moi (F-M4-PIN-
        # R2-03, migration 041 - khoang cach issued_at..expires_at phai <= 30 phut) - dat CA
        # HAI moc vao qua khu, cach nhau 25 phut (trong tran), va expires_at van truoc now().
        await admin2.execute(
            "UPDATE m4_stage0p_pin_bootstrap_tokens SET "
            "issued_at = now() - interval '35 minutes', "
            "expires_at = now() - interval '10 minutes' "
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


async def scenario_11_pin_mismatch_does_not_burn_token() -> None:
    print("== [11] PIN mismatch/qua ngan -> tu choi NHUNG token VAN dung duoc lai ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-retry-approver")
        target_id = await _make_staff(admin, "provision-pin-test-retry-target")
    finally:
        await admin.close()

    gen = _run_generate_token()
    token = _extract_field(gen.stdout, "TOKEN=")
    token_hash = _extract_field(gen.stdout, "TOKEN_HASH=")
    approve = _run_record_bind_approval(target_id, approver_id, "test-approval-retry")
    approval_id = _extract_approval_id(approve.stdout)
    bind = _run_bind_token(token_hash, target_id, approval_id)
    check(bind.returncode == 0, "bind-token thanh cong (chuan bi cho test retry)")

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


async def scenario_12_revoke_after_bind_invalidates_token() -> None:
    print("== [12] bind THANH CONG truoc, SAU DO revoke approval -> provision-pin bi tu choi "
          "dung (F-M4-PIN-R3-01) ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-postrevoke-approver")
        target_id = await _make_staff(admin, "provision-pin-test-postrevoke-target")
    finally:
        await admin.close()

    gen = _run_generate_token()
    token = _extract_field(gen.stdout, "TOKEN=")
    token_hash = _extract_field(gen.stdout, "TOKEN_HASH=")
    approve = _run_record_bind_approval(target_id, approver_id, "test-approval-postrevoke")
    approval_id = _extract_approval_id(approve.stdout)
    bind = _run_bind_token(token_hash, target_id, approval_id)
    check(bind.returncode == 0, "bind-token thanh cong TRUOC khi revoke (chuan bi)")

    revoke = _run_revoke_bind_approval(approval_id, "danh gia lai SAU khi da bind")
    check(revoke.returncode == 0, f"revoke-bind-approval SAU bind exit 0 (thuc te {revoke.returncode})")

    r = _run_provision_pin(f"{token}\npostrevoke-pin-value-1\npostrevoke-pin-value-1\n")
    check(r.returncode != 0,
          "provision-pin voi token DA bind nhung approval bi revoke SAU do van bi tu choi")

    verify_conn = await asyncpg.connect(DB_URL)
    try:
        row = await verify_conn.fetchrow(
            "SELECT 1 FROM m4_stage0p_actor_credentials WHERE staff_id = $1", target_id)
        check(row is None, "KHONG co credential nao duoc tao tu token co approval bi revoke sau bind")
        token_row = await verify_conn.fetchrow(
            "SELECT consumed_at FROM m4_stage0p_pin_bootstrap_tokens WHERE token_hash = $1",
            hashlib.sha256(token.encode()).hexdigest())
        check(token_row is not None and token_row["consumed_at"] is None,
              "token BAN THAN no khong bi danh dau consumed (bi chan boi approval, khong phai "
              "boi chinh no)")
    finally:
        await verify_conn.close()


async def scenario_13_approval_expiry_after_bind_invalidates_token() -> None:
    print("== [13] bind THANH CONG truoc, SAU DO approval het han (token.expires_at rieng no "
          "VAN con tuong lai) -> provision-pin van bi tu choi dung (F-M4-PIN-R3-01) ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-postexpiry-approver")
        target_id = await _make_staff(admin, "provision-pin-test-postexpiry-target")
    finally:
        await admin.close()

    gen = _run_generate_token()
    token = _extract_field(gen.stdout, "TOKEN=")
    token_hash = _extract_field(gen.stdout, "TOKEN_HASH=")
    # valid-minutes du dai (60p) de token.expires_at (cap boi MIN(ttl, valid_until)) khong bi
    # anh huong boi buoc lui valid_until ve qua khu O DUOI - no da duoc GHI CO DINH luc bind.
    approve = _run_record_bind_approval(target_id, approver_id, "test-approval-postexpiry",
                                         valid_minutes=60)
    approval_id = _extract_approval_id(approve.stdout)
    bind = _run_bind_token(token_hash, target_id, approval_id, ttl_minutes=30)
    check(bind.returncode == 0, "bind-token thanh cong TRUOC khi approval het han (chuan bi)")

    verify_conn = await asyncpg.connect(DB_URL)
    try:
        token_expires_at = await verify_conn.fetchval(
            "SELECT expires_at FROM m4_stage0p_pin_bootstrap_tokens WHERE token_hash = $1",
            token_hash)
    finally:
        await verify_conn.close()

    admin2 = await asyncpg.connect(DB_URL)
    try:
        await admin2.execute(
            "UPDATE m4_stage0p_pin_bind_approvals SET "
            "valid_from = now() - interval '2 hours', valid_until = now() - interval '1 hour' "
            "WHERE id = $1", approval_id)
    finally:
        await admin2.close()

    r = _run_provision_pin(f"{token}\npostexpiry-pin-value-1\npostexpiry-pin-value-1\n")
    check(r.returncode != 0,
          "provision-pin voi token co approval het han SAU bind van bi tu choi, "
          "MAC DU token.expires_at rieng no van con trong tuong lai")

    check(token_expires_at > datetime.now(timezone.utc),
          "xac nhan gia thiet: token.expires_at rieng no THAT SU van con trong tuong lai luc "
          "test nay chay (nen viec bi tu choi la NHO join lai approval, khong phai tinh co)")


async def scenario_14_ttl_capped_by_approval_window() -> None:
    print("== [14] token.expires_at bi CAP theo approval.valid_until khi ngan hon ttl yeu cau; "
          "approval sap het han duoi 1 phut -> bind-token tu choi hoan toan (F-M4-PIN-R3-01) ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-ttlcap-approver")
        target_id = await _make_staff(admin, "provision-pin-test-ttlcap-target")
    finally:
        await admin.close()

    gen = _run_generate_token()
    token_hash = _extract_field(gen.stdout, "TOKEN_HASH=")
    approve = _run_record_bind_approval(target_id, approver_id, "test-approval-ttlcap",
                                         valid_minutes=5)
    approval_id = _extract_approval_id(approve.stdout)

    bind = _run_bind_token(token_hash, target_id, approval_id, ttl_minutes=30)
    check(bind.returncode == 0, "bind-token thanh cong (approval con hieu luc ~5p, yeu cau 30p)")

    verify_conn = await asyncpg.connect(DB_URL)
    try:
        row = await verify_conn.fetchrow(
            "SELECT t.expires_at, a.valid_until FROM m4_stage0p_pin_bootstrap_tokens t "
            "JOIN m4_stage0p_pin_bind_approvals a ON a.id = t.approval_id "
            "WHERE t.token_hash = $1", token_hash)
    finally:
        await verify_conn.close()
    delta_seconds = abs((row["expires_at"] - row["valid_until"]).total_seconds())
    check(delta_seconds < 2,
          f"token.expires_at ({row['expires_at'].isoformat()}) khop approval.valid_until "
          f"({row['valid_until'].isoformat()}) trong sai so <2s - CAP dung, KHONG dung ttl "
          f"30p yeu cau")

    admin2 = await asyncpg.connect(DB_URL)
    try:
        approve2 = _run_record_bind_approval(target_id, approver_id, "test-approval-ttlcap-tiny",
                                              valid_minutes=5)
        approval_id2 = _extract_approval_id(approve2.stdout)
        await admin2.execute(
            "UPDATE m4_stage0p_pin_bind_approvals SET valid_until = now() + interval '30 seconds' "
            "WHERE id = $1", approval_id2)
    finally:
        await admin2.close()

    gen2 = _run_generate_token()
    token_hash2 = _extract_field(gen2.stdout, "TOKEN_HASH=")
    bind2 = _run_bind_token(token_hash2, target_id, approval_id2, ttl_minutes=30)
    check(bind2.returncode != 0,
          "bind-token tu choi khi approval con lai duoi 1 phut - khong du thoi gian toi thieu")

    verify_conn2 = await asyncpg.connect(DB_URL)
    try:
        row2 = await verify_conn2.fetchrow(
            "SELECT 1 FROM m4_stage0p_pin_bootstrap_tokens WHERE token_hash = $1", token_hash2)
        check(row2 is None, "KHONG co token row nao duoc tao khi approval sap het han")
    finally:
        await verify_conn2.close()


async def scenario_15_revoke_consume_race_locking() -> None:
    print("== [15] Race THAT giua revoke va consume qua 2 ket noi Postgres dong thoi - dung "
          "CHINH XAC cau lenh JOIN+FOR UPDATE ma provision_pin() dung (F-M4-PIN-R3-01) ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-race-approver")
        target_id = await _make_staff(admin, "provision-pin-test-race-target")
    finally:
        await admin.close()

    gen = _run_generate_token()
    token = _extract_field(gen.stdout, "TOKEN=")
    token_hash = _extract_field(gen.stdout, "TOKEN_HASH=")
    approve = _run_record_bind_approval(target_id, approver_id, "test-approval-race")
    approval_id = _extract_approval_id(approve.stdout)
    bind = _run_bind_token(token_hash, target_id, approval_id)
    check(bind.returncode == 0, "bind-token thanh cong (chuan bi cho test race)")

    conn_a = await asyncpg.connect(DB_URL)
    conn_b = await asyncpg.connect(DB_URL)
    tx = conn_a.transaction()
    await tx.start()
    try:
        # CHINH XAC cung 1 cau lenh provision_pin() dung o buoc consume (xem
        # m4_stage0p_provision_pin.py) - khoa CA HAI bang cung luc.
        locked = await conn_a.fetchrow(
            "SELECT t.staff_id FROM m4_stage0p_pin_bootstrap_tokens t "
            "JOIN m4_stage0p_pin_bind_approvals a ON a.id = t.approval_id "
            "WHERE t.token_hash = $1 AND t.consumed_at IS NULL AND t.expires_at > now() "
            "AND a.revoked_at IS NULL AND now() < a.valid_until "
            "FOR UPDATE OF t, a",
            token_hash)
        check(locked is not None, "connection A lay duoc lock (approval van hop le luc do)")

        task_b = asyncio.create_task(conn_b.execute(
            "UPDATE m4_stage0p_pin_bind_approvals SET revoked_at = now(), "
            "revoke_reason = 'test-race-scenario-15' WHERE id = $1", approval_id))
        blocked = False
        try:
            await asyncio.wait_for(asyncio.shield(task_b), timeout=1.5)
        except asyncio.TimeoutError:
            blocked = True
        check(blocked, "revoke tu connection B THAT SU bi Postgres CHAN boi FOR UPDATE cua "
              "connection A (row-level lock that, khong phai gia lap bang code)")

        await tx.commit()  # nha lock - KHONG tu tieu thu token o day, chi kiem tra lock
        await asyncio.wait_for(task_b, timeout=5)
    finally:
        await conn_a.close()

    revoked_row = await conn_b.fetchrow(
        "SELECT revoked_at FROM m4_stage0p_pin_bind_approvals WHERE id = $1", approval_id)
    check(revoked_row is not None and revoked_row["revoked_at"] is not None,
          "SAU KHI A nha lock, revoke cua B hoan tat thanh cong (bi tri hoan, khong bi mat)")
    await conn_b.close()

    r_after = _run_provision_pin(f"{token}\nrace-after-value-123\nrace-after-value-123\n")
    check(r_after.returncode != 0,
          "provision-pin SAU race that (approval da revoke) van bi tu choi dung - khong co "
          "trang thai vua-revoked-vua-provisioned")


def _load_pin_tool_module():
    """Import truc tiep module (khong qua subprocess) CHI cho unit-level check cua _db_url() -
    moi kich ban khac trong file nay van chay tool nhu 1 subprocess doc lap (black-box), dung
    quy uoc chinh cua bo evidence nay."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "m4_stage0p_provision_pin_module", ROOT / "scripts" / "m4_stage0p_provision_pin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def scenario_16_dsn_scheme_normalize_unit() -> None:
    print("== [16] F-EX-B1-01/02: _db_url() normalize dung scheme SQLAlchemy async, giu "
          "nguyen DSN thuan, tu choi scheme la (unit-level, khong qua subprocess) ==")
    import m4_dsn_utils
    pin_tool = _load_pin_tool_module()
    original = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:FAKESECRET1@h:5432/d"
        check(pin_tool._db_url() == "postgresql://u:FAKESECRET1@h:5432/d",
              "postgresql+asyncpg:// duoc normalize dung thanh postgresql:// (CHI doi scheme, "
              "giu nguyen user/pass/host/db)")

        os.environ["DATABASE_URL"] = "postgres://u:FAKESECRET2@h:5432/d"
        check(pin_tool._db_url() == "postgres://u:FAKESECRET2@h:5432/d",
              "postgres:// (alias thuan) giu nguyen, khong bi doi")

        os.environ["DATABASE_URL"] = "postgresql://u:FAKESECRET3@h:5432/d"
        check(pin_tool._db_url() == "postgresql://u:FAKESECRET3@h:5432/d",
              "postgresql:// (DSN thuan, dang cu) giu nguyen 100% - khong regression")

        os.environ["DATABASE_URL"] = "mysql://u:FAKESECRET4@h:5432/d"
        raised = False
        exc_text = ""
        try:
            pin_tool._db_url()
        except SystemExit as e:
            raised = True
            exc_text = str(e.code)
        check(raised, "scheme khong nam trong allowlist (vd 'mysql') bi tu choi bang SystemExit "
              "TRUOC khi co the goi asyncpg.connect (fail-closed)")
        # F-DSN-R1-01: kiem CHINH XAC bang hang so cua module (khong chi "khong chua marker") -
        # chung minh thong bao loi la HANG SO CO DINH, khong noi suy BAT KY phan nao cua input
        # goc (ke ca phan "scheme" tuong nhu vo hai) vao thong diep.
        check(exc_text == m4_dsn_utils.DB_URL_UNSUPPORTED_SCHEME_MSG,
              "thong bao loi tu choi scheme la HANG SO CO DINH tu module - khong noi suy bat ky "
              "phan nao cua DATABASE_URL goc (khong chi rieng FAKESECRET4)")
    finally:
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def _run_record_bind_approval_with_env(target_staff_id: int, recorded_by: int,
                                        approval_ref: str, db_url: str,
                                        valid_minutes: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/m4_stage0p_provision_pin.py", "record-bind-approval",
         "--target-staff-id", str(target_staff_id), "--recorded-by", str(recorded_by),
         "--approval-ref", approval_ref, "--valid-minutes", str(valid_minutes)],
        cwd=str(ROOT), env={**os.environ, "DATABASE_URL": db_url},
        capture_output=True, text=True, timeout=30)


async def scenario_17_unknown_scheme_failclosed_subprocess_no_secret_leak() -> None:
    print("== [17] F-EX-B1-01/02: scheme la qua CLI THAT (subprocess) bi tu choi TRUOC ket noi "
          "DB, khong traceback, khong lo secret ra stdout/stderr ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-scheme-reject-approver")
        target_id = await _make_staff(admin, "provision-pin-test-scheme-reject-target")
    finally:
        await admin.close()

    marker = "SUPER_SECRET_MARKER_XYZ_998877"
    bad_dsn = f"badscheme://testuser:{marker}@db:5432/alpha3s"
    r = _run_record_bind_approval_with_env(
        target_id, approver_id, "test-approval-scheme-reject", bad_dsn)
    combined = r.stdout + r.stderr
    check(r.returncode != 0, "record-bind-approval voi scheme la exit != 0")
    check(marker not in combined, "mat khau gia trong DATABASE_URL KHONG xuat hien trong "
          "stdout/stderr")
    check(bad_dsn not in combined, "toan bo chuoi DSN goc KHONG xuat hien trong stdout/stderr")
    check("Traceback" not in r.stderr, "tu choi SACH (sys.exit co thong diep), khong phai "
          "unhandled traceback nhu truoc khi sua")

    # Xac nhan KHONG co approval nao duoc tao du that bai (fail-closed thuc su, khong partial
    # write) - dung ket noi DB_URL that (khong phai bad_dsn) de kiem tra.
    verify = await asyncpg.connect(DB_URL)
    try:
        row = await verify.fetchrow(
            "SELECT id FROM m4_stage0p_pin_bind_approvals WHERE approval_ref = $1",
            "test-approval-scheme-reject")
        check(row is None, "KHONG co approval row nao duoc tao khi scheme bi tu choi (khong "
              "partial write)")
    finally:
        await verify.close()


async def scenario_18_production_shaped_dsn_integration() -> None:
    print("== [18] F-EX-B1-02 muc 5: integration THAT voi DATABASE_URL dang production "
          "(postgresql+asyncpg://) di qua record-bind-approval tren sandbox ==")
    assert DB_URL.startswith("postgresql://"), "gia dinh sandbox DB_URL dang postgresql://"
    production_shaped_dsn = "postgresql+asyncpg://" + DB_URL[len("postgresql://"):]

    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-prodshape-approver")
        target_id = await _make_staff(admin, "provision-pin-test-prodshape-target")
    finally:
        await admin.close()

    r = _run_record_bind_approval_with_env(
        target_id, approver_id, "test-approval-prodshape", production_shaped_dsn)
    check(r.returncode == 0,
          f"record-bind-approval THANH CONG qua DATABASE_URL dang production "
          f"'postgresql+asyncpg://...' (thuc te exit={r.returncode}, stderr={r.stderr!r})")
    check("postgresql+asyncpg" not in (r.stdout + r.stderr),
          "output khong echo lai chuoi DSN goc")

    verify = await asyncpg.connect(DB_URL)
    try:
        row = await verify.fetchrow(
            "SELECT id, target_staff_id, recorded_by FROM m4_stage0p_pin_bind_approvals "
            "WHERE approval_ref = $1", "test-approval-prodshape")
        check(row is not None, "approval row THAT SU duoc ghi vao DB qua ket noi normalize tu "
              "DSN dang production")
        if row is not None:
            check(row["target_staff_id"] == target_id and row["recorded_by"] == approver_id,
                  "row ghi dung target_staff_id/recorded_by (khong bi lech du DSN duoc bien doi)")
    finally:
        await verify.close()


async def scenario_19_malformed_scheme_with_secret_and_control_chars_no_leak() -> None:
    print("== [19] F-DSN-R1-01: DATABASE_URL malformed - phan truoc '://' dau tien tinh co "
          "chua fake secret VA ky tu dieu khien/xuong dong - van khong lo gi, khong goi DB ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approver_id = await _make_staff(admin, "provision-pin-test-malformed-approver")
        target_id = await _make_staff(admin, "provision-pin-test-malformed-target")
    finally:
        await admin.close()

    marker = "LEAKED_CREDENTIAL_MARKER_445566"
    # Phan "scheme" (truoc "://" dau tien) o day KHONG phai 1 scheme hop le - no la 1 chuoi
    # trong tinh huong DATABASE_URL bi cau hinh sai/gia mao, co chua marker bi ro ri VA ky tu
    # dieu khien (\n, \r, \t) - dung de xac nhan _db_url() khong bao gio phan chieu bat ky phan
    # nao cua no (F-DSN-R1-01), khac voi test [17] (chi test 1 ten scheme "sach" nhu tu dien).
    malformed_scheme = f"oops{marker}\n\r\tstill-not-a-scheme"
    malformed_dsn = f"{malformed_scheme}://testuser:{marker}@db:5432/alpha3s"
    r = _run_record_bind_approval_with_env(
        target_id, approver_id, "test-approval-malformed-scheme", malformed_dsn)
    combined = r.stdout + r.stderr
    check(r.returncode != 0, "record-bind-approval voi DATABASE_URL malformed exit != 0")
    check(marker not in combined,
          "marker bi ro ri gia (xuat hien CA trong scheme LAN password) KHONG xuat hien o "
          "stdout/stderr du la 1 phan cua 'scheme' malformed")
    check(malformed_dsn not in combined, "toan bo DSN malformed goc KHONG xuat hien trong output")
    check("Traceback" not in r.stderr, "tu choi SACH bang thong bao hang so, khong traceback")
    check(r.stderr.strip().count("\n") <= 1,
          "thong bao loi la 1 dong hang so - khong phan chieu ky tu xuong dong tu input malformed "
          "vao stderr (chong log injection)")

    verify = await asyncpg.connect(DB_URL)
    try:
        row = await verify.fetchrow(
            "SELECT id FROM m4_stage0p_pin_bind_approvals WHERE approval_ref = $1",
            "test-approval-malformed-scheme")
        check(row is None, "KHONG co approval row nao duoc tao tu DATABASE_URL malformed (khong "
              "partial write)")
    finally:
        await verify.close()


async def scenario_20_dsn_shared_module_identity_regression() -> None:
    print("== [20] F-EX-B2-02: regression - PIN tool._db_url la CHINH m4_dsn_utils."
          "normalized_db_url (khong phai ban sao rieng co the lech voi runner trong tuong lai) ==")
    import m4_dsn_utils
    pin_tool = _load_pin_tool_module()
    check(pin_tool._db_url is m4_dsn_utils.normalized_db_url,
          "PIN tool._db_url va m4_dsn_utils.normalized_db_url la CUNG 1 ham object (identity "
          "check) - dam bao khong con logic normalize DSN nao rieng, lech trong PIN tool")


async def scenario_21_revoke_credential_success_and_pin_actor_rejects() -> None:
    print("== [21] F-EX-B2-03: revoke-credential thanh cong -> credential bi xoa -> "
          "m4_stage0p_pin_actor() tu choi PIN cu ngay lap tuc ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        recorder_id = await _make_staff(admin, "provision-pin-test-revcred21-recorder")
        await _grant_permission(admin, staff_id=recorder_id, permission="m4.stage0p.approve")
        target_id = await _make_staff(admin, "provision-pin-test-revcred21-target")
        test_pin = "revoke-test-pin-value-999"
        await _provision_pin_secret_directly(admin, staff_id=target_id, pin_secret=test_pin)

        before = await admin.fetchrow(
            "SELECT * FROM m4_stage0p_pin_actor($1, $2)", target_id, test_pin)
        check(before["pinned_staff_id"] == target_id,
              "PIN con hop le TRUOC khi revoke (xac nhan setup dung, khong phai false positive)")

        r = _run_revoke_credential(target_id, recorder_id, "test-revoke-scenario-21")
        check(r.returncode == 0, f"revoke-credential exit 0 (thuc te {r.returncode}, "
              f"stderr={r.stderr!r})")
        # Luu y: output CO the (va nen) chua chuoi CHU "pin_secret_hash" trong 1 cau xac nhan
        # dang "(KHONG in pin_secret_hash - ...)" - dung quy uoc da co san o provision_pin(). Cai
        # can kiem la GIA TRI hash/PIN that khong bao gio xuat hien, khong phai ten cot.
        check(test_pin not in (r.stdout + r.stderr), "output KHONG chua gia tri PIN that")
        check("$2a$" not in (r.stdout + r.stderr) and "$2b$" not in (r.stdout + r.stderr),
              "output KHONG chua gia tri bcrypt hash that (prefix $2a$/$2b$)")

        row_after = await admin.fetchrow(
            "SELECT 1 FROM m4_stage0p_actor_credentials WHERE staff_id = $1", target_id)
        check(row_after is None, "hang credential THAT SU khong con trong DB sau revoke")

        # m4_stage0p_pin_actor() RAISE EXCEPTION thuc su (khong tra ve NULL row) khi khong tim
        # thay credential - phai bat exception That, khong mong doi gia tri tra ve.
        raised_correctly = False
        try:
            await admin.fetchrow(
                "SELECT * FROM m4_stage0p_pin_actor($1, $2)", target_id, test_pin)
        except asyncpg.exceptions.PostgresError as e:
            raised_correctly = "provisioning" in str(e).lower()
        check(raised_correctly,
              "m4_stage0p_pin_actor() RAISE EXCEPTION ('chua duoc provisioning') dung cho "
              "staff_id vua bi revoke - PIN cu khong con dung duoc nua")
    finally:
        await admin.close()


async def scenario_22_revoke_credential_idempotent_repeat() -> None:
    print("== [22] F-EX-B2-03: revoke-credential goi LAN 2 tren CUNG staff_id (da revoke) van "
          "exit 0 - idempotent, khong loi ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        recorder_id = await _make_staff(admin, "provision-pin-test-revcred22-recorder")
        await _grant_permission(admin, staff_id=recorder_id, permission="m4.stage0p.approve")
        target_id = await _make_staff(admin, "provision-pin-test-revcred22-target")
        await _provision_pin_secret_directly(admin, staff_id=target_id, pin_secret="idem-pin-value")

        r1 = _run_revoke_credential(target_id, recorder_id, "first-revoke")
        check(r1.returncode == 0, f"lan 1 revoke exit 0 (thuc te {r1.returncode})")

        r2 = _run_revoke_credential(target_id, recorder_id, "second-revoke-idempotent")
        check(r2.returncode == 0,
              f"lan 2 revoke (khong con gi de xoa) VAN exit 0 - idempotent (thuc te {r2.returncode})")
        check("idempotent" in r2.stdout.lower(),
              "output lan 2 neu ro day la truong hop idempotent (khong co gi de xoa)")
    finally:
        await admin.close()


async def scenario_23_revoke_credential_wrong_actor_target_failclosed() -> None:
    print("== [23] F-EX-B2-03/04: revoke-credential voi actor/target khong ton tai hoac khong "
          "active bi tu choi TRUOC khi dung toi DB write ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        recorder_id = await _make_staff(admin, "provision-pin-test-revcred23-recorder")
        await _grant_permission(admin, staff_id=recorder_id, permission="m4.stage0p.approve")
        target_id = await _make_staff(admin, "provision-pin-test-revcred23-target")
        await _provision_pin_secret_directly(admin, staff_id=target_id, pin_secret="wrongat-pin")

        nonexistent_id = 9_999_000_111
        r_bad_target = _run_revoke_credential(nonexistent_id, recorder_id, "bad-target")
        check(r_bad_target.returncode != 0,
              "target-staff-id khong ton tai bi tu choi (exit != 0)")

        r_bad_actor = _run_revoke_credential(target_id, nonexistent_id, "bad-actor")
        check(r_bad_actor.returncode != 0,
              "actor-staff-id khong ton tai bi tu choi (exit != 0)")

        # Xac nhan credential THAT (target_id hop le) KHONG bi dung toi boi 2 lan goi sai o tren.
        row = await admin.fetchrow(
            "SELECT 1 FROM m4_stage0p_actor_credentials WHERE staff_id = $1", target_id)
        check(row is not None,
              "credential hop le KHONG bi xoa boi cac lan goi that bai voi actor/target sai")
    finally:
        await admin.close()


async def scenario_24_revoke_credential_unauthorized_active_actor_failclosed() -> None:
    print("== [24] F-RCR-R1-01: actor ACTIVE nhung KHONG co quyen m4.stage0p.approve bi tu choi "
          "- khac voi kich ban [23] (actor khong ton tai) ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        # Actor active, TON TAI that, nhung KHONG duoc grant quyen m4.stage0p.approve.
        unauthorized_actor_id = await _make_staff(admin, "provision-pin-test-revcred24-noperm")
        target_id = await _make_staff(admin, "provision-pin-test-revcred24-target")
        await _provision_pin_secret_directly(admin, staff_id=target_id, pin_secret="noperm-pin")

        r = _run_revoke_credential(target_id, unauthorized_actor_id, "unauthorized-attempt")
        check(r.returncode != 0,
              "actor active nhung KHONG co quyen m4.stage0p.approve bi tu choi (exit != 0)")

        row = await admin.fetchrow(
            "SELECT 1 FROM m4_stage0p_actor_credentials WHERE staff_id = $1", target_id)
        check(row is not None, "credential KHONG bi xoa boi actor khong co quyen")

        audit_count = await admin.fetchval(
            "SELECT count(*) FROM audit_log WHERE action = 'm4_stage0p.pin_credential.revoke' "
            "AND entity_id = $1", str(target_id))
        check(audit_count == 0, "KHONG co audit_log row nao duoc ghi tu lan goi bi tu choi nay")
    finally:
        await admin.close()


async def scenario_25_revoke_credential_authorized_actor_and_inactive_target_succeed() -> None:
    print("== [25] F-RCR-R1-01: actor co dung quyen m4.stage0p.approve THANH CONG; target da "
          "DEACTIVATE van revoke duoc (deactivated staff cang can duoc cleanup, khong phai ngoai "
          "le) ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        authorized_actor_id = await _make_staff(admin, "provision-pin-test-revcred25-recorder")
        await _grant_permission(admin, staff_id=authorized_actor_id,
                                 permission="m4.stage0p.approve")
        target_id = await _make_staff(admin, "provision-pin-test-revcred25-target")
        await _provision_pin_secret_directly(admin, staff_id=target_id, pin_secret="inactive-pin")
        await admin.execute("UPDATE staff_users SET is_active = false WHERE id = $1", target_id)

        r = _run_revoke_credential(target_id, authorized_actor_id, "cleanup-deactivated-staff")
        check(r.returncode == 0,
              f"revoke-credential THANH CONG cho target DA deactivate (thuc te exit={r.returncode}, "
              f"stderr={r.stderr!r})")

        row = await admin.fetchrow(
            "SELECT 1 FROM m4_stage0p_actor_credentials WHERE staff_id = $1", target_id)
        check(row is None, "credential cua target da deactivate THAT SU bi xoa")
    finally:
        await admin.close()


async def scenario_26_revoke_credential_reason_validation() -> None:
    print("== [26] F-RCR-R1-04: --reason rong/toan khoang trang/qua dai bi tu choi TRUOC khi cham "
          "DB - khong xoa, khong ghi audit ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        actor_id = await _make_staff(admin, "provision-pin-test-revcred26-recorder")
        await _grant_permission(admin, staff_id=actor_id, permission="m4.stage0p.approve")
        target_id = await _make_staff(admin, "provision-pin-test-revcred26-target")
        await _provision_pin_secret_directly(admin, staff_id=target_id, pin_secret="reason-pin")

        r_empty = _run_revoke_credential(target_id, actor_id, "")
        check(r_empty.returncode != 0, "reason rong bi tu choi (exit != 0)")

        r_whitespace = _run_revoke_credential(target_id, actor_id, "   \t  ")
        check(r_whitespace.returncode != 0, "reason toan khoang trang bi tu choi sau trim")

        r_oversized = _run_revoke_credential(target_id, actor_id, "x" * 501)
        check(r_oversized.returncode != 0, "reason vuot qua gioi han do dai bi tu choi")

        row = await admin.fetchrow(
            "SELECT 1 FROM m4_stage0p_actor_credentials WHERE staff_id = $1", target_id)
        check(row is not None, "credential KHONG bi xoa boi bat ky lan goi reason khong hop le nao")
        audit_count = await admin.fetchval(
            "SELECT count(*) FROM audit_log WHERE action = 'm4_stage0p.pin_credential.revoke' "
            "AND entity_id = $1", str(target_id))
        check(audit_count == 0, "KHONG co audit_log row nao tu cac lan reason khong hop le")

        r_valid = _run_revoke_credential(target_id, actor_id, "  valid reason after trim  ")
        check(r_valid.returncode == 0,
              f"reason hop le (co khoang trang thua o 2 dau, se duoc trim) THANH CONG "
              f"(thuc te exit={r_valid.returncode})")
    finally:
        await admin.close()


async def scenario_27_dsn_present_but_empty_failclosed() -> None:
    print("== [27] F-RCR-R1-02: DATABASE_URL duoc SET nhung rong/toan khoang trang phai tu choi "
          "- KHONG duoc am tham dung default (phan biet ABSENT voi PRESENT-BUT-EMPTY) ==")
    import m4_dsn_utils
    original = os.environ.get("DATABASE_URL")
    original_present = "DATABASE_URL" in os.environ
    try:
        os.environ["DATABASE_URL"] = ""
        raised_empty = False
        exc_text = ""
        try:
            m4_dsn_utils.normalized_db_url()
        except SystemExit as e:
            raised_empty = True
            exc_text = str(e.code)
        check(raised_empty, "DATABASE_URL='' (rong) bi tu choi bang SystemExit, KHONG am tham "
              "dung default")
        check(exc_text == m4_dsn_utils.DB_URL_EMPTY_MSG,
              "thong bao loi la HANG SO rieng cho truong hop rong (DB_URL_EMPTY_MSG)")

        os.environ["DATABASE_URL"] = "   \t  "
        raised_whitespace = False
        try:
            m4_dsn_utils.normalized_db_url()
        except SystemExit:
            raised_whitespace = True
        check(raised_whitespace, "DATABASE_URL toan khoang trang cung bi tu choi (khong chi "
              "chuoi rong tuyet doi)")

        os.environ.pop("DATABASE_URL", None)
        check(m4_dsn_utils.normalized_db_url() == "postgresql://alpha3s:alpha3s@db:5432/alpha3s",
              "DATABASE_URL HOAN TOAN ABSENT (chua tung set) van dung default nhu cu - khong "
              "regression cho truong hop chay local khong co env")

        r_subprocess = subprocess.run(
            [sys.executable, "scripts/m4_stage0p_provision_pin.py", "revoke-credential",
             "--target-staff-id", "1", "--actor-staff-id", "1", "--reason", "dsn-empty-test"],
            cwd=str(ROOT), env={**os.environ, "DATABASE_URL": ""},
            capture_output=True, text=True, timeout=30)
        check(r_subprocess.returncode != 0,
              "qua CLI that: DATABASE_URL='' cung bi tu choi TRUOC khi goi asyncpg.connect")
        check("Traceback" not in r_subprocess.stderr,
              "tu choi SACH bang thong bao hang so, khong traceback")
    finally:
        if original_present:
            os.environ["DATABASE_URL"] = original
        else:
            os.environ.pop("DATABASE_URL", None)


# F-RCR-R1-03: manifest tuong minh cho MOI file trong repo goi asyncpg.connect()/create_pool() -
# scanner o kich ban [28] fail neu tim thay 1 call site KHONG nam trong danh sach nay (drift
# trong tuong lai) HOAC 1 entry trong manifest khong con dung disposition da khai bao.
_DSN_INVENTORY_MANIFEST = {
    "scripts/m4_stage0p_provision_pin.py": "shared_helper",
    "scripts/m4_stage0p_rehearsal_runner.py": "shared_helper",
    "app/db_pool.py": "bounded_legacy_replace",
    "app/api/dashboard.py": "bounded_legacy_replace",
    "app/services/audit_service.py": "bounded_legacy_replace",
    # auth_router.py goi asyncpg.connect() truc tiep nhung KHONG tu doc DATABASE_URL - no de
    # cho auth_service._db_url() (file khac) normalize ho, nen kiem tra phai doi chieu CA HAI
    # file: call site (o day) VA noi thuc su implement (auth_service.py, id 1 cua tuple).
    "app/api/auth_router.py": ("external_service_helper", "app/services/auth_service.py"),
    "scripts/migrate.py": "bounded_legacy_replace",
    "scripts/assign_staff_roles.py": "bounded_legacy_replace",
    "scripts/kb_ingest.py": "bounded_legacy_replace",
    "scripts/ingest.py": "bounded_legacy_replace",
    "scripts/m0_foundation_validation.py": "bounded_legacy_replace",
    "scripts/m2_backfill.py": "bounded_legacy_replace",
    "app/services/pii/stage0p_pool.py": "parameter_only",
    "scripts/m2_backfill_prod_dryrun.py": "hardcoded_constant",
    "scripts/m2_existing_apply_rehearsal.py": "hardcoded_constant",
    "scripts/m3_existing_apply_rehearsal.py": "hardcoded_constant",
}


async def scenario_28_dsn_inventory_regression_machine_verifiable() -> None:
    print("== [28] F-RCR-R1-03: machine-verifiable static scan - MOI file trong repo goi "
          "asyncpg.connect()/create_pool() phai duoc phan loai ro rang trong manifest, va "
          "disposition khai bao phai khop pattern that trong source ==")
    scan_re = re.compile(r"asyncpg\.(?:connect|create_pool)\s*\(")
    exclude_name_suffixes = ("_test.py",)
    exclude_names = {"m4_dsn_utils.py"}
    found: dict[str, str] = {}
    for subdir in ("scripts", "app"):
        for path in (ROOT / subdir).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if path.name.endswith(exclude_name_suffixes) or path.name in exclude_names:
                continue
            text = path.read_text(encoding="utf-8")
            if scan_re.search(text):
                found[path.relative_to(ROOT).as_posix()] = text

    unclassified = sorted(set(found) - set(_DSN_INVENTORY_MANIFEST))
    check(not unclassified,
          f"KHONG co file nao goi asyncpg.connect/create_pool ma chua co trong manifest - "
          f"phat hien entry point MOI can duoc phan loai (thuc te: {unclassified})")

    stale_manifest_entries = sorted(set(_DSN_INVENTORY_MANIFEST) - set(found))
    check(not stale_manifest_entries,
          f"moi entry trong manifest van con ton tai va con goi asyncpg trong repo THAT (khong "
          f"co entry 'chet' hoac sai duong dan - thuc te thieu: {stale_manifest_entries})")

    for rel, text in sorted(found.items()):
        disposition = _DSN_INVENTORY_MANIFEST.get(rel)
        if isinstance(disposition, tuple) and disposition[0] == "external_service_helper":
            helper_rel = disposition[1]
            helper_module = helper_rel.rsplit("/", 1)[-1].removesuffix(".py")
            check(f"{helper_module}._db_url()" in text,
                  f"{rel}: goi dung {helper_module}._db_url() dung nhu disposition "
                  f"'external_service_helper' da khai bao")
            helper_text = (ROOT / helper_rel).read_text(encoding="utf-8")
            check('.replace("+asyncpg"' in helper_text or ".replace('+asyncpg'" in helper_text,
                  f"{rel}: file duoc tro toi ({helper_rel}) dung dung .replace(\"+asyncpg\"...) "
                  f"nhu disposition da khai bao")
            continue
        if disposition == "shared_helper":
            check("from m4_dsn_utils import" in text or "import m4_dsn_utils" in text,
                  f"{rel}: import dung m4_dsn_utils, khop disposition 'shared_helper' da khai bao")
        elif disposition == "bounded_legacy_replace":
            check('.replace("+asyncpg"' in text or ".replace('+asyncpg'" in text,
                  f"{rel}: dung dung .replace(\"+asyncpg\"...), khop disposition "
                  f"'bounded_legacy_replace' da khai bao")
        elif disposition == "parameter_only":
            check("DATABASE_URL" not in text,
                  f"{rel}: khong tu tham chieu DATABASE_URL, khop disposition 'parameter_only' "
                  f"da khai bao (chi nhan dsn qua tham so)")
        elif disposition == "hardcoded_constant":
            check('os.environ.get("DATABASE_URL")' not in text
                  and "os.environ['DATABASE_URL']" not in text
                  and 'os.environ["DATABASE_URL"]' not in text,
                  f"{rel}: khong doc DATABASE_URL tu env, khop disposition 'hardcoded_constant' "
                  f"da khai bao (dung hang so co dinh)")
        else:
            check(False, f"{rel}: disposition khong hop le/khong xac dinh trong manifest "
                  f"({disposition!r})")

    print(f"  (thong ke: {len(found)} file goi asyncpg.connect/create_pool, tat ca da duoc phan "
          f"loai)")


async def scenario_29_revoke_credential_concurrency_race_locking() -> None:
    print("== [29] F-RCR-R1-01: race THAT giua revoke-credential va deactivate actor dong thoi "
          "qua 2 ket noi Postgres - FOR UPDATE THAT SU chan, khong con khoang ho TOCTOU ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        actor_id = await _make_staff(admin, "provision-pin-test-revcred29-recorder")
        await _grant_permission(admin, staff_id=actor_id, permission="m4.stage0p.approve")
        target_id = await _make_staff(admin, "provision-pin-test-revcred29-target")
        await _provision_pin_secret_directly(admin, staff_id=target_id, pin_secret="race29-pin")
    finally:
        await admin.close()

    conn_a = await asyncpg.connect(DB_URL)
    conn_b = await asyncpg.connect(DB_URL)
    tx = conn_a.transaction()
    await tx.start()
    try:
        # CHINH XAC cau lenh dau tien ma revoke_credential() dung de khoa actor (khong hand-copy
        # sai lech).
        locked = await conn_a.fetchrow(
            "SELECT id, username, is_active FROM staff_users WHERE id = $1 FOR UPDATE",
            actor_id)
        check(locked is not None and locked["is_active"],
              "connection A lay duoc lock tren actor (actor van active luc do)")

        task_b = asyncio.create_task(conn_b.execute(
            "UPDATE staff_users SET is_active = false WHERE id = $1", actor_id))
        blocked = False
        try:
            await asyncio.wait_for(asyncio.shield(task_b), timeout=1.5)
        except asyncio.TimeoutError:
            blocked = True
        check(blocked, "deactivate actor tu connection B THAT SU bi Postgres CHAN boi FOR UPDATE "
              "cua connection A (row-level lock that, khong phai gia lap bang code)")

        # A tiep tuc dung buoc thu 2 cua revoke_credential(): kiem quyen, cung FOR UPDATE, cung
        # transaction - chung minh quyen van con hop le trong pham vi giao dich cua A.
        has_permission = await conn_a.fetchval(
            "SELECT EXISTS(SELECT 1 FROM m4_stage0p_staff_permissions "
            "WHERE staff_id = $1 AND permission = $2 FOR UPDATE)",
            actor_id, "m4.stage0p.approve")
        check(has_permission,
              "quyen van con hop le trong pham vi transaction cua A (B van dang bi chan, chua "
              "the can thiep)")

        await tx.commit()  # nha lock - A hoan tat "revoke thanh cong" truoc khi B duoc tiep tuc
        await asyncio.wait_for(task_b, timeout=5)
    finally:
        await conn_a.close()

    row = await conn_b.fetchrow("SELECT is_active FROM staff_users WHERE id = $1", actor_id)
    check(row is not None and row["is_active"] is False,
          "SAU KHI A nha lock, deactivate cua B hoan tat thanh cong (bi tri hoan dung thu tu, "
          "khong bi mat) - khong co interleaving nao xay ra giua 2 giao dich")
    await conn_b.close()

    # Xac nhan he qua thuc te: 1 lan goi revoke-credential MOI (SAU KHI actor da bi deactivate
    # do race o tren) gio bi tu choi dung - khong con cach nao "lot qua" duoc trang thai active cu.
    r_after = _run_revoke_credential(target_id, actor_id, "attempt-after-actor-deactivated")
    check(r_after.returncode != 0,
          "revoke-credential SAU KHI actor bi deactivate (boi race o tren) bi tu choi dung - "
          "khong co unauthorized delete/audit nao co the xay ra tu trang thai cu")


async def main() -> int:
    await scenario_1_no_staff_id_input_surface()
    await scenario_2_generate_token_local_only()
    await scenario_3_round_trip_real_pin_actor()
    await scenario_4_cross_principal_approval_mismatch_rejected()
    await scenario_5_bind_without_matching_approval_rejected()
    await scenario_6_revoked_approval_rejected()
    await scenario_7_expired_approval_rejected()
    await scenario_8_ttl_out_of_range_rejected()
    await scenario_9_token_reuse_rejected()
    await scenario_10_expired_token_rejected()
    await scenario_11_pin_mismatch_does_not_burn_token()
    await scenario_12_revoke_after_bind_invalidates_token()
    await scenario_13_approval_expiry_after_bind_invalidates_token()
    await scenario_14_ttl_capped_by_approval_window()
    await scenario_15_revoke_consume_race_locking()
    await scenario_16_dsn_scheme_normalize_unit()
    await scenario_17_unknown_scheme_failclosed_subprocess_no_secret_leak()
    await scenario_18_production_shaped_dsn_integration()
    await scenario_19_malformed_scheme_with_secret_and_control_chars_no_leak()
    await scenario_20_dsn_shared_module_identity_regression()
    await scenario_21_revoke_credential_success_and_pin_actor_rejects()
    await scenario_22_revoke_credential_idempotent_repeat()
    await scenario_23_revoke_credential_wrong_actor_target_failclosed()
    await scenario_24_revoke_credential_unauthorized_active_actor_failclosed()
    await scenario_25_revoke_credential_authorized_actor_and_inactive_target_succeed()
    await scenario_26_revoke_credential_reason_validation()
    await scenario_27_dsn_present_but_empty_failclosed()
    await scenario_28_dsn_inventory_regression_machine_verifiable()
    await scenario_29_revoke_credential_concurrency_race_locking()

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
