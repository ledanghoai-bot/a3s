#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence cho `scripts/m4_stage0p_rehearsal_runner.py`, dap lai
`PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-REVIEW-1-VI.md` §5 (yeu cau "PR/head cua
reviewed runner + generator + immutable manifest" kem theo test).

Chay (can DATABASE_URL/REDIS_URL tro toi 1 sandbox RIENG, KHONG bao gio chay tren production —
script nay TU RESET schema public):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@<sandbox-db>:5432/alpha3s \
      -e REDIS_URL=redis://<sandbox-redis>:6379/0 \
      alpha3s-api-1 python scripts/m4_stage0p_rehearsal_runner_test.py

Kich ban:
  [1] Happy-path E2E qua chinh CLI runner (subprocess, dung cach 1 operator that se go lenh):
      record-approval -> provision-keys -> dry-run (bao PASS) -> run (execute) -> xac nhan
      capture OFF + 0 synthetic residual + keys retired + evaluation_completed_at co gia tri.
  [2] F-M4-RH-R1-01 hard fence: seed 1 conversation "non-synthetic" (psid KHONG mang marker)
      trong CUNG cua so thoi gian voi rehearsal — xac nhan _seed_synthetic()/lock_batch() KHONG
      BAO GIO dua conversation nay vao locked_conversation_ids (kiem tra CAU TRUC, khong chi
      runtime assertion) va _assert_batch_isolated() se abort neu bi ep chen thu cong.
  [3] F-M4-RH-R1-07: _assert_distinct_principals() tu choi khi 2 staff_id trung nhau.
  [4] Dry-run khong ghi gi: dem row truoc/sau `run --dry-run`, phai bang nhau tuyet doi.
  [5a/5b] F-M4-RH-R2-01/05: fault-injection BLACK-BOX tren CHINH subprocess `run` that (khong
      phai ban sao cleanup viet tay) — [5a] sabotage pin_secret operator ngay khi capture vua
      bat, buoc capture-off THAT SU that bai; [5b] chen 1 row `orders` tham chieu customer
      synthetic ngay sau khi seed, buoc purge THAT SU that bai vi FK conflict. Ca 2 xac nhan:
      exit code khac 0, log CLEANUP_FAILED, va trang thai DB doc lap THAT SU nguy hiem (capture
      con ON / residual con lai) — khong bao gio bao cao thanh cong trong tinh huong nay.
  [11] F-EX-B2-01/02/04 (Amendment 07 Execution Blocker 1): integration THAT voi DATABASE_URL
      dang production (`postgresql+asyncpg://...`) di qua CLI runner that (`retire-keys`,
      idempotent/an toan) — chung minh runner gio dung chung `m4_dsn_utils.normalized_db_url`
      voi PIN tool va thuc su ket noi duoc, khong con bi ClientConfigurationError nhu blocker.
  [12] F-EX-B2-01/02/04: DATABASE_URL malformed (phan "scheme" tinh co chua fake secret VA ky tu
      dieu khien/xuong dong) qua CLI runner that — tu choi sach, khong leak, khong traceback,
      khong log injection, khong DB call/write.
"""

import asyncio
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "m4_rehearsal_runner", ROOT / "scripts" / "m4_stage0p_rehearsal_runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

DB_URL = os.environ.get("DATABASE_URL") or "postgresql://alpha3s:alpha3s@db:5432/alpha3s"
REDIS_URL = os.environ.get("REDIS_URL") or "redis://redis:6379/0"

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


async def _provision_pin_secret(admin, *, staff_id: int, pin_secret: str) -> None:
    await admin.execute(
        "INSERT INTO m4_stage0p_actor_credentials (staff_id, pin_secret_hash, provisioned_by) "
        "VALUES ($1, crypt($2, gen_salt('bf')), $1) "
        "ON CONFLICT (staff_id) DO UPDATE SET pin_secret_hash=crypt($2, gen_salt('bf')), "
        "failed_attempts=0, locked_until=NULL", staff_id, pin_secret)


async def _make_staff(admin, *, username: str, permissions: list[str], pin_secret: str) -> int:
    row = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ($1, 'x', 'x', true) RETURNING id", username)
    staff_id = row["id"]
    for perm in permissions:
        await admin.execute(
            "INSERT INTO m4_stage0p_staff_permissions (staff_id, permission, granted_by) "
            "VALUES ($1, $2, $1) ON CONFLICT DO NOTHING", staff_id, perm)
    await _provision_pin_secret(admin, staff_id=staff_id, pin_secret=pin_secret)
    return staff_id


def _run_cli(*args, env_extra: dict | None = None, expect_rc: int | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": DB_URL, "REDIS_URL": REDIS_URL, **(env_extra or {})}
    result = subprocess.run(
        [sys.executable, "scripts/m4_stage0p_rehearsal_runner.py", *args],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
    if expect_rc is not None and result.returncode != expect_rc:
        print("STDOUT:", result.stdout[-4000:])
        print("STDERR:", result.stderr[-4000:])
    return result


def _gen_key_b64() -> str:
    return base64.b64encode(os.urandom(32)).decode()


async def scenario_1_happy_path_e2e() -> None:
    print("== [1] Happy-path E2E qua CLI runner that (record-approval -> provision-keys -> "
          "dry-run -> execute -> verify OFF-state) ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        await _reset_schema(admin)
    finally:
        await admin.close()
    _run_migrations()

    admin = await asyncpg.connect(DB_URL)
    try:
        approval_staff = await _make_staff(
            admin, username="rehearsal-test-approver", permissions=["m4.stage0p.approve"],
            pin_secret="approver-pin")
        operator_staff = await _make_staff(
            admin, username="rehearsal-test-operator", permissions=["m4.stage0p.operate"],
            pin_secret="operator-pin")
        reviewer_staff = await _make_staff(
            admin, username="rehearsal-test-reviewer",
            permissions=["m4.stage0p.review", "m4.stage0p.evaluate"], pin_secret="reviewer-pin")
        check(len({approval_staff, operator_staff, reviewer_staff}) == 3,
              "setup: 3 staff_id phan biet duoc tao")
    finally:
        await admin.close()

    approval_ref = "m4-rehearsal-test-e2e"
    r = _run_cli("record-approval", "--approval-staff-id", str(approval_staff),
                "--approval-ref", approval_ref,
                "--valid-from", "2020-01-01T00:00:00+00:00",
                "--valid-until", "2099-01-01T00:00:00+00:00",
                env_extra={"STAGE0P_REHEARSAL_APPROVAL_PIN": "approver-pin"}, expect_rc=0)
    check(r.returncode == 0, "record-approval CLI thanh cong")

    sample_key = _gen_key_b64()
    transcript_key = _gen_key_b64()
    auth_key = _gen_key_b64()
    r = _run_cli("provision-keys", env_extra={
        "M4_SAMPLE_KEY_B64": sample_key, "M4_TRANSCRIPT_HMAC_KEY_B64": transcript_key,
        "M4_SIGNING_AUTH_VERIFY_KEY_B64": auth_key}, expect_rc=0)
    check(r.returncode == 0, "provision-keys CLI thanh cong")

    manifest_path = ROOT / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v2.jsonl"
    r = _run_cli("run", "--dry-run", "--manifest", str(manifest_path),
                "--approval-ref", approval_ref,
                "--operator-staff-id", str(operator_staff),
                "--reviewer-staff-id", str(reviewer_staff),
                env_extra={"STAGE0P_REHEARSAL_OPERATOR_PIN": "operator-pin",
                          "STAGE0P_REHEARSAL_REVIEWER_PIN": "reviewer-pin"}, expect_rc=0)
    check(r.returncode == 0, "dry-run CLI bao PASS voi approval/manifest hop le")
    check('"dry_run_ready"' in r.stdout, "dry-run log dung 'dry_run_ready'")

    # E2E day du can chay signing service that (process rieng) - qua pham vi 1 test script
    # don gian. Scenario nay dung lai o dry-run (chung minh CLI/preflight hoat dong dung) - E2E
    # execute-that duoc kiem trong scenario 5 (khong can signing service qua monkeypatch
    # request_signature, xem duoi).
    print("  (E2E execute-that voi signing service that: xem huong dan van hanh trong package; "
          "scenario nay dung lai preflight - da chung minh dry-run + record-approval + "
          "provision-keys hoat dong dung qua CLI that)")

    # Retire keys ngay - de scenario [5] duoc phep provision lai (precheck tu choi ghi de key
    # dang active, dung thiet ke F-M4-RH-R1-02 - khong phai bug can workaround, chi can don dep
    # dung trinh tu giua cac kich ban test doc lap).
    r = _run_cli("retire-keys", expect_rc=0)
    check(r.returncode == 0, "cleanup: retire-keys sau scenario 1 thanh cong")


async def scenario_2_hard_fence() -> None:
    print("== [2] F-M4-RH-R1-01: non-synthetic conversation KHONG the vao locked batch ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        # 1 customer/conversation "that" (KHONG mang marker) trong CUNG cua so thoi gian.
        real_cust = await admin.fetchrow(
            "INSERT INTO customers (psid, name) VALUES ($1, $2) RETURNING id",
            "1234567890123_real_facebook_psid", "Khach That")
        real_conv = await admin.fetchrow(
            "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id",
            real_cust["id"])
        await admin.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES ($1, 'customer', 'tin nhan khach that', now())", real_conv["id"])

        manifest = runner._load_manifest(
            ROOT / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v2.jsonl")
        state = runner.RehearsalState()
        await runner._seed_synthetic(admin, manifest[:5], state)

        check(real_conv["id"] not in state.conversation_ids,
              "conversation THAT khong nam trong danh sach synthetic tracked (cau truc, "
              "khong phai chi runtime check) - lock_batch() se KHONG BAO GIO nhan no lam "
              "'selected' vi selected chi xay tu state.conversation_ids")

        # Dau vet: ep 1 phien ban "bi loi" cua state (them lan conversation that vao, gia lap
        # bug tuong lai) - xac nhan _assert_batch_isolated CHAN LAI truoc khi bat capture.
        bad_state = runner.RehearsalState()
        bad_state.customer_ids = list(state.customer_ids) + [real_cust["id"]]
        bad_state.conversation_ids = list(state.conversation_ids) + [real_conv["id"]]
        raised = False
        try:
            await runner._assert_batch_isolated(admin, bad_state)
        except SystemExit:
            raised = True
        check(raised, "_assert_batch_isolated() ABORT (SystemExit) khi bi ep chen 1 "
                      "conversation khong mang psid synthetic - defense-in-depth hoat dong")

        # cleanup (messages truoc, roi conversations, roi customers - ton trong FK)
        await admin.execute("DELETE FROM messages WHERE conversation_id = ANY($1::bigint[])",
                            state.conversation_ids)
        await admin.execute("DELETE FROM conversations WHERE id = ANY($1::bigint[])",
                            state.conversation_ids)
        await admin.execute("DELETE FROM customers WHERE id = ANY($1::bigint[])",
                            state.customer_ids)
        await admin.execute("DELETE FROM messages WHERE conversation_id = $1", real_conv["id"])
        await admin.execute("DELETE FROM conversations WHERE id = $1", real_conv["id"])
        await admin.execute("DELETE FROM customers WHERE id = $1", real_cust["id"])
    finally:
        await admin.close()


async def scenario_3_distinct_principals() -> None:
    print("== [3] F-M4-RH-R1-07: staff_id trung nhau bi tu choi ==")
    raised = False
    try:
        runner._assert_distinct_principals(101, 101)
    except SystemExit:
        raised = True
    check(raised, "operator_staff_id == reviewer_staff_id -> SystemExit")

    ok = True
    try:
        runner._assert_distinct_principals(101, 102, 103)
    except SystemExit:
        ok = False
    check(ok, "3 staff_id phan biet -> khong raise")


async def scenario_4_dry_run_no_writes() -> None:
    print("== [4] Dry-run khong ghi gi vao DB ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        # Khong tao approval staff - kich ban nay CO Y KHONG record approval nao (dry-run phai
        # bao FAIL vi approval_ref khong ton tai, khong phai vi thieu quyen record).
        operator_staff = await _make_staff(
            admin, username="rehearsal-test-dryrun-operator", permissions=["m4.stage0p.operate"],
            pin_secret="operator-pin-2")
        reviewer_staff = await _make_staff(
            admin, username="rehearsal-test-dryrun-reviewer",
            permissions=["m4.stage0p.review", "m4.stage0p.evaluate"], pin_secret="reviewer-pin-2")

        before = {}
        for table in ("customers", "conversations", "messages", "m4_selection_batches",
                      "m4_shadow_review_samples", "m4_stage0p_capture_progress"):
            before[table] = await admin.fetchval(f"SELECT count(*) FROM {table}")
    finally:
        await admin.close()

    approval_ref = "m4-rehearsal-test-dryrun-noapproval"
    manifest_path = ROOT / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v2.jsonl"
    r = _run_cli("run", "--dry-run", "--manifest", str(manifest_path),
                "--approval-ref", approval_ref,
                "--operator-staff-id", str(operator_staff),
                "--reviewer-staff-id", str(reviewer_staff),
                env_extra={"STAGE0P_REHEARSAL_OPERATOR_PIN": "operator-pin-2",
                          "STAGE0P_REHEARSAL_REVIEWER_PIN": "reviewer-pin-2"})
    check(r.returncode == 1, "dry-run bao FAIL dung (approval_ref chua duoc record) - rc=1")

    admin = await asyncpg.connect(DB_URL)
    try:
        after = {}
        for table in before:
            after[table] = await admin.fetchval(f"SELECT count(*) FROM {table}")
        check(before == after, f"dry-run KHONG thay doi row count bat ky bang nao "
                               f"(before={before}, after={after})")
    finally:
        await admin.close()


def _write_small_manifest(n: int, suffix: str) -> Path:
    """Manifest con (N conversation dau) rieng cho 1 kich ban fault-injection — psid van dung
    tien to that (PSID_PREFIX) nhung noi dung file la 1 ban sao rieng, khong dung chung voi cac
    kich ban khac chay song song/tuan tu."""
    full = runner._load_manifest(ROOT / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v2.jsonl")
    subset = full[:n]
    path = ROOT / "datasets" / "pii" / f"_rehearsal_test_manifest_{suffix}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for r in subset:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


async def _poll_until(predicate_coro_fn, *, timeout: float, interval: float = 0.3) -> bool:
    """Poll `await predicate_coro_fn()` cho toi khi True hoac het `timeout` giay. Tra True/False."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if await predicate_coro_fn():
            return True
        await asyncio.sleep(interval)
    return False


async def scenario_5a_blackbox_capture_off_failure() -> None:
    """F-M4-RH-R2-05: fault-injection tren CHINH tien trinh `run` that (subprocess that, khong
    phai ban sao cleanup viet tay) — sabotage credential cua operator NGAY khi capture vua bat,
    buoc buoc cleanup capture-OFF trong _run_execute() THAT SU that bai. Xac nhan runner phat
    hien dung (F-M4-RH-R2-01): exit khac 0, log CLEANUP_FAILED, va capture_enabled VAN true (vi
    that su khong tat duoc) — khong bao gio bao cao thanh cong trong tinh huong nguy hiem nay."""
    print("== [5a] Black-box fault-injection: capture-off THAT SU that bai giua _run_execute() ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approval_staff = await _make_staff(
            admin, username="rehearsal-test-5a-approver", permissions=["m4.stage0p.approve"],
            pin_secret="approver-pin-5a")
        operator_staff = await _make_staff(
            admin, username="rehearsal-test-5a-operator", permissions=["m4.stage0p.operate"],
            pin_secret="operator-pin-5a")
        reviewer_staff = await _make_staff(
            admin, username="rehearsal-test-5a-reviewer",
            permissions=["m4.stage0p.review", "m4.stage0p.evaluate"], pin_secret="reviewer-pin-5a")
    finally:
        await admin.close()

    approval_ref = "m4-rehearsal-test-5a-capture-off-fail"
    r = _run_cli("record-approval", "--approval-staff-id", str(approval_staff),
                "--approval-ref", approval_ref,
                "--valid-from", "2020-01-01T00:00:00+00:00",
                "--valid-until", "2099-01-01T00:00:00+00:00",
                env_extra={"STAGE0P_REHEARSAL_APPROVAL_PIN": "approver-pin-5a"})
    check(r.returncode == 0, "setup: record-approval thanh cong")

    manifest_path = _write_small_manifest(3, "5a")
    env = {**os.environ, "DATABASE_URL": DB_URL, "REDIS_URL": REDIS_URL,
          "STAGE0P_REHEARSAL_OPERATOR_PIN": "operator-pin-5a",
          "STAGE0P_REHEARSAL_REVIEWER_PIN": "reviewer-pin-5a"}
    proc = subprocess.Popen(
        [sys.executable, "scripts/m4_stage0p_rehearsal_runner.py", "run",
         "--manifest", str(manifest_path), "--approval-ref", approval_ref,
         "--operator-staff-id", str(operator_staff), "--reviewer-staff-id", str(reviewer_staff)],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    poll_conn = await asyncpg.connect(DB_URL)
    try:
        async def _capture_is_on():
            return bool(await poll_conn.fetchval(
                "SELECT capture_enabled FROM m4_stage0p_control WHERE id = 1"))
        observed_on = await _poll_until(_capture_is_on, timeout=20.0)
        check(observed_on, "quan sat duoc capture_enabled chuyen true trong khi subprocess dang chay")

        # Sabotage credential operator NGAY luc nay - lan pin_actor KE TIEP (trong cleanup) se
        # that bai vi pin_secret khong con khop hash trong DB.
        await poll_conn.execute(
            "UPDATE m4_stage0p_actor_credentials SET pin_secret_hash = crypt('sabotaged-wrong-pin', "
            "gen_salt('bf')), failed_attempts = 0, locked_until = NULL WHERE staff_id = $1",
            operator_staff)
    finally:
        await poll_conn.close()

    try:
        stdout, stderr = proc.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        check(False, "subprocess KHONG thoat trong 120s sau sabotage - treo bat thuong")
        stdout = stdout or ""

    check(proc.returncode != 0,
          f"exit code khac 0 khi cleanup capture-off that bai THAT SU (thuc te {proc.returncode})")
    check('"CLEANUP_FAILED"' in stdout,
          "log co dung marker CLEANUP_FAILED (F-M4-RH-R2-01) thay vi bao cao thanh cong")
    check('"capture_enabled VAN la true sau cleanup"' in stdout,
          "CLEANUP_FAILED neu ro dung nguyen nhan: capture_enabled van true")

    verify_conn = await asyncpg.connect(DB_URL)
    try:
        capture_still_on = await verify_conn.fetchval(
            "SELECT capture_enabled FROM m4_stage0p_control WHERE id = 1")
        check(bool(capture_still_on) is True,
              "xac nhan DOC LAP: capture_enabled THAT SU van con true (dung nhu CLEANUP_FAILED tuyen bo, "
              "khong phai bao gia)")

        # Don dep sandbox cho cac kich ban sau: phuc hoi pin_secret dung, tu tat capture, purge
        # thu cong (test tu chiu trach nhiem don dep sau khi CO Y gay loi de kiem thu).
        await _provision_pin_secret(verify_conn, staff_id=operator_staff, pin_secret="operator-pin-5a")
        pool = await runner.create_stage0p_pool(DB_URL)
        try:
            async with runner.pinned_actor_session(
                pool, staff_id=operator_staff, pin_secret="operator-pin-5a",
                business_role=runner.Stage0PBusinessRole.CONTROL_PLANE,
            ) as ctrl_conn:
                await runner.set_capture_enabled(ctrl_conn, enabled=False, approval_ref=None)
        finally:
            await pool.close()
        await verify_conn.execute("DELETE FROM messages WHERE conversation_id IN "
                                  "(SELECT id FROM conversations WHERE customer_id IN "
                                  "(SELECT id FROM customers WHERE psid LIKE $1))", f"{runner.PSID_PREFIX}%")
        await verify_conn.execute("DELETE FROM conversations WHERE customer_id IN "
                                  "(SELECT id FROM customers WHERE psid LIKE $1)", f"{runner.PSID_PREFIX}%")
        await verify_conn.execute("DELETE FROM customers WHERE psid LIKE $1", f"{runner.PSID_PREFIX}%")
        await runner._retire_key(verify_conn, "m4_stage0p_transcript_signing_keys",
                                 runner.TRANSCRIPT_KEY_VERSION)
        await runner._retire_key(verify_conn, "m4_stage0p_signing_auth_keys",
                                 runner._SIGNING_AUTH_KEY_VERSION)
    finally:
        await verify_conn.close()
    manifest_path.unlink(missing_ok=True)


async def scenario_5b_blackbox_purge_failure() -> None:
    """F-M4-RH-R2-05: fault-injection thu 2 tren CHINH `run` that — chen 1 row `orders` tham
    chieu toi 1 customer synthetic NGAY sau khi seed xong (FK ma purge KHONG lam sach), buoc
    DELETE FROM customers trong `_purge_synthetic` that bai that su vi ForeignKeyViolationError.
    Khong co signing service that trong sandbox nay nen collector se tu fail-closed (thieu
    socket) — dung de lifecycle chinh ket thuc nhanh, nhung diem can kiem la CLEANUP co phat
    hien dung purge that bai hay khong, khong phai lifecycle chinh."""
    print("== [5b] Black-box fault-injection: purge THAT SU that bai (FK conflict tu orders) ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approval_staff = await _make_staff(
            admin, username="rehearsal-test-5b-approver", permissions=["m4.stage0p.approve"],
            pin_secret="approver-pin-5b")
        operator_staff = await _make_staff(
            admin, username="rehearsal-test-5b-operator", permissions=["m4.stage0p.operate"],
            pin_secret="operator-pin-5b")
        reviewer_staff = await _make_staff(
            admin, username="rehearsal-test-5b-reviewer",
            permissions=["m4.stage0p.review", "m4.stage0p.evaluate"], pin_secret="reviewer-pin-5b")
    finally:
        await admin.close()

    approval_ref = "m4-rehearsal-test-5b-purge-fail"
    r = _run_cli("record-approval", "--approval-staff-id", str(approval_staff),
                "--approval-ref", approval_ref,
                "--valid-from", "2020-01-01T00:00:00+00:00",
                "--valid-until", "2099-01-01T00:00:00+00:00",
                env_extra={"STAGE0P_REHEARSAL_APPROVAL_PIN": "approver-pin-5b"})
    check(r.returncode == 0, "setup: record-approval thanh cong")

    manifest_path = _write_small_manifest(3, "5b")
    env = {**os.environ, "DATABASE_URL": DB_URL, "REDIS_URL": REDIS_URL,
          "STAGE0P_REHEARSAL_OPERATOR_PIN": "operator-pin-5b",
          "STAGE0P_REHEARSAL_REVIEWER_PIN": "reviewer-pin-5b"}
    proc = subprocess.Popen(
        [sys.executable, "scripts/m4_stage0p_rehearsal_runner.py", "run",
         "--manifest", str(manifest_path), "--approval-ref", approval_ref,
         "--operator-staff-id", str(operator_staff), "--reviewer-staff-id", str(reviewer_staff)],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    poll_conn = await asyncpg.connect(DB_URL)
    injected_customer_id = None
    try:
        async def _synthetic_seeded():
            row = await poll_conn.fetchval(
                "SELECT id FROM customers WHERE psid LIKE $1 ORDER BY id LIMIT 1",
                f"{runner.PSID_PREFIX}%")
            return row is not None
        observed = await _poll_until(_synthetic_seeded, timeout=20.0)
        check(observed, "quan sat duoc customer synthetic xuat hien trong khi subprocess dang chay")

        injected_customer_id = await poll_conn.fetchval(
            "SELECT id FROM customers WHERE psid LIKE $1 ORDER BY id LIMIT 1",
            f"{runner.PSID_PREFIX}%")
        # Chen 1 order THAT tham chieu toi customer synthetic nay - purge KHONG biet ve bang
        # orders (chi xoa customers/conversations/messages/samples/capture_progress theo ID
        # tracked), nen DELETE FROM customers se vi pham FK va that bai that su.
        await poll_conn.execute(
            "INSERT INTO orders (customer_id, created_at) VALUES ($1, now())", injected_customer_id)
    finally:
        await poll_conn.close()

    try:
        stdout, stderr = proc.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        check(False, "subprocess KHONG thoat trong 120s - treo bat thuong")
        stdout = stdout or ""

    check(proc.returncode != 0,
          f"exit code khac 0 khi purge that bai THAT SU do FK conflict (thuc te {proc.returncode})")
    check('"CLEANUP_FAILED"' in stdout, "log co dung marker CLEANUP_FAILED")
    check("chua bi purge" in stdout,
          "CLEANUP_FAILED neu ro nguyen nhan lien quan residual row chua purge duoc")

    verify_conn = await asyncpg.connect(DB_URL)
    try:
        residual = await verify_conn.fetchval(
            "SELECT count(*) FROM customers WHERE psid LIKE $1", f"{runner.PSID_PREFIX}%")
        check(residual > 0,
              f"xac nhan DOC LAP: van con {residual} customer synthetic sot lai that su (purge that "
              "bai dung nhu CLEANUP_FAILED tuyen bo)")
        capture_off = not bool(await verify_conn.fetchval(
            "SELECT capture_enabled FROM m4_stage0p_control WHERE id = 1"))
        check(capture_off, "capture-off van thanh cong doc lap voi purge (2 buoc cleanup that bai "
                           "rieng biet, khong lien luy nhau)")

        # Don dep that su: xoa order da chen, roi purge tay phan con lai.
        if injected_customer_id is not None:
            await verify_conn.execute("DELETE FROM orders WHERE customer_id = $1", injected_customer_id)
        await verify_conn.execute("DELETE FROM messages WHERE conversation_id IN "
                                  "(SELECT id FROM conversations WHERE customer_id IN "
                                  "(SELECT id FROM customers WHERE psid LIKE $1))", f"{runner.PSID_PREFIX}%")
        await verify_conn.execute("DELETE FROM conversations WHERE customer_id IN "
                                  "(SELECT id FROM customers WHERE psid LIKE $1)", f"{runner.PSID_PREFIX}%")
        await verify_conn.execute("DELETE FROM customers WHERE psid LIKE $1", f"{runner.PSID_PREFIX}%")
        await runner._retire_key(verify_conn, "m4_stage0p_transcript_signing_keys",
                                 runner.TRANSCRIPT_KEY_VERSION)
        await runner._retire_key(verify_conn, "m4_stage0p_signing_auth_keys",
                                 runner._SIGNING_AUTH_KEY_VERSION)
    finally:
        await verify_conn.close()
    manifest_path.unlink(missing_ok=True)


async def scenario_6_real_full_lifecycle() -> None:
    """F-M4-RH-R1-05: chung minh runner chay duoc TOAN BO lifecycle that (qua write_predictions/
    complete_evaluation, khong chi capture/seal) voi 1 signing service THAT dang chay - dung
    manifest v2 day du (220 gate-eligible), phai vuot qua ca nguong 10%/200 hien co (khong dung
    bat ky bypass nao)."""
    print("== [6] Full lifecycle THAT (signing service that + toan bo 220 conversation manifest) ==")
    from scripts._stage0p_signing_service_helper import (  # noqa: PLC0415
        start_signing_service,
        stop_signing_service,
    )

    admin = await asyncpg.connect(DB_URL)
    try:
        approval_staff = await _make_staff(
            admin, username="rehearsal-test-full-approver", permissions=["m4.stage0p.approve"],
            pin_secret="approver-pin-6")
        operator_staff = await _make_staff(
            admin, username="rehearsal-test-full-operator", permissions=["m4.stage0p.operate"],
            pin_secret="operator-pin-6")
        reviewer_staff = await _make_staff(
            admin, username="rehearsal-test-full-reviewer",
            permissions=["m4.stage0p.review", "m4.stage0p.evaluate"], pin_secret="reviewer-pin-6")
    finally:
        await admin.close()

    approval_ref = "m4-rehearsal-test-full-lifecycle"
    r = _run_cli("record-approval", "--approval-staff-id", str(approval_staff),
                "--approval-ref", approval_ref,
                "--valid-from", "2020-01-01T00:00:00+00:00",
                "--valid-until", "2099-01-01T00:00:00+00:00",
                env_extra={"STAGE0P_REHEARSAL_APPROVAL_PIN": "approver-pin-6"})
    check(r.returncode == 0, "setup: record-approval thanh cong")

    socket_path = "/tmp/m4-rehearsal-test-signer.sock"
    proc, sample_key, hmac_key, auth_key = await start_signing_service(
        socket_path=socket_path, allowed_uid=os.getuid())
    try:
        r = _run_cli("provision-keys", env_extra={
            "M4_SAMPLE_KEY_B64": base64.b64encode(sample_key).decode(),
            "M4_TRANSCRIPT_HMAC_KEY_B64": base64.b64encode(hmac_key).decode(),
            "M4_SIGNING_AUTH_VERIFY_KEY_B64": base64.b64encode(auth_key).decode()})
        check(r.returncode == 0, "setup: provision-keys (khop key that cua signing service) thanh cong")

        manifest_path = ROOT / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v2.jsonl"
        r = _run_cli("run", "--manifest", str(manifest_path),
                    "--approval-ref", approval_ref,
                    "--operator-staff-id", str(operator_staff),
                    "--reviewer-staff-id", str(reviewer_staff),
                    env_extra={"STAGE0P_REHEARSAL_OPERATOR_PIN": "operator-pin-6",
                              "STAGE0P_REHEARSAL_REVIEWER_PIN": "reviewer-pin-6",
                              "M4_STAGE0P_SIGNING_SOCKET": socket_path,
                              # prediction writer (chay TRONG runner process, khong phai signing
                              # service) tu giai ma sample de chay detector - can CUNG sample_key
                              # ma signing service da dung de ma hoa (AES-GCM doi xung).
                              "M4_SAMPLE_KEY_B64": base64.b64encode(sample_key).decode()},
                    expect_rc=0)
        check(r.returncode == 0, "run (execute, KHONG dry-run) EXIT=0 - toan bo lifecycle qua "
                                 "collector->label->seal->predict->evaluate thanh cong")
        check('"rehearsal_execute_succeeded"' in r.stdout,
              "log xac nhan rehearsal_execute_succeeded")
        check('"evaluation_completed"' in r.stdout,
              "log xac nhan evaluation_completed - full lifecycle THAT chay toi cung, khong "
              "dung o seal")
    finally:
        await stop_signing_service(proc, socket_path)

    admin = await asyncpg.connect(DB_URL)
    try:
        capture_now = await runner.read_capture_enabled(admin)
        check(capture_now is False, "post-execute: capture_enabled = False")
        residual = await admin.fetchval(
            "SELECT count(*) FROM customers WHERE psid LIKE $1", f"{runner.PSID_PREFIX}%")
        check(residual == 0, f"post-execute: 0 synthetic customer con sot lai (thuc te {residual})")
        eval_row = await admin.fetchrow(
            "SELECT status, evaluation_completed_at, evaluation_report_hash "
            "FROM m4_selection_batches ORDER BY locked_at DESC LIMIT 1")
        check(eval_row is not None and eval_row["evaluation_completed_at"] is not None,
              "batch cuoi cung dat status evaluation_completed that su (khong phai gia dinh)")
    finally:
        await admin.close()


async def scenario_7_dry_run_four_approval_states() -> None:
    """F-M4-RH-R2-03, evidence CA yeu cau ro o Submission #3 muc 4: dry-run PHAI phan biet dung
    4 tinh huong approval_ref — hop le, CHUA bat dau, DA het han, DA thu hoi. Ca 4 dung CHINH
    CLI `run --dry-run` that (khong goi ham noi bo)."""
    print("== [7] Dry-run evidence cho 4 trang thai approval (F-M4-RH-R2-03) ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        operator_staff = await _make_staff(
            admin, username="rehearsal-test-7-operator", permissions=["m4.stage0p.operate"],
            pin_secret="operator-pin-7")
        reviewer_staff = await _make_staff(
            admin, username="rehearsal-test-7-reviewer",
            permissions=["m4.stage0p.review", "m4.stage0p.evaluate"], pin_secret="reviewer-pin-7")
    finally:
        await admin.close()
    manifest_path = ROOT / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v2.jsonl"

    def _dry_run_for(approval_ref: str) -> subprocess.CompletedProcess:
        return _run_cli("run", "--dry-run", "--manifest", str(manifest_path),
                        "--approval-ref", approval_ref,
                        "--operator-staff-id", str(operator_staff),
                        "--reviewer-staff-id", str(reviewer_staff),
                        env_extra={"STAGE0P_REHEARSAL_OPERATOR_PIN": "operator-pin-7",
                                  "STAGE0P_REHEARSAL_REVIEWER_PIN": "reviewer-pin-7"})

    cases = [
        ("m4-rehearsal-test-7-valid", "2020-01-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00",
         False, 0, "hop le (dang trong cua so)"),
        ("m4-rehearsal-test-7-not-started", "2099-01-01T00:00:00+00:00", "2100-01-01T00:00:00+00:00",
         False, 1, "CHUA bat dau (valid_from o tuong lai)"),
        ("m4-rehearsal-test-7-expired", "2020-01-01T00:00:00+00:00", "2021-01-01T00:00:00+00:00",
         False, 1, "DA het han (valid_until o qua khu)"),
        ("m4-rehearsal-test-7-revoked", "2020-01-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00",
         True, 1, "DA bi thu hoi"),
    ]
    for approval_ref, valid_from, valid_until, revoke, expect_rc, label in cases:
        admin2 = await asyncpg.connect(DB_URL)
        try:
            approver = await _make_staff(
                admin2, username=f"rehearsal-test-7-approver-{approval_ref[-12:]}",
                permissions=["m4.stage0p.approve"], pin_secret="approver-pin-7x")
        finally:
            await admin2.close()
        r = _run_cli("record-approval", "--approval-staff-id", str(approver),
                    "--approval-ref", approval_ref, "--valid-from", valid_from,
                    "--valid-until", valid_until,
                    env_extra={"STAGE0P_REHEARSAL_APPROVAL_PIN": "approver-pin-7x"})
        check(r.returncode == 0, f"[{label}] setup record-approval thanh cong")
        if revoke:
            r = _run_cli("record-approval", "--revoke", "--approval-staff-id", str(approver),
                        "--approval-ref", approval_ref, "--reason", "test thu hoi",
                        env_extra={"STAGE0P_REHEARSAL_APPROVAL_PIN": "approver-pin-7x"})
            check(r.returncode == 0, f"[{label}] setup revoke thanh cong")

        r = _dry_run_for(approval_ref)
        check(r.returncode == expect_rc,
              f"[{label}] dry-run --approval-ref {approval_ref} tra rc={r.returncode} "
              f"(ky vong {expect_rc})")


async def scenario_8_capture_off_ignores_stale_flag() -> None:
    """F-M4-RH-R3-02: goi TRUC TIEP `runner._do_cleanup()` (ham THAT, khong copy tay) voi 1
    `RehearsalState` co `capture_turned_on=False` GIA (gia lap crash giua luc DB da ghi True va
    luc gan co nho), nhung DB THAT SU dang capture_enabled=true — xac nhan cleanup van tat dung
    vi no doc TRANG THAI THAT tu DB, khong con dua vao co nho."""
    print("== [8] F-M4-RH-R3-02: capture-off doc DB that, khong phu thuoc co nho stale ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approval_staff = await _make_staff(
            admin, username="rehearsal-test-8-approver", permissions=["m4.stage0p.approve"],
            pin_secret="approver-pin-8")
        operator_staff = await _make_staff(
            admin, username="rehearsal-test-8-operator", permissions=["m4.stage0p.operate"],
            pin_secret="operator-pin-8")
    finally:
        await admin.close()

    approval_ref = "m4-rehearsal-test-8-stale-flag"
    r = _run_cli("record-approval", "--approval-staff-id", str(approval_staff),
                "--approval-ref", approval_ref,
                "--valid-from", "2020-01-01T00:00:00+00:00",
                "--valid-until", "2099-01-01T00:00:00+00:00",
                env_extra={"STAGE0P_REHEARSAL_APPROVAL_PIN": "approver-pin-8"})
    check(r.returncode == 0, "setup: record-approval thanh cong")

    admin_conn = await asyncpg.connect(DB_URL)
    pool = await runner.create_stage0p_pool(DB_URL)
    try:
        # Bat capture qua DUNG con duong that (khong di tat) - roi CO Y KHONG gan
        # state.capture_turned_on, mo phong crash giua 2 buoc do.
        async with runner.pinned_actor_session(
            pool, staff_id=operator_staff, pin_secret="operator-pin-8",
            business_role=runner.Stage0PBusinessRole.CONTROL_PLANE,
        ) as ctrl_conn:
            await runner.set_capture_enabled(ctrl_conn, enabled=True, approval_ref=approval_ref)
        capture_on_confirmed = await runner.read_capture_enabled(admin_conn)
        check(capture_on_confirmed is True, "setup: capture THAT SU da ON truoc khi goi cleanup")

        stale_state = runner.RehearsalState()
        stale_state.capture_turned_on = False  # CO Y sai lech voi DB that

        cleanup_step_ok = await runner._do_cleanup(
            admin_conn, pool, operator_staff_id=operator_staff, operator_pin="operator-pin-8",
            state=stale_state)
        check(cleanup_step_ok.get("capture_off") is True, "_do_cleanup() bao capture_off=True")

        capture_after = await runner.read_capture_enabled(admin_conn)
        check(capture_after is False,
              "xac nhan DOC LAP: capture_enabled THAT SU da tat du state.capture_turned_on=False "
              "(cleanup doc DB, khong con phu thuoc co nho stale)")
    finally:
        await admin_conn.close()
        await pool.close()


async def scenario_9_redis_postcheck_is_mandatory() -> None:
    """F-M4-RH-R3-03: goi TRUC TIEP `runner._do_cleanup_and_verify()` voi REDIS_URL bi pha (khong
    ket noi duoc) — xac nhan postcondition_ok=False DU moi thu khac (DB) deu sach, vi Redis
    postcheck gio la hau dieu kien bat buoc, khong con chi la 1 dong log tham khao."""
    print("== [9] F-M4-RH-R3-03: Redis postcheck la hau dieu kien BAT BUOC ==")
    admin_conn = await asyncpg.connect(DB_URL)
    pool = await runner.create_stage0p_pool(DB_URL)
    try:
        empty_state = runner.RehearsalState()  # khong tracked gi - moi thu khac trivially sach
        original_redis_url = os.environ.get("REDIS_URL")
        os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"  # port 1 - chac chan khong ket noi duoc
        try:
            postcondition_ok, problems, cleanup_step_ok = await runner._do_cleanup_and_verify(
                admin_conn, pool, operator_staff_id=0, operator_pin="unused-no-capture-to-turn-off",
                state=empty_state)
        finally:
            if original_redis_url is not None:
                os.environ["REDIS_URL"] = original_redis_url
            else:
                os.environ.pop("REDIS_URL", None)

        check(cleanup_step_ok.get("redis_postcheck") is False,
              "_do_cleanup() tu bao redis_postcheck=False khi REDIS_URL bi pha")
        check(postcondition_ok is False,
              "postcondition_ok=False DU cac truy van DB khac (state rong) deu se PASS - Redis "
              "loi mot minh cung du lam CLEANUP_FAILED")
        check(any("Redis" in p for p in problems),
              f"problems neu ro nguyen nhan Redis (thuc te {problems})")
    finally:
        await admin_conn.close()
        await pool.close()


async def scenario_10_verifier_itself_fails_closed() -> None:
    """F-M4-RH-R3-04: goi `runner._do_cleanup_and_verify()` voi 1 connection DA DONG cho tham so
    verifier dung (mo phong "mat ket noi DB giua luc dang xac minh") — xac nhan KHONG co
    traceback thoat thang ra ngoai ham, ma tra ve postcondition_ok=False voi ly do ro rang."""
    print("== [10] F-M4-RH-R3-04: postcondition verifier tu loi -> fail-closed, khong traceback ==")
    admin_conn = await asyncpg.connect(DB_URL)
    pool = await runner.create_stage0p_pool(DB_URL)
    try:
        empty_state = runner.RehearsalState()
        closed_conn = await asyncpg.connect(DB_URL)
        await closed_conn.close()

        raised = False
        postcondition_ok, problems, cleanup_step_ok = (None, None, None)
        try:
            postcondition_ok, problems, cleanup_step_ok = await runner._do_cleanup_and_verify(
                closed_conn, pool, operator_staff_id=0, operator_pin="unused-no-capture-to-turn-off",
                state=empty_state)
        except Exception:  # noqa: BLE001 — chinh dieu KHONG duoc xay ra, day la assertion
            raised = True

        check(not raised,
              "_do_cleanup_and_verify() KHONG de traceback thoat thang ra ngoai du verifier tu loi")
        check(postcondition_ok is False,
              f"postcondition_ok=False khi verifier tu no khong xac minh duoc (thuc te {postcondition_ok})")
        check(problems is not None and any("KHONG THE XAC MINH" in p for p in problems),
              f"problems neu ro 'khong the xac minh' thay vi 1 loi mo ho (thuc te {problems})")
    finally:
        await admin_conn.close()
        await pool.close()


async def scenario_11_dsn_production_shaped_integration() -> None:
    print("== [11] F-EX-B2-01/02/04: integration THAT voi DATABASE_URL dang production "
          "(postgresql+asyncpg://) di qua CLI runner that (retire-keys, idempotent/an toan) ==")
    assert DB_URL.startswith("postgresql://"), "gia dinh sandbox DB_URL dang postgresql://"
    production_shaped_dsn = "postgresql+asyncpg://" + DB_URL[len("postgresql://"):]

    r = _run_cli("retire-keys", env_extra={"DATABASE_URL": production_shaped_dsn})
    check(r.returncode == 0,
          f"retire-keys THANH CONG qua DATABASE_URL dang production 'postgresql+asyncpg://...' "
          f"(thuc te exit={r.returncode}, stderr={r.stderr!r})")
    check("postgresql+asyncpg" not in (r.stdout + r.stderr),
          "output khong echo lai chuoi DSN goc")


async def scenario_12_dsn_malformed_scheme_failclosed() -> None:
    print("== [12] F-EX-B2-01/02/04: DATABASE_URL malformed (fake secret + ky tu dieu khien "
          "trong phan scheme) bi tu choi SACH, khong leak, khong DB call, qua CLI runner that ==")
    marker = "RUNNER_LEAKED_MARKER_778899"
    malformed_scheme = f"oops{marker}\n\r\tstill-not-a-scheme"
    malformed_dsn = f"{malformed_scheme}://testuser:{marker}@db:5432/alpha3s"

    r = _run_cli("retire-keys", env_extra={"DATABASE_URL": malformed_dsn})
    combined = r.stdout + r.stderr
    check(r.returncode != 0, "retire-keys voi DATABASE_URL malformed exit != 0")
    check(marker not in combined, "marker gia (ke ca phan trong 'scheme' malformed) KHONG xuat "
          "hien trong stdout/stderr")
    check(malformed_dsn not in combined, "toan bo DSN malformed goc KHONG xuat hien trong output")
    check("Traceback" not in r.stderr, "tu choi SACH bang thong bao hang so, khong traceback")
    check(r.stderr.strip().count("\n") <= 1,
          "thong bao loi la 1 dong hang so - khong phan chieu ky tu xuong dong tu input malformed "
          "(chong log injection)")


async def scenario_13_dsn_shared_module_identity_regression() -> None:
    print("== [13] F-EX-B2-02: regression - runner._db_url la CHINH m4_dsn_utils.normalized_db_url "
          "(khong phai ban sao rieng co the lech voi PIN tool trong tuong lai) ==")
    import m4_dsn_utils
    check(runner._db_url is m4_dsn_utils.normalized_db_url,
          "runner._db_url va m4_dsn_utils.normalized_db_url la CUNG 1 ham object (identity "
          "check) - dam bao khong con logic normalize DSN nao rieng, lech trong runner")


async def main() -> int:
    await scenario_1_happy_path_e2e()
    await scenario_2_hard_fence()
    await scenario_3_distinct_principals()
    await scenario_4_dry_run_no_writes()
    await scenario_5a_blackbox_capture_off_failure()
    await scenario_5b_blackbox_purge_failure()
    await scenario_6_real_full_lifecycle()
    await scenario_7_dry_run_four_approval_states()
    await scenario_8_capture_off_ignores_stale_flag()
    await scenario_9_redis_postcheck_is_mandatory()
    await scenario_10_verifier_itself_fails_closed()
    await scenario_11_dsn_production_shaped_integration()
    await scenario_12_dsn_malformed_scheme_failclosed()
    await scenario_13_dsn_shared_module_identity_regression()

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
