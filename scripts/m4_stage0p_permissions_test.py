#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: negative-permission matrix (CA acceptance criteria #2, #3).

Chay:
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      alpha3s-m4-test python scripts/m4_stage0p_permissions_test.py

REV 2 (CA Technical Review #1 T1-01..T1-06): cap nhat theo 5 ham SECURITY DEFINER moi. Diem
khac biet chinh so voi ban goc:
  - alpha3s_m4_control_plane / alpha3s_m4_prediction_writer KHONG con UPDATE truc tiep — matrix
    va 1 buoc rieng xac nhan CA dieu nay (T1-01/T1-03/T1-05).
  - Vong lap SECURITY DEFINER hardening chay tren CA 5 ham (khong chi 1 ham nhu ban goc).
  - Ma tran EXECUTE rieng: dung role duoc EXECUTE dung ham, PUBLIC/vendor-path bi tu choi tat ca.
  - 3 kich ban moi: sua label sau seal bi trigger chan (T1-03), write_predictions tren batch
    chua sealed bi tu choi (T1-03), complete_evaluation khi con sample chua co prediction bi
    tu choi (T1-06) — ca 3 goi TRUC TIEP ham DB (khong qua Python wrapper) de chung minh enforce
    nam O DB, khong phai app convention.
  - Cac test kiem tra batch validation (batch khong ton tai / closed) can BAT control ON truoc
    (m4_stage0p_fetch_next_message kiem tra control TRUOC ca validate batch — T1-01) — BAT/TAT
    qua chinh ham m4_stage0p_set_capture, dam bao control quay ve OFF truoc khi script ket thuc.

Duyet DAY DU 8 role (7 role M4 + alpha3s_app + alpha3s_vendor_path + PUBLIC) x cac thao tac tren
3 bang + 5 ham. Moi dong la 1 khang dinh DENY hoac ALLOW ro rang — khong suy dien.
"""

import asyncio
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
    "alpha3s_m4_pending_checker", "alpha3s_app", "alpha3s_vendor_path", "PUBLIC",
]

FUNCTIONS = [
    ("m4_stage0p_fetch_next_message", "uuid,bigint,bigint", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_set_capture", "boolean,bigint,text", "alpha3s_m4_control_plane"),
    ("m4_stage0p_seal_labels", "uuid,bigint,text", "alpha3s_m4_sample_reviewer_api"),
    ("m4_stage0p_write_predictions", "uuid,jsonb,text,text", "alpha3s_m4_prediction_writer"),
    ("m4_stage0p_complete_evaluation", "uuid,bigint,text", "alpha3s_m4_sample_evaluator"),
]


async def main() -> int:
    admin = await asyncpg.connect(DB_URL)

    staff = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ('m4-perm-test-staff', 'x', 'x', true) RETURNING id"
    )

    # Seed 1 row toi thieu de test UPDATE/DELETE tren du lieu that su ton tai (khong chi WHERE 0=1)
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

    print("== Ma tran negative-permission: 3 bang chinh ==")
    matrix = [
        # (role, table, action, sql, expected_allowed)
        ("alpha3s_m4_sample_collector", "samples", "SELECT",
         "SELECT * FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_sample_collector", "samples", "INSERT",
         f"INSERT INTO m4_shadow_review_samples (sample_id,customer_ref,conversation_ref,"
         f"encrypted_message,canonical_text_len,expires_at,purpose_code,normalization_version,"
         f"selection_batch) VALUES ('{uuid.uuid4()}','1','1','\\x00'::bytea,1,"
         f"now()+interval '1 day','P12_PII_DETECTOR_EVAL','nfc-v1','{batch['batch_id']}')", True),
        ("alpha3s_m4_sample_collector", "samples", "UPDATE",
         "UPDATE m4_shadow_review_samples SET label_status='labeled'", False),
        ("alpha3s_m4_sample_collector", "control", "UPDATE",
         "UPDATE m4_stage0p_control SET capture_enabled=true", False),
        ("alpha3s_m4_sample_collector", "control", "SELECT direct",
         "SELECT capture_enabled FROM m4_stage0p_control", False),
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

        # REV2 T1-03: prediction_writer KHONG con UPDATE truc tiep (chi EXECUTE write_predictions)
        ("alpha3s_m4_prediction_writer", "samples", "UPDATE predicted_slots (direct, phai DENY)",
         "UPDATE m4_shadow_review_samples SET predicted_slots='[]'::jsonb", False),
        ("alpha3s_m4_prediction_writer", "samples", "SELECT encrypted_message",
         "SELECT encrypted_message FROM m4_shadow_review_samples", True),
        ("alpha3s_m4_prediction_writer", "samples", "UPDATE labeled_slots",
         "UPDATE m4_shadow_review_samples SET labeled_slots='[]'::jsonb", False),
        ("alpha3s_m4_prediction_writer", "samples", "DELETE",
         "DELETE FROM m4_shadow_review_samples", False),

        ("alpha3s_m4_sample_purge", "samples", "DELETE",
         "DELETE FROM m4_shadow_review_samples WHERE expires_at < now()-interval '1000 days'", True),
        ("alpha3s_m4_sample_purge", "samples", "SELECT encrypted_message",
         "SELECT encrypted_message FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_sample_purge", "samples", "UPDATE",
         "UPDATE m4_shadow_review_samples SET label_status='labeled'", False),

        # REV2 T1-01/T1-05: control_plane KHONG con UPDATE truc tiep (chi EXECUTE set_capture)
        ("alpha3s_m4_control_plane", "control", "UPDATE capture_enabled (direct, phai DENY)",
         "UPDATE m4_stage0p_control SET capture_enabled=true", False),
        ("alpha3s_m4_control_plane", "control", "SELECT capture_enabled",
         "SELECT capture_enabled FROM m4_stage0p_control", True),
        ("alpha3s_m4_control_plane", "samples", "SELECT",
         "SELECT * FROM m4_shadow_review_samples", False),

        ("alpha3s_m4_pending_checker", "customers", "SELECT psid",
         "SELECT psid FROM customers LIMIT 1", True),
        ("alpha3s_m4_pending_checker", "samples", "SELECT",
         "SELECT * FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_pending_checker", "customers", "UPDATE",
         "UPDATE customers SET name='x'", False),

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

        ("alpha3s_vendor_path", "samples", "SELECT",
         "SELECT * FROM m4_shadow_review_samples", False),
        ("alpha3s_vendor_path", "control", "SELECT",
         "SELECT * FROM m4_stage0p_control", False),
        ("alpha3s_vendor_path", "batches", "SELECT",
         "SELECT * FROM m4_selection_batches", False),

        ("public", "samples", "SELECT", "SELECT * FROM m4_shadow_review_samples", False),
        ("public", "control", "SELECT", "SELECT * FROM m4_stage0p_control", False),
        ("public", "batches", "SELECT", "SELECT * FROM m4_selection_batches", False),
    ]

    for role, table, action, sql, expected in matrix:
        if role == "public":
            # PUBLIC KHONG phai role login duoc — SET ROLE se khong co tac dung han che gi
            # (ket noi admin la superuser, bo qua moi kiem tra quyen). Dung has_*_privilege
            # qua admin connection thay vi thu ket noi that.
            table_name = {"samples": "m4_shadow_review_samples", "control": "m4_stage0p_control",
                         "batches": "m4_selection_batches"}[table]
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

    print("== Ma tran EXECUTE tren 5 ham SECURITY DEFINER (REV2) ==")
    for fname, fsig, owner_role in FUNCTIONS:
        for role in ROLES:
            expected = (role == owner_role)
            if role.lower() == "public":
                allowed = await admin.fetchval(
                    "SELECT has_function_privilege('public', $1, 'EXECUTE')",
                    f"{fname}({fsig})")
            else:
                allowed = await admin.fetchval(
                    "SELECT has_function_privilege($1, $2, 'EXECUTE')",
                    role, f"{fname}({fsig})")
            verb = "ALLOW" if expected else "DENY"
            check(allowed == expected,
                  f"{role} / EXECUTE {fname} -> {verb} (thuc te: {'allowed' if allowed else 'denied'})")

    print("== SECURITY DEFINER hardening (5 ham REV2) ==")
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
    owner_super = await admin.fetchval(
        "SELECT rolsuper OR rolcreaterole OR rolcreatedb FROM pg_roles WHERE rolname='alpha3s_m4_definer'")
    check(owner_super is False, "alpha3s_m4_definer KHONG superuser/createrole/createdb")

    print("== BAT control (via ham) de test batch validation — fetch kiem tra control TRUOC batch ==")
    ctrl_conn = await asyncpg.connect(DB_URL)
    await ctrl_conn.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        on_row = await ctrl_conn.fetchrow(
            "SELECT * FROM m4_stage0p_set_capture($1,$2,$3)", True, staff["id"], "perm-test-enable-temp")
        check(on_row["after_enabled"] is True, "set_capture(True) qua ham -> control ON (tam thoi, se tat lai cuoi test)")
    finally:
        await ctrl_conn.execute("RESET ROLE")

    print("== Ham fetch_next_message tu choi batch sai trang thai/window/purpose ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        await conn.fetchval("SELECT * FROM m4_stage0p_fetch_next_message($1,-1,-1)", str(uuid.uuid4()))
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
        await conn.fetchval("SELECT * FROM m4_stage0p_fetch_next_message($1,-1,-1)", closed_batch["batch_id"])
        check(False, "batch status='closed' -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("closed" in str(e), "batch status='closed' -> RAISE dung")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== control OFF -> fetch tra 'control_off', KHONG raise, KHONG doc content (T1-01) ==")
    ctrl_conn = await asyncpg.connect(DB_URL)
    await ctrl_conn.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        off_row = await ctrl_conn.fetchrow(
            "SELECT * FROM m4_stage0p_set_capture($1,$2,$3)", False, staff["id"], "perm-test-disable-temp")
        check(off_row["after_enabled"] is False, "set_capture(False) qua ham -> control OFF")
    finally:
        await ctrl_conn.execute("RESET ROLE")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        off_result = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_fetch_next_message($1,-1,-1)", closed_batch["batch_id"])
        check(off_result["status"] == "control_off", "control OFF -> status='control_off'")
        check(off_result["content"] is None, "control OFF -> content=NULL (khong doc plaintext)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== Audit fail-closed: fetch_next_message tu choi tra du lieu neu ghi audit_log bi chan ==")
    # bat control lai tam thoi de vuot qua checkpoint control-off truoc khi test audit block
    ctrl_conn = await asyncpg.connect(DB_URL)
    await ctrl_conn.execute("SET ROLE alpha3s_m4_control_plane")
    await ctrl_conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2,$3)", True, staff["id"], "perm-test-audit")
    await ctrl_conn.execute("RESET ROLE")
    revoke_conn = await asyncpg.connect(DB_URL)
    await revoke_conn.execute("REVOKE INSERT ON audit_log FROM alpha3s_m4_definer")
    ok_batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, "
        "selected_count, algorithm_seed, locked_conversation_ids, purpose_code) "
        "VALUES (now()-interval '1 day', now(), 0, 0, 'perm-test-3', ARRAY[]::bigint[], "
        "'P12_PII_DETECTOR_EVAL') RETURNING batch_id"
    )
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    audit_blocked_denies_data = False
    try:
        await conn.fetchval("SELECT * FROM m4_stage0p_fetch_next_message($1,-1,-1)", ok_batch["batch_id"])
    except asyncpg.PostgresError:
        audit_blocked_denies_data = True
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()
    check(audit_blocked_denies_data, "audit INSERT bi chan -> fetch_next_message KHONG tra du lieu (fail closed)")
    await revoke_conn.execute("GRANT INSERT ON audit_log TO alpha3s_m4_definer")
    await revoke_conn.close()
    ctrl_conn = await asyncpg.connect(DB_URL)
    await ctrl_conn.execute("SET ROLE alpha3s_m4_control_plane")
    await ctrl_conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2,$3)", False, staff["id"], "perm-test-audit-off")
    await ctrl_conn.execute("RESET ROLE")

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
        await conn.fetchrow("SELECT * FROM m4_stage0p_seal_labels($1,$2,$3)",
                            seal_batch["batch_id"], staff["id"], "hash-x")
        check(False, "seal voi row unlabeled -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("unlabeled" in str(e), "seal voi row unlabeled -> RAISE dung")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T1-03: write_predictions tu choi tren batch CHUA sealed (goi truc tiep, khong qua Python) ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1,$2::jsonb,$3,$4)",
            seal_batch["batch_id"], f'[{{"sample_id":"{seal_sample}","predicted_slots":[]}}]',
            "m4d-0.1.0", "perm-test-eval")
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
    try:
        sealed = await conn.fetchrow("SELECT * FROM m4_stage0p_seal_labels($1,$2,$3)",
                                     seal_batch["batch_id"], staff["id"], "hash-real")
        check(sealed["sample_count"] == 1, "seal_labels thanh cong khi tat ca da labeled")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()
    # reviewer_api VAN co UPDATE grant tren labeled_slots (§6b) — nhung TRIGGER phai chan sau seal,
    # bat ke quyen bang co hay khong. Day la khac biet cot loi voi T1-03 (bat bien O DB, khong phai
    # app convention/quyen bang don thuan).
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

    print("== T1-03: write_predictions THANH CONG tren batch DA sealed ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        pred_row = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1,$2::jsonb,$3,$4)",
            seal_batch["batch_id"], f'[{{"sample_id":"{seal_sample}","predicted_slots":[]}}]',
            "m4d-0.1.0", "perm-test-eval")
        check(pred_row["updated_count"] == 1, "write_predictions tren batch DA sealed -> thanh cong")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T1-06: complete_evaluation tu choi neu con sample chua predicted (evaluator role) ==")
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
    await conn.fetchrow("SELECT * FROM m4_stage0p_seal_labels($1,$2,$3)",
                        empty_seal_batch["batch_id"], staff["id"], "hash-unpred")
    await conn.execute("RESET ROLE")
    await conn.close()
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_evaluator")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_complete_evaluation($1,$2,$3)",
                            empty_seal_batch["batch_id"], staff["id"], "report-hash-x")
        check(False, "complete_evaluation voi sample chua predicted -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("chua co prediction" in str(e), "complete_evaluation voi sample chua predicted -> RAISE dung")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== Xac nhan control da ve OFF (bat buoc truoc khi ket thuc script) ==")
    final_state = await admin.fetchval("SELECT capture_enabled FROM m4_stage0p_control WHERE id=1")
    check(final_state is False, "control ve OFF truoc khi script ket thuc (khong de lai flag ON)")

    await admin.execute("DELETE FROM m4_shadow_review_samples")
    await admin.execute("DELETE FROM m4_selection_batches")
    await admin.execute("DELETE FROM audit_log")
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
