#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: negative-permission matrix (CA acceptance criteria #2, #3).

Chay:
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      alpha3s-m4-test python scripts/m4_stage0p_permissions_test.py

REV 3 (CA Technical Review #2, T2-01..T2-06) — cap nhat theo 8 ham SECURITY DEFINER REV3 (thay
cho 5 ham REV2):
  - `m4_stage0p_fetch_next_message` (REV2) TACH thanh `m4_stage0p_peek_next_candidate` (khong
    lock) + `m4_stage0p_fetch_message_content` (fenced, nhan dung 1 message) (T2-01).
  - `m4_stage0p_record_sample` (MOI) — INSERT + captured_count atomic (T2-06); collector KHONG
    con INSERT truc tiep tren sample.
  - `m4_stage0p_fetch_sealed_message` (MOI) — duong doc DUY NHAT cho prediction_writer, kiem
    sealed TRUOC khi tra content (T2-02); prediction_writer KHONG con SELECT truc tiep cot noi
    dung.
  - `m4_stage0p_seal_labels` DB TU TINH hash (khong nhan tham so hash), `m4_stage0p_
    write_predictions` validate JSONB day du + bind hash + bat bien 1-lan-ghi (T2-03/T2-04),
    `m4_stage0p_complete_evaluation` nhan metrics + bind result_hash (T2-04).
  - Bang moi `m4_stage0p_capture_approvals` + role `alpha3s_m4_approval_recorder` (T2-05) — ON
    doi hoi approval record that; OFF khong doi hoi.

