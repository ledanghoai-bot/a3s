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
import hashlib
import hmac as _hmac
import json as _json
import os
import sys
import unicodedata
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402

from app.services.pii.crypto import TRANSCRIPT_KEY_VERSION  # noqa: E402

MAX_CHARS = 2000
MAX_BYTES = 8000
# REV10 T8-02: khoa HMAC RIENG cua chinh script nay (provision truc tiep vao
# m4_stage0p_transcript_signing_keys qua admin - xem main()) - cho phep tung kich ban adversarial
# tu xay 1 transcript hop le voi CHINH XAC cac gia tri (ke ca gia tri SAI dang test) ma khong can
# di qua app/services/pii/crypto.py:sign_capture() (ham do luon tu encrypt, khong cho phep truyen
# ciphertext gia lap tuy y nhu nhieu kich ban duoi day can).
TRANSCRIPT_HMAC_KEY = os.urandom(32)


def _canonical_digest(raw_content: str) -> bytes:
    """T6-02: replicate CHINH XAC thu tu Python _truncate(nfc(...)) (stage0p_sampling.py) tren
    `left(raw_content, 2000)` (gia tri fetch_message_content tra ve) de tinh digest DUNG nhu DB —
    dung cho cac kich ban goi record_sample TRUC TIEP (khong qua run_collector) trong file nay."""
    received = raw_content[:MAX_CHARS]
    text = unicodedata.normalize("NFC", received)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_BYTES:
        text = encoded[:MAX_BYTES].decode("utf-8", errors="ignore")
    return hashlib.sha256(text.encode("utf-8")).digest()


def _sample_aad(customer_ref: str, conversation_ref: str, sample_id: str) -> bytes:
    """REV10 T8-02: replicate CHINH XAC app/services/pii/crypto.py:_sample_aad() (domain-tag +
    length-prefix) — dung de tinh aad_digest cho transcript test tu xay."""
    parts = (customer_ref.encode("utf-8"), conversation_ref.encode("utf-8"), sample_id.encode("utf-8"))
    out = [b"a3s-m4-shadow-sample-aad-v1"]
    for p in parts:
        out.append(len(p).to_bytes(4, "big"))
        out.append(p)
    return b"".join(out)


def _sign_test_transcript(*, batch_id, conversation_id, message_id, sample_id, txid,
                          canonical_digest: bytes, canonical_len: int, truncated: bool,
                          ciphertext: bytes, customer_ref: str, conversation_ref: str,
                          purpose_code: str = "P12_PII_DETECTOR_EVAL",
                          key_version: str = TRANSCRIPT_KEY_VERSION,
                          aead_algorithm: str = "AES-256-GCM", ttl_seconds: int = 60,
                          issued_at=None, hmac_key: bytes = TRANSCRIPT_HMAC_KEY,
                          aad_digest: bytes | None = None) -> tuple[bytes, bytes]:
    """REV10 T8-02: xay + ky 1 transcript THAT (cung thuat toan canonical JSON + HMAC-SHA256 voi
    app/services/pii/crypto.py:sign_capture()), nhung nhan TRUC TIEP ciphertext/canonical_len/
    truncated tu caller thay vi tu encrypt — cho phep moi kich ban adversarial trong file nay xay
    1 transcript NOI BO NHAT QUAN voi cac tham so (ke ca gia tri SAI) no dang truyen cho
    record_sample, de kiem tra dung logic downstream (T4-01/T5-02/T6-02) thay vi bi chan som boi
    chinh lop xac minh transcript (T8-02). Tra ve (transcript_bytes, signature)."""
    now = issued_at or datetime.datetime.now(datetime.timezone.utc)
    if aad_digest is None:
        aad_digest = hashlib.sha256(_sample_aad(customer_ref, conversation_ref, sample_id)).digest()
    fields = {
        "v": 1,
        "batch_id": str(batch_id),
        "conversation_id": conversation_id,
        "message_id": message_id,
        "sample_id": sample_id,
        "txid": txid,
        "canonical_digest": canonical_digest.hex(),
        "canonical_len": canonical_len,
        "truncated": truncated,
        "ciphertext_digest": hashlib.sha256(ciphertext).hexdigest(),
        "aead_algorithm": aead_algorithm,
        "key_version": key_version,
        "aad_digest": aad_digest.hex(),
        "purpose_code": purpose_code,
        "issued_at": now.isoformat(),
        "expires_at": (now + datetime.timedelta(seconds=ttl_seconds)).isoformat(),
    }
    transcript_bytes = _json.dumps(fields, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=True).encode("utf-8")
    signature = _hmac.new(hmac_key, transcript_bytes, hashlib.sha256).digest()
    return transcript_bytes, signature


async def _record_sample_signed(conn, *, batch_id, conversation_id, message_id, sample_id,
                                ciphertext: bytes, canonical_len: int, truncated: bool,
                                canonical_digest: bytes, customer_ref: str, conversation_ref: str,
                                **sign_overrides):
    """REV10 T8-02: wrapper tien ich - tu doc txid_current() (PHAI CUNG transaction voi
    fetch_message_content da goi truoc do), xay+ky transcript NHAT QUAN voi cac tham so truyen
    vao (ke ca gia tri SAI qua sign_overrides), roi goi m4_stage0p_record_sample voi du 11 tham
    so. Tra ve row ket qua (hoac nem asyncpg.PostgresError nhu binh thuong)."""
    txid = await conn.fetchval("SELECT txid_current()")
    transcript_bytes, signature = _sign_test_transcript(
        batch_id=batch_id, conversation_id=conversation_id, message_id=message_id,
        sample_id=sample_id, txid=txid, canonical_digest=canonical_digest,
        canonical_len=canonical_len, truncated=truncated, ciphertext=ciphertext,
        customer_ref=customer_ref, conversation_ref=conversation_ref, **sign_overrides)
    key_version = sign_overrides.get("key_version", TRANSCRIPT_KEY_VERSION)
    return await conn.fetchrow(
        "SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
        batch_id, conversation_id, message_id, sample_id, ciphertext, canonical_len, truncated,
        canonical_digest, transcript_bytes, signature, key_version)

DB_URL = (os.environ.get("DATABASE_URL")
          or "postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s").replace("+asyncpg", "")

_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


async def _try(conn, sql: str, *args) -> bool:
    """True neu cau lenh THANH CONG (khong loi quyen). Rollback ngay sau (savepoint).

    Thieu USAGE tren schema public (vd alpha3s_vendor_path, PUBLIC) khien object khong the
    RESOLVE duoc — Postgres bao UndefinedTable/UndefinedFunction thay vi InsufficientPrivilege,
    nhung ve mat bao mat day van la 1 dang DENY (con manh hon: khong thay object ton tai)."""
    try:
        async with conn.transaction():
            await conn.execute(sql, *args)
            raise _RollbackSentinel
    except _RollbackSentinel:
        return True
    except (asyncpg.InsufficientPrivilegeError, asyncpg.UndefinedTableError,
            asyncpg.UndefinedFunctionError):
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
    ("m4_stage0p_record_sample", "uuid,bigint,bigint,uuid,bytea,int,boolean,bytea,bytea,bytea,text", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_close_collection", "uuid", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_seed_capture_progress", "uuid", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_mark_candidate_outcome", "uuid,bigint,bigint,text,text", "alpha3s_m4_sample_collector"),
    ("m4_stage0p_pin_actor", "bigint,text", "alpha3s_m4_actor_binder"),
    ("m4_stage0p_require_pinned_actor", "text", None),
    ("m4_stage0p_set_capture", "boolean,text", "alpha3s_m4_control_plane"),
    ("m4_stage0p_record_approval", "text,boolean,timestamptz,timestamptz,text", "alpha3s_m4_approval_recorder"),
    ("m4_stage0p_revoke_approval", "text,text", "alpha3s_m4_approval_recorder"),
    ("m4_stage0p_seal_labels", "uuid", "alpha3s_m4_sample_reviewer_api"),
    ("m4_stage0p_fetch_sealed_message", "uuid,uuid", "alpha3s_m4_prediction_writer"),
    ("m4_stage0p_write_predictions", "uuid,text,jsonb,jsonb,text,text", "alpha3s_m4_prediction_writer"),
    ("m4_stage0p_complete_evaluation", "uuid,text", "alpha3s_m4_sample_evaluator"),
    ("m4_stage0p_unpin_actor", "", "alpha3s_m4_actor_binder"),
    ("m4_stage0p_set_current_normalization_version", "text,text", "alpha3s_m4_approval_recorder"),
    ("m4_stage0p_record_normalization_approval", "text,text,timestamptz,timestamptz,text", "alpha3s_m4_approval_recorder"),
    ("m4_stage0p_revoke_normalization_approval", "text,text", "alpha3s_m4_approval_recorder"),
]

PERMISSIONS = ["m4.stage0p.approve", "m4.stage0p.operate", "m4.stage0p.review", "m4.stage0p.evaluate"]
PIN_SECRET = "perm-test-pin-secret"


async def _provision_pin_secret(admin, *, staff_id, pin_secret=PIN_SECRET, provisioned_by=None):
    """T5-01/T6-01: cap pin_secret NGOAI LUONG (khong qua pin_actor) — mo phong buoc provisioning
    thuoc quyet dinh van hanh. pin_secret_hash dung pgcrypto crypt()/gen_salt('bf') — KHONG con
    luu plaintext (T6-01)."""
    await admin.execute(
        "INSERT INTO m4_stage0p_actor_credentials (staff_id, pin_secret_hash, provisioned_by) "
        "VALUES ($1, crypt($2, gen_salt('bf')), $3) "
        "ON CONFLICT (staff_id) DO UPDATE SET pin_secret_hash=crypt($2, gen_salt('bf')), "
        "failed_attempts=0, locked_until=NULL",
        staff_id, pin_secret, provisioned_by or staff_id)


