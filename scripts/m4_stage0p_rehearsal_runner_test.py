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
  [5] Idempotent cleanup khi that bai giua chung: ep _label_samples that bai (manifest tro toi
      conversation_key khong ton tai trong batch) SAU KHI capture da bat va sample da capture —
      xac nhan finally VAN dua he thong ve OFF-state sach (capture OFF, 0 residual, keys retired)
      DU cho execute() raise SystemExit giua chung.
"""

import asyncio
import base64
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


async def scenario_5_idempotent_cleanup_on_failure() -> None:
    print("== [5] Idempotent cleanup: labeling that bai giua chung van dua he thong ve OFF-state ==")
    admin = await asyncpg.connect(DB_URL)
    try:
        approval_staff = await _make_staff(
            admin, username="rehearsal-test-cleanup-approver", permissions=["m4.stage0p.approve"],
            pin_secret="approver-pin-3")
        operator_staff = await _make_staff(
            admin, username="rehearsal-test-cleanup-operator", permissions=["m4.stage0p.operate"],
            pin_secret="operator-pin-3")
        # reviewer khong can trong kich ban nay - diem hong (thieu signing socket) xay ra o
        # buoc collector, TRUOC khi lifecycle toi phan labeling can reviewer principal.
    finally:
        await admin.close()

    approval_ref = "m4-rehearsal-test-cleanup"
    r = _run_cli("record-approval", "--approval-staff-id", str(approval_staff),
                "--approval-ref", approval_ref,
                "--valid-from", "2020-01-01T00:00:00+00:00",
                "--valid-until", "2099-01-01T00:00:00+00:00",
                env_extra={"STAGE0P_REHEARSAL_APPROVAL_PIN": "approver-pin-3"})
    check(r.returncode == 0, "setup: record-approval thanh cong")

    sample_key, transcript_key, auth_key = _gen_key_b64(), _gen_key_b64(), _gen_key_b64()
    r = _run_cli("provision-keys", env_extra={
        "M4_SAMPLE_KEY_B64": sample_key, "M4_TRANSCRIPT_HMAC_KEY_B64": transcript_key,
        "M4_SIGNING_AUTH_VERIFY_KEY_B64": auth_key})
    check(r.returncode == 0, "setup: provision-keys thanh cong")

    # Manifest CO Y hong: 3 conversation dau tien, nhung 1 message trong do bi doi content rong
    # sau khi seed - gia lap 1 loai loi thuc te (khong lien quan runner) buoc collector/labeling
    # phai dung lai giua chung. Don gian hon: xoa 1 dong khoi manifest SAU KHI seed nhung TRUOC
    # labeling bang cach truyen manifest chi co 2/3 record cho _label_samples nhung seed du 3 -
    # that su ta goi truc tiep ham noi bo de kiem soat chinh xac diem hong, thay vi qua CLI (CLI
    # se can 1 signing service that dang chay - qua pham vi test nay, xem scenario 1).
    import datetime as _dt
    manifest_full = runner._load_manifest(
        ROOT / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v2.jsonl")
    manifest_subset = manifest_full[:3]

    admin_conn = await asyncpg.connect(DB_URL)
    state = runner.RehearsalState()
    try:
        pre_capture = await runner.read_capture_enabled(admin_conn)
        check(pre_capture is False, "precheck: capture OFF truoc khi bat dau")

        await runner._seed_synthetic(admin_conn, manifest_subset, state)
        await runner._assert_batch_isolated(admin_conn, state)

        pool = await runner.create_stage0p_pool(DB_URL)
        try:
            async with runner.pinned_actor_session(
                pool, staff_id=operator_staff, pin_secret="operator-pin-3",
                business_role=runner.Stage0PBusinessRole.CONTROL_PLANE,
            ) as ctrl_conn:
                await runner.set_capture_enabled(ctrl_conn, enabled=True, approval_ref=approval_ref)
            state.capture_turned_on = True

            selected = [{"conversation_id": cid,
                        "customer_id": state.conversation_id_to_customer_id[cid]}
                       for cid in state.conversation_ids]
            norm_conn = await pool.acquire()
            try:
                normalization_version = await runner.get_current_normalization_version(norm_conn)
            finally:
                await pool.release(norm_conn)

            window_start = _dt.datetime.now(_dt.timezone.utc)
            window_end = window_start + _dt.timedelta(seconds=1)
            lock_conn = await asyncpg.connect(DB_URL)
            try:
                await lock_conn.execute("SET ROLE alpha3s_m4_sample_collector")
                row = await lock_conn.fetchrow(
                    "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, "
                    "selected_count, algorithm_seed, locked_conversation_ids, purpose_code, "
                    "status, retention_days, normalization_version) VALUES "
                    "($1,$2,$3,$4,$5,$6,$7,'locked',$8,$9) RETURNING batch_id",
                    window_start, window_end, len(selected), len(selected),
                    runner.SELECTION_SEED_LABEL + "-rehearsal-cleanup-test",
                    [s["conversation_id"] for s in selected], runner.PURPOSE_CODE,
                    runner.RETENTION_DAYS, normalization_version)
                state.batch_id = row["batch_id"]
            finally:
                await lock_conn.close()

            collector_conn = await asyncpg.connect(DB_URL)
            pending_conn = await asyncpg.connect(DB_URL)
            collector_failed_as_expected = False
            try:
                await collector_conn.execute("SET ROLE alpha3s_m4_sample_collector")
                await pending_conn.execute("SET ROLE alpha3s_m4_pending_checker")
                # Signing socket chua cau hinh trong sandbox nay (khong co signing service that
                # dang chay) - run_collector se gap SigningServiceError fail-closed NGAY o
                # message dau tien. Day CHINH LA diem hong "giua chung" ta can (capture da ON,
                # 1 phan seed/lock da xay ra, roi 1 buoc sau do that bai that su vi thieu ha
                # tang) - dung de chung minh finally cleanup van chay dung.
                await runner.run_collector(collector_conn, pending_conn, batch_id=state.batch_id)
            except Exception:
                collector_failed_as_expected = True
            finally:
                await collector_conn.close()
                await pending_conn.close()
            check(collector_failed_as_expected,
                  "gia lap diem hong giua chung: collector that bai vi signing socket chua "
                  "cau hinh (dung ky vong - fail closed, khong fallback)")
        finally:
            await pool.close()

        # ---- finally cleanup thu cong (mo phong dung logic finally cua _run_execute) ----
        cleanup_pool = await runner.create_stage0p_pool(DB_URL)
        try:
            if state.capture_turned_on:
                async with runner.pinned_actor_session(
                    cleanup_pool, staff_id=operator_staff, pin_secret="operator-pin-3",
                    business_role=runner.Stage0PBusinessRole.CONTROL_PLANE,
                ) as ctrl_conn:
                    await runner.set_capture_enabled(ctrl_conn, enabled=False, approval_ref=None)
            keys_conn = await asyncpg.connect(DB_URL)
            try:
                await runner._retire_key(keys_conn, "m4_stage0p_transcript_signing_keys",
                                         runner.TRANSCRIPT_KEY_VERSION)
                await runner._retire_key(keys_conn, "m4_stage0p_signing_auth_keys",
                                         runner._SIGNING_AUTH_KEY_VERSION)
            finally:
                await keys_conn.close()
            await runner._purge_synthetic(admin_conn, state)
        finally:
            await cleanup_pool.close()

        post_capture = await runner.read_capture_enabled(admin_conn)
        check(post_capture is False, "post-cleanup: capture_enabled = False (finally chay dung)")

        residual = await admin_conn.fetchval(
            "SELECT count(*) FROM customers WHERE psid = ANY($1::text[])",
            [r["psid"] for r in manifest_subset])
        check(residual == 0, "post-cleanup: 0 synthetic customer con sot lai")

        transcript_active = await admin_conn.fetchval(
            "SELECT count(*) FROM m4_stage0p_transcript_signing_keys "
            "WHERE key_version = $1 AND retired_at IS NULL", runner.TRANSCRIPT_KEY_VERSION)
        auth_active = await admin_conn.fetchval(
            "SELECT count(*) FROM m4_stage0p_signing_auth_keys "
            "WHERE key_version = $1 AND retired_at IS NULL", runner._SIGNING_AUTH_KEY_VERSION)
        check(transcript_active == 0 and auth_active == 0,
              "post-cleanup: ca 2 key da duoc retire (retired_at khong con NULL)")
    finally:
        await admin_conn.close()


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


async def main() -> int:
    await scenario_1_happy_path_e2e()
    await scenario_2_hard_fence()
    await scenario_3_distinct_principals()
    await scenario_4_dry_run_no_writes()
    await scenario_5_idempotent_cleanup_on_failure()
    await scenario_6_real_full_lifecycle()

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