Duyet DAY DU 9 role (8 role M4 + alpha3s_app + alpha3s_vendor_path + PUBLIC) x cac thao tac tren
4 bang + 8 ham nghiep vu.
"""

import asyncio
import datetime
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402

DB_URL = (os.environ.get("DATABASE_URL")
          or "postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s").replace("+asyncpg", "")

_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


async def _try(conn, sql: str, *args) -> bool:
    """True neu cau lenh THANH CONG (khong loi quyen). Rollback ngay sau (savepoint)."""
    try:
        async with conn.transaction():
            await conn.execute(sql, *args)
            raise _RollbackSentinel
    except _RollbackSentinel:
        return True
    except asyncpg.InsufficientPrivilegeError:
        return False


class _RollbackSentinel(Exception):
    pass


ROLES = [
    "alpha3s_m4_sample_collector", "alpha3s_m4_sample_reviewer_api",
    "alpha3s_m4_sample_evaluator", "alpha3s_m4_prediction_writer",
    "alpha3s_m4_sample_purge", "alpha3s_m4_control_plane",
    "alpha3s_m4_pending_checker", "alpha3s_m4_approval_recorder",
    "alpha3s_app", "alpha3s_vendor_path", "PUBLIC",
]

FUNCTIONS = [
    ("m4_stage0p_peek_next_candidate", "uuid,bigint,bigint", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_fetch_message_content", "uuid,bigint,bigint", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_record_sample", "uuid,uuid,text,text,bytea,int,boolean,int,text", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_set_capture", "boolean,bigint,text", "alpha3s_m4_control_plane"),
    ("m4_stage0p_seal_labels", "uuid,bigint", "alpha3s_m4_sample_reviewer_api"),
    ("m4_stage0p_fetch_sealed_message", "uuid,uuid", "alpha3s_m4_prediction_writer"),
    ("m4_stage0p_write_predictions", "uuid,text,jsonb,jsonb,text,text", "alpha3s_m4_prediction_writer"),
    ("m4_stage0p_complete_evaluation", "uuid,bigint,text,jsonb", "alpha3s_m4_sample_evaluator"),
]


async def _set_capture(conn, *, enabled, staff_id, approval_ref):
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        return await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2,$3)",
                                   enabled, staff_id, approval_ref)
    finally:
        await conn.execute("RESET ROLE")


async def main() -> int:
    admin = await asyncpg.connect(DB_URL)

    staff = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ('m4-perm-test-staff', 'x', 'x', true) RETURNING id"
    )

    # Seed 1 row toi thieu de test UPDATE/DELETE tren du lieu that su ton tai
    batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, "
        "selected_count, algorithm_seed, locked_conversation_ids, purpose_code) "
        "VALUES (now()-interval '1 day', now(), 0, 0, 'perm-test', ARRAY[]::bigint[], "
        "'P12_PII_DETECTOR_EVAL') RETURNING batch_id"
    )
    sample_id = str(uuid.uuid4())
    await admin.execute(
        "INSERT INTO m4_shadow_review_samples (sample_id, customer_ref, conversation_ref, "
        "encrypted_message, canonical_text_len, expires_at, purpose_code, normalization_version, "
        "selection_batch) VALUES ($1,'999','999','\\x00'::bytea,1,now()+interval '1 day',"
        "'P12_PII_DETECTOR_EVAL','nfc-v1',$2)",
        sample_id, batch["batch_id"],
    )
    # 1 approval record hop le (T2-05) — de test cac kich ban ON/EXECUTE khac can control ON tam thoi
    now = datetime.datetime.now(datetime.timezone.utc)
    approval_conn = await asyncpg.connect(DB_URL)
    await approval_conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    await approval_conn.execute(
        "INSERT INTO m4_stage0p_capture_approvals (approval_ref, purpose_code, requested_enabled, "
        "status, valid_from, valid_until, recorded_by) VALUES ($1,'P12_PII_DETECTOR_EVAL',true,"
        "'approved',$2,$3,$4)",
        "perm-test-approval-ok", now - datetime.timedelta(hours=1), now + datetime.timedelta(hours=1),
        staff["id"],
    )
    await approval_conn.execute("RESET ROLE")

    print("== Ma tran negative-permission: 4 bang chinh ==")
    matrix = [
        # (role, table, action, sql, expected_allowed)
        ("alpha3s_m4_sample_collector", "samples", "SELECT",
         "SELECT * FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_sample_collector", "samples", "INSERT (direct, phai DENY — T2-06)",
         f"INSERT INTO m4_shadow_review_samples (sample_id,customer_ref,conversation_ref,"
         f"encrypted_message,canonical_text_len,expires_at,purpose_code,normalization_version,"
         f"selection_batch) VALUES ('{uuid.uuid4()}','1','1','\\x00'::bytea,1,"
         f"now()+interval '1 day','P12_PII_DETECTOR_EVAL','nfc-v1','{batch['batch_id']}')", False),
        ("alpha3s_m4_sample_collector", "samples", "UPDATE",
         "UPDATE m4_shadow_review_samples SET label_status='labeled'", False),
        ("alpha3s_m4_sample_collector", "control", "UPDATE",
         "UPDATE m4_stage0p_control SET capture_enabled=true", False),
        ("alpha3s_m4_sample_collector", "control", "SELECT direct",
         "SELECT capture_enabled FROM m4_stage0p_control", False),
        ("alpha3s_m4_sample_collector", "approvals", "INSERT",
         "INSERT INTO m4_stage0p_capture_approvals (approval_ref,purpose_code,requested_enabled,"
         "status,valid_from,valid_until) VALUES ('x','P12_PII_DETECTOR_EVAL',true,'approved',now(),now()+interval '1 day')", False),
        ("alpha3s_m4_sample_collector", "customers", "SELECT psid",
         "SELECT psid FROM customers", False),
        ("alpha3s_m4_sample_collector", "messages", "SELECT direct",
         "SELECT * FROM messages", False),

        ("alpha3s_m4_sample_reviewer_api", "samples", "SELECT predicted_slots",
         "SELECT predicted_slots FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_sample_reviewer_api", "samples", "SELECT encrypted_message",
         "SELECT encrypted_message FROM m4_shadow_review_samples", True),
        ("alpha3s_m4_sample_reviewer_api", "samples", "SELECT labeled_slots",
         "SELECT labeled_slots FROM m4_shadow_review_samples", True),
        ("alpha3s_m4_sample_reviewer_api", "samples", "UPDATE labeled_slots",
         "UPDATE m4_shadow_review_samples SET labeled_slots='[]'::jsonb", True),
        ("alpha3s_m4_sample_reviewer_api", "samples", "DELETE",
         "DELETE FROM m4_shadow_review_samples", False),

        ("alpha3s_m4_sample_evaluator", "samples", "SELECT encrypted_message",
         "SELECT encrypted_message FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_sample_evaluator", "samples", "SELECT customer_ref",
         "SELECT customer_ref FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_sample_evaluator", "samples", "SELECT labeled_slots",
         "SELECT labeled_slots FROM m4_shadow_review_samples", True),
        ("alpha3s_m4_sample_evaluator", "samples", "UPDATE",
         "UPDATE m4_shadow_review_samples SET label_status='labeled'", False),

        # REV3 T2-02: prediction_writer KHONG con SELECT truc tiep tren cot noi dung
        ("alpha3s_m4_prediction_writer", "samples", "UPDATE predicted_slots (direct, phai DENY)",
         "UPDATE m4_shadow_review_samples SET predicted_slots='[]'::jsonb", False),
        ("alpha3s_m4_prediction_writer", "samples", "SELECT encrypted_message (direct, phai DENY — T2-02)",
         "SELECT encrypted_message FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_prediction_writer", "samples", "SELECT customer_ref (direct, phai DENY — T2-02)",
         "SELECT customer_ref FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_prediction_writer", "samples", "UPDATE labeled_slots",
         "UPDATE m4_shadow_review_samples SET labeled_slots='[]'::jsonb", False),
        ("alpha3s_m4_prediction_writer", "samples", "DELETE",
         "DELETE FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_prediction_writer", "batches", "SELECT labels_sealed_hash",
         "SELECT labels_sealed_hash FROM m4_selection_batches", True),

        ("alpha3s_m4_sample_purge", "samples", "DELETE",
         "DELETE FROM m4_shadow_review_samples WHERE expires_at < now()-interval '1000 days'", True),
        ("alpha3s_m4_sample_purge", "samples", "SELECT encrypted_message",
         "SELECT encrypted_message FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_sample_purge", "samples", "UPDATE",
         "UPDATE m4_shadow_review_samples SET label_status='labeled'", False),

        # REV3 T2-05: control_plane KHONG duoc dung/ghi bang approvals truc tiep
        ("alpha3s_m4_control_plane", "control", "UPDATE capture_enabled (direct, phai DENY)",
         "UPDATE m4_stage0p_control SET capture_enabled=true", False),
        ("alpha3s_m4_control_plane", "control", "SELECT capture_enabled",
         "SELECT capture_enabled FROM m4_stage0p_control", True),
        ("alpha3s_m4_control_plane", "samples", "SELECT",
         "SELECT * FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_control_plane", "approvals", "INSERT (phai DENY — chong tu duyet)",
         "INSERT INTO m4_stage0p_capture_approvals (approval_ref,purpose_code,requested_enabled,"
         "status,valid_from,valid_until) VALUES ('y','P12_PII_DETECTOR_EVAL',true,'approved',now(),now()+interval '1 day')", False),
        ("alpha3s_m4_control_plane", "approvals", "SELECT (phai DENY)",
         "SELECT * FROM m4_stage0p_capture_approvals", False),

        ("alpha3s_m4_pending_checker", "customers", "SELECT psid",
         "SELECT psid FROM customers LIMIT 1", True),
        ("alpha3s_m4_pending_checker", "samples", "SELECT",
         "SELECT * FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_pending_checker", "customers", "UPDATE",
         "UPDATE customers SET name='x'", False),

        ("alpha3s_m4_approval_recorder", "approvals", "INSERT",
         "INSERT INTO m4_stage0p_capture_approvals (approval_ref,purpose_code,requested_enabled,"
         "status,valid_from,valid_until) VALUES ('perm-test-approval-matrix','P12_PII_DETECTOR_EVAL',"
         "true,'approved',now(),now()+interval '1 day')", True),
        ("alpha3s_m4_approval_recorder", "control", "UPDATE (phai DENY)",
         "UPDATE m4_stage0p_control SET capture_enabled=true", False),
        ("alpha3s_m4_approval_recorder", "samples", "SELECT (phai DENY)",
         "SELECT * FROM m4_shadow_review_samples", False),

        ("alpha3s_app", "samples", "SELECT encrypted_message",
         "SELECT encrypted_message FROM m4_shadow_review_samples", False),
        ("alpha3s_app", "samples", "INSERT",
         f"INSERT INTO m4_shadow_review_samples (sample_id,customer_ref,conversation_ref,"
         f"encrypted_message,canonical_text_len,expires_at,purpose_code,normalization_version,"
         f"selection_batch) VALUES ('{uuid.uuid4()}','1','1','\\x00'::bytea,1,"
         f"now()+interval '1 day','P12_PII_DETECTOR_EVAL','nfc-v1','{batch['batch_id']}')", False),
        ("alpha3s_app", "samples", "SELECT customer_ref (DSR)",
         "SELECT customer_ref FROM m4_shadow_review_samples", True),
        ("alpha3s_app", "samples", "DELETE (DSR)",
         "DELETE FROM m4_shadow_review_samples WHERE customer_ref='__none__'", True),
        ("alpha3s_app", "control", "SELECT",
         "SELECT * FROM m4_stage0p_control", False),
        ("alpha3s_app", "approvals", "SELECT",
         "SELECT * FROM m4_stage0p_capture_approvals", False),

        ("alpha3s_vendor_path", "samples", "SELECT",
         "SELECT * FROM m4_shadow_review_samples", False),
        ("alpha3s_vendor_path", "control", "SELECT",
         "SELECT * FROM m4_stage0p_control", False),
        ("alpha3s_vendor_path", "batches", "SELECT",
         "SELECT * FROM m4_selection_batches", False),
        ("alpha3s_vendor_path", "approvals", "SELECT",
         "SELECT * FROM m4_stage0p_capture_approvals", False),

        ("public", "samples", "SELECT", "SELECT * FROM m4_shadow_review_samples", False),
        ("public", "control", "SELECT", "SELECT * FROM m4_stage0p_control", False),
        ("public", "batches", "SELECT", "SELECT * FROM m4_selection_batches", False),
        ("public", "approvals", "SELECT", "SELECT * FROM m4_stage0p_capture_approvals", False),
    ]

    for role, table, action, sql, expected in matrix:
        if role == "public":
            table_name = {"samples": "m4_shadow_review_samples", "control": "m4_stage0p_control",
                         "batches": "m4_selection_batches", "approvals": "m4_stage0p_capture_approvals"}[table]
            allowed = await admin.fetchval(
                "SELECT has_table_privilege('public', $1, 'SELECT')", table_name)
        else:
            conn = await asyncpg.connect(DB_URL)
            try:
                await conn.execute(f"SET ROLE {role}")
                allowed = await _try(conn, sql)
            finally:
                await conn.execute("RESET ROLE")
                await conn.close()
        verb = "ALLOW" if expected else "DENY"
        check(allowed == expected, f"{role} / {table} {action} -> {verb} (thuc te: "
              f"{'allowed' if allowed else 'denied'})")

    print("== Ma tran EXECUTE tren 8 ham SECURITY DEFINER (REV3) ==")
    for fname, fsig, owner_role in FUNCTIONS:
        for role in ROLES:
            expected = (role == owner_role)
            if role.lower() == "public":
                allowed = await admin.fetchval(
                    "SELECT has_function_privilege('public', $1, 'EXECUTE')", f"{fname}({fsig})")
            else:
                allowed = await admin.fetchval(
                    "SELECT has_function_privilege($1, $2, 'EXECUTE')", role, f"{fname}({fsig})")
            verb = "ALLOW" if expected else "DENY"
            check(allowed == expected,
                  f"{role} / EXECUTE {fname} -> {verb} (thuc te: {'allowed' if allowed else 'denied'})")

    print("== SECURITY DEFINER hardening (8 ham nghiep vu + trigger REV3) ==")
    for fname, fsig, _owner_role in FUNCTIONS:
        row = await admin.fetchrow(
            "SELECT prosecdef, proowner::regrole::text AS owner, "
            "(SELECT bool_or(c LIKE 'search_path=%') FROM unnest(coalesce(proconfig,'{}')) c) "
            "AS has_search_path_lock "
            "FROM pg_proc WHERE proname=$1", fname
        )
        check(row["prosecdef"] is True, f"{fname}: prosecdef = true (SECURITY DEFINER)")
        check(row["owner"] == "alpha3s_m4_definer",
              f"{fname}: owner = alpha3s_m4_definer (khong phai migration-owner)")
        check(row["has_search_path_lock"] is True, f"{fname}: search_path bi khoa trong CREATE FUNCTION")
    trig_row = await admin.fetchrow(
        "SELECT prosecdef, proowner::regrole::text AS owner FROM pg_proc "
        "WHERE proname='m4_stage0p_block_label_after_seal'")
    check(trig_row["prosecdef"] is True and trig_row["owner"] == "alpha3s_m4_definer",
          "m4_stage0p_block_label_after_seal: SECURITY DEFINER, owner dung (T1-03 bug tu phat hien)")
    owner_super = await admin.fetchval(
        "SELECT rolsuper OR rolcreaterole OR rolcreatedb FROM pg_roles WHERE rolname='alpha3s_m4_definer'")
    check(owner_super is False, "alpha3s_m4_definer KHONG superuser/createrole/createdb")

    print("== T2-05: set_capture(ON) tu choi approval khong ton tai/het han/thu hoi ==")
    conn = await asyncpg.connect(DB_URL)
    try:
        await _set_capture(conn, enabled=True, staff_id=staff["id"], approval_ref="khong-ton-tai")
        check(False, "approval khong ton tai -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong hop le" in str(e), "approval khong ton tai -> RAISE dung")

    expired_conn = await asyncpg.connect(DB_URL)
    await expired_conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    await expired_conn.execute(
        "INSERT INTO m4_stage0p_capture_approvals (approval_ref,purpose_code,requested_enabled,"
        "status,valid_from,valid_until,recorded_by) VALUES ($1,'P12_PII_DETECTOR_EVAL',true,"
        "'approved',$2,$3,$4)",
        "perm-test-approval-expired", now - datetime.timedelta(days=2), now - datetime.timedelta(days=1),
        staff["id"])
    await expired_conn.execute(
        "INSERT INTO m4_stage0p_capture_approvals (approval_ref,purpose_code,requested_enabled,"
        "status,valid_from,valid_until,recorded_by) VALUES ($1,'P12_PII_DETECTOR_EVAL',true,"
        "'revoked',$2,$3,$4)",
        "perm-test-approval-revoked", now - datetime.timedelta(hours=1), now + datetime.timedelta(hours=1),
        staff["id"])
    await expired_conn.execute("RESET ROLE")
    await expired_conn.close()
    try:
        await _set_capture(conn, enabled=True, staff_id=staff["id"], approval_ref="perm-test-approval-expired")
        check(False, "approval het han -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong hop le" in str(e), "approval het han -> RAISE dung")
    try:
        await _set_capture(conn, enabled=True, staff_id=staff["id"], approval_ref="perm-test-approval-revoked")
        check(False, "approval bi thu hoi -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong hop le" in str(e), "approval bi thu hoi -> RAISE dung")
    await conn.close()

    print("== T2-05: OFF khong doi hoi approval (chi can actor hop le) ==")
    conn = await asyncpg.connect(DB_URL)
    off_row = await _set_capture(conn, enabled=False, staff_id=staff["id"], approval_ref="khong-lien-quan-gi-ca")
    check(off_row["after_enabled"] is False, "OFF thanh cong du approval_ref khong tham chieu record nao")
    await conn.close()

    print("== BAT control that su bang approval hop le (chuan bi kich ban can control ON) ==")
    ctrl_conn = await asyncpg.connect(DB_URL)
    on_row = await _set_capture(ctrl_conn, enabled=True, staff_id=staff["id"], approval_ref="perm-test-approval-ok")
    check(on_row["after_enabled"] is True, "set_capture(ON) voi approval hop le -> thanh cong")
    await ctrl_conn.close()

    print("== Ham fetch_message_content tu choi batch sai trang thai/window/purpose ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        await conn.fetchval("SELECT * FROM m4_stage0p_fetch_message_content($1,1,1)", str(uuid.uuid4()))
        check(False, "batch_id khong ton tai -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong ton tai" in str(e), "batch_id khong ton tai -> RAISE dung")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    closed_batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, "
        "selected_count, algorithm_seed, locked_conversation_ids, purpose_code, status) "
        "VALUES (now()-interval '1 day', now(), 0, 0, 'perm-test-2', ARRAY[]::bigint[], "
        "'P12_PII_DETECTOR_EVAL', 'closed') RETURNING batch_id"
    )
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        await conn.fetchval("SELECT * FROM m4_stage0p_fetch_message_content($1,1,1)", closed_batch["batch_id"])
        check(False, "batch status='closed' -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("closed" in str(e), "batch status='closed' -> RAISE dung")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T2-01: peek_next_candidate KHONG can control ON (khong lock/khong PII) ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    off_conn = await asyncpg.connect(DB_URL)
    await _set_capture(off_conn, enabled=False, staff_id=staff["id"], approval_ref="perm-test-peek-off")
    await off_conn.close()
    try:
        await conn.fetchrow(
            "SELECT * FROM m4_stage0p_peek_next_candidate($1,-1,-1)", closed_batch["batch_id"])
        check(False, "peek tren batch closed van phai RAISE (validate batch, khong phai control)")
    except asyncpg.PostgresError as e:
        check("closed" in str(e), "peek tu choi dung ly do (batch closed, KHONG phai control)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== control OFF -> fetch_message_content tra 'control_off', KHONG raise, KHONG doc content (T1-01/T2-01) ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        off_result = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_fetch_message_content($1,1,1)", closed_batch["batch_id"])
        check(off_result["status"] == "control_off", "control OFF -> status='control_off'")
        check(off_result["content"] is None, "control OFF -> content=NULL (khong doc plaintext)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== Audit fail-closed + T2-06: fetch_message_content/record_sample voi du lieu that ==")
    ctrl_conn = await asyncpg.connect(DB_URL)
    await _set_capture(ctrl_conn, enabled=True, staff_id=staff["id"], approval_ref="perm-test-approval-ok")
    await ctrl_conn.close()
    cust = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('perm-audit-test','x') RETURNING id")
    conv = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", cust["id"])
    msg = await admin.fetchrow(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer','tin nhan that') RETURNING id",
        conv["id"])
    audit_batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, "
        "selected_count, algorithm_seed, locked_conversation_ids, purpose_code) "
        "VALUES (now()-interval '1 day', now(), 1, 1, 'perm-test-audit', ARRAY[$1]::bigint[], "
        "'P12_PII_DETECTOR_EVAL') RETURNING batch_id", conv["id"]
    )
    revoke_conn = await asyncpg.connect(DB_URL)
    await revoke_conn.execute("REVOKE INSERT ON audit_log FROM alpha3s_m4_definer")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    audit_blocked_denies_data = False
    try:
        await conn.fetchval("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                            audit_batch["batch_id"], conv["id"], msg["id"])
    except asyncpg.PostgresError:
        audit_blocked_denies_data = True
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()
    check(audit_blocked_denies_data, "audit INSERT bi chan -> fetch_message_content KHONG tra du lieu (fail closed)")
    count_after_blocked_fetch = await admin.fetchval(
        "SELECT captured_count FROM m4_selection_batches WHERE batch_id=$1", audit_batch["batch_id"])
    check(count_after_blocked_fetch == 0, "T2-06: fetch (du bi chan audit) KHONG lam captured_count tang")
    await revoke_conn.execute("GRANT INSERT ON audit_log TO alpha3s_m4_definer")
    await revoke_conn.close()

    # Bay gio fetch that (audit khong con bi chan) + record_sample — xac nhan captured_count CHI
    # tang khi record_sample duoc goi, khong phai luc fetch (T2-06).
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    fetched = await conn.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                                  audit_batch["batch_id"], conv["id"], msg["id"])
    check(fetched["status"] == "ok", "fetch_message_content thanh cong tren du lieu that")
    count_after_fetch_before_record = await admin.fetchval(
        "SELECT captured_count FROM m4_selection_batches WHERE batch_id=$1", audit_batch["batch_id"])
    check(count_after_fetch_before_record == 0,
          "T2-06: fetch content thanh cong nhung CHUA record_sample -> captured_count VAN la 0")
    rec = await conn.fetchrow(
        "SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7,$8,$9)",
        audit_batch["batch_id"], str(uuid.uuid4()), str(cust["id"]), str(conv["id"]),
        b"\x00" * 30, 1, False, 45, "nfc-v1")
    check(rec["captured_count"] == 1, "T2-06: record_sample -> captured_count tang DUNG 1 (chi khi sample THAT SU luu)")
    await conn.execute("RESET ROLE")
    await conn.close()

    off_conn2 = await asyncpg.connect(DB_URL)
    await _set_capture(off_conn2, enabled=False, staff_id=staff["id"], approval_ref="perm-test-audit-off")
    await off_conn2.close()

    print("== T1-03: seal_labels tu choi neu con row unlabeled ==")
    seal_batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, "
        "selected_count, algorithm_seed, locked_conversation_ids, purpose_code) "
        "VALUES (now()-interval '1 day', now(), 1, 1, 'perm-test-seal', ARRAY[]::bigint[], "
        "'P12_PII_DETECTOR_EVAL') RETURNING batch_id"
    )
    seal_sample = str(uuid.uuid4())
    await admin.execute(
        "INSERT INTO m4_shadow_review_samples (sample_id, customer_ref, conversation_ref, "
        "encrypted_message, canonical_text_len, expires_at, purpose_code, normalization_version, "
        "selection_batch) VALUES ($1,'998','998','\\x00'::bytea,1,now()+interval '1 day',"
        "'P12_PII_DETECTOR_EVAL','nfc-v1',$2)",
        seal_sample, seal_batch["batch_id"],
    )
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_reviewer_api")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_seal_labels($1,$2)", seal_batch["batch_id"], staff["id"])
        check(False, "seal voi row unlabeled -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("unlabeled" in str(e), "seal voi row unlabeled -> RAISE dung")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T2-02: fetch_sealed_message tu choi tren batch CHUA sealed — 0 raw fetch ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_fetch_sealed_message($1,NULL)", seal_batch["batch_id"])
        check(False, "fetch_sealed_message tren batch chua sealed -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("chua sealed" in str(e), "fetch_sealed_message tren batch chua sealed -> RAISE dung (0 raw fetch)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T2-03: write_predictions tu choi tren batch CHUA sealed (goi truc tiep) ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
            seal_batch["batch_id"], "fake-hash", f'[{{"sample_id":"{seal_sample}","predicted_slots":[]}}]',
            '[]', "m4d-0.1.0", "perm-test-eval")
        check(False, "write_predictions tren batch chua sealed -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("chua sealed" in str(e), "write_predictions tren batch chua sealed -> RAISE dung")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T1-03: sau seal, sua labeled_slots/label_status bi TRIGGER chan (bat ke role nao) ==")
    await admin.execute(
        "UPDATE m4_shadow_review_samples SET label_status='labeled', labeled_slots='[]'::jsonb "
        "WHERE sample_id=$1", seal_sample)
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_reviewer_api")
    sealed_hash = None
    try:
        sealed = await conn.fetchrow("SELECT * FROM m4_stage0p_seal_labels($1,$2)",
                                     seal_batch["batch_id"], staff["id"])
        check(sealed["sample_count"] == 1, "seal_labels thanh cong khi tat ca da labeled")
        sealed_hash = sealed["sealed_hash"]
        check(bool(sealed_hash) and len(sealed_hash) == 64,
              "T2-04: DB tu tinh labels_sealed_hash (sha256 hex, 64 ky tu) — Python KHONG truyen vao")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_reviewer_api")
    try:
        await conn.execute(
            "UPDATE m4_shadow_review_samples SET labeled_slots='[{\"x\":1}]'::jsonb WHERE sample_id=$1",
            seal_sample)
        check(False, "sua labeled_slots SAU SEAL -> phai bi TRIGGER chan")
    except asyncpg.PostgresError as e:
        check("bat bien" in str(e), "sua labeled_slots SAU SEAL -> trigger RAISE dung")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T2-04: write_predictions tu choi neu expected_labels_sealed_hash SAI (stale/forged) ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
            seal_batch["batch_id"], "0" * 64, f'[{{"sample_id":"{seal_sample}","predicted_slots":[]}}]',
            '[]', "m4d-0.1.0", "perm-test-eval")
        check(False, "write_predictions voi hash sai -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong khop" in str(e), "write_predictions voi hash sai -> RAISE dung (chong forged/stale)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T2-03: write_predictions adversarial JSON (schema/enum/bounds/overlap/coverage) ==")
    adversarial_batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, "
        "selected_count, algorithm_seed, locked_conversation_ids, purpose_code) "
        "VALUES (now()-interval '1 day', now(), 1, 1, 'perm-test-adv', ARRAY[]::bigint[], "
        "'P12_PII_DETECTOR_EVAL') RETURNING batch_id"
    )
    adv_sample = str(uuid.uuid4())
    await admin.execute(
        "INSERT INTO m4_shadow_review_samples (sample_id, customer_ref, conversation_ref, "
        "encrypted_message, canonical_text_len, expires_at, purpose_code, normalization_version, "
        "label_status, labeled_slots, selection_batch) VALUES ($1,'996','996','\\x00'::bytea,20,"
        "now()+interval '1 day','P12_PII_DETECTOR_EVAL','nfc-v1','labeled','[]'::jsonb,$2)",
        adv_sample, adversarial_batch["batch_id"],
    )
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_reviewer_api")
    adv_seal = await conn.fetchrow("SELECT * FROM m4_stage0p_seal_labels($1,$2)",
                                   adversarial_batch["batch_id"], staff["id"])
    await conn.execute("RESET ROLE")
    await conn.close()
    adv_hash = adv_seal["sealed_hash"]

    async def _adv(predictions_json, exclusions_json, label):
        conn = await asyncpg.connect(DB_URL)
        await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
        try:
            await conn.fetchrow(
                "SELECT * FROM m4_stage0p_write_predictions($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
                adversarial_batch["batch_id"], adv_hash, predictions_json, exclusions_json,
                "m4d-0.1.0", "perm-test-adv")
            check(False, f"{label} -> phai RAISE")
        except asyncpg.PostgresError:
            check(True, f"{label} -> RAISE dung")
        finally:
            await conn.execute("RESET ROLE")
            await conn.close()

    import json as _json
    await _adv(_json.dumps([{"sample_id": adv_sample, "predicted_slots": [], "extra_key": 1}]), "[]",
              "prediction voi key thua")
    await _adv(_json.dumps([{"sample_id": adv_sample,
                            "predicted_slots": [{"slot_type": "not_a_real_type", "start": 0, "end": 5,
                                                 "confidence": "high", "reason": "x"}]}]), "[]",
              "slot_type khong hop le")
    await _adv(_json.dumps([{"sample_id": adv_sample,
                            "predicted_slots": [{"slot_type": "phone", "start": 0, "end": 5,
                                                 "confidence": "super-high", "reason": "x"}]}]), "[]",
              "confidence khong hop le")
    await _adv(_json.dumps([{"sample_id": adv_sample,
                            "predicted_slots": [{"slot_type": "phone", "start": 5, "end": 3,
                                                 "confidence": "high", "reason": "x"}]}]), "[]",
              "start >= end (offset sai)")
    await _adv(_json.dumps([{"sample_id": adv_sample,
                            "predicted_slots": [{"slot_type": "phone", "start": 0, "end": 100,
                                                 "confidence": "high", "reason": "x"}]}]), "[]",
              "end > canonical_text_len (ngoai bounds)")
    await _adv(_json.dumps([{"sample_id": adv_sample,
                            "predicted_slots": [
                                {"slot_type": "phone", "start": 0, "end": 5, "confidence": "high", "reason": "a"},
                                {"slot_type": "name", "start": 3, "end": 8, "confidence": "high", "reason": "b"},
                            ]}]), "[]", "2 span chong lan trong cung sample")
    await _adv(_json.dumps([{"sample_id": adv_sample, "predicted_slots": []},
                           {"sample_id": adv_sample, "predicted_slots": []}]), "[]",
              "sample_id lap trong predictions")
    await _adv(_json.dumps([{"sample_id": str(uuid.uuid4()), "predicted_slots": []}]), "[]",
              "sample_id khong thuoc batch (foreign)")
    await _adv("[]", "[]", "predictions+exclusions rong — khong phu du corpus (thieu coverage)")
    await _adv(_json.dumps([{"sample_id": adv_sample, "predicted_slots": []}]),
              _json.dumps([{"sample_id": adv_sample, "reason": "x"}]),
              "1 sample vua predict vua exclude")

    print("== T2-03: write_predictions THANH CONG voi payload hop le + phu dung coverage ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        good = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
            adversarial_batch["batch_id"], adv_hash,
            _json.dumps([{"sample_id": adv_sample,
                         "predicted_slots": [{"slot_type": "phone", "start": 0, "end": 5,
                                              "confidence": "high", "reason": "ok"}]}]),
            "[]", "m4d-0.1.0", "perm-test-adv")
        check(good["updated_count"] == 1, "payload hop le -> write_predictions thanh cong")
        result_hash_1 = good["result_hash"]
        check(bool(result_hash_1) and len(result_hash_1) == 64, "T2-04: DB tu tinh result_hash")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T2-03: write_predictions bat bien — goi lai (rerun) tren batch DA ghi -> RAISE ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
            adversarial_batch["batch_id"], adv_hash,
            _json.dumps([{"sample_id": adv_sample, "predicted_slots": []}]), "[]",
            "m4d-0.1.0", "perm-test-adv-2")
        check(False, "rerun tren batch da ghi prediction -> phai RAISE (bat bien)")
    except asyncpg.PostgresError as e:
        check("bat bien" in str(e), "rerun tren batch da ghi prediction -> RAISE dung")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T2-04: complete_evaluation tu choi neu expected_result_hash SAI ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_evaluator")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_complete_evaluation($1,$2,$3,$4::jsonb)",
                            adversarial_batch["batch_id"], staff["id"], "0" * 64, "{}")
        check(False, "complete_evaluation voi result_hash sai -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong khop" in str(e), "complete_evaluation voi result_hash sai -> RAISE dung")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T2-04: complete_evaluation THANH CONG voi result_hash dung -> TU TINH report_hash ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_evaluator")
    try:
        completed = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_complete_evaluation($1,$2,$3,$4::jsonb)",
            adversarial_batch["batch_id"], staff["id"], result_hash_1,
            _json.dumps({"phone": {"tp": 1, "fn": 0, "fp": 0}}))
        check(completed["completed_at"] is not None, "complete_evaluation thanh cong")
        check(bool(completed["report_hash"]) and len(completed["report_hash"]) == 64,
              "T2-04: DB tu tinh evaluation_report_hash")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T1-06: complete_evaluation tu choi neu con sample chua predicted/excluded ==")
    empty_seal_batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, "
        "selected_count, algorithm_seed, locked_conversation_ids, purpose_code) "
        "VALUES (now()-interval '1 day', now(), 1, 1, 'perm-test-eval2', ARRAY[]::bigint[], "
        "'P12_PII_DETECTOR_EVAL') RETURNING batch_id"
    )
    unpred_sample = str(uuid.uuid4())
    await admin.execute(
        "INSERT INTO m4_shadow_review_samples (sample_id, customer_ref, conversation_ref, "
        "encrypted_message, canonical_text_len, expires_at, purpose_code, normalization_version, "
        "label_status, labeled_slots, selection_batch) VALUES ($1,'997','997','\\x00'::bytea,1,"
        "now()+interval '1 day','P12_PII_DETECTOR_EVAL','nfc-v1','labeled','[]'::jsonb,$2)",
        unpred_sample, empty_seal_batch["batch_id"],
    )
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_reviewer_api")
    await conn.fetchrow("SELECT * FROM m4_stage0p_seal_labels($1,$2)", empty_seal_batch["batch_id"], staff["id"])
    await conn.execute("RESET ROLE")
    await conn.close()
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_evaluator")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_complete_evaluation($1,$2,$3,$4::jsonb)",
                            empty_seal_batch["batch_id"], staff["id"], "0" * 64, "{}")
        check(False, "complete_evaluation voi batch chua ghi prediction -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("chua ghi prediction" in str(e), "complete_evaluation voi batch chua ghi prediction -> RAISE dung")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== Xac nhan control da ve OFF (bat buoc truoc khi ket thuc script) ==")
    final_state = await admin.fetchval("SELECT capture_enabled FROM m4_stage0p_control WHERE id=1")
    check(final_state is False, "control ve OFF truoc khi script ket thuc (khong de lai flag ON)")

    await admin.execute("DELETE FROM m4_shadow_review_samples")
    await admin.execute("DELETE FROM m4_selection_batches")
    await admin.execute("DELETE FROM audit_log")
    await admin.execute("DELETE FROM messages")
    await admin.execute("DELETE FROM conversations")
    await admin.execute("DELETE FROM customers WHERE psid='perm-audit-test'")
    await admin.execute("DELETE FROM m4_stage0p_capture_approvals WHERE approval_ref LIKE 'perm-test-%'")
    await admin.execute("DELETE FROM staff_users WHERE id=$1", staff["id"])
    await admin.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