async def _pin(conn, staff_id: int, pin_secret: str = PIN_SECRET) -> None:
    """T5-01: pin actor vao session (role alpha3s_m4_actor_binder), roi RESET ROLE — khoa boi
    pg_backend_pid() cua CHINH connection nay, sinh ton qua lan SET ROLE tiep theo cua caller."""
    await conn.execute("SET ROLE alpha3s_m4_actor_binder")
    await conn.fetchrow("SELECT * FROM m4_stage0p_pin_actor($1,$2)", staff_id, pin_secret)
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


async def _record_normalization_approval(conn, *, staff_id, approval_ref, requested_version,
                                          valid_from, valid_until, note=None):
    await _pin(conn, staff_id)
    await conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    try:
        return await conn.fetchrow(
            "SELECT * FROM m4_stage0p_record_normalization_approval($1,$2,$3,$4,$5)",
            approval_ref, requested_version, valid_from, valid_until, note)
    finally:
        await conn.execute("RESET ROLE")


async def _revoke_normalization_approval(conn, *, staff_id, approval_ref, reason):
    await _pin(conn, staff_id)
    await conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    try:
        return await conn.fetchrow(
            "SELECT * FROM m4_stage0p_revoke_normalization_approval($1,$2)", approval_ref, reason)
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
        "algorithm_seed, locked_conversation_ids, purpose_code, normalization_version, status, captured_count, collection_closed_at) "
        "VALUES (now()-interval '1 day', now(), $1, $1, $2, ARRAY[]::bigint[], 'P12_PII_DETECTOR_EVAL', 'nfc-v1', "
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
        "algorithm_seed, locked_conversation_ids, purpose_code, normalization_version, status, captured_count, collection_closed_at) "
        "VALUES (now()-interval '1 day', now(), $1, $1, $2, ARRAY[]::bigint[], 'P12_PII_DETECTOR_EVAL', 'nfc-v1', "
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
    # REV10 T8-02: provision khoa HMAC transcript (xem TRANSCRIPT_HMAC_KEY o dau file) vao bang
    # SELECT-chi-cho-definer, cho record_sample verify duoc chu ky cac transcript test tu ky.
    await admin.execute(
        "INSERT INTO m4_stage0p_transcript_signing_keys (key_version, hmac_key) VALUES ($1, $2) "
        "ON CONFLICT (key_version) DO UPDATE SET hmac_key = EXCLUDED.hmac_key, retired_at = NULL",
        TRANSCRIPT_KEY_VERSION, TRANSCRIPT_HMAC_KEY)

    staff = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ('m4-perm-test-staff', 'x', 'x', true) RETURNING id"
    )
    for perm in PERMISSIONS:
        await _grant_permission(admin, staff_id=staff["id"], permission=perm, granted_by=staff["id"])
    await _provision_pin_secret(admin, staff_id=staff["id"])

    batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, "
        "selected_count, algorithm_seed, locked_conversation_ids, purpose_code, normalization_version) "
        "VALUES (now()-interval '1 day', now(), 0, 0, 'perm-test', ARRAY[]::bigint[], "
        "'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id"
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
        ("alpha3s_m4_actor_binder", "actor_credentials", "SELECT (phai DENY — T5-01)",
         "SELECT * FROM m4_stage0p_actor_credentials", False),
        ("alpha3s_m4_actor_binder", "actor_session", "SELECT (phai DENY — T5-01)",
         "SELECT * FROM m4_stage0p_actor_session", False),
        ("alpha3s_m4_actor_binder", "actor_session", "INSERT (direct, phai DENY — T5-01, khong tu forge duoc)",
         "INSERT INTO m4_stage0p_actor_session (backend_pid,staff_id) VALUES (pg_backend_pid(),1)", False),
        ("alpha3s_m4_sample_collector", "actor_session", "SELECT (phai DENY — T5-01)",
         "SELECT * FROM m4_stage0p_actor_session", False),
        ("alpha3s_m4_control_plane", "actor_credentials", "SELECT (phai DENY — T5-01)",
         "SELECT * FROM m4_stage0p_actor_credentials", False),
        ("alpha3s_m4_prediction_writer", "normalization_registry", "UPDATE (phai DENY — T5-04)",
         "UPDATE m4_stage0p_normalization_registry SET is_current=false", False),
        ("public", "actor_credentials", "SELECT", "SELECT * FROM m4_stage0p_actor_credentials", False),
        ("public", "actor_session", "SELECT", "SELECT * FROM m4_stage0p_actor_session", False),
        ("public", "normalization_registry", "SELECT", "SELECT * FROM m4_stage0p_normalization_registry", False),

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
        ("alpha3s_vendor_path", "normalization_approvals", "SELECT",
         "SELECT * FROM m4_stage0p_normalization_approvals", False),
        ("alpha3s_vendor_path", "normalization_approval_revocations", "SELECT",
         "SELECT * FROM m4_stage0p_normalization_approval_revocations", False),
        ("alpha3s_vendor_path", "transcript_signing_keys", "SELECT",
         "SELECT * FROM m4_stage0p_transcript_signing_keys", False),
        ("alpha3s_m4_sample_collector", "transcript_signing_keys", "SELECT",
         "SELECT * FROM m4_stage0p_transcript_signing_keys", False),

        ("public", "samples", "SELECT", "SELECT * FROM m4_shadow_review_samples", False),
        ("public", "control", "SELECT", "SELECT * FROM m4_stage0p_control", False),
        ("public", "batches", "SELECT", "SELECT * FROM m4_selection_batches", False),
        ("public", "approvals", "SELECT", "SELECT * FROM m4_stage0p_capture_approvals", False),
        ("public", "revocations", "SELECT", "SELECT * FROM m4_stage0p_capture_approval_revocations", False),
        ("public", "fetch_capability", "SELECT", "SELECT * FROM m4_stage0p_fetch_capability", False),
        ("public", "capture_progress", "SELECT", "SELECT * FROM m4_stage0p_capture_progress", False),
        ("public", "staff_permissions", "SELECT", "SELECT * FROM m4_stage0p_staff_permissions", False),
        ("public", "exclusion_gate", "SELECT", "SELECT * FROM m4_stage0p_exclusion_gate", False),
        ("public", "normalization_approvals", "SELECT",
         "SELECT * FROM m4_stage0p_normalization_approvals", False),
        ("public", "normalization_approval_revocations", "SELECT",
         "SELECT * FROM m4_stage0p_normalization_approval_revocations", False),
        ("public", "transcript_signing_keys", "SELECT",
         "SELECT * FROM m4_stage0p_transcript_signing_keys", False),
    ]

    table_name_map = {
        "samples": "m4_shadow_review_samples", "control": "m4_stage0p_control",
        "batches": "m4_selection_batches", "approvals": "m4_stage0p_capture_approvals",
        "revocations": "m4_stage0p_capture_approval_revocations",
        "fetch_capability": "m4_stage0p_fetch_capability",
        "capture_progress": "m4_stage0p_capture_progress",
        "staff_permissions": "m4_stage0p_staff_permissions",
        "exclusion_gate": "m4_stage0p_exclusion_gate",
        "actor_credentials": "m4_stage0p_actor_credentials",
        "actor_session": "m4_stage0p_actor_session",
        "normalization_registry": "m4_stage0p_normalization_registry",
        "normalization_approvals": "m4_stage0p_normalization_approvals",
        "normalization_approval_revocations": "m4_stage0p_normalization_approval_revocations",
        "transcript_signing_keys": "m4_stage0p_transcript_signing_keys",
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

    print("== Ma tran EXECUTE tren 19 ham SECURITY DEFINER (REV9 T8-03) ==")
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

    print("== SECURITY DEFINER hardening (19 ham nghiep vu + trigger REV9 T8-03) ==")
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

    print("== T5-01: pin_actor tu choi staff khong ton tai/khong active ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_actor_binder")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_pin_actor($1,$2)", 999999999, PIN_SECRET)
        check(False, "pin_actor staff khong ton tai -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong ton tai" in str(e), "pin_actor staff khong ton tai -> RAISE dung")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T5-01: pin_actor tu choi pin_secret sai/khong ton tai (binder KHONG the tu chon tuy y staff) ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_actor_binder")
    # T6-01: pin_secret sai KHONG con RAISE (xem docstring migration — PL/pgSQL khong co autonomous
    # transaction, RAISE se lam mat UPDATE failed_attempts) — DB tra ve pinned_staff_id=NULL.
    wrong_row = await conn.fetchrow("SELECT * FROM m4_stage0p_pin_actor($1,$2)", staff["id"], "sai-secret-hoan-toan")
    check(wrong_row["pinned_staff_id"] is None, "pin_actor voi pin_secret sai -> pinned_staff_id=NULL (T5-01/T6-01)")
    # don sach ngay de khong anh huong failed_attempts cua staff["id"] cho cac test rate-limit rieng ve sau.
    await admin.execute(
        "UPDATE m4_stage0p_actor_credentials SET failed_attempts=0, locked_until=NULL WHERE staff_id=$1",
        staff["id"])
    staff_no_secret = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ('m4-perm-test-nosecret', 'x', 'x', true) RETURNING id")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_pin_actor($1,$2)", staff_no_secret["id"], PIN_SECRET)
        check(False, "pin_actor cho staff CHUA duoc provision pin_secret -> phai RAISE (T5-01, binder khong the tu chon tuy y)")
    except asyncpg.PostgresError as e:
        check("chua duoc provisioning" in str(e), "pin_actor cho staff chua provision -> RAISE dung (T5-01/T6-01)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()
    await admin.execute("DELETE FROM staff_users WHERE id=$1", staff_no_secret["id"])

    print("== T5-01: goi ham nghiep vu MA CHUA pin_actor -> tu choi ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", False, None)
        check(False, "set_capture chua pin actor -> phai RAISE (T5-01)")
    except asyncpg.PostgresError as e:
        check("chua pin actor" in str(e), "set_capture chua pin actor -> RAISE dung (T5-01)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T5-01: caller TU set_config GUC cu (REV5) -> KHONG con hieu luc gi ca ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SELECT set_config('alpha3s.m4_actor_staff_id', $1, false)", str(staff["id"]))
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", False, None)
        check(False, "tu set_config GUC cu (khong qua pin_actor that) -> phai RAISE (T5-01, GUC khong con duoc doc)")
    except asyncpg.PostgresError as e:
        check("chua pin actor" in str(e),
              "tu set_config GUC cu -> van bi tu choi dung 'chua pin actor' (T5-01, xac nhan GUC forgery REV5 da dong)")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()

    print("== T4-04: actor da pin nhung KHONG co quyen cu the -> tu choi ==")
    staff_no_perm = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ('m4-perm-test-noperm', 'x', 'x', true) RETURNING id")
    await _provision_pin_secret(admin, staff_id=staff_no_perm["id"])
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

    print("== T5-01: pin sinh ton qua SET ROLE (khoa boi pg_backend_pid, khong phai GUC) ==")
    conn = await asyncpg.connect(DB_URL)
    await _pin(conn, staff["id"])
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    conn_pid = await conn.fetchval("SELECT pg_backend_pid()")
    # bang actor_session KHONG GRANT cho role nao (T5-01) — doc qua admin (superuser) de kiem tra
    # tu BEN NGOAI, dung dung backend_pid cua `conn`.
    own_pid_check = await admin.fetchval(
        "SELECT staff_id FROM m4_stage0p_actor_session WHERE backend_pid = $1", conn_pid)
    check(own_pid_check == staff["id"], "actor da pin VAN doc duoc SAU khi SET ROLE (khoa boi pg_backend_pid dung)")
    await conn.execute("RESET ROLE")

    print("== T5-01: connection KHAC (backend_pid khac) KHONG thay pin cua connection nay ==")
    conn2 = await asyncpg.connect(DB_URL)
    await conn2.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        await conn2.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", False, None)
        check(False, "connection MOI (chua pin) -> phai RAISE (T5-01, pin khong roi ra ngoai session)")
    except asyncpg.PostgresError as e:
        check("chua pin actor" in str(e), "connection moi chua pin -> RAISE dung (T5-01)")
    finally:
        await conn2.execute("RESET ROLE")
        await conn2.close()
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
        "selected_count, algorithm_seed, locked_conversation_ids, purpose_code, normalization_version, status, "
        "collection_closed_at) VALUES (now()-interval '1 day', now(), 0, 0, 'perm-test-2', "
        "ARRAY[]::bigint[], 'P12_PII_DETECTOR_EVAL', 'nfc-v1', 'collection_closed', now()) RETURNING batch_id"
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
        "algorithm_seed, locked_conversation_ids, purpose_code, normalization_version) VALUES (now()-interval '1 day', now(), "
        "0, 0, 'perm-test-2b', ARRAY[]::bigint[], 'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id"
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
        "selected_count, algorithm_seed, locked_conversation_ids, purpose_code, normalization_version) "
        "VALUES (now()-interval '1 day', now(), 1, 1, 'perm-test-audit', ARRAY[$1]::bigint[], "
        "'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id", conv["id"]
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
        # REV10 T8-02: boc trong 1 transaction tuong minh de txid transcript khop txid_current()
        # THAT SU dung luc record_sample chay (khac di, T8-02 se RAISE truoc khi cham toi T4-01).
        async with conn.transaction():
            await _record_sample_signed(
                conn, batch_id=audit_batch["batch_id"], conversation_id=conv["id"],
                message_id=msg["id"], sample_id=str(uuid.uuid4()), ciphertext=b"\x00" * 30,
                canonical_len=1, truncated=False, canonical_digest=hashlib.sha256(b"dummy").digest(),
                customer_ref=str(cust["id"]), conversation_ref=str(conv["id"]))
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
        async with conn.transaction():
            await _record_sample_signed(
                conn, batch_id=audit_batch["batch_id"], conversation_id=conv["id"],
                message_id=msg["id"], sample_id=str(uuid.uuid4()), ciphertext=b"\x00" * 30,
                canonical_len=1, truncated=False, canonical_digest=hashlib.sha256(b"dummy").digest(),
                customer_ref=str(cust["id"]), conversation_ref=str(conv["id"]))
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
        # T6-02: canonical_text_len/digest gio PHAI khop CHINH XAC noi dung that ("tin nhan that",
        # 13 ky tu) — khong con "canonical_text_len=1 gia" nhu REV6 (chi kiem <=, gio la <>).
        real_digest = _canonical_digest("tin nhan that")
        rec = await _record_sample_signed(
            conn, batch_id=audit_batch["batch_id"], conversation_id=conv["id"], message_id=msg["id"],
            sample_id=str(uuid.uuid4()),
            # T5-02: ciphertext PHAI >= canonical_text_len+30 (AEAD overhead) — 43 byte cho 13 ky tu.
            ciphertext=b"\x00" * 43, canonical_len=13, truncated=False, canonical_digest=real_digest,
            customer_ref=str(cust["id"]), conversation_ref=str(conv["id"]))
        check(rec["captured_count"] == 1,
              "T2-06/T4-01: record_sample (CUNG transaction voi fetch) -> captured_count tang DUNG 1")
    progress_after = await admin.fetchval(
        "SELECT status FROM m4_stage0p_capture_progress WHERE batch_id=$1 AND conversation_id=$2 AND message_id=$3",
        audit_batch["batch_id"], conv["id"], msg["id"])
    check(progress_after == "committed", "T4-03: candidate progress row -> 'committed' sau record_sample thanh cong")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T5-02: record_sample tu choi canonical_text_len vuot qua do dai da fetch ==")
    msg_a = await admin.fetchrow(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer','tin nhan ngan') RETURNING id",
        conv["id"])
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    async with conn.transaction():
        await conn.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                            audit_batch["batch_id"], conv["id"], msg_a["id"])
        try:
            # T6-02: digest DUNG (noi dung that "tin nhan ngan") nhung canonical_text_len khai SAI
            # (5000, thuc te 13) — digest check PASS (doc lap voi do dai khai bao), roi moi den
            # exact-length check RAISE. REV10 T8-02: transcript tu ky NHAT QUAN voi canonical_len=
            # 5000 (gia tri SAI dang test) + ciphertext 5000 byte tuong ung, nen lop T8-02 PASS,
            # cho phep chay toi lop T5-02/T6-02 that su dang test o day.
            await _record_sample_signed(
                conn, batch_id=audit_batch["batch_id"], conversation_id=conv["id"],
                message_id=msg_a["id"], sample_id=str(uuid.uuid4()), ciphertext=b"\x00" * 5000,
                canonical_len=5000, truncated=False, canonical_digest=_canonical_digest("tin nhan ngan"),
                customer_ref=str(cust["id"]), conversation_ref=str(conv["id"]))
            check(False, "canonical_text_len (5000) khong khop do dai da fetch -> phai RAISE (T5-02)")
        except asyncpg.PostgresError as e:
            check("khong khop do dai da fetch" in str(e), "canonical_text_len khong khop do dai da fetch -> RAISE dung (T5-02/T6-02)")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T5-02: record_sample tu choi p_truncated=false khi DB biet noi dung goc DA bi cat ==")
    long_content = "a" * 2500
    conv_long = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", cust["id"])
    await admin.execute(
        "UPDATE m4_selection_batches SET locked_conversation_ids = locked_conversation_ids || ARRAY[$1::bigint] "
        "WHERE batch_id=$2", conv_long["id"], audit_batch["batch_id"])
    msg_b = await admin.fetchrow(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer',$2) RETURNING id",
        conv_long["id"], long_content)
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    async with conn.transaction():
        fetched_long = await conn.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                                           audit_batch["batch_id"], conv_long["id"], msg_b["id"])
        check(fetched_long["char_truncated"] is True, "setup: noi dung 2500 ky tu -> DB bao char_truncated=true")
        try:
            # T6-02: digest DUNG (canonical that = "a"*2000, dung nhu DB da tinh luc fetch) + do
            # dai dung (2000) nhung p_truncated=False la LOI DUY NHAT dang test.
            await _record_sample_signed(
                conn, batch_id=audit_batch["batch_id"], conversation_id=conv_long["id"],
                message_id=msg_b["id"], sample_id=str(uuid.uuid4()), ciphertext=b"\x00" * 2030,
                canonical_len=2000, truncated=False, canonical_digest=_canonical_digest("a" * 2500),
                customer_ref=str(cust["id"]), conversation_ref=str(conv_long["id"]))
            check(False, "p_truncated=false khi DB biet noi dung goc bi cat -> phai RAISE (T5-02)")
        except asyncpg.PostgresError as e:
            check("khong khop trang thai cat da fetch" in str(e),
                  "p_truncated=false che giau truncation -> RAISE dung (T5-02/T6-02)")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T5-02: record_sample tu choi ciphertext qua ngan/qua dai so canonical_text_len (AEAD overhead sanity) ==")
    msg_c = await admin.fetchrow(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer','tin nhan c') RETURNING id",
        conv["id"])
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    async with conn.transaction():
        await conn.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                            audit_batch["batch_id"], conv["id"], msg_c["id"])
        try:
            # T6-02: digest+do dai (10, "tin nhan c") DUNG het — chi ciphertext 3000 byte la SAI
            # (vuot xa AEAD overhead hop ly cho 10 ky tu, toi da 10*4+30=70 byte). REV10 T8-02:
            # transcript tu ky NHAT QUAN voi CHINH 3000-byte ciphertext nay (ciphertext_digest
            # khop) nen lop T8-02 PASS, cho phep chay toi AEAD-overhead-sanity check that su dang
            # test o day.
            await _record_sample_signed(
                conn, batch_id=audit_batch["batch_id"], conversation_id=conv["id"],
                message_id=msg_c["id"], sample_id=str(uuid.uuid4()), ciphertext=b"\x00" * 3000,
                canonical_len=10, truncated=False, canonical_digest=_canonical_digest("tin nhan c"),
                customer_ref=str(cust["id"]), conversation_ref=str(conv["id"]))
            check(False, "ciphertext 3000 byte cho canonical_text_len=10 -> phai RAISE (T5-02)")
        except asyncpg.PostgresError as e:
            check("khong hop ly" in str(e), "ciphertext qua dai so canonical_text_len -> RAISE dung (T5-02)")
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
        "algorithm_seed, locked_conversation_ids, purpose_code, normalization_version) VALUES (now()-interval '1 day', now(), "
        "1, 1, 'perm-test-403', ARRAY[$1]::bigint[], 'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id", conv3["id"])
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    seed3 = await conn.fetchrow("SELECT * FROM m4_stage0p_seed_capture_progress($1)", batch3["batch_id"])
    check(seed3["candidate_count"] == 1, "seed_capture_progress vet dung 1 candidate")
    o1 = await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'fence_timeout',$4)",
                             batch3["batch_id"], conv3["id"], msg3["id"], "asyncio_wait_for_timeout")
    check(o1["new_status"] == "retryable_failed" and o1["attempt_count"] == 1,
          f"lan 1 fence_timeout -> retryable_failed, attempt_count=1 (thuc te {o1['new_status']},{o1['attempt_count']})")
    o2 = await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'fence_timeout',$4)",
                             batch3["batch_id"], conv3["id"], msg3["id"], "asyncio_wait_for_timeout")
    check(o2["new_status"] == "retryable_failed" and o2["attempt_count"] == 2,
          f"lan 2 fence_timeout -> retryable_failed, attempt_count=2 (thuc te {o2['new_status']},{o2['attempt_count']})")
    o3 = await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'fence_timeout',$4)",
                             batch3["batch_id"], conv3["id"], msg3["id"], "asyncio_wait_for_timeout")
    check(o3["new_status"] == "permanent_failed" and o3["attempt_count"] == 3,
          f"lan 3 fence_timeout -> permanent_failed (terminal), attempt_count=3 (thuc te {o3['new_status']},{o3['attempt_count']})")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'fence_timeout',$4)",
                            batch3["batch_id"], conv3["id"], msg3["id"], "asyncio_wait_for_timeout")
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
                            batch3["batch_id"], 888888, 888888, "asyncio_wait_for_timeout")
        check(False, "candidate chua duoc seed -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("khong duoc seed" in str(e), "candidate chua duoc seed -> RAISE dung")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'pending_deletion',$4)",
                            batch3["batch_id"], conv3["id"], msg3["id"], "reason-tuy-y-khong-hop-le")
        check(False, "reason ngoai allowlist -> phai RAISE (T5-03)")
    except asyncpg.PostgresError as e:
        check("allowlist" in str(e), "reason ngoai allowlist -> RAISE dung (T5-03)")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T5-03: close_collection TU CHOI khi ty le permanent_failed vuot nguong (1/1 = 100% > 10%) ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_close_collection($1)", batch3["batch_id"])
        check(False, "close_collection voi candidate duy nhat permanent_failed (100%) -> phai RAISE (T5-03)")
    except asyncpg.PostgresError as e:
        check("INSUFFICIENT_DATA" in str(e) and "permanent_failed" in str(e),
              "close_collection voi ty le permanent_failed 100% -> RAISE dung (T5-03)")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T6-03: close_collection TU CHOI VO DIEU KIEN du chi 1/20 = 5% permanent_failed (khong con dung ty le) ==")
    cust3b = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('perm-t503','x') RETURNING id")
    conv3b = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", cust3b["id"])
    for i in range(20):
        await admin.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer',$2)",
            conv3b["id"], f"tin t503 so {i}")
    batch3b = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, selected_count, "
        "algorithm_seed, locked_conversation_ids, purpose_code, normalization_version) VALUES (now()-interval '1 day', now(), "
        "1, 1, 'perm-test-503', ARRAY[$1]::bigint[], 'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id", conv3b["id"])
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    seed3b = await conn.fetchrow("SELECT * FROM m4_stage0p_seed_capture_progress($1)", batch3b["batch_id"])
    check(seed3b["candidate_count"] == 20, "seed_capture_progress vet dung 20 candidate")
    rows3b = await admin.fetch(
        "SELECT conversation_id, message_id FROM m4_stage0p_capture_progress WHERE batch_id=$1 ORDER BY message_id",
        batch3b["batch_id"])
    # T6-03: 1 candidate permanent_failed (3 lan fence_timeout), 19 con lai excluded — ty le CHI
    # 5%, nhung REV7 KHONG con dung nguong ty le (CA Review #6 chi ro nguong exclusion_gate van la
    # de xuat CA chua duyet, khong duoc dung de "cho phep" permanent_failed di tiep) -> PHAI RAISE
    # VO DIEU KIEN, khac han REV6 (tung THANH CONG o kich ban y het nay).
    for _ in range(3):
        await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'fence_timeout',$4)",
                            batch3b["batch_id"], rows3b[0]["conversation_id"], rows3b[0]["message_id"],
                            "asyncio_wait_for_timeout")
    for r in rows3b[1:]:
        await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'pending_deletion',$4)",
                            batch3b["batch_id"], r["conversation_id"], r["message_id"],
                            "customer_in_pending_cache")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_close_collection($1)", batch3b["batch_id"])
        check(False, "close_collection voi 1/20 (5%) permanent_failed -> phai RAISE VO DIEU KIEN (T6-03)")
    except asyncpg.PostgresError as e:
        check("INSUFFICIENT_DATA" in str(e) and "permanent_failed" in str(e),
              "close_collection tu choi VO DIEU KIEN du ty le thap (5%) -> RAISE dung (T6-03)")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T6-03: close_collection THANH CONG khi 0 permanent_failed (chi excluded+committed) — luu capture_gate_policy ==")
    cust3c = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('perm-t603','x') RETURNING id")
    conv3c = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", cust3c["id"])
    msgs3c = []
    for i in range(3):
        m = await admin.fetchrow(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer',$2) RETURNING id",
            conv3c["id"], f"tin t603 so {i}")
        msgs3c.append(m)
    batch3c = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, selected_count, "
        "algorithm_seed, locked_conversation_ids, purpose_code, normalization_version) VALUES (now()-interval '1 day', now(), "
        "1, 1, 'perm-test-603', ARRAY[$1]::bigint[], 'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id", conv3c["id"])
    on_conn3c = await asyncpg.connect(DB_URL)
    await _set_capture(on_conn3c, enabled=True, staff_id=staff["id"], approval_ref="perm-test-approval-ok")
    await on_conn3c.close()
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    seed3c = await conn.fetchrow("SELECT * FROM m4_stage0p_seed_capture_progress($1)", batch3c["batch_id"])
    check(seed3c["candidate_count"] == 3, "seed_capture_progress vet dung 3 candidate")
    async with conn.transaction():
        fetched3c = await conn.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                                        batch3c["batch_id"], conv3c["id"], msgs3c[0]["id"])
        check(fetched3c["status"] == "ok", f"setup: fetch batch3c thanh cong (thuc te {dict(fetched3c)})")
        await _record_sample_signed(
            conn, batch_id=batch3c["batch_id"], conversation_id=conv3c["id"],
            message_id=msgs3c[0]["id"], sample_id=str(uuid.uuid4()), ciphertext=b"\x00" * 60,
            canonical_len=13, truncated=False, canonical_digest=_canonical_digest("tin t603 so 0"),
            customer_ref=str(cust3c["id"]), conversation_ref=str(conv3c["id"]))
    for m in msgs3c[1:]:
        await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'pending_deletion',$4)",
                            batch3c["batch_id"], conv3c["id"], m["id"], "customer_in_pending_cache")
    close3c = await conn.fetchrow("SELECT * FROM m4_stage0p_close_collection($1)", batch3c["batch_id"])
    check(close3c["status"] == "collection_closed",
          "close_collection THANH CONG khi 0 permanent_failed (1 committed + 2 excluded, T6-03)")
    batch3c_row = await admin.fetchrow(
        "SELECT capture_excluded_count, capture_permanent_failed_count, capture_gate_policy "
        "FROM m4_selection_batches WHERE batch_id=$1", batch3c["batch_id"])
    check(batch3c_row["capture_excluded_count"] == 2 and batch3c_row["capture_permanent_failed_count"] == 0,
          f"T6-03: capture_excluded_count/capture_permanent_failed_count luu dung tren batch row (thuc te {dict(batch3c_row)})")
    check(batch3c_row["capture_gate_policy"] == "zero_tolerance_pending_po_decision_v1",
          f"T6-03: capture_gate_policy luu dung tren batch row (thuc te {batch3c_row['capture_gate_policy']})")
    await conn.execute("RESET ROLE")
    await conn.close()
    off_conn3c = await asyncpg.connect(DB_URL)
    await _set_capture(off_conn3c, enabled=False, staff_id=staff["id"], approval_ref="perm-test-t603-off")
    await off_conn3c.close()

    print("== T6-03: close_collection TU CHOI corpus RONG (0 candidate committed, khong permanent_failed) ==")
    cust3d = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('perm-t603d','x') RETURNING id")
    conv3d = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", cust3d["id"])
    msg3d = await admin.fetchrow(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer','tin t603d') RETURNING id",
        conv3d["id"])
    batch3d = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, selected_count, "
        "algorithm_seed, locked_conversation_ids, purpose_code, normalization_version) VALUES (now()-interval '1 day', now(), "
        "1, 1, 'perm-test-603d', ARRAY[$1]::bigint[], 'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id", conv3d["id"])
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    await conn.fetchrow("SELECT * FROM m4_stage0p_seed_capture_progress($1)", batch3d["batch_id"])
    await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'pending_deletion',$4)",
                        batch3d["batch_id"], conv3d["id"], msg3d["id"], "customer_in_pending_cache")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_close_collection($1)", batch3d["batch_id"])
        check(False, "close_collection voi corpus rong (0 committed) -> phai RAISE (T6-03)")
    except asyncpg.PostgresError as e:
        check("corpus rong" in str(e), "close_collection tu choi corpus rong -> RAISE dung (T6-03)")
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
        "algorithm_seed, locked_conversation_ids, purpose_code, normalization_version) VALUES (now()-interval '1 day', now(), "
        "1, 1, 'perm-test-403b', ARRAY[$1]::bigint[], 'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id", conv4["id"])
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
    # T6-03: dat 1 candidate terminal qua excluded, 1 candidate qua record_sample THAT (committed)
    # — corpus KHONG con rong (khac REV6, ca 2 candidate deu excluded van THANH CONG duoc; REV7
    # doi hoi >=1 committed).
    rows4 = await admin.fetch(
        "SELECT conversation_id, message_id FROM m4_stage0p_capture_progress WHERE batch_id=$1 ORDER BY message_id",
        batch4["batch_id"])
    on_conn4 = await asyncpg.connect(DB_URL)
    await _set_capture(on_conn4, enabled=True, staff_id=staff["id"], approval_ref="perm-test-approval-ok")
    await on_conn4.close()
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    async with conn.transaction():
        await conn.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                            batch4["batch_id"], rows4[0]["conversation_id"], rows4[0]["message_id"])
        await _record_sample_signed(
            conn, batch_id=batch4["batch_id"], conversation_id=rows4[0]["conversation_id"],
            message_id=rows4[0]["message_id"], sample_id=str(uuid.uuid4()), ciphertext=b"\x00" * 40,
            canonical_len=5, truncated=False, canonical_digest=_canonical_digest("tin 0"),
            customer_ref=str(cust4["id"]), conversation_ref=str(rows4[0]["conversation_id"]))
    await conn.fetchrow("SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,'pending_deletion',$4)",
                        batch4["batch_id"], rows4[1]["conversation_id"], rows4[1]["message_id"],
                        "customer_in_pending_cache")
    close4 = await conn.fetchrow("SELECT * FROM m4_stage0p_close_collection($1)", batch4["batch_id"])
    check(close4["status"] == "collection_closed",
          "close_collection THANH CONG sau khi MOI candidate dat terminal (1 committed + 1 excluded) — T4-03/T6-03")
    await conn.execute("RESET ROLE")
    await conn.close()
    off_conn4 = await asyncpg.connect(DB_URL)
    await _set_capture(off_conn4, enabled=False, staff_id=staff["id"], approval_ref="perm-test-t403-off")
    await off_conn4.close()

    print("== T4-03: close_collection tu choi neu captured_count/row-thuc-te/progress-committed lech nhau ==")
    batch5 = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, selected_count, "
        "algorithm_seed, locked_conversation_ids, purpose_code, normalization_version, captured_count, status) VALUES "
        "(now()-interval '1 day', now(), 1, 1, 'perm-test-305', ARRAY[]::bigint[], 'P12_PII_DETECTOR_EVAL', 'nfc-v1', "
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

    print("== T5-04/T6-04: normalization registry la nguon THAT DUY NHAT (append-only, versioned) ==")
    registry_row = await admin.fetchrow(
        "SELECT version FROM m4_stage0p_normalization_registry WHERE is_current")
    check(registry_row["version"] == "nfc-v1",
          f"registry seed dung 'nfc-v1' (thuc te {registry_row['version']})")

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

    print("== T7-03: registry doi SAU khi batch lock/seal, TRUOC prediction — batch cu van dung theo version DA KHOA ==")
    pinned_batch, pinned_ids = await _make_large_batch(admin, seed="perm-t703-pinned", n=200)
    conn = await asyncpg.connect(DB_URL)
    pinned_seal = await _seal_labels(conn, staff_id=staff["id"], batch_id=pinned_batch)
    await conn.close()
    # Doi "current" TOAN CUC sang 1 version MOI HOAN TOAN — batch pinned_batch van khoa 'nfc-v1'
    # tu luc _make_large_batch tao (khong doi). Neu write_predictions con doc "current" toan cuc
    # (loi REV7 CA chi ra), toan bo 200 sample se bi loai NHAM vi "mismatch" — phai KHONG xay ra.
    t703_now = datetime.datetime.now(datetime.timezone.utc)
    norm_conn_t703 = await asyncpg.connect(DB_URL)
    await _record_normalization_approval(
        norm_conn_t703, staff_id=staff["id"], approval_ref="PO-DECISION-T703",
        requested_version="nfc-v703-test",
        valid_from=t703_now - datetime.timedelta(hours=1), valid_until=t703_now + datetime.timedelta(hours=1))
    await norm_conn_t703.close()

    conn = await asyncpg.connect(DB_URL)
    await _pin(conn, staff["id"])
    await conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    new_current = await conn.fetchrow(
        "SELECT * FROM m4_stage0p_set_current_normalization_version($1,$2)",
        "nfc-v703-test", "PO-DECISION-T703")
    check(new_current["version"] == "nfc-v703-test", "setup: doi 'current' toan cuc sang version MOI (T7-03)")
    await conn.execute("RESET ROLE")
    await conn.close()
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        pinned_preds = _json.dumps([{"sample_id": sid, "predicted_slots": []} for sid in pinned_ids])
        pinned_result = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1,$2,$3::jsonb,$4::jsonb,$5,$6)",
            pinned_batch, pinned_seal["sealed_hash"], pinned_preds, "[]", "m4d-0.1.0", "perm-t703-pinned")
        check(pinned_result["updated_count"] == 200,
              f"batch cu (khoa 'nfc-v1') van xu ly DUNG 200 sample du 'current' toan cuc da doi (thuc te {pinned_result['updated_count']})")
        check(pinned_result["non_excluded_conversation_count"] == 200,
              "T7-03: KHONG sample nao bi loai nham vi mismatch — dung version DA KHOA cua batch, khong phai 'current' toan cuc")
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()
    # batch MOI (lock SAU khi doi current) phai dung version MOI, khong phai 'nfc-v1' cu.
    # _make_large_batch (helper T4-05) luon hardcode 'nfc-v1' (khong doc registry) nen KHONG dung
    # duoc o day — kiem tra qua lock_batch() THAT (Python) thay vi helper SQL truc tiep.
    from app.services.pii.stage0p_sampling import lock_batch as _lock_batch_fn
    lb_conn = await asyncpg.connect(DB_URL)
    await lb_conn.execute("SET ROLE alpha3s_m4_sample_collector")
    new_batch_id_via_python = await _lock_batch_fn(
        lb_conn, window_start=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1),
        window_end=datetime.datetime.now(datetime.timezone.utc), eligible_count=0, selected=[])
    await lb_conn.execute("RESET ROLE")
    await lb_conn.close()
    new_batch_version = await admin.fetchval(
        "SELECT normalization_version FROM m4_selection_batches WHERE batch_id=$1", new_batch_id_via_python)
    check(new_batch_version == "nfc-v703-test",
          f"batch MOI (lock() SAU khi doi current) dung version MOI 'nfc-v703-test' (thuc te {new_batch_version})")
    # khoi phuc registry ve 'nfc-v1' de khong anh huong cac lan chay khac.
    await admin.execute("UPDATE m4_stage0p_normalization_registry SET is_current=false WHERE version='nfc-v703-test'")
    await admin.execute("UPDATE m4_stage0p_normalization_registry SET is_current=true WHERE version='nfc-v1'")

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

    print("== T6-01: pin_actor rate-limit — 5 lan sai lien tiep -> khoa 15 phut, dung ca khi bien secret DUNG sau do ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_actor_binder")
    for i in range(5):
        row_i = await conn.fetchrow("SELECT * FROM m4_stage0p_pin_actor($1,$2)", staff["id"], f"sai-lan-{i}")
        check(row_i["pinned_staff_id"] is None, f"lan sai thu {i + 1} -> pinned_staff_id=NULL")
    cred_row = await admin.fetchrow(
        "SELECT failed_attempts, locked_until FROM m4_stage0p_actor_credentials WHERE staff_id=$1", staff["id"])
    check(cred_row["failed_attempts"] == 5 and cred_row["locked_until"] is not None,
          f"sau 5 lan sai -> failed_attempts=5 + locked_until dat (thuc te {dict(cred_row)})")
    locked_row = await conn.fetchrow("SELECT * FROM m4_stage0p_pin_actor($1,$2)", staff["id"], PIN_SECRET)
    check(locked_row["pinned_staff_id"] is None,
          "pin_actor tu choi du secret DUNG vi dang bi rate-limit-khoa -> pinned_staff_id=NULL (T6-01)")
    await conn.execute("RESET ROLE")
    await conn.close()
    # don sach de khong anh huong cac test con lai dung staff["id"].
    await admin.execute(
        "UPDATE m4_stage0p_actor_credentials SET failed_attempts=0, locked_until=NULL WHERE staff_id=$1",
        staff["id"])

    print("== T6-01: pin het han (expires_at qua khu) -> tu choi + tu xoa session row (khong con STALE mai) ==")
    conn = await asyncpg.connect(DB_URL)
    conn_pid_a = await conn.fetchval("SELECT pg_backend_pid()")
    await _pin(conn, staff["id"])
    await admin.execute(
        "UPDATE m4_stage0p_actor_session SET expires_at = now() - interval '1 second' WHERE backend_pid=$1",
        conn_pid_a)
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", False, None)
        check(False, "goi ham nghiep vu voi pin DA HET HAN -> phai RAISE (T6-01)")
    except asyncpg.PostgresError as e:
        check("het han" in str(e), "pin het han -> RAISE dung (T6-01)")
    await conn.execute("RESET ROLE")
    # T6-01: KHONG con tu xoa row (PL/pgSQL khong co autonomous transaction — DELETE truoc RAISE se
    # bi rollback cung, vo tac dung — xem docstring migration); kiem tra LAI danh gia moi lan goi
    # nen an toan du row cu con ton tai. Pin lai (ON CONFLICT) ghi de row cu, xac nhan duoi day.
    await _pin(conn, staff["id"])
    row_after_repin = await admin.fetchval(
        "SELECT expires_at > now() FROM m4_stage0p_actor_session WHERE backend_pid=$1", conn_pid_a)
    check(row_after_repin is True, "pin lai SAU khi het han -> row cu bi ghi de dung (expires_at moi, T6-01)")
    await conn.close()

    print("== T6-01: session_nonce khong khop (mo phong backend_pid bi tai su dung tu 1 ket noi da chet) -> tu choi ==")
    conn = await asyncpg.connect(DB_URL)
    conn_pid_b = await conn.fetchval("SELECT pg_backend_pid()")
    await _pin(conn, staff["id"])
    # Mo phong: row hien tai dai dien cho 1 lan pin cua 1 backend DA CHET ma OS vo tinh cap lai
    # CHINH backend_pid nay cho ket noi HIEN TAI (conn) — GUC session-scoped cua conn van con gia
    # tri THAT (con dang song, khong the bi xoa tu ben ngoai), nhung row trong bang bi doi session_
    # nonce khac (mo phong "day la row cua 1 pin CU, khong phai cua conn dang goi").
    await admin.execute(
        "UPDATE m4_stage0p_actor_session SET session_nonce = gen_random_uuid() WHERE backend_pid=$1", conn_pid_b)
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", False, None)
        check(False, "session_nonce khong khop -> phai RAISE (T6-01)")
    except asyncpg.PostgresError as e:
        check("STALE" in str(e) and "session_nonce" in str(e),
              "session_nonce khong khop (PID tai su dung mo phong) -> RAISE dung (T6-01)")
    await conn.execute("RESET ROLE")
    # T6-01: KHONG con tu xoa row (cung ly do nhu tren) — pin lai ghi de dung, xac nhan an toan.
    await _pin(conn, staff["id"])
    row_after_repin2 = await admin.fetchval(
        "SELECT session_nonce FROM m4_stage0p_actor_session WHERE backend_pid=$1", conn_pid_b)
    check(row_after_repin2 is not None, "pin lai SAU session_nonce khong khop -> row cu bi ghi de dung (T6-01)")
    await conn.close()

    print("== T6-01: unpin_actor() — 'logout' tuong minh, sau do goi ham nghiep vu bi tu choi ngay ==")
    conn = await asyncpg.connect(DB_URL)
    await _pin(conn, staff["id"])
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    ok_before_unpin = await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", False, None)
    check(ok_before_unpin is not None, "set_capture thanh cong TRUOC unpin (dung actor da pin)")
    await conn.execute("RESET ROLE")
    await conn.execute("SET ROLE alpha3s_m4_actor_binder")
    await conn.execute("SELECT m4_stage0p_unpin_actor()")
    await conn.execute("RESET ROLE")
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", True, "khong-quan-trong")
        check(False, "goi ham nghiep vu SAU unpin_actor() -> phai RAISE (T6-01)")
    except asyncpg.PostgresError as e:
        check("chua pin actor" in str(e), "sau unpin_actor() -> tu choi dung (T6-01, 'logout' co hieu luc)")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T6-02: record_sample tu choi digest KHONG khop (noi dung KHAC, cung do dai/truncated khai bao dung) ==")
    on_conn_d = await asyncpg.connect(DB_URL)
    await _set_capture(on_conn_d, enabled=True, staff_id=staff["id"], approval_ref="perm-test-approval-ok")
    await on_conn_d.close()
    cust_d = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('perm-t602d','x') RETURNING id")
    conv_d = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", cust_d["id"])
    await admin.execute(
        "UPDATE m4_selection_batches SET locked_conversation_ids = locked_conversation_ids || ARRAY[$1::bigint] "
        "WHERE batch_id=$2", conv_d["id"], audit_batch["batch_id"])
    msg_d = await admin.fetchrow(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer','noi dung goc that su') RETURNING id",
        conv_d["id"])
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_sample_collector")
    async with conn.transaction():
        await conn.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                            audit_batch["batch_id"], conv_d["id"], msg_d["id"])
        try:
            # canonical_text_len=20/truncated=False DUNG het (khop dung "noi dung goc that su"),
            # nhung digest la cua 1 chuoi KHAC CO CUNG DO DAI (20 ky tu) — day chinh la kich ban CA
            # neu ro trong F-M4-0P-T6-02: "ciphertext substitution... cung length van qua duoc".
            forged_same_len = "noi dung gia mao roi"
            check(len(forged_same_len) == len("noi dung goc that su"),
                  "setup: chuoi gia mao CUNG do dai voi noi dung that (20 ky tu)")
            await _record_sample_signed(
                conn, batch_id=audit_batch["batch_id"], conversation_id=conv_d["id"],
                message_id=msg_d["id"], sample_id=str(uuid.uuid4()), ciphertext=b"\x00" * 55,
                canonical_len=20, truncated=False, canonical_digest=_canonical_digest(forged_same_len),
                customer_ref=str(cust_d["id"]), conversation_ref=str(conv_d["id"]))
            check(False, "digest cua noi dung KHAC (cung do dai) -> phai RAISE (T6-02)")
        except asyncpg.PostgresError as e:
            check("canonical_text_digest khong khop" in str(e),
                  "digest khong khop noi dung da fetch (cung do dai) -> RAISE dung (T6-02)")
    await conn.execute("RESET ROLE")
    await conn.close()
    off_conn_d = await asyncpg.connect(DB_URL)
    await _set_capture(off_conn_d, enabled=False, staff_id=staff["id"], approval_ref="perm-test-t602d-off")
    await off_conn_d.close()

    print("== T8-02: signed capture transcript — 8 kich ban adversarial CA yeu cau (Review #9 §4) ==")
    cust_t8 = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('perm-t802','x') RETURNING id")
    conv_t8 = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", cust_t8["id"])
    conv_t8b = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", cust_t8["id"])
    batch_t8 = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, selected_count, "
        "algorithm_seed, locked_conversation_ids, purpose_code, normalization_version) VALUES "
        "(now()-interval '1 day', now(), 2, 2, 'perm-test-t802', ARRAY[$1,$2]::bigint[], "
        "'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id", conv_t8["id"], conv_t8b["id"])
    batch_t8b_other = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, selected_count, "
        "algorithm_seed, locked_conversation_ids, purpose_code, normalization_version) VALUES "
        "(now()-interval '1 day', now(), 1, 1, 'perm-test-t802-other', ARRAY[$1]::bigint[], "
        "'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id", conv_t8["id"])
    msg_t8 = await admin.fetchrow(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer','noi dung t802') RETURNING id",
        conv_t8["id"])
    msg_t8b = await admin.fetchrow(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer','noi dung t802 khac') "
        "RETURNING id", conv_t8b["id"])
    on_conn_t8 = await asyncpg.connect(DB_URL)
    await _set_capture(on_conn_t8, enabled=True, staff_id=staff["id"], approval_ref="perm-test-approval-ok")
    await on_conn_t8.close()
    seed_conn_t8 = await asyncpg.connect(DB_URL)
    await seed_conn_t8.execute("SET ROLE alpha3s_m4_sample_collector")
    await seed_conn_t8.fetchrow("SELECT * FROM m4_stage0p_seed_capture_progress($1)", batch_t8["batch_id"])
    await seed_conn_t8.execute("RESET ROLE")
    await seed_conn_t8.close()
    t8_digest = _canonical_digest("noi dung t802")
    t8_ct = b"\x00" * 43

    async def _t8_expect_raise(label, needle, *, batch_id=None, conversation_id=None, message_id=None,
                               sample_id=None, canonical_len=20, truncated=False, canonical_digest=None,
                               ciphertext=None, customer_ref=None, conversation_ref=None,
                               transcript_override=None, signature_override=None, **sign_overrides):
        conn_t8 = await asyncpg.connect(DB_URL)
        await conn_t8.execute("SET ROLE alpha3s_m4_sample_collector")
        actual_sample_id = sample_id or str(uuid.uuid4())
        try:
            async with conn_t8.transaction():
                await conn_t8.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                                       batch_t8["batch_id"], conv_t8["id"], msg_t8["id"])
                txid = await conn_t8.fetchval("SELECT txid_current()")
                real_ciphertext = ciphertext if ciphertext is not None else t8_ct
                if transcript_override is not None:
                    transcript_bytes, signature = transcript_override, signature_override
                else:
                    transcript_bytes, signature = _sign_test_transcript(
                        batch_id=batch_id or batch_t8["batch_id"],
                        conversation_id=conversation_id if conversation_id is not None else conv_t8["id"],
                        message_id=message_id if message_id is not None else msg_t8["id"],
                        sample_id=actual_sample_id, txid=txid,
                        canonical_digest=canonical_digest or t8_digest, canonical_len=canonical_len,
                        truncated=truncated, ciphertext=real_ciphertext,
                        customer_ref=customer_ref or str(cust_t8["id"]),
                        conversation_ref=conversation_ref or str(conv_t8["id"]), **sign_overrides)
                    if signature_override is not None:
                        signature = signature_override
                await conn_t8.fetchrow(
                    "SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                    batch_t8["batch_id"], conv_t8["id"], msg_t8["id"], actual_sample_id,
                    real_ciphertext, canonical_len, truncated, canonical_digest or t8_digest,
                    transcript_bytes, signature, sign_overrides.get("key_version", TRANSCRIPT_KEY_VERSION))
            check(False, f"{label} -> phai RAISE (T8-02)")
        except asyncpg.PostgresError as e:
            check(needle in str(e), f"{label} -> RAISE dung: {needle!r} (T8-02)")
        finally:
            await conn_t8.execute("RESET ROLE")
            await conn_t8.close()

    # [a] Thieu signature/transcript hoan toan.
    conn_missing = await asyncpg.connect(DB_URL)
    await conn_missing.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        async with conn_missing.transaction():
            await conn_missing.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                                        batch_t8["batch_id"], conv_t8["id"], msg_t8["id"])
            await conn_missing.fetchrow(
                "SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                batch_t8["batch_id"], conv_t8["id"], msg_t8["id"], str(uuid.uuid4()), t8_ct, 13,
                False, t8_digest, None, None, None)
        check(False, "thieu transcript/signature -> phai RAISE (T8-02)")
    except asyncpg.PostgresError as e:
        check("thieu transcript/signature/key_version" in str(e),
              "thieu transcript/signature -> RAISE dung (T8-02)")
    finally:
        await conn_missing.execute("RESET ROLE")
        await conn_missing.close()

    # [b] Signature sai (transcript hop le nhung chu ky bi sua 1 byte).
    conn_badsig = await asyncpg.connect(DB_URL)
    await conn_badsig.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        async with conn_badsig.transaction():
            await conn_badsig.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                                       batch_t8["batch_id"], conv_t8["id"], msg_t8["id"])
            txid_bad = await conn_badsig.fetchval("SELECT txid_current()")
            sample_id_bad = str(uuid.uuid4())
            transcript_bad, sig_bad = _sign_test_transcript(
                batch_id=batch_t8["batch_id"], conversation_id=conv_t8["id"], message_id=msg_t8["id"],
                sample_id=sample_id_bad, txid=txid_bad, canonical_digest=t8_digest, canonical_len=13,
                truncated=False, ciphertext=t8_ct, customer_ref=str(cust_t8["id"]),
                conversation_ref=str(conv_t8["id"]))
            corrupted_sig = bytes([sig_bad[0] ^ 0xFF]) + sig_bad[1:]
            await conn_badsig.fetchrow(
                "SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                batch_t8["batch_id"], conv_t8["id"], msg_t8["id"], sample_id_bad, t8_ct, 13, False,
                t8_digest, transcript_bad, corrupted_sig, TRANSCRIPT_KEY_VERSION)
        check(False, "chu ky sai (1 byte) -> phai RAISE (T8-02)")
    except asyncpg.PostgresError as e:
        check("chu ky transcript khong hop le" in str(e), "chu ky sai -> RAISE dung (T8-02)")
    finally:
        await conn_badsig.execute("RESET ROLE")
        await conn_badsig.close()

    # [c] ciphertext-substitution: digest plaintext THAT nhung ciphertext GUI LEN khac voi
    # ciphertext transcript da ky (chinh loi CA neu — T7-02/T8-02 goc).
    conn_sub = await asyncpg.connect(DB_URL)
    await conn_sub.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        async with conn_sub.transaction():
            await conn_sub.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                                    batch_t8["batch_id"], conv_t8["id"], msg_t8["id"])
            txid_sub = await conn_sub.fetchval("SELECT txid_current()")
            sample_id_sub = str(uuid.uuid4())
            transcript_sub, sig_sub = _sign_test_transcript(
                batch_id=batch_t8["batch_id"], conversation_id=conv_t8["id"], message_id=msg_t8["id"],
                sample_id=sample_id_sub, txid=txid_sub, canonical_digest=t8_digest, canonical_len=13,
                truncated=False, ciphertext=t8_ct, customer_ref=str(cust_t8["id"]),
                conversation_ref=str(conv_t8["id"]))
            substituted_ct = b"\x11" * 43  # ciphertext KHAC, cung do dai — hop le AEAD-overhead-sanity
            await conn_sub.fetchrow(
                "SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                batch_t8["batch_id"], conv_t8["id"], msg_t8["id"], sample_id_sub, substituted_ct, 13,
                False, t8_digest, transcript_sub, sig_sub, TRANSCRIPT_KEY_VERSION)
        check(False, "ciphertext-substitution (cung do dai, chu ky transcript cua ciphertext GOC) "
              "-> phai RAISE (T8-02)")
    except asyncpg.PostgresError as e:
        check("ciphertext_digest" in str(e), "ciphertext-substitution -> RAISE dung (T8-02, chinh "
              "khoang cach CA neu o T7-02/T8-02 goc)")
    finally:
        await conn_sub.execute("RESET ROLE")
        await conn_sub.close()

    # [d] Replay: dung LAI CHINH transcript+signature da THANH CONG truoc do cho 1 message MOI.
    conn_replay_setup = await asyncpg.connect(DB_URL)
    await conn_replay_setup.execute("SET ROLE alpha3s_m4_sample_collector")
    replay_transcript = replay_sig = None
    async with conn_replay_setup.transaction():
        await conn_replay_setup.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                                         batch_t8["batch_id"], conv_t8["id"], msg_t8["id"])
        txid_r = await conn_replay_setup.fetchval("SELECT txid_current()")
        replay_sample_id = str(uuid.uuid4())
        replay_transcript, replay_sig = _sign_test_transcript(
            batch_id=batch_t8["batch_id"], conversation_id=conv_t8["id"], message_id=msg_t8["id"],
            sample_id=replay_sample_id, txid=txid_r, canonical_digest=t8_digest, canonical_len=13,
            truncated=False, ciphertext=t8_ct, customer_ref=str(cust_t8["id"]),
            conversation_ref=str(conv_t8["id"]))
        replay_rec = await conn_replay_setup.fetchrow(
            "SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
            batch_t8["batch_id"], conv_t8["id"], msg_t8["id"], replay_sample_id, t8_ct, 13, False,
            t8_digest, replay_transcript, replay_sig, TRANSCRIPT_KEY_VERSION)
    check(replay_rec["captured_count"] >= 1, "setup: lan dau dung transcript nay THANH CONG")
    await conn_replay_setup.execute("RESET ROLE")
    await conn_replay_setup.close()
    conn_replay = await asyncpg.connect(DB_URL)
    await conn_replay.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        async with conn_replay.transaction():
            await conn_replay.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                                       batch_t8["batch_id"], conv_t8b["id"], msg_t8b["id"])
            # Dung LAI (replay) DUNG transcript+signature cua lan truoc cho message KHAC — txid
            # cua transaction nay KHAC txid da ky, nen T8-02 phai tu choi.
            await conn_replay.fetchrow(
                "SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                batch_t8["batch_id"], conv_t8b["id"], msg_t8b["id"], replay_sample_id, t8_ct, 13, False,
                t8_digest, replay_transcript, replay_sig, TRANSCRIPT_KEY_VERSION)
        check(False, "replay transcript+signature cu cho request MOI -> phai RAISE (T8-02)")
    except asyncpg.PostgresError as e:
        check("khong thuoc CHINH transaction nay" in str(e) or "khong khop identity" in str(e),
              "replay transcript cu -> RAISE dung (T8-02, txid/identity khong khop)")
    finally:
        await conn_replay.execute("RESET ROLE")
        await conn_replay.close()

    # [e] Transcript da het han (expires_at trong qua khu).
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=120)
    await _t8_expect_raise("transcript het han (expires_at qua khu)", "transcript da het han",
                           canonical_len=13, canonical_digest=t8_digest, ciphertext=t8_ct,
                           issued_at=past, ttl_seconds=1)

    # [f] key_version khong ton tai trong m4_stage0p_transcript_signing_keys.
    await _t8_expect_raise("key_version khong ton tai", "key_version",
                           canonical_len=13, canonical_digest=t8_digest, ciphertext=t8_ct,
                           key_version="khong-ton-tai-v99")

    # [g] cross-message: transcript ky cho message_id KHAC voi tham so record_sample thuc su gui.
    await _t8_expect_raise("cross-message (transcript ky cho message KHAC)", "khong khop identity",
                           canonical_len=13, canonical_digest=t8_digest, ciphertext=t8_ct,
                           message_id=msg_t8b["id"])

    # [h] cross-batch: transcript ky cho batch_id KHAC.
    await _t8_expect_raise("cross-batch (transcript ky cho batch KHAC)", "khong khop identity",
                           canonical_len=13, canonical_digest=t8_digest, ciphertext=t8_ct,
                           batch_id=batch_t8b_other["batch_id"])

    # [i] cross-sample: transcript ky cho sample_id KHAC voi p_sample_id THAT SU gui.
    conn_xs = await asyncpg.connect(DB_URL)
    await conn_xs.execute("SET ROLE alpha3s_m4_sample_collector")
    try:
        async with conn_xs.transaction():
            await conn_xs.fetchrow("SELECT * FROM m4_stage0p_fetch_message_content($1,$2,$3)",
                                   batch_t8["batch_id"], conv_t8["id"], msg_t8["id"])
            txid_xs = await conn_xs.fetchval("SELECT txid_current()")
            transcript_xs, sig_xs = _sign_test_transcript(
                batch_id=batch_t8["batch_id"], conversation_id=conv_t8["id"], message_id=msg_t8["id"],
                sample_id=str(uuid.uuid4()),  # sample_id A - KHAC voi p_sample_id se gui duoi day
                txid=txid_xs, canonical_digest=t8_digest, canonical_len=13, truncated=False,
                ciphertext=t8_ct, customer_ref=str(cust_t8["id"]), conversation_ref=str(conv_t8["id"]))
            await conn_xs.fetchrow(
                "SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                batch_t8["batch_id"], conv_t8["id"], msg_t8["id"], str(uuid.uuid4()),  # sample_id B
                t8_ct, 13, False, t8_digest, transcript_xs, sig_xs, TRANSCRIPT_KEY_VERSION)
        check(False, "cross-sample (transcript ky cho sample_id KHAC) -> phai RAISE (T8-02)")
    except asyncpg.PostgresError as e:
        check("khong khop identity" in str(e), "cross-sample -> RAISE dung (T8-02)")
    finally:
        await conn_xs.execute("RESET ROLE")
        await conn_xs.close()

    # [j] Modified AAD: transcript ky voi aad_digest cua 1 customer_ref KHAC (gia mao boi).
    await _t8_expect_raise("modified AAD (aad_digest cua customer_ref khac)", "aad_digest",
                           canonical_len=13, canonical_digest=t8_digest, ciphertext=t8_ct,
                           customer_ref=str(cust_t8["id"] + 999999))

    off_conn_t8 = await asyncpg.connect(DB_URL)
    await _set_capture(off_conn_t8, enabled=False, staff_id=staff["id"], approval_ref="perm-test-t802-off")
    await off_conn_t8.close()

    print("== T7-01: pin la consume-on-use — actor B MUON connection cua actor A (khong pin lai) bi tu choi ==")
    conn = await asyncpg.connect(DB_URL)
    await _pin(conn, staff["id"])
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    action_a = await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", False, None)
    check(action_a is not None, "actor A (da pin) thanh cong hanh dong nghiep vu dau tien")
    await conn.execute("RESET ROLE")
    # T7-01: KHONG pin lai — mo phong 1 connection-pool tra CHINH connection nay cho 1 request/
    # actor B KHAC. CA Review #7 chi ro day la khoang cach REV7 (session_nonce+TTL) chua dong: row/
    # backend_pid/GUC deu con nguyen neu KHONG tieu thu pin sau khi dung. Sua T7-01: consume-on-use
    # — hanh dong THANH CONG o tren da TIEU THU pin, nen goi tiep theo PHAI bi tu choi ngay.
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", True, "perm-test-approval-ok")
        check(False, "actor B muon connection cua A (khong pin lai) -> phai RAISE (T7-01)")
    except asyncpg.PostgresError as e:
        check("chua pin actor" in str(e),
              "actor B muon connection cua A sau 1 hanh dong THANH CONG -> tu choi dung (T7-01, consume-on-use)")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T7-01: hanh dong THAT BAI (ly do KHAC) KHONG tieu thu pin — retry hop le voi CUNG pin van thanh cong ==")
    conn = await asyncpg.connect(DB_URL)
    await _pin(conn, staff["id"])
    await conn.execute("SET ROLE alpha3s_m4_control_plane")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", True, "khong-ton-tai-retry-test")
        check(False, "set_capture(ON) voi approval khong ton tai -> phai RAISE (setup)")
    except asyncpg.PostgresError as e:
        check("approval" in str(e).lower() or "khong ton tai" in str(e) or "khong hop le" in str(e),
              "set_capture(ON) that bai vi approval khong ton tai (KHONG phai vi actor) - setup dung")
    retry_ok = await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", False, None)
    check(retry_ok is not None,
          "retry SAU 1 lan that bai (ly do KHAC actor) van dung DUOC CUNG pin (T7-01, chi hanh dong THANH CONG moi tieu thu)")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T6-04: normalization_registry APPEND-ONLY — UPDATE/DELETE truc tiep tren entry bi trigger chan ==")
    try:
        await admin.execute("UPDATE m4_stage0p_normalization_registry SET version='hacked' WHERE version='nfc-v1'")
        check(False, "UPDATE version tren registry entry -> phai bi trigger chan")
    except asyncpg.PostgresError as e:
        check("bat bien" in str(e), "UPDATE version bi trigger chan -> RAISE dung (T6-04)")
    try:
        await admin.execute("DELETE FROM m4_stage0p_normalization_registry WHERE version='nfc-v1'")
        check(False, "DELETE registry entry -> phai bi trigger chan")
    except asyncpg.PostgresError as e:
        check("append-only" in str(e), "DELETE registry entry bi trigger chan -> RAISE dung (T6-04)")

    print("== T6-04: set_current_normalization_version — doi hoi pinned actor + quyen approve; version trung -> RAISE ==")
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_current_normalization_version($1,$2)",
                            "nfc-v2-test", "PO-DECISION-001")
        check(False, "set_current_normalization_version MA CHUA pin -> phai RAISE")
    except asyncpg.PostgresError as e:
        check("chua pin actor" in str(e), "set_current_normalization_version chua pin -> RAISE dung (T6-04)")
    await conn.execute("RESET ROLE")
    await conn.close()

    print("== T8-03: normalization approval authority — approval_ref phai tro toi record THAT, dung version, con hieu luc, chua bi thu hoi ==")
    now_t803 = datetime.datetime.now(datetime.timezone.utc)

    conn = await asyncpg.connect(DB_URL)
    await _pin(conn, staff["id"])
    await conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_current_normalization_version($1,$2)",
                            "nfc-v2-test", "PO-DECISION-FORGED-NOTREAL")
        check(False, "approval_ref GIA MAO (khong ton tai) -> phai RAISE (T8-03)")
    except asyncpg.PostgresError as e:
        check("khong hop le" in str(e), "approval_ref gia mao -> RAISE dung (T8-03)")
    await conn.execute("RESET ROLE")
    await conn.close()

    norm_conn = await asyncpg.connect(DB_URL)
    await _record_normalization_approval(
        norm_conn, staff_id=staff["id"], approval_ref="perm-test-norm-approval-expired",
        requested_version="nfc-v2-test",
        valid_from=now_t803 - datetime.timedelta(days=2), valid_until=now_t803 - datetime.timedelta(days=1))
    await _record_normalization_approval(
        norm_conn, staff_id=staff["id"], approval_ref="perm-test-norm-approval-torevoke",
        requested_version="nfc-v2-test",
        valid_from=now_t803 - datetime.timedelta(hours=1), valid_until=now_t803 + datetime.timedelta(hours=1))
    norm_revoke_result = await _revoke_normalization_approval(
        norm_conn, staff_id=staff["id"], approval_ref="perm-test-norm-approval-torevoke",
        reason="permissions test rehearsal")
    check(norm_revoke_result["revoked_at"] is not None, "revoke_normalization_approval thanh cong (T8-03)")
    await _record_normalization_approval(
        norm_conn, staff_id=staff["id"], approval_ref="perm-test-norm-approval-wrongversion",
        requested_version="nfc-v3-does-not-match",
        valid_from=now_t803 - datetime.timedelta(hours=1), valid_until=now_t803 + datetime.timedelta(hours=1))
    await norm_conn.close()

    conn = await asyncpg.connect(DB_URL)
    await _pin(conn, staff["id"])
    await conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_current_normalization_version($1,$2)",
                            "nfc-v2-test", "perm-test-norm-approval-expired")
        check(False, "approval HET HAN -> phai RAISE (T8-03)")
    except asyncpg.PostgresError as e:
        check("khong hop le" in str(e), "approval het han -> RAISE dung (T8-03)")
    await conn.execute("RESET ROLE")
    await conn.close()

    conn = await asyncpg.connect(DB_URL)
    await _pin(conn, staff["id"])
    await conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_current_normalization_version($1,$2)",
                            "nfc-v2-test", "perm-test-norm-approval-torevoke")
        check(False, "approval DA BI THU HOI -> phai RAISE (T8-03)")
    except asyncpg.PostgresError as e:
        check("khong hop le" in str(e), "approval da bi thu hoi -> RAISE dung (T8-03)")
    await conn.execute("RESET ROLE")
    await conn.close()

    conn = await asyncpg.connect(DB_URL)
    await _pin(conn, staff["id"])
    await conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_current_normalization_version($1,$2)",
                            "nfc-v2-test", "perm-test-norm-approval-wrongversion")
        check(False, "approval hop le cho VERSION KHAC (khong phai nfc-v2-test) -> phai RAISE (T8-03)")
    except asyncpg.PostgresError as e:
        check("khong hop le" in str(e), "approval sai version -> RAISE dung (T8-03, khong the 'muon' approval)")
    await conn.execute("RESET ROLE")
    await conn.close()

    norm_conn2 = await asyncpg.connect(DB_URL)
    await _record_normalization_approval(
        norm_conn2, staff_id=staff["id"], approval_ref="perm-test-norm-approval-valid",
        requested_version="nfc-v2-test",
        valid_from=now_t803 - datetime.timedelta(hours=1), valid_until=now_t803 + datetime.timedelta(hours=1))
    await norm_conn2.close()

    conn = await asyncpg.connect(DB_URL)
    await _pin(conn, staff["id"])
    await conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    new_reg = await conn.fetchrow("SELECT * FROM m4_stage0p_set_current_normalization_version($1,$2)",
                                  "nfc-v2-test", "perm-test-norm-approval-valid")
    check(new_reg["version"] == "nfc-v2-test", "set_current_normalization_version thanh cong -> version moi tra ve dung")
    cur_row = await admin.fetchrow(
        "SELECT version FROM m4_stage0p_normalization_registry WHERE is_current")
    check(cur_row["version"] == "nfc-v2-test", "registry is_current chuyen dung sang version moi")
    old_row = await admin.fetchrow(
        "SELECT is_current FROM m4_stage0p_normalization_registry WHERE version='nfc-v1'")
    check(old_row["is_current"] is False, "version cu 'nfc-v1' van con (lich su bat bien), chi is_current=false")
    reg_approval_ref = await admin.fetchval(
        "SELECT approval_ref FROM m4_stage0p_normalization_registry WHERE version='nfc-v2-test'")
    check(reg_approval_ref == "perm-test-norm-approval-valid",
          "registry entry ghi dung approval_ref THAT da xac minh (T8-03, khong con 'khong rong' la du)")
    # REV8 T7-01: pin la consume-on-use — lan goi THANH CONG o tren da tieu thu pin, phai pin LAI
    # truoc khi goi tiep (khong con "1 pin dung nhieu lan" nhu REV7).
    await conn.execute("RESET ROLE")
    await _pin(conn, staff["id"])
    await conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    try:
        await conn.fetchrow("SELECT * FROM m4_stage0p_set_current_normalization_version($1,$2)",
                            "nfc-v2-test", "perm-test-norm-approval-valid")
        check(False, "set_current_normalization_version voi version DA TON TAI -> phai RAISE (T6-04)")
    except asyncpg.PostgresError as e:
        check("da ton tai" in str(e), "set_current_normalization_version version trung -> RAISE dung (T6-04)")
    await conn.execute("RESET ROLE")
    await conn.close()
    # khoi phuc registry ve 'nfc-v1' de khong anh huong gia tri seed mac dinh cho cac lan chay khac.
    await admin.execute("UPDATE m4_stage0p_normalization_registry SET is_current=false WHERE version='nfc-v2-test'")
    await admin.execute("UPDATE m4_stage0p_normalization_registry SET is_current=true WHERE version='nfc-v1'")
    await admin.execute(
        "DELETE FROM m4_stage0p_normalization_approval_revocations "
        "WHERE approval_ref LIKE 'perm-test-norm-approval-%' OR approval_ref = 'PO-DECISION-T703'")
    await admin.execute(
        "DELETE FROM m4_stage0p_normalization_approvals "
        "WHERE approval_ref LIKE 'perm-test-norm-approval-%' OR approval_ref = 'PO-DECISION-T703'")

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
    await admin.execute("DELETE FROM m4_stage0p_actor_session WHERE staff_id IN ($1,$2)",
                        staff["id"], staff_no_perm["id"])
    await admin.execute("DELETE FROM m4_stage0p_actor_credentials WHERE staff_id IN ($1,$2)",
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
