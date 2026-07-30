#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: negative-permission matrix (CA acceptance criteria #2, #3).

Chay:
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      alpha3s-m4-test python scripts/m4_stage0p_permissions_test.py

REV 5 (CA Technical Review #4, T4-01..05) — cap nhat theo 15 ham SECURITY DEFINER (thay cho
11 ham REV4):
  - `m4_stage0p_fetch_message_content`/`m4_stage0p_record_sample` (T4-01): "token" khong con la
    GUC (`set_config`/`current_setting` — CA chi ro day KHONG phai secret/privileged storage) ma
    la 1 row trong bang MOI `m4_stage0p_fetch_capability` (khong GRANT cho role m4 nao) —
    fetch_message_content INSERT (txid_current(), caller khong tu chon duoc), record_sample
    DELETE...RETURNING dung row do CUNG transaction.
  - `m4_stage0p_peek_next_candidate` (T4-03): doi chu ky con `(batch_id)` — doc tu bang MOI
    `m4_stage0p_capture_progress` (state machine 5 gia tri) thay vi cursor rieng.
  - `m4_stage0p_seed_capture_progress`/`m4_stage0p_mark_candidate_outcome` (MOI, T4-03): seed toan
    bo candidate 1 lan; chuyen retryable_failed (>=3 lan -> permanent_failed) hoac excluded.
  - `m4_stage0p_close_collection` (T4-03): them dieu kien — KHONG con row pending/retryable_failed.
  - `m4_stage0p_pin_actor`/`m4_stage0p_require_pinned_actor` (MOI, T4-04): actor khong con la tham
    so caller-supplied — phai "pin" vao session TRUOC (role rieng `alpha3s_m4_actor_binder`), cac
    ham nghiep vu doc actor tu session + kiem QUYEN CU THE (bang MOI
    `m4_stage0p_staff_permissions`). `m4_stage0p_set_capture`/`record_approval`/`revoke_approval`/
    `seal_labels`/`complete_evaluation` deu BOT 1 tham so actor.
  - `m4_stage0p_write_predictions` (T4-02/T4-05): bo `p_current_normalization_version` (hardcode
    server-side); tran exclusion doc tu bang MOI `m4_stage0p_exclusion_gate` (10%/200, de xuat CA
    Review #4) thay vi hardcode 50%.

Duyet DAY DU 15 role (9 role M4 + alpha3s_app + alpha3s_vendor_path + PUBLIC) x cac thao tac tren
9 bang (them fetch_capability/capture_progress/staff_permissions/exclusion_gate) + 15 ham nghiep vu.
"""

import asyncio
import datetime
import json as _json
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
    "alpha3s_m4_actor_binder", "alpha3s_app", "alpha3s_vendor_path", "PUBLIC",
]

# owner_role = None -> KHONG role nao trong ROLES duoc EXECUTE (ham noi bo thuan tuy, chi goi
# tu BEN TRONG ham SECURITY DEFINER khac, chay voi quyen owner).
FUNCTIONS = [
    ("m4_stage0p_peek_next_candidate", "uuid", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_fetch_message_content", "uuid,bigint,bigint", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_record_sample", "uuid,bigint,bigint,uuid,bytea,int,boolean", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_close_collection", "uuid", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_seed_capture_progress", "uuid", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_mark_candidate_outcome", "uuid,bigint,bigint,text,text", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_pin_actor", "bigint", "alpha3s_m4_actor_binder"),
    ("m4_stage0p_require_pinned_actor", "text", None),
    ("m4_stage0p_set_capture", "boolean,text", "alpha3s_m4_control_plane"),
    ("m4_stage0p_record_approval", "text,boolean,timestamptz,timestamptz,text", "alpha3s_m4_approval_recorder"),
    ("m4_stage0p_revoke_approval", "text,text", "alpha3s_m4_approval_recorder"),
    ("m4_stage0p_seal_labels", "uuid", "alpha3s_m4_sample_reviewer_api"),
    ("m4_stage0p_fetch_sealed_message", "uuid,uuid", "alpha3s_m4_prediction_writer"),
    ("m4_stage0p_write_predictions", "uuid,text,jsonb,jsonb,text,text", "alpha3s_m4_prediction_writer"),
    ("m4_stage0p_complete_evaluation", "uuid,text", "alpha3s_m4_sample_evaluator"),
]

PERMISSIONS = ["m4.stage0p.approve", "m4.stage0p.operate", "m4.stage0p.review", "m4.stage0p.evaluate"]


async def _pin(conn, staff_id: int) -> None:
    """T4-04: pin actor vao session (role alpha3s_m4_actor_binder), roi RESET ROLE — GUC session-
    scoped sinh ton qua lan SET ROLE tiep theo cua caller."""
    await conn.execute("SET ROLE alpha3s_m4_actor_binder")
    await conn.fetchrow("SELECT * FROM m4_stage0p_pin_actor($1)", staff_id)
    await conn.execute("RESET ROLE")


async def _set_capture(conn, *, enabled, staff_id, approval_ref):
    await _pin(conn, staff_id)
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        return await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", enabled, approval_ref)
    finally:
        await conn.execute("RESET ROLE")


async def _record_approval(conn, *, staff_id, approval_ref, requested_enabled, valid_from,
                           valid_until, note=None):
    await _pin(conn, staff_id)
    await conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    try:
        return await conn.fetchrow(
            "SELECT * FROM m4_stage0p_record_approval($1,$2,$3,$4,$5)",
            approval_ref, requested_enabled, valid_from, valid_until, note)
    finally:
        await conn.execute("RESET ROLE")


async def _revoke_approval(conn, *, staff_id, approval_ref, reason):
    await _pin(conn, staff_id)
    await conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    try:
        return await conn.fetchrow("SELECT * FROM m4_stage0p_revoke_approval($1,$2)", approval_ref, reason)
    finally:
        await conn.execute("RESET ROLE")


async def _seal_labels(conn, *, staff_id, batch_id):
    await _pin(conn, staff_id)
    await conn.execute("SET ROLE alpha3s_m4_sample_reviewer_api")
    try:
        return await conn.fetchrow("SELECT * FROM m4_stage0p_seal_labels($1)", batch_id)
    finally:
        await conn.execute("RESET ROLE")


async def _complete_evaluation(conn, *, staff_id, batch_id, expected_result_hash):
    await _pin(conn, staff_id)
    await conn.execute("SET ROLE alpha3s_m4_sample_evaluator")
    try:
        return await conn.fetchrow("SELECT * FROM m4_stage0p_complete_evaluation($1,$2)",
                                   batch_id, expected_result_hash)
    finally:
        await conn.execute("RESET ROLE")


async def _grant_permission(admin, *, staff_id, permission, granted_by):
    await admin.execute(
        "INSERT INTO m4_stage0p_staff_permissions (staff_id, permission, granted_by) "
        "VALUES ($1,$2,$3) ON CONFLICT DO NOTHING", staff_id, permission, granted_by)


async def _make_collection_closed_batch(admin, *, seed: str, samples: list[tuple]) -> str:
    """Tao batch da 'collection_closed' truc tiep — chuan bi tien de cho test seal/predict/eval.
    `samples`: [(sample_id, customer_ref, canonical_text_len)]."""
    batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, selected_count, "
        "algorithm_seed, locked_conversation_ids, purpose_code, status, captured_count, collection_closed_at) "
        "VALUES (now()-interval '1 day', now(), $1, $1, $2, ARRAY[]::bigint[], 'P12_PII_DETECTOR_EVAL', "
        "'collection_closed', $1, now()) RETURNING batch_id",
        len(samples), seed)
    for sample_id, customer_ref, canonical_len in samples:
        await admin.execute(
            "INSERT INTO m4_shadow_review_samples (sample_id, customer_ref, conversation_ref, "
            "encrypted_message, canonical_text_len, expires_at, purpose_code, normalization_version, "
            "selection_batch) VALUES ($1,$2,$2,'\\x00'::bytea,$3,now()+interval '1 day',"
            "'P12_PII_DETECTOR_EVAL','nfc-v1',$4)",
            sample_id, customer_ref, canonical_len, batch["batch_id"])
    return batch["batch_id"]


async def _make_large_batch(admin, *, seed: str, n: int) -> tuple:
    """T4-05: gate mac dinh doi hoi >=200 conversation KHONG bi loai — bulk insert n sample (moi
    sample 1 conversation_ref rieng) qua 1 lenh INSERT...SELECT FROM unnest (khong N round-trip),
    da labeled (labeled_slots rong) + sealed-ready (status='collection_closed')."""
    batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, selected_count, "
        "algorithm_seed, locked_conversation_ids, purpose_code, status, captured_count, collection_closed_at) "
        "VALUES (now()-interval '1 day', now(), $1, $1, $2, ARRAY[]::bigint[], 'P12_PII_DETECTOR_EVAL', "
        "'collection_closed', $1, now()) RETURNING batch_id", n, seed)
    sample_ids = [str(uuid.uuid4()) for _ in range(n)]
    refs = [f"{seed}-{i}" for i in range(n)]
    await admin.execute(
        "INSERT INTO m4_shadow_review_samples (sample_id, customer_ref, conversation_ref, "
        "encrypted_message, canonical_text_len, expires_at, purpose_code, normalization_version, "
        "label_status, labeled_slots, selection_batch) "
        "SELECT sid::uuid, cref, cref, '\\x00'::bytea, 20, now()+interval '1 day', "
        "'P12_PII_DETECTOR_EVAL', 'nfc-v1', 'labeled', '[]'::jsonb, $1 "
        "FROM unnest($2::text[], $3::text[]) AS t(sid, cref)",
        batch["batch_id"], sample_ids, refs)
    return batch["batch_id"], sample_ids


async def main() -> int:
    admin = await asyncpg.connect(DB_URL)

    staff = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ('m4-perm-test-staff', 'x', 'x', true) RETURNING id"
    )
    for perm in PERMISSIONS:
        await _grant_permission(admin, staff_id=staff["id"], permission=perm, granted_by=staff["id"])

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
    now = datetime.datetime.now(datetime.timezone.utc)
    approval_conn = await asyncpg.connect(DB_URL)
    await _record_approval(approval_conn, staff_id=staff["id"], approval_ref="perm-test-approval-ok",
                           requested_enabled=True, valid_from=now - datetime.timedelta(hours=1),
                           valid_until=now + datetime.timedelta(hours=1))
    await approval_conn.close()

    print("== Ma tran negative-permission: 9 bang chinh ==")
    matrix = [
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
        ("alpha3s_m4_sample_collector", "approvals", "INSERT (direct, phai DENY)",
         f"INSERT INTO m4_stage0p_capture_approvals (approval_ref,purpose_code,requested_enabled,"
         f"valid_from,valid_until,recorded_by) VALUES ('x','P12_PII_DETECTOR_EVAL',true,now(),"
         f"now()+interval '1 day',{staff['id']})", False),
        ("alpha3s_m4_sample_collector", "customers", "SELECT psid",
         "SELECT psid FROM customers", False),
        ("alpha3s_m4_sample_collector", "messages", "SELECT direct",
         "SELECT * FROM messages", False),
        ("alpha3s_m4_sample_collector", "fetch_capability", "SELECT (phai DENY — T4-01)",
         "SELECT * FROM m4_stage0p_fetch_capability", False),
        ("alpha3s_m4_sample_collector", "fetch_capability", "INSERT (phai DENY — T4-01, khong the tu forge)",
         "INSERT INTO m4_stage0p_fetch_capability (batch_id,conversation_id,message_id,txid) "
         "VALUES (gen_random_uuid(),1,1,txid_current())", False),
        ("alpha3s_m4_sample_collector", "fetch_capability", "DELETE (phai DENY — T4-01)",
         "DELETE FROM m4_stage0p_fetch_capability", False),
        ("alpha3s_m4_sample_collector", "capture_progress", "SELECT (phai DENY — T4-03)",
         "SELECT * FROM m4_stage0p_capture_progress", False),
        ("alpha3s_m4_sample_collector", "capture_progress", "UPDATE (phai DENY — T4-03)",
         "UPDATE m4_stage0p_capture_progress SET status='committed'", False),

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

        ("alpha3s_m4_prediction_writer", "samples", "UPDATE predicted_slots (direct, phai DENY)",
         "UPDATE m4_shadow_review_samples SET predicted_slots='[]'::jsonb", False),
        ("alpha3s_m4_prediction_writer", "samples", "SELECT encrypted_message (direct, phai DENY)",
         "SELECT encrypted_message FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_prediction_writer", "samples", "SELECT customer_ref (direct, phai DENY)",
         "SELECT customer_ref FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_prediction_writer", "samples", "UPDATE labeled_slots",
         "UPDATE m4_shadow_review_samples SET labeled_slots='[]'::jsonb", False),
        ("alpha3s_m4_prediction_writer", "samples", "DELETE",
         "DELETE FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_prediction_writer", "batches", "SELECT labels_sealed_hash",
         "SELECT labels_sealed_hash FROM m4_selection_batches", True),
        ("alpha3s_m4_prediction_writer", "exclusion_gate", "UPDATE (phai DENY — T4-05)",
         "UPDATE m4_stage0p_exclusion_gate SET max_exclusion_rate=0.99", False),
        ("alpha3s_m4_prediction_writer", "exclusion_gate", "SELECT (phai DENY — chi definer noi bo doc)",
         "SELECT * FROM m4_stage0p_exclusion_gate", False),

        ("alpha3s_m4_sample_purge", "samples", "DELETE",
         "DELETE FROM m4_shadow_review_samples WHERE expires_at < now()-interval '1000 days'", True),
        ("alpha3s_m4_sample_purge", "samples", "SELECT encrypted_message",
         "SELECT encrypted_message FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_sample_purge", "samples", "UPDATE",
         "UPDATE m4_shadow_review_samples SET label_status='labeled'", False),

        ("alpha3s_m4_control_plane", "control", "UPDATE capture_enabled (direct, phai DENY)",
         "UPDATE m4_stage0p_control SET capture_enabled=true", False),
        ("alpha3s_m4_control_plane", "control", "SELECT capture_enabled",
         "SELECT capture_enabled FROM m4_stage0p_control", True),
        ("alpha3s_m4_control_plane", "samples", "SELECT",
         "SELECT * FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_control_plane", "approvals", "INSERT (phai DENY — chong tu duyet)",
         f"INSERT INTO m4_stage0p_capture_approvals (approval_ref,purpose_code,requested_enabled,"
         f"valid_from,valid_until,recorded_by) VALUES ('y','P12_PII_DETECTOR_EVAL',true,now(),"
         f"now()+interval '1 day',{staff['id']})", False),
        ("alpha3s_m4_control_plane", "approvals", "SELECT (phai DENY)",
         "SELECT * FROM m4_stage0p_capture_approvals", False),

        ("alpha3s_m4_pending_checker", "customers", "SELECT psid",
         "SELECT psid FROM customers LIMIT 1", True),
        ("alpha3s_m4_pending_checker", "samples", "SELECT",
         "SELECT * FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_pending_checker", "customers", "UPDATE",
         "UPDATE customers SET name='x'", False),

        ("alpha3s_m4_approval_recorder", "approvals", "INSERT (direct, phai DENY — T3-05)",
         f"INSERT INTO m4_stage0p_capture_approvals (approval_ref,purpose_code,requested_enabled,"
         f"valid_from,valid_until,recorded_by) VALUES ('perm-test-approval-matrix',"
         f"'P12_PII_DETECTOR_EVAL',true,now(),now()+interval '1 day',{staff['id']})", False),
        ("alpha3s_m4_approval_recorder", "approvals", "SELECT (direct, phai DENY — T3-05)",
         "SELECT * FROM m4_stage0p_capture_approvals", False),
        ("alpha3s_m4_approval_recorder", "revocations", "INSERT (direct, phai DENY — T3-05)",
         f"INSERT INTO m4_stage0p_capture_approval_revocations (approval_ref,revoked_by,reason) "
         f"VALUES ('perm-test-approval-ok',{staff['id']},'test')", False),
        ("alpha3s_m4_approval_recorder", "control", "UPDATE (phai DENY)",
         "UPDATE m4_stage0p_control SET capture_enabled=true", False),
        ("alpha3s_m4_approval_recorder", "samples", "SELECT (phai DENY)",
         "SELECT * FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_approval_recorder", "staff_permissions", "SELECT (phai DENY — T4-04)",
         "SELECT * FROM m4_stage0p_staff_permissions", False),

        ("alpha3s_m4_actor_binder", "staff_permissions", "SELECT (phai DENY — T4-04)",
         "SELECT * FROM m4_stage0p_staff_permissions", False),
        ("alpha3s_m4_actor_binder", "samples", "SELECT (phai DENY)",
         "SELECT * FROM m4_shadow_review_samples", False),
        ("alpha3s_m4_actor_binder", "control", "UPDATE (phai DENY)",
         "UPDATE m4_stage0p_control SET capture_enabled=true", False),

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
        ("alpha3s_vendor_path", "revocations", "SELECT",
         "SELECT * FROM m4_stage0p_capture_approval_revocations", False),
        ("alpha3s_vendor_path", "fetch_capability", "SELECT",
         "SELECT * FROM m4_stage0p_fetch_capability", False),
        ("alpha3s_vendor_path", "capture_progress", "SELECT",
         "SELECT * FROM m4_stage0p_capture_progress", False),
        ("alpha3s_vendor_path", "staff_permissions", "SELECT",
         "SELECT * FROM m4_stage0p_staff_permissions", False),
        ("alpha3s_vendor_path", "exclusion_gate", "SELECT",
         "SELECT * FROM m4_stage0p_exclusion_gate", False),

        ("public", "samples", "SELECT", "SELECT * FROM m4_shadow_review_samples", False),
        ("public", "control", "SELECT", "SELECT * FROM m4_stage0p_control", False),
        ("public", "batches", "SELECT", "SELECT * FROM m4_selection_batches", False),
        ("public", "approvals", "SELECT", "SELECT * FROM m4_stage0p_capture_approvals", False),
        ("public", "revocations", "SELECT", "SELECT * FROM m4_stage0p_capture_approval_revocations", False),
        ("public", "fetch_capability", "SELECT", "SELECT * FROM m4_stage0p_fetch_capability", False),
        ("public", "capture_progress", "SELECT", "SELECT * FROM m4_stage0p_capture_progress", False),
        ("public", "staff_permissions", "SELECT", "SELECT * FROM m4_stage0p_staff_permissions", False),
        ("public", "exclusion_gate", "SELECT", "SELECT * FROM m4_stage0p_exclusion_gate", False),
    ]

    table_name_map = {
        "samples": "m4_shadow_review_samples", "control": "m4_stage0p_control",
        "batches": "m4_selection_batches", "approvals": "m4_stage0p_capture_approvals",
        "revocations": "m4_stage0p_capture_approval_revocations",
        "fetch_capability": "m4_stage0p_fetch_capability",
        "capture_progress": "m4_stage0p_capture_progress",
        "staff_permissions": "m4_stage0p_staff_permissions",
        "exclusion_gate": "m4_stage0p_exclusion_gate",
    }

    for role, table, action, sql, expected in matrix:
        if role == "public":
            table_name = table_name_map[table]
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

    print("== Ma tran EXECUTE tren 15 ham SECURITY DEFINER (REV5) ==")
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

    print("== SECURITY DEFINER hardening (15 ham nghiep vu + trigger REV5) ==")
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
          "m4_stage0p_block_label_after_seal: SECURITY DEFINER, owner dung")
    owner_super = await admin.fetchval(
        "SELECT rolsuper OR rolcreaterole OR rolcreatedb FROM pg_roles WHERE rolname='alpha3s_m4_definer'")
    check(owner_super is False, "alpha3s_m4_definer KHONG superuser/createrole/createdb")

    print("== T4-04: pin_actor tu choi staff khong ton tai/khong active ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_actor_binder")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_pin_actor($1)", 999999999)
        check(False, "pin_actor staff khong ton tai -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong ton tai" in str(e), "pin_actor staff khong ton tai -> RAISE dung")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T4-04: goi ham nghiep vu MA CHUA pin_actor -> tu choi ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", False, None)
        check(False, "set_capture chua pin actor -> phai RAISE (T4-04)")
    except asyncpg.PostgresError as e:
        check("chua pin actor" in str(e), "set_capture chua pin actor -> RAISE dung (T4-04)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T4-04: actor da pin nhung KHONG co quyen cu the -> tu choi ==")
    staff_no_perm = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ('m4-perm-test-noperm', 'x', 'x', true) RETURNING id")
    conn = await asyncpg.connect(DB_URL)
    await _pin(conn, staff_no_perm["id"])
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", False, None)
        check(False, "actor khong co quyen m4.stage0p.operate -> phai RAISE (T4-04)")
    except asyncpg.PostgresError as e:
        check("khong co quyen" in str(e), "actor khong co quyen -> RAISE dung (T4-04)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T4-04: pin_actor sinh ton qua SET ROLE (session-scoped, khong phai LOCAL) ==")
    conn = await asyncpg.connect(DB_URL)
    await _pin(conn, staff["id"])
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    pinned_val = await conn.fetchval("SELECT current_setting('alpha3s.m4_actor_staff_id', true)")
    check(pinned_val == str(staff["id"]), "actor da pin VAN doc duoc SAU khi SET ROLE (session-scoped dung)")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T4-05: set_capture(ON) tu choi approval khong ton tai/het han/bi thu hoi ==")
    conn = await asyncpg.connect(DB_URL)
    try:
        await _set_capture(conn, enabled=True, staff_id=staff["id"], approval_ref="khong-ton-tai")
        check(False, "approval khong ton tai -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong hop le" in str(e), "approval khong ton tai -> RAISE dung")

    expired_conn = await asyncpg.connect(DB_URL)
    await _record_approval(expired_conn, staff_id=staff["id"], approval_ref="perm-test-approval-expired",
                           requested_enabled=True, valid_from=now - datetime.timedelta(days=2),
                           valid_until=now - datetime.timedelta(days=1))
    await _record_approval(expired_conn, staff_id=staff["id"], approval_ref="perm-test-approval-torevoke",
                           requested_enabled=True, valid_from=now - datetime.timedelta(hours=1),
                           valid_until=now + datetime.timedelta(hours=1))
    revoke_result = await _revoke_approval(expired_conn, staff_id=staff["id"],
                                           approval_ref="perm-test-approval-torevoke",
                                           reason="kill test rehearsal")
    check(revoke_result["revoked_at"] is not None, "revoke_approval thanh cong (T3-05)")
    await expired_conn.close()

    try:
        await _set_capture(conn, enabled=True, staff_id=staff["id"], approval_ref="perm-test-approval-expired")
        check(False, "approval het han -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong hop le" in str(e), "approval het han -> RAISE dung")
    try:
        await _set_capture(conn, enabled=True, staff_id=staff["id"], approval_ref="perm-test-approval-torevoke")
        check(False, "approval da bi thu hoi -> phai RAISE (T3-05)")
    except asyncpg.PostgresError as e:
        check("khong hop le" in str(e), "approval da bi thu hoi -> RAISE dung (T3-05)")
    await conn.close()

    print("== T3-05: revoke_approval tu choi thu hoi lap / approval khong ton tai ==")
    conn2 = await asyncpg.connect(DB_URL)
    try:
        await _revoke_approval(conn2, staff_id=staff["id"], approval_ref="perm-test-approval-torevoke",
                               reason="thu hoi lan 2")
        check(False, "thu hoi lap -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("da bi thu hoi" in str(e), "thu hoi lap -> RAISE dung")
    try:
        await _revoke_approval(conn2, staff_id=staff["id"], approval_ref="khong-ton-tai-approval-xyz",
                               reason="test")
        check(False, "thu hoi approval khong ton tai -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong ton tai" in str(e), "thu hoi approval khong ton tai -> RAISE dung")
    await conn2.close()

    print("== T3-05: OFF khong doi hoi approval (chi can actor hop le + quyen operate) ==")
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
        "selected_count, algorithm_seed, locked_conversation_ids, purpose_code, status, "
        "collection_closed_at) VALUES (now()-interval '1 day', now(), 0, 0, 'perm-test-2', "
        "ARRAY[]::bigint[], 'P12_PII_DETECTOR_EVAL', 'collection_closed', now()) RETURNING batch_id"
    )
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        await conn.fetchval("SELECT * FROM m4_stage0p_fetch_message_content($1,1,1)", closed_batch["batch_id"])
        check(False, "batch status='collection_closed' -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("collecting" in str(e), "batch status='collection_closed' -> RAISE dung (T3-02)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T2-01: peek_next_candidate KHONG can control ON (khong lock/khong PII) ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        await conn.fetchrow(
            "SELECT * FROM m4_stage0p_peek_next_candidate($1)", closed_batch["batch_id"])
        check(False, "peek tren batch collection_closed van phai RAISE (validate batch, khong phai control)")
    except asyncpg.PostgresError as e:
        check("collecting" in str(e), "peek tu choi dung ly do (batch state, KHONG phai control)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== control OFF -> fetch_message_content tra 'control_off', KHONG raise, KHONG doc content (T1-01/T2-01) ==")
    off_conn = await asyncpg.connect(DB_URL)
    await _set_capture(off_conn, enabled=False, staff_id=staff["id"], approval_ref="perm-test-peek-off")
    await off_conn.close()
    fresh_batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, selected_count, "
        "algorithm_seed, locked_conversation_ids, purpose_code) VALUES (now()-interval '1 day', now(), "
        "0, 0, 'perm-test-2b', ARRAY[]::bigint[], 'P12_PII_DETECTOR_EVAL') RETURNING batch_id"
    )
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        off_result = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_fetch_message_content($1,1,1)", fresh_batch["batch_id"])
        check(off_result["status"] == "control_off", "control OFF -> status='control_off'")
        check(off_result["content"] is None, "control OFF -> content=NULL (khong doc plaintext)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== Audit fail-closed + T2-06 + T4-01: fetch_message_content/record_sample voi du lieu that ==")
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
    seed_conn = await asyncpg.connect(DB_URL)
    await seed_conn.execute("SET ROLE alpha3s_m4_sample_collector")
    await seed_conn.fetchrow("SELECT * FROM m4_stage0p_seed_capture_progress($1)", audit_batch["batch_id"])
    await seed_conn.execute("RESET ROLE")
    await seed_conn.close()

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

    print("== T4-01: record_sample GOI DOC LAP (khong qua fetch_message_content truoc) -> tu choi ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7)",
                            audit_batch["batch_id"], conv["id"], msg["id"], str(uuid.uuid4()),
                            b"\x00" * 30, 1, False)
        check(False, "record_sample doc lap (khong fetch truoc) -> phai RAISE (T4-01)")
    except asyncpg.PostgresError as e:
        check("khong co capability fetch hop le" in str(e), "record_sample doc lap -> RAISE dung (T4-01)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T4-01: fetch_message_content va record_sample o 2 TRANSACTION KHAC NHAU -> capability row sai txid ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    async with conn.transaction():
        fetched_cross = await conn.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                                            audit_batch["batch_id"], conv["id"], msg["id"])
        check(fetched_cross["status"] == "ok", "fetch_message_content thanh cong (transaction A)")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7)",
                            audit_batch["batch_id"], conv["id"], msg["id"], str(uuid.uuid4()),
                            b"\x00" * 30, 1, False)
        check(False, "record_sample o transaction KHAC voi fetch -> phai RAISE (T4-01)")
    except asyncpg.PostgresError as e:
        check("khong co capability fetch hop le" in str(e),
              "record_sample o transaction khac -> RAISE dung (T4-01, capability row txid khac nhau)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== fetch+record TRONG CUNG 1 transaction -> thanh cong (T4-01 pattern dung) ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    async with conn.transaction():
        fetched = await conn.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                                      audit_batch["batch_id"], conv["id"], msg["id"])
        check(fetched["status"] == "ok", "fetch_message_content thanh cong tren du lieu that")
        count_mid = await admin.fetchval(
            "SELECT captured_count FROM m4_selection_batches WHERE batch_id=$1", audit_batch["batch_id"])
        check(count_mid == 0, "T2-06: fetch content thanh cong nhung CHUA record_sample -> captured_count VAN la 0")
        rec = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7)",
            audit_batch["batch_id"], conv["id"], msg["id"], str(uuid.uuid4()), b"\x00" * 30, 1, False)
        check(rec["captured_count"] == 1,
              "T2-06/T4-01: record_sample (CUNG transaction voi fetch) -> captured_count tang DUNG 1")
    progress_after = await admin.fetchval(
        "SELECT status FROM m4_stage0p_capture_progress WHERE batch_id=$1 AND conversation_id=$2 AND message_id=$3",
        audit_batch["batch_id"], conv["id"], msg["id"])
    check(progress_after == "committed", "T4-03: candidate progress row -> 'committed' sau record_sample thanh cong")
    await conn.execute("RESET ROLE")
    await conn.close()

    off_conn2 = await asyncpg.connect(DB_URL)
    await _set_capture(off_conn2, enabled=False, staff_id=staff["id"], approval_ref="perm-test-audit-off")
    await off_conn2.close()

    print("== T4-03: mark_candidate_outcome — fence_timeout tang dan retryable_failed -> permanent_failed (3 lan) ==")
    cust3 = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('perm-t403','x') RETURNING id")
    conv3 = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", cust3["id"])
    msg3 = await admin.fetchrow(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer','tin nhan 403') RETURNING id",
        conv3["id"])
    batch3 = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, selected_count, "
        "algorithm_seed, locked_conversation_ids, purpose_code) VALUES (now()-interval '1 day', now(), "
        "1, 1, 'perm-test-403', ARRAY[$1]::bigint[], 'P12_PII_DETECTOR_EVAL') RETURNING batch_id", conv3["id"])
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    seed3 = await conn.fetchrow("SELECT * FROM m4_stage0p_seed_capture_progress($1)", batch3["batch_id"])
    check(seed3["candidate_count"] == 1, "seed_capture_progress vet dung 1 candidate")
    o1 = await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'fence_timeout',$4)",
                             batch3["batch_id"], conv3["id"], msg3["id"], "attempt-1")
    check(o1["new_status"] == "retryable_failed" and o1["attempt_count"] == 1,
          f"lan 1 fence_timeout -> retryable_failed, attempt_count=1 (thuc te {o1['new_status']},{o1['attempt_count']})")
    o2 = await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'fence_timeout',$4)",
                             batch3["batch_id"], conv3["id"], msg3["id"], "attempt-2")
    check(o2["new_status"] == "retryable_failed" and o2["attempt_count"] == 2,
          f"lan 2 fence_timeout -> retryable_failed, attempt_count=2 (thuc te {o2['new_status']},{o2['attempt_count']})")
    o3 = await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'fence_timeout',$4)",
                             batch3["batch_id"], conv3["id"], msg3["id"], "attempt-3")
    check(o3["new_status"] == "permanent_failed" and o3["attempt_count"] == 3,
          f"lan 3 fence_timeout -> permanent_failed (terminal), attempt_count=3 (thuc te {o3['new_status']},{o3['attempt_count']})")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'fence_timeout',$4)",
                            batch3["batch_id"], conv3["id"], msg3["id"], "attempt-4")
        check(False, "mark_candidate_outcome tren candidate DA terminal -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("da o trang thai terminal" in str(e), "mark_candidate_outcome tren candidate da terminal -> RAISE dung")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'invalid_outcome',$4)",
                            batch3["batch_id"], 999999, 999999, "x")
        check(False, "outcome khong hop le -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("outcome khong hop le" in str(e), "outcome khong hop le -> RAISE dung")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'fence_timeout',$4)",
                            batch3["batch_id"], 888888, 888888, "unseeded")
        check(False, "candidate chua duoc seed -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong duoc seed" in str(e), "candidate chua duoc seed -> RAISE dung")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T4-03: close_collection THANH CONG khi candidate duy nhat da permanent_failed (terminal) ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    close3 = await conn.fetchrow("SELECT * FROM m4_stage0p_close_collection($1)", batch3["batch_id"])
    check(close3["status"] == "collection_closed",
          "close_collection THANH CONG khi candidate duy nhat da permanent_failed (terminal) — 0 sample captured khop 0 row")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T4-03: close_collection TU CHOI khi con candidate pending/retryable_failed ==")
    cust4 = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('perm-t403b','x') RETURNING id")
    conv4 = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", cust4["id"])
    for i in range(2):
        await admin.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer',$2)",
            conv4["id"], f"tin {i}")
    batch4 = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, selected_count, "
        "algorithm_seed, locked_conversation_ids, purpose_code) VALUES (now()-interval '1 day', now(), "
        "1, 1, 'perm-test-403b', ARRAY[$1]::bigint[], 'P12_PII_DETECTOR_EVAL') RETURNING batch_id", conv4["id"])
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    seed4 = await conn.fetchrow("SELECT * FROM m4_stage0p_seed_capture_progress($1)", batch4["batch_id"])
    check(seed4["candidate_count"] == 2, "seed_capture_progress vet dung 2 candidate")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_close_collection($1)", batch4["batch_id"])
        check(False, "close_collection voi 2 candidate con 'pending' -> phai RAISE (T4-03)")
    except asyncpg.PostgresError as e:
        check("CHUA o trang thai terminal" in str(e), "close_collection voi candidate pending -> RAISE dung (T4-03)")
    await conn.execute("RESET ROLE")
    await conn.close()
    # danh dau ca 2 candidate excluded (terminal) qua mark_candidate_outcome — chuan bi cho close thanh cong.
    rows4 = await admin.fetch(
        "SELECT conversation_id, message_id FROM m4_stage0p_capture_progress WHERE batch_id=$1", batch4["batch_id"])
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    for r in rows4:
        await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'pending_deletion',$4)",
                            batch4["batch_id"], r["conversation_id"], r["message_id"], "test-exclude")
    close4 = await conn.fetchrow("SELECT * FROM m4_stage0p_close_collection($1)", batch4["batch_id"])
    check(close4["status"] == "collection_closed",
          "close_collection THANH CONG sau khi MOI candidate dat terminal (excluded) — T4-03")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T4-03: close_collection tu choi neu captured_count/row-thuc-te/progress-committed lech nhau ==")
    batch5 = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, selected_count, "
        "algorithm_seed, locked_conversation_ids, purpose_code, captured_count, status) VALUES "
        "(now()-interval '1 day', now(), 1, 1, 'perm-test-305', ARRAY[]::bigint[], 'P12_PII_DETECTOR_EVAL', "
        "5, 'collecting') RETURNING batch_id")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    await conn.fetchrow("SELECT * FROM m4_stage0p_seed_capture_progress($1)", batch5["batch_id"])
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_close_collection($1)", batch5["batch_id"])
        check(False, "close_collection voi captured_count lech so row that -> phai RAISE (T3-02)")
    except asyncpg.PostgresError as e:
        check("khong khop nhau" in str(e), "close_collection voi captured_count lech -> RAISE dung (T3-02)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T1-03: seal_labels tu choi neu con row unlabeled ==")
    seal_batch = await _make_collection_closed_batch(admin, seed="perm-test-seal",
                                                      samples=[(str(uuid.uuid4()), "998", 1)])
    conn = await asyncpg.connect(DB_URL)
    try:
        await _seal_labels(conn, staff_id=staff["id"], batch_id=seal_batch)
        check(False, "seal voi row unlabeled -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("unlabeled" in str(e), "seal voi row unlabeled -> RAISE dung")
    finally:
        await conn.close()
    seal_sample = await admin.fetchval(
        "SELECT sample_id FROM m4_shadow_review_samples WHERE selection_batch=$1", seal_batch)

    print("== T2-02: fetch_sealed_message tu choi tren batch CHUA sealed — 0 raw fetch ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_fetch_sealed_message($1,NULL)", seal_batch)
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
            seal_batch, "fake-hash", f'[{{"sample_id":"{seal_sample}","predicted_slots":[]}}]',
            '[]', "m4d-0.1.0", "perm-test-eval")
        check(False, "write_predictions tren batch chua sealed -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("labels_sealed" in str(e), "write_predictions tren batch chua sealed -> RAISE dung (T3-02)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T1-03: sau seal, sua labeled_slots/label_status bi TRIGGER chan (bat ke role nao) ==")
    await admin.execute(
        "UPDATE m4_shadow_review_samples SET label_status='labeled', labeled_slots='[]'::jsonb "
        "WHERE sample_id=$1", seal_sample)
    conn = await asyncpg.connect(DB_URL)
    sealed_hash = None
    try:
        sealed = await _seal_labels(conn, staff_id=staff["id"], batch_id=seal_batch)
        check(sealed["sample_count"] == 1, "seal_labels thanh cong khi tat ca da labeled")
        sealed_hash = sealed["sealed_hash"]
        check(bool(sealed_hash) and len(sealed_hash) == 64,
              "T2-04/T3-06: DB tu tinh labels_sealed_hash v2 (sha256 hex, 64 ky tu)")
    finally:
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
            seal_batch, "0" * 64, f'[{{"sample_id":"{seal_sample}","predicted_slots":[]}}]',
            '[]', "m4d-0.1.0", "perm-test-eval")
        check(False, "write_predictions voi hash sai -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong khop" in str(e), "write_predictions voi hash sai -> RAISE dung (chong forged/stale)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T4-02: exclusion normalization_version_mismatch — DB tu so sanh voi HANG SO HARDCODE ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
            seal_batch, sealed_hash, "[]",
            f'[{{"sample_id":"{seal_sample}","reason":"toi_thich_the"}}]',
            "m4d-0.1.0", "perm-test-eval")
        check(False, "exclusion reason ngoai allowlist -> phai RAISE (T3-03)")
    except asyncpg.PostgresError as e:
        check("allowlist" in str(e), "exclusion reason ngoai allowlist -> RAISE dung (T3-03)")
    try:
        # sample THAT SU dung normalization_version 'nfc-v1' — khop hang so hardcode trong ham ->
        # claim mismatch la SAI (T4-02: khong con tham so caller de gia mao "current version").
        await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
            seal_batch, sealed_hash, "[]",
            f'[{{"sample_id":"{seal_sample}","reason":"normalization_version_mismatch"}}]',
            "m4d-0.1.0", "perm-test-eval")
        check(False, "exclusion normalization_version_mismatch SAI (row thuc khop hardcode) -> phai RAISE (T4-02)")
    except asyncpg.PostgresError as e:
        check("SAI cho sample" in str(e), "exclusion false-claim mismatch -> RAISE dung (T4-02, DB tu xac minh voi hang so hardcode)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T2-03: write_predictions adversarial JSON (schema/enum/bounds/overlap/coverage) — batch lon (T4-05: >=200 conv) ==")
    adversarial_batch, adv_sample_ids = await _make_large_batch(admin, seed="perm-test-adv", n=200)
    adv_sample = adv_sample_ids[0]
    conn = await asyncpg.connect(DB_URL)
    adv_seal = await _seal_labels(conn, staff_id=staff["id"], batch_id=adversarial_batch)
    await conn.close()
    adv_hash = adv_seal["sealed_hash"]

    async def _adv(predictions_json, exclusions_json, label):
        conn = await asyncpg.connect(DB_URL)
        await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
        try:
            await conn.fetchrow(
                "SELECT * FROM m4_stage0p_write_predictions($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
                adversarial_batch, adv_hash, predictions_json, exclusions_json,
                "m4d-0.1.0", "perm-test-adv")
            check(False, f"{label} -> phai RAISE")
        except asyncpg.PostgresError:
            check(True, f"{label} -> RAISE dung")
        finally:
            await conn.execute("RESET ROLE")
            await conn.close()

    await _adv(_json.dumps(
        [{"sample_id": adv_sample, "predicted_slots": [], "extra_key": 1}]
        + [{"sample_id": sid, "predicted_slots": []} for sid in adv_sample_ids[1:]]),
              "[]", "prediction voi key thua")
    await _adv(_json.dumps(
        [{"sample_id": adv_sample,
          "predicted_slots": [{"slot_type": "not_a_real_type", "start": 0, "end": 5,
                               "confidence": "high", "reason": "x"}]}]
        + [{"sample_id": sid, "predicted_slots": []} for sid in adv_sample_ids[1:]]), "[]",
              "slot_type khong hop le")
    await _adv(_json.dumps(
        [{"sample_id": adv_sample,
          "predicted_slots": [{"slot_type": "phone", "start": 0, "end": 5,
                               "confidence": "super-high", "reason": "x"}]}]
        + [{"sample_id": sid, "predicted_slots": []} for sid in adv_sample_ids[1:]]), "[]",
              "confidence khong hop le")
    await _adv(_json.dumps(
        [{"sample_id": adv_sample,
          "predicted_slots": [{"slot_type": "phone", "start": 5, "end": 3,
                               "confidence": "high", "reason": "x"}]}]
        + [{"sample_id": sid, "predicted_slots": []} for sid in adv_sample_ids[1:]]), "[]",
              "start >= end (offset sai)")
    await _adv(_json.dumps(
        [{"sample_id": adv_sample,
          "predicted_slots": [{"slot_type": "phone", "start": 0, "end": 100,
                               "confidence": "high", "reason": "x"}]}]
        + [{"sample_id": sid, "predicted_slots": []} for sid in adv_sample_ids[1:]]), "[]",
              "end > canonical_text_len (ngoai bounds)")
    await _adv(_json.dumps(
        [{"sample_id": adv_sample,
          "predicted_slots": [
              {"slot_type": "phone", "start": 0, "end": 5, "confidence": "high", "reason": "a"},
              {"slot_type": "name", "start": 3, "end": 8, "confidence": "high", "reason": "b"},
          ]}]
        + [{"sample_id": sid, "predicted_slots": []} for sid in adv_sample_ids[1:]]), "[]",
              "2 span chong lan trong cung sample")
    await _adv(_json.dumps(
        [{"sample_id": adv_sample, "predicted_slots": []}, {"sample_id": adv_sample, "predicted_slots": []}]
        + [{"sample_id": sid, "predicted_slots": []} for sid in adv_sample_ids[1:]]), "[]",
              "sample_id lap trong predictions")
    await _adv(_json.dumps(
        [{"sample_id": str(uuid.uuid4()), "predicted_slots": []}]
        + [{"sample_id": sid, "predicted_slots": []} for sid in adv_sample_ids[1:]]), "[]",
              "sample_id khong thuoc batch (foreign)")
    await _adv("[]", "[]", "predictions+exclusions rong — khong phu du corpus (thieu coverage)")
    await _adv(_json.dumps([{"sample_id": adv_sample, "predicted_slots": []}]
                          + [{"sample_id": sid, "predicted_slots": []} for sid in adv_sample_ids[1:]]),
              _json.dumps([{"sample_id": adv_sample, "reason": "normalization_version_mismatch"}]),
              "1 sample vua predict vua exclude")

    print("== T2-03: write_predictions THANH CONG voi payload hop le + phu dung coverage (200 conv) ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        good_predictions = _json.dumps(
            [{"sample_id": adv_sample,
              "predicted_slots": [{"slot_type": "phone", "start": 0, "end": 5,
                                   "confidence": "high", "reason": "ok"}]}]
            + [{"sample_id": sid, "predicted_slots": []} for sid in adv_sample_ids[1:]])
        good = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
            adversarial_batch, adv_hash, good_predictions, "[]", "m4d-0.1.0", "perm-test-adv")
        check(good["updated_count"] == 200, "payload hop le -> write_predictions thanh cong (200 updated)")
        result_hash_1 = good["result_hash"]
        check(bool(result_hash_1) and len(result_hash_1) == 64, "T2-04/T3-06: DB tu tinh result_hash v2")
        check(good["gate_version"] == "ca-review-4-proposed-v1",
              f"T4-05: gate_version tra ve dung de xuat CA Review #4 (thuc te {good['gate_version']})")
        check(good["non_excluded_conversation_count"] == 200,
              f"T4-05: non_excluded_conversation_count dung 200 (thuc te {good['non_excluded_conversation_count']})")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T2-03: write_predictions bat bien — goi lai (rerun) tren batch DA ghi -> RAISE ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
            adversarial_batch, adv_hash,
            _json.dumps([{"sample_id": adv_sample, "predicted_slots": []}]), "[]",
            "m4d-0.1.0", "perm-test-adv-2")
        check(False, "rerun tren batch da ghi prediction -> phai RAISE (bat bien)")
    except asyncpg.PostgresError as e:
        check("predictions_written" in str(e), "rerun tren batch da ghi prediction -> RAISE dung (T3-02)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T2-04/T4-04: complete_evaluation tu choi neu expected_result_hash SAI ==")
    conn = await asyncpg.connect(DB_URL)
    try:
        await _complete_evaluation(conn, staff_id=staff["id"], batch_id=adversarial_batch,
                                   expected_result_hash="0" * 64)
        check(False, "complete_evaluation voi result_hash sai -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong khop" in str(e), "complete_evaluation voi result_hash sai -> RAISE dung")
    finally:
        await conn.close()

    print("== T3-04: complete_evaluation THANH CONG voi result_hash dung -> DB TU TINH metrics + report_hash ==")
    conn = await asyncpg.connect(DB_URL)
    try:
        completed = await _complete_evaluation(conn, staff_id=staff["id"], batch_id=adversarial_batch,
                                                expected_result_hash=result_hash_1)
        check(completed["completed_at"] is not None, "complete_evaluation thanh cong")
        check(bool(completed["report_hash"]) and len(completed["report_hash"]) == 64,
              "T2-04: DB tu tinh evaluation_report_hash")
        metrics = completed["metrics"]
        if isinstance(metrics, str):
            metrics = _json.loads(metrics)
        check(metrics.get("phone") == {"tp": 0, "fn": 0, "fp": 1, "recall": None, "precision": 0.0},
              f"T3-04: DB TU TINH metrics dung tu exact-span (khong nhan tu caller) — thuc te: {metrics}")
    finally:
        await conn.close()

    print("== T4-05: batch DUOI 200 conversation khong bi loai -> INSUFFICIENT_DATA ==")
    small_batch, small_ids = await _make_large_batch(admin, seed="perm-t405-small", n=50)
    conn = await asyncpg.connect(DB_URL)
    small_seal = await _seal_labels(conn, staff_id=staff["id"], batch_id=small_batch)
    await conn.close()
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
            small_batch, small_seal["sealed_hash"],
            _json.dumps([{"sample_id": sid, "predicted_slots": []} for sid in small_ids]),
            "[]", "m4d-0.1.0", "perm-t405-small")
        check(False, "batch 50 conversation (< nguong toi thieu 200) -> phai RAISE (T4-05)")
    except asyncpg.PostgresError as e:
        check("INSUFFICIENT_DATA" in str(e) and "toi thieu" in str(e),
              "batch duoi nguong 200 conversation -> RAISE dung (T4-05)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T4-05: ty le exclusion vuot 10% (nhung van >=200 non-excluded) -> INSUFFICIENT_DATA ==")
    excl_batch, excl_ids = await _make_large_batch(admin, seed="perm-t405-excl", n=250)
    # 250 total, loai 30 (12%, vuot 10%) — con lai 220 non-excluded (>=200, khong cham nguong kia).
    excl_targets = excl_ids[:30]
    await admin.execute(
        "UPDATE m4_shadow_review_samples SET normalization_version='nfc-v0-cu' WHERE sample_id = ANY($1::uuid[])",
        excl_targets)
    conn = await asyncpg.connect(DB_URL)
    excl_seal = await _seal_labels(conn, staff_id=staff["id"], batch_id=excl_batch)
    await conn.close()
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        preds = _json.dumps([{"sample_id": sid, "predicted_slots": []} for sid in excl_ids if sid not in excl_targets])
        excls = _json.dumps([{"sample_id": sid, "reason": "normalization_version_mismatch"} for sid in excl_targets])
        await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
            excl_batch, excl_seal["sealed_hash"], preds, excls, "m4d-0.1.0", "perm-t405-excl")
        check(False, "ty le exclusion 30/250=12% (>10%) -> phai RAISE (T4-05)")
    except asyncpg.PostgresError as e:
        check("INSUFFICIENT_DATA" in str(e) and "vuot nguong" in str(e),
              "ty le exclusion vuot 10% -> RAISE dung (T4-05)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T1-06: complete_evaluation tu choi neu con sample chua predicted/excluded ==")
    empty_seal_batch = await _make_collection_closed_batch(admin, seed="perm-test-eval2",
                                                            samples=[(str(uuid.uuid4()), "997", 1)])
    unpred_sample = await admin.fetchval(
        "SELECT sample_id FROM m4_shadow_review_samples WHERE selection_batch=$1", empty_seal_batch)
    await admin.execute(
        "UPDATE m4_shadow_review_samples SET label_status='labeled', labeled_slots='[]'::jsonb WHERE sample_id=$1",
        unpred_sample)
    conn = await asyncpg.connect(DB_URL)
    await _seal_labels(conn, staff_id=staff["id"], batch_id=empty_seal_batch)
    await conn.close()
    conn = await asyncpg.connect(DB_URL)
    try:
        await _complete_evaluation(conn, staff_id=staff["id"], batch_id=empty_seal_batch,
                                   expected_result_hash="0" * 64)
        check(False, "complete_evaluation voi batch chua ghi prediction -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("predictions_written" in str(e), "complete_evaluation voi batch chua ghi prediction -> RAISE dung (T3-02)")
    finally:
        await conn.close()

    print("== Xac nhan control da ve OFF (bat buoc truoc khi ket thuc script) ==")
    final_state = await admin.fetchval("SELECT capture_enabled FROM m4_stage0p_control WHERE id=1")
    check(final_state is False, "control ve OFF truoc khi script ket thuc (khong de lai flag ON)")

    await admin.execute("DELETE FROM m4_shadow_review_samples")
    await admin.execute("DELETE FROM m4_stage0p_capture_progress")
    await admin.execute("DELETE FROM m4_selection_batches")
    await admin.execute("DELETE FROM audit_log")
    await admin.execute("DELETE FROM messages")
    await admin.execute("DELETE FROM conversations")
    await admin.execute("DELETE FROM customers WHERE psid LIKE 'perm-%'")
    await admin.execute("DELETE FROM m4_stage0p_capture_approval_revocations WHERE approval_ref LIKE 'perm-test-%'")
    await admin.execute("DELETE FROM m4_stage0p_capture_approvals WHERE approval_ref LIKE 'perm-test-%'")
    await admin.execute("DELETE FROM m4_stage0p_staff_permissions WHERE staff_id IN ($1,$2)",
                        staff["id"], staff_no_perm["id"])
    await admin.execute("DELETE FROM staff_users WHERE id IN ($1,$2)", staff["id"], staff_no_perm["id"])
    await admin.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
