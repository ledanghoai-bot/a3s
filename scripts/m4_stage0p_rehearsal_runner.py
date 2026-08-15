#!/usr/bin/env python
"""I-B M4 Stage 0P — Internal Synthetic Rehearsal operational runner.

Dap lai `PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-REVIEW-1-VI.md`
(CHANGES_REQUIRED_ACTIVATION_NOT_AUTHORIZED) finding F-M4-RH-R1-04 — "Runner chua ton tai".
Script nay la 1 CONG CU MOI, KHONG sua bat ky file production da merge nao (khong dung
`stage0p_signing_service.py`/`stage0p_sampling.py`/migration 039 — chi GOI cac ham noi bo da
duoc CA nghiem thu qua cac Correction #1-#14, giong het cach cac evidence script
`scripts/m4_stage0p_*_test.py` da lam).

KHONG chay script nay tren production truoc khi:
  1. `PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-PACKAGE-2-VI.md` duoc CA chap nhan;
  2. PO phe duyet `approval_ref`/window/scope CU THE (xem subcommand `record-approval`);
  3. CA xac minh preconditions va mo Internal Synthetic Activation Gate.

3 nguyen tac thiet ke dap lai tung finding CA:

F-M4-RH-R1-01 (hard fence): `_seed_synthetic()` insert customers/conversations/messages TU
MANIFEST, ghi lai CHINH XAC cac ID Postgres vua cap — `lock_batch()` sau do CHI nhan danh sach ID
nay lam `selected` (KHONG goi `select_eligible_conversations` — ham do quet TOAN BO conversation
trong 1 cua so thoi gian, chinh la thu F-01 yeu cau tranh). Truoc khi bat capture,
`_assert_batch_isolated()` join lai `locked_conversation_ids` -> `customers.psid` va abort neu
count sai hoac bat ky psid nao khong dung tien to `PSID_PREFIX`.

F-M4-RH-R1-02 (key provisioning): dung DUNG 3 gia tri key_version code da hardcode (doc truc
tiep tu `app/services/pii/crypto.py` va `stage0p_signing_service.py`, KHONG tu dat ten moi):
`sample-aead-v1` (khong can provisioning DB, chi la nhan trong transcript), `sample-transcript-
hmac-v1` (bang `m4_stage0p_transcript_signing_keys`), `m4-signing-auth-v1` (bang
`m4_stage0p_signing_auth_keys`). `provision-keys`/`retire-keys` la thao tac ADMIN rieng (ket
noi qua chinh `DATABASE_URL` superuser, dung mo hinh voi 2 bang do da document "provisioning
NGOAI LUONG qua superuser, KHONG qua role/ham duoc GRANT").

F-M4-RH-R1-03 (labeling workflow): sau `close_collection`, `_label_samples()` doc lai tung
sample da capture qua `sample_id` (map nguoc tu conversation_key/message index da ghi luc seed),
UPDATE `labeled_slots`/`label_status='labeled'` bang GROUND TRUTH tu manifest (KHONG chay
detect() de tu sinh nhan - se lam evaluation tu cham diem chinh no), duoi vai `alpha3s_m4_
sample_reviewer_api` (reviewer principal RIENG, xem F-07), roi moi goi `seal_labels`.

F-M4-RH-R1-04 (runner): chinh file nay.

F-M4-RH-R1-05 (scope): mac dinh chay FULL LIFECYCLE (qua `run_prediction_writer` +
`complete_evaluation`) tren manifest >=220 gate-eligible (xem `m4_stage0p_gen_rehearsal_
manifest.py` REV2) — KHONG dung "chi seal" nua, tranh phai dung ca cai gate 10%/200.

F-M4-RH-R1-06 (Redis): `_postcheck_redis_nonces()` dung `SCAN` (khong phai `KEYS`) gioi han
dung 1 prefix `m4-signing-nonce:`, CHI de XAC MINH (khong xoa) - nonce tu het han qua TTL da co
san (xem `stage0p_signing_service.py` `_NONCE_TTL_BUFFER_SECONDS`), khong bao gio DEL blind.

F-M4-RH-R1-07 (principal separation): 3 credential doc lap bat buoc qua CLI/env RIENG -
`--approval-staff-id` (subcommand `record-approval`), `--operator-staff-id`, `--reviewer-staff-id`
(subcommand `run`) - runner tu choi ngay neu 2 staff_id nao trung nhau (xem `_assert_distinct_
principals`). pin_secret CHI doc tu bien moi truong (khong bao gio nhan qua CLI argument -
tranh lo trong process list/shell history), va khong bao gio duoc log/in ra.

Usage:
    # Buoc 1 (do approval recorder/PO thuc hien, credential RIENG):
    STAGE0P_REHEARSAL_APPROVAL_PIN=... python scripts/m4_stage0p_rehearsal_runner.py \\
        record-approval --approval-staff-id 101 --approval-ref m4-rehearsal-2026-08-12 \\
        --valid-from 2026-08-12T01:00:00+00:00 --valid-until 2026-08-12T11:00:00+00:00

    # Buoc 2 (do operator - Dev - thuc hien, credential RIENG cho tung vai tro):
    STAGE0P_REHEARSAL_OPERATOR_PIN=... STAGE0P_REHEARSAL_REVIEWER_PIN=... \\
    M4_SAMPLE_KEY_B64=... M4_TRANSCRIPT_HMAC_KEY_B64=... M4_SIGNING_AUTH_VERIFY_KEY_B64=... \\
        python scripts/m4_stage0p_rehearsal_runner.py provision-keys

    # Preflight (KHONG ghi gi):
        python scripts/m4_stage0p_rehearsal_runner.py run --dry-run \\
        --manifest datasets/pii/m4_stage0p_rehearsal_manifest_v2.jsonl \\
        --approval-ref m4-rehearsal-2026-08-12 --operator-staff-id 102 --reviewer-staff-id 103

    # Execute that (bo --dry-run) - PHAI trong approval window da duyet:
        python scripts/m4_stage0p_rehearsal_runner.py run ... (bo --dry-run)

    # Cuoi cung:
        python scripts/m4_stage0p_rehearsal_runner.py retire-keys
        python scripts/m4_stage0p_rehearsal_runner.py record-approval --revoke ...
"""

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# --- exact key_version constants (F-M4-RH-R1-02) — DOC TRUC TIEP tu code da merge, khong tu bia. ---
from app.services.pii.crypto import (  # noqa: E402
    ENCRYPTION_KEY_VERSION,
    TRANSCRIPT_KEY_VERSION,
)
from app.services.pii.stage0p_control import (  # noqa: E402
    ActorNotPinnedError,
    ApprovalRejectedError,
    read_capture_enabled,
    record_capture_approval,
    revoke_capture_approval,
    set_capture_enabled,
)
from app.services.pii.stage0p_evaluation import (  # noqa: E402
    complete_evaluation,
    seal_labels,
)
from app.services.pii.stage0p_pool import (  # noqa: E402
    Stage0PBusinessRole,
    create_stage0p_pool,
    pinned_actor_session,
)
from app.services.pii.stage0p_prediction import (  # noqa: E402
    PredictionNotAllowedError,
    run_prediction_writer,
)
from app.services.pii.stage0p_sampling import (  # noqa: E402
    MAX_CONVERSATIONS,
    PURPOSE_CODE,
    RETENTION_DAYS,
    SELECTION_SEED_LABEL,
    get_current_normalization_version,
    run_collector,
)
from app.services.pii.stage0p_signing_service import (  # noqa: E402
    _SIGNING_AUTH_KEY_VERSION,
)

PSID_PREFIX = "m4synthrehearsalv1_"
KEY_LEN = 32  # khop app/services/pii/crypto.py _KEY_LEN
NONCE_PREFIX = "m4-signing-nonce:"
EVALUATION_BATCH_LABEL = "m4-stage0p-rehearsal-eval-v1"


def _log(event: str, **fields) -> None:
    print("[m4-rehearsal-runner] " + json.dumps({"event": event, **fields},
                                                  ensure_ascii=False, sort_keys=True, default=str))


# F-EX-B2-01/02 (Amendment 07 Execution Blocker 1): truoc day ham nay tra nguyen DATABASE_URL
# cho asyncpg.connect()/create_pool() - loi giong het `m4_stage0p_provision_pin.py` truoc PR #9,
# nhung bi bo sot vi 2 tool co 2 ban sao rieng cua cung 1 logic. Gio dung CHUNG 1 nguon
# (m4_dsn_utils.py) voi PIN tool - sua 1 lan, ca 2 tool tu dong nhat quan.
from m4_dsn_utils import normalized_db_url as _db_url  # noqa: E402


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://redis:6379/0")


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"thieu bien moi truong bat buoc {name} (khong bao gio nhan qua CLI arg)")
    return val


def _assert_distinct_principals(*staff_ids: int) -> None:
    if len(set(staff_ids)) != len(staff_ids):
        raise SystemExit(
            f"F-M4-RH-R1-07: cac staff_id PHAI phan biet (approval recorder != operator != "
            f"reviewer) - nhan duoc {staff_ids}, co gia tri trung nhau")


async def _check_approval_active(conn, approval_ref: str) -> tuple[bool, int | None, list[str]]:
    """F-M4-RH-R2-02/03: doc lai approval record THAT (ai record + cua so hieu luc) tu DB —
    dung CHUNG cho dry-run VA execute (execute PHAI kiem tra lai NGAY TRUOC khi bat capture,
    khong chi dua vao 1 lan dry-run truoc do co the da cu). Tra (ok, recorded_by, problems) —
    `recorded_by` dung de doi chieu principal (F-R2-02: approval recorder phai KHAC operator/
    reviewer THAT, khong chi 2 CLI argument tu khai)."""
    row = await conn.fetchrow(
        "SELECT a.recorded_by, a.requested_enabled, a.valid_from, a.valid_until, "
        "EXISTS(SELECT 1 FROM m4_stage0p_capture_approval_revocations r "
        "       WHERE r.approval_ref = a.approval_ref) AS revoked "
        "FROM m4_stage0p_capture_approvals a WHERE a.approval_ref = $1 "
        "AND a.purpose_code = $2", approval_ref, PURPOSE_CODE)
    if row is None:
        return False, None, ["khong tim thay approval_ref hop le (chua record hoac sai purpose_code)"]
    problems = []
    if row["revoked"]:
        problems.append("approval_ref da bi thu hoi")
    if not row["requested_enabled"]:
        problems.append("approval_ref khong phai loai requested_enabled=true - khong the dung bat capture")
    now = datetime.now(timezone.utc)
    if now < row["valid_from"]:
        problems.append(f"approval_ref CHUA bat dau hieu luc (valid_from={row['valid_from'].isoformat()}, "
                        f"now={now.isoformat()})")
    if now >= row["valid_until"]:
        problems.append(f"approval_ref DA het han (valid_until={row['valid_until'].isoformat()}, "
                        f"now={now.isoformat()})")
    return (len(problems) == 0), row["recorded_by"], problems


def _principal_conflict_problems(*staff_ids: int) -> list[str]:
    """Phien ban KHONG raise cua `_assert_distinct_principals` — dung trong dry-run de gom vao
    danh sach `problems` thay vi thoat ngay, giu duoc bao cao day du tat ca van de cung luc."""
    if len(set(staff_ids)) != len(staff_ids):
        return [f"F-M4-RH-R1-07/R2-02: staff_id trung nhau giua cac principal - {staff_ids}"]
    return []


def _cap_a_problem(manifest: list[dict]) -> str | None:
    """F-A13-01/F-A13-02 (dap PHASE1B-M4-AMENDMENT-13-EXECUTION-ABORT-REVIEW-1/2-VI.md).

    Cap A ("hard cap 260 hoi thoai") la MOT BIEN PHAP BAO VE QUYEN RIENG TU da duoc duyet
    (F-M4-0P-03, PHASE1B-M4-STAGE-0P-GOVERNANCE-CORRECTION-1-VI.md), enforce o 2 tang:
    `MAX_CONVERSATIONS` trong stage0p_sampling.py VA `CHECK (selected_count <= 260)` tren
    m4_selection_batches.

    VI SAO CAN HAM NAY — runner CO Y KHONG goi `select_sample()` (xem `_run_execute`: lock batch
    qua allowlist tracked theo fence F-01, khong `select_eligible_conversations`). Nhung
    `select_sample()` CHINH LA cho ap Cap A o tang Python. Bo qua no => Cap A khong con duoc
    enforce truoc khi ghi, va DB constraint chi chan tai INSERT m4_selection_batches — tuc la
    GIUA lifecycle, SAU khi da seed toan bo manifest va da bat capture (chinh xac dieu da xay ra
    o Amendment 13: seed 315 hang, capture ON, roi moi CheckViolationError).

    Doc TRUC TIEP `MAX_CONVERSATIONS` tu stage0p_sampling — mot nguon su that duy nhat. Neu Cap A
    doi (chi qua PO decision rieng), ca dry-run lan execute tu dong theo, khong co so 260 nao bi
    hard-code lai o day de lech nhau.

    Tra ve `None` neu dat, hoac chuoi mo ta van de. Ban KHONG raise nay dung cho dry-run (gom vao
    `problems`); `_run_execute` raise SystemExit TRUOC MOI write.
    """
    n = len(manifest)
    if n > MAX_CONVERSATIONS:
        return (f"manifest co {n} conversation, VUOT Cap A (MAX_CONVERSATIONS="
                f"{MAX_CONVERSATIONS}) - day la bien phap bao ve quyen rieng tu da duoc duyet "
                f"(F-M4-0P-03), khong phai gioi han ky thuat tuy chinh duoc. Runner chi lock 1 "
                f"batch/lifecycle nen selected_count = {n} se vi pham CHECK m4_batch_count_valid. "
                f"Can manifest <= {MAX_CONVERSATIONS}, hoac mot path da duoc CA/PO duyet rieng "
                f"(multi-batch, hoac quyet dinh thay Cap A).")
    return None


# ===========================================================================
# record-approval — do approval recorder (PO hoac staff PO chi dinh) thuc hien, TACH BIET
# khoi operator/reviewer. Runner KHONG tu goi ham nay trong luong `run` (F-07: "runner khong
# duoc tu record approval bang credential cua control operator").
# ===========================================================================

async def cmd_record_approval(args) -> int:
    pin = _require_env("STAGE0P_REHEARSAL_APPROVAL_PIN")
    pool = await create_stage0p_pool(_db_url())
    try:
        async with pinned_actor_session(
            pool, staff_id=args.approval_staff_id, pin_secret=pin,
            business_role=Stage0PBusinessRole.APPROVAL_RECORDER,
        ) as conn:
            if args.revoke:
                revoked_at = await revoke_capture_approval(
                    conn, approval_ref=args.approval_ref, reason=args.reason or "rehearsal window closed")
                _log("approval_revoked", approval_ref=args.approval_ref, revoked_at=revoked_at)
            else:
                valid_from = datetime.fromisoformat(args.valid_from)
                valid_until = datetime.fromisoformat(args.valid_until)
                ref = await record_capture_approval(
                    conn, approval_ref=args.approval_ref, requested_enabled=True,
                    valid_from=valid_from, valid_until=valid_until, note=args.note)
                _log("approval_recorded", approval_ref=ref,
                     valid_from=valid_from.isoformat(), valid_until=valid_until.isoformat())
        return 0
    except (ApprovalRejectedError, ActorNotPinnedError) as e:
        _log("record_approval_failed", error=str(e))
        return 1
    finally:
        await pool.close()


# ===========================================================================
# provision-keys / retire-keys — thao tac ADMIN (superuser DSN), TACH BIET khoi moi role M4.
# ===========================================================================

async def cmd_provision_keys(args) -> int:
    sample_key_b64 = _require_env("M4_SAMPLE_KEY_B64")
    transcript_key_b64 = _require_env("M4_TRANSCRIPT_HMAC_KEY_B64")
    auth_key_b64 = _require_env("M4_SIGNING_AUTH_VERIFY_KEY_B64")
    for name, val in (("M4_SAMPLE_KEY_B64", sample_key_b64),
                      ("M4_TRANSCRIPT_HMAC_KEY_B64", transcript_key_b64),
                      ("M4_SIGNING_AUTH_VERIFY_KEY_B64", auth_key_b64)):
        if len(base64.b64decode(val, validate=True)) != KEY_LEN:
            raise SystemExit(f"{name}: phai la {KEY_LEN} byte sau khi decode base64")

    conn = await asyncpg.connect(_db_url())
    try:
        existing_transcript = await conn.fetchrow(
            "SELECT key_version, retired_at FROM m4_stage0p_transcript_signing_keys "
            "WHERE key_version = $1", TRANSCRIPT_KEY_VERSION)
        if existing_transcript is not None and existing_transcript["retired_at"] is None:
            raise SystemExit(
                f"m4_stage0p_transcript_signing_keys: key_version {TRANSCRIPT_KEY_VERSION!r} "
                "DA active - tu choi ghi de am tham (F-M4-RH-R1-02). Retire truoc neu can rotate.")
        existing_auth = await conn.fetchrow(
            "SELECT key_version, retired_at FROM m4_stage0p_signing_auth_keys "
            "WHERE key_version = $1", _SIGNING_AUTH_KEY_VERSION)
        if existing_auth is not None and existing_auth["retired_at"] is None:
            raise SystemExit(
                f"m4_stage0p_signing_auth_keys: key_version {_SIGNING_AUTH_KEY_VERSION!r} "
                "DA active - tu choi ghi de am tham (F-M4-RH-R1-02). Retire truoc neu can rotate.")

        async with conn.transaction():
            await conn.execute(
                "INSERT INTO m4_stage0p_transcript_signing_keys (key_version, hmac_key) "
                "VALUES ($1, $2) ON CONFLICT (key_version) DO UPDATE "
                "SET hmac_key = EXCLUDED.hmac_key, retired_at = NULL, created_at = now() "
                "WHERE m4_stage0p_transcript_signing_keys.retired_at IS NOT NULL",
                TRANSCRIPT_KEY_VERSION, base64.b64decode(transcript_key_b64, validate=True))
            await conn.execute(
                "INSERT INTO m4_stage0p_signing_auth_keys (key_version, hmac_key) "
                "VALUES ($1, $2) ON CONFLICT (key_version) DO UPDATE "
                "SET hmac_key = EXCLUDED.hmac_key, retired_at = NULL, created_at = now() "
                "WHERE m4_stage0p_signing_auth_keys.retired_at IS NOT NULL",
                _SIGNING_AUTH_KEY_VERSION, base64.b64decode(auth_key_b64, validate=True))
        _log("keys_provisioned", transcript_key_version=TRANSCRIPT_KEY_VERSION,
             signing_auth_key_version=_SIGNING_AUTH_KEY_VERSION,
             encryption_key_version_label=ENCRYPTION_KEY_VERSION,
             note="encryption key (M4_SAMPLE_KEY_B64) khong can provisioning DB - chi la nhan "
                  "trong transcript, gia tri that chi song trong bien moi truong signing service")
        return 0
    finally:
        await conn.close()


async def _retire_key(conn, table: str, key_version: str) -> bool:
    result = await conn.execute(
        f"UPDATE {table} SET retired_at = now() WHERE key_version = $1 AND retired_at IS NULL",
        key_version)
    return result.endswith(" 1")


async def cmd_retire_keys(args) -> int:
    conn = await asyncpg.connect(_db_url())
    try:
        t = await _retire_key(conn, "m4_stage0p_transcript_signing_keys", TRANSCRIPT_KEY_VERSION)
        a = await _retire_key(conn, "m4_stage0p_signing_auth_keys", _SIGNING_AUTH_KEY_VERSION)
        _log("keys_retired", transcript_retired_now=t, signing_auth_retired_now=a,
             note="idempotent - false nghia la da retired tu truoc hoac chua tung provision")
        return 0
    finally:
        await conn.close()


# ===========================================================================
# run — preflight (--dry-run) hoac execute full lifecycle.
# ===========================================================================

class RehearsalState:
    """Theo doi TOAN BO ID/nonce da tao trong 1 lan chay - purge/cleanup CHI dung danh sach
    tracked nay (F-M4-RH-R1-01: khong bao gio purge bang truy van marker-based rong sau khi da
    co danh sach chinh xac trong tay)."""

    def __init__(self):
        self.customer_ids: list[int] = []
        self.conversation_ids: list[int] = []
        self.message_ids: list[int] = []
        self.conversation_id_to_customer_id: dict[int, int] = {}
        self.conversation_key_to_conversation_id: dict[str, int] = {}
        self.message_key_to_message_id: dict[tuple, int] = {}  # (conv_key, msg_index) -> message_id
        self.batch_id: str | None = None
        self.capture_turned_on: bool = False


def _load_manifest(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    seen_psid = set()
    seen_conv_key = set()
    for r in records:
        if not r["psid"].startswith(PSID_PREFIX):
            raise SystemExit(f"manifest psid {r['psid']!r} khong dung tien to {PSID_PREFIX!r}")
        if r["psid"] in seen_psid:
            raise SystemExit(f"manifest psid trung lap: {r['psid']!r}")
        seen_psid.add(r["psid"])
        # F-V4-01: `conversation_key` PHAI duy nhat — chot nay truoc day thieu, trong khi psid da
        # co. `_seed_synthetic` luu `state.conversation_key_to_conversation_id[key] = conv_id`
        # (DICT), nen key trung khien ban SAU ghi de ban TRUOC va lam MAT conversation_id khoi
        # map; toi `_label_samples`, `conv_key_by_id.get(conv_id)` tra None va runner raise
        # "FENCE FAIL: ... khong nam trong danh sach synthetic tracked". Fail-closed (khong gan
        # nhan sai) nhung thong bao DO LOI CHO FENCE, che mat nguyen nhan that la manifest.
        # Manifest v3 that su co 38 key trung (generator v3 tai dung prefix RB/RC cua v2); loi do
        # chua kip lo vi Amendment 13 abort o lock_batch, TRUOC buoc labeling.
        if r["conversation_key"] in seen_conv_key:
            raise SystemExit(
                f"manifest conversation_key trung lap: {r['conversation_key']!r} - runner map "
                "conversation_key -> conversation_id bang dict nen key trung se lam mat "
                "conversation va abort nham o buoc labeling (F-V4-01)")
        seen_conv_key.add(r["conversation_key"])
    return records


async def _seed_synthetic(admin_conn, manifest: list[dict], state: RehearsalState) -> None:
    """Insert customers/conversations/messages TU MANIFEST — TRACK moi ID Postgres cap. Chi tao
    trong 1 transaction DUY NHAT (all-or-nothing) qua admin connection (base app role, co quyen
    ghi truc tiep len customers/conversations/messages nhu bat ky luong nghiep vu binh thuong
    nao khac — KHONG can quyen M4 dac biet cho buoc nay)."""
    async with admin_conn.transaction():
        for record in manifest:
            cust = await admin_conn.fetchrow(
                "INSERT INTO customers (psid, name) VALUES ($1, $2) RETURNING id",
                record["psid"], "M4 REHEARSAL SYNTHETIC — KHONG PHAI KHACH THAT")
            cust_id = cust["id"]
            state.customer_ids.append(cust_id)

            conv = await admin_conn.fetchrow(
                "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id",
                cust_id)
            conv_id = conv["id"]
            state.conversation_ids.append(conv_id)
            state.conversation_id_to_customer_id[conv_id] = cust_id
            state.conversation_key_to_conversation_id[record["conversation_key"]] = conv_id

            for msg_idx, msg in enumerate(record["messages"]):
                msg_row = await admin_conn.fetchrow(
                    "INSERT INTO messages (conversation_id, role, content, created_at) "
                    "VALUES ($1, $2, $3, now()) RETURNING id",
                    conv_id, msg["role"], msg["content"])
                state.message_ids.append(msg_row["id"])
                state.message_key_to_message_id[(record["conversation_key"], msg_idx)] = msg_row["id"]

    _log("synthetic_seeded", customers=len(state.customer_ids),
         conversations=len(state.conversation_ids), messages=len(state.message_ids))


async def _assert_batch_isolated(admin_conn, state: RehearsalState) -> None:
    """F-M4-RH-R1-01 hard fence: join locked_conversation_ids -> customers.psid, assert count
    CHINH XAC va MOI psid dung tien to synthetic — abort truoc khi bat capture neu bat ky mismatch
    nao. Day la defense-in-depth: co che CHINH la KHONG BAO GIO truy van production theo cua so
    thoi gian (xem _seed_synthetic — `selected` cho lock_batch chi den tu danh sach tracked)."""
    rows = await admin_conn.fetch(
        "SELECT c.id AS conversation_id, cu.psid FROM conversations c "
        "JOIN customers cu ON cu.id = c.customer_id WHERE c.id = ANY($1::bigint[])",
        state.conversation_ids)
    if len(rows) != len(state.conversation_ids):
        raise SystemExit(
            f"FENCE FAIL: {len(state.conversation_ids)} conversation ID tracked nhung chi tim "
            f"thay {len(rows)} row - abort truoc khi bat capture")
    bad = [r["conversation_id"] for r in rows if not r["psid"].startswith(PSID_PREFIX)]
    if bad:
        raise SystemExit(
            f"FENCE FAIL: {len(bad)} conversation KHONG mang psid synthetic "
            f"(conversation_id={bad}) - abort truoc khi bat capture, tu choi tuyet doi")
    _log("fence_assertion_passed", conversation_count=len(rows))


async def _label_samples(reviewer_conn, manifest: list[dict], state: RehearsalState) -> int:
    """F-M4-RH-R1-03: doc lai sample da capture (qua batch_id + customer_ref/conversation_ref =
    str(id) - dung quy uoc DB da derive, xem migration 039), map nguoc ve conversation_key/
    message index qua state, ghi labeled_slots = GROUND TRUTH tu manifest (KHONG chay detect()).
    `reviewer_conn` PHAI da SET ROLE alpha3s_m4_sample_reviewer_api (qua pinned_actor_session)."""
    # sample_id khong duoc tra ve tu run_collector (chi tra so lieu tong hop) — doc lai qua
    # batch + conversation_ref/customer_ref (ca hai DB tu derive = str(id), doc duoc vi role
    # reviewer co GRANT SELECT sample_id/customer_ref/conversation_ref, xem migration 039 §6).
    rows = await reviewer_conn.fetch(
        "SELECT sample_id, customer_ref, conversation_ref FROM m4_shadow_review_samples "
        "WHERE selection_batch = $1", state.batch_id)
    by_conv_id: dict[int, list] = {}
    for r in rows:
        by_conv_id.setdefault(int(r["conversation_ref"]), []).append(r)

    conv_key_by_id = {v: k for k, v in state.conversation_key_to_conversation_id.items()}
    labeled_count = 0
    for conv_id, sample_rows in by_conv_id.items():
        conv_key = conv_key_by_id.get(conv_id)
        if conv_key is None:
            raise SystemExit(f"FENCE FAIL: sample thuoc conversation_id={conv_id} khong nam "
                             "trong danh sach synthetic tracked - abort labeling")
        manifest_record = next(r for r in manifest if r["conversation_key"] == conv_key)
        # m4_shadow_review_samples KHONG co cot message_id (chi customer_ref/conversation_ref) -
        # neu 1 conversation co >1 message role='customer', seed_capture_progress() se capture
        # CA HAI (toi da 20/conversation), nhung khong the anh xa nguoc sample nao khop message
        # nao chi qua conversation_ref. De tranh mo ho, MOI conversation trong manifest generator
        # (m4_stage0p_gen_rehearsal_manifest.py REV2) CHI co DUNG 1 message - assert ngay o day
        # thay vi am tham gia dinh, phong truong hop manifest sau nay drift khoi bat bien nay.
        if len(manifest_record["messages"]) != 1:
            raise SystemExit(
                f"MANIFEST INVARIANT VIOLATED: conversation {conv_key!r} co "
                f"{len(manifest_record['messages'])} message, runner chi ho tro DUNG 1 "
                "message/conversation (xem docstring _label_samples)")
        if len(sample_rows) != 1:
            raise SystemExit(
                f"MANIFEST INVARIANT VIOLATED: conversation {conv_key!r} co "
                f"{len(sample_rows)} sample captured, ky vong DUNG 1 - kiem tra "
                "seed_capture_progress co capture nham message khac role 'customer' nao khong")
        msg = manifest_record["messages"][0]
        for sample in sample_rows:
            await reviewer_conn.execute(
                "UPDATE m4_shadow_review_samples SET labeled_slots = $1::jsonb, "
                "label_status = 'labeled' WHERE sample_id = $2",
                json.dumps(msg["labeled_slots"]), sample["sample_id"])
            labeled_count += 1
    return labeled_count


async def _postcheck_redis_nonces(window_seconds: float) -> dict:
    """F-M4-RH-R1-06: bounded SCAN (KHONG dung KEYS chan production Redis), CHI de XAC MINH
    khong con nonce nao con hieu luc con lai sau rehearsal — khong DELETE (nonce tu het han qua
    TTL da co san, `_NONCE_TTL_BUFFER_SECONDS` trong stage0p_signing_service.py)."""
    import redis.asyncio as aioredis
    redis = await aioredis.from_url(_redis_url(), decode_responses=True, socket_timeout=5.0)
    try:
        remaining = []
        cursor = 0
        scanned = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"{NONCE_PREFIX}*", count=100)
            scanned += len(keys)
            remaining.extend(keys)
            if cursor == 0 or scanned > 100_000:  # backstop cung, khong bao gio quet vo han
                break
        ttls = {}
        for k in remaining[:50]:  # gioi han so lan goi TTL rieng, chi lay mau bao cao
            ttls[k] = await redis.ttl(k)
        return {"remaining_count": len(remaining), "sample_ttls": ttls}
    finally:
        await redis.aclose()


async def _terminalize_batch(admin_conn, state: RehearsalState) -> str | None:
    """F-A08-EXEC-02/A08-COR-02: doi batch TRACKED (chi dung state.batch_id, khong wildcard) sang
    trang thai terminal 'aborted' khi lifecycle THAT BAI truoc khi toi 'evaluation_completed' —
    KHONG xoa hang (giu lam audit trail, cung triet ly voi approval/token lich su), va tuyet doi
    khong dong vao 1 batch DA thanh cong that su (status<>'evaluation_completed' trong WHERE la
    fail-closed predicate duy nhat can, vi batch_id la PK nen toi da 1 hang khop). Idempotent
    (status<>'aborted' tranh ghi de aborted_at neu goi lai). Tra ve status SAU cung (None neu
    khong co batch_id hoac khong hang nao khop - vd batch da 'evaluation_completed')."""
    if not state.batch_id:
        return None
    row = await admin_conn.fetchrow(
        "UPDATE m4_selection_batches SET status = 'aborted', aborted_at = now() "
        "WHERE batch_id = $1 AND status NOT IN ('evaluation_completed', 'aborted') "
        "RETURNING status",
        state.batch_id)
    if row is not None:
        return row["status"]
    return await admin_conn.fetchval(
        "SELECT status FROM m4_selection_batches WHERE batch_id = $1", state.batch_id)


async def _purge_synthetic(admin_conn, state: RehearsalState) -> dict:
    """Purge THEO DANH SACH ID TRACKED (khong phai truy van marker-based rong lai) — an toan du
    batch dang o bat ky trang thai nao (idempotent, chay duoc kha ca khi 1 buoc truoc do that
    bai giua chung)."""
    counts = {}
    if state.batch_id:
        r = await admin_conn.execute(
            "DELETE FROM m4_shadow_review_samples WHERE selection_batch = $1", state.batch_id)
        counts["samples"] = r
        r = await admin_conn.execute(
            "DELETE FROM m4_stage0p_capture_progress WHERE batch_id = $1", state.batch_id)
        counts["capture_progress"] = r
    if state.message_ids:
        r = await admin_conn.execute(
            "DELETE FROM messages WHERE id = ANY($1::bigint[])", state.message_ids)
        counts["messages"] = r
    if state.conversation_ids:
        r = await admin_conn.execute(
            "DELETE FROM conversations WHERE id = ANY($1::bigint[])", state.conversation_ids)
        counts["conversations"] = r
    if state.customer_ids:
        r = await admin_conn.execute(
            "DELETE FROM customers WHERE id = ANY($1::bigint[])", state.customer_ids)
        counts["customers"] = r
    _log("purge_done", **counts)
    return counts


# Self-discovered qua evidence chay that (scripts/m4_stage0p_rehearsal_runner_test.py scenario
# [6]): signing service co admission rate limit (_RATE_LIMIT_MAX_REQUESTS/_RATE_LIMIT_WINDOW_
# SECONDS trong stage0p_signing_service.py, T13-03 - 40 request/10s). `run_collector()` (goc,
# stage0p_sampling.py, KHONG sua) xu ly TUAN TU va crash NGAY (raise thang, khong catch) neu 1
# request bi tu choi/reset boi rate limit — `asyncio.wait_for` trong no CHI bat
# `asyncio.TimeoutError`, khong bat `ConnectionResetError`. Voi manifest >=220 message, tien
# trinh xu ly tuan tu THUONG nhanh hon toc do sustained ma rate limit cho phep, nen 1 lan chay
# DUY NHAT gan nhu chac chan cham gioi han truoc khi xong toan bo batch.
COLLECTOR_MAX_ATTEMPTS = 40
COLLECTOR_RETRY_BACKOFF_SECONDS = 11.0  # > _RATE_LIMIT_WINDOW_SECONDS (10s) ben signing service


async def _pending_candidate_count(conn, batch_id) -> int:
    return await conn.fetchval(
        "SELECT count(*) FROM m4_stage0p_capture_progress WHERE batch_id = $1 "
        "AND status IN ('pending', 'retryable_failed')", batch_id)


async def _run_collector_with_retry(batch_id) -> dict:
    """Boc `run_collector()` bang retry-with-backoff O TANG RUNNER (khong sua code goc) — goi
    lai NHIEU LAN, moi lan tiep tuc tu `m4_stage0p_capture_progress` con lai (idempotent: seed
    chi chay 1 lan o lan goi dau, candidate da 'committed' khong bao gio bi xu ly lai), nghi
    `COLLECTOR_RETRY_BACKOFF_SECONDS` giua cac lan de cua so rate-limit ben signing service troi
    qua. Dung lai (khong retry vo han) neu 2 lan lien tiep KHONG giam duoc so pending — dau hieu
    loi THAT (vd socket sai cau hinh), khong phai rate-limit tam thoi."""
    last_result = None
    prev_pending = None
    stall_count = 0
    for attempt in range(1, COLLECTOR_MAX_ATTEMPTS + 1):
        collector_conn = await asyncpg.connect(_db_url())
        pending_conn = await asyncpg.connect(_db_url())
        try:
            await collector_conn.execute("SET ROLE alpha3s_m4_sample_collector")
            await pending_conn.execute("SET ROLE alpha3s_m4_pending_checker")
            last_result = await run_collector(collector_conn, pending_conn, batch_id=batch_id)
        except Exception as e:  # noqa: BLE001 — se retry o vong lap ngoai, log ro nguyen nhan
            _log("collector_attempt_raised", attempt=attempt, error_type=type(e).__name__, error=str(e))
        finally:
            await collector_conn.close()
            await pending_conn.close()

        if last_result is not None and last_result.get("collection_closed"):
            return last_result

        check_conn = await asyncpg.connect(_db_url())
        try:
            pending_now = await _pending_candidate_count(check_conn, batch_id)
        finally:
            await check_conn.close()
        _log("collector_retry_status", attempt=attempt, pending_remaining=pending_now)
        if pending_now == 0:
            # Het candidate pending/retryable nhung collection_closed van chua True (vd toan bo
            # con lai la permanent_failed) — tra ve ket qua cuoi cung da co, caller (_run_execute)
            # tu quyet dinh buoc tiep theo qua kiem tra permanent_failed/collection_closed.
            return last_result or {"inserted": 0, "skipped_pending": 0, "truncated": 0,
                                   "aborted_control_off": False, "lock_failed": False,
                                   "fence_timeout": False, "permanent_failed": 0,
                                   "collection_closed": False}
        if prev_pending is not None and pending_now >= prev_pending:
            stall_count += 1
        else:
            stall_count = 0
        prev_pending = pending_now
        if stall_count >= 2:
            raise SystemExit(
                f"COLLECTOR FAIL: {pending_now} candidate con pending nhung KHONG giam qua 2 "
                "lan retry lien tiep - day KHONG con la rate-limit tam thoi, dau hieu loi THAT "
                "(kiem tra signing service/socket con hoat dong khong) - abort thay vi retry vo han")
        await asyncio.sleep(COLLECTOR_RETRY_BACKOFF_SECONDS)
    raise SystemExit(f"COLLECTOR FAIL: het {COLLECTOR_MAX_ATTEMPTS} lan retry, van con candidate "
                     "chua xu ly xong - abort")


async def _verify_cleanup_postconditions(
        admin_conn, state: RehearsalState, *, lifecycle_failed: bool) -> tuple[bool, list[str]]:
    """F-M4-RH-R2-01: xac minh HAU DIEU KIEN bat buoc bang truy van DOC LAP sau khi cleanup da
    chay — KHONG tin vao viec tung buoc cleanup "khong nem loi" (buoc do co the tu no thanh cong
    nhung van de lai residual vi ly do khac, hoac nguoc lai bi nuot loi ma khong ai biet). Day la
    nguon su that DUY NHAT quyet dinh cleanup co THAT SU dat trang thai an toan hay khong.

    F-A08-EXEC-02/A08-COR-03: them kiem tra batch TRACKED phai o dung trang thai terminal — neu
    `lifecycle_failed`, batch (neu co) PHAI la 'aborted' (khong con 'locked'/'collecting'/... —
    day CHINH LA lop kiem da bi thieu o Amendment 08, khien residual 'locked' lot qua ma khong ai
    biet). Neu lifecycle THANH CONG, batch phai la 'evaluation_completed' — bat ky trang thai
    khac deu la dau hieu 1 buoc nao do trong luong thanh cong khong thuc su hoan tat du khong
    raise loi ro rang."""
    problems: list[str] = []
    if await read_capture_enabled(admin_conn):
        problems.append("capture_enabled VAN la true sau cleanup")
    if state.customer_ids:
        n = await admin_conn.fetchval(
            "SELECT count(*) FROM customers WHERE id = ANY($1::bigint[])", state.customer_ids)
        if n:
            problems.append(f"con {n}/{len(state.customer_ids)} customer synthetic (ID tracked cua "
                            "chinh lan chay nay) chua bi purge")
    if state.conversation_ids:
        n = await admin_conn.fetchval(
            "SELECT count(*) FROM conversations WHERE id = ANY($1::bigint[])", state.conversation_ids)
        if n:
            problems.append(f"con {n} conversation synthetic (ID tracked) chua bi purge")
    if state.batch_id:
        n = await admin_conn.fetchval(
            "SELECT count(*) FROM m4_shadow_review_samples WHERE selection_batch = $1", state.batch_id)
        if n:
            problems.append(f"con {n} sample chua bi purge cho batch {state.batch_id}")
        batch_status = await admin_conn.fetchval(
            "SELECT status FROM m4_selection_batches WHERE batch_id = $1", state.batch_id)
        expected_status = "aborted" if lifecycle_failed else "evaluation_completed"
        if batch_status != expected_status:
            problems.append(
                f"batch {state.batch_id} o trang thai {batch_status!r}, ky vong {expected_status!r} "
                f"(lifecycle_failed={lifecycle_failed}) - residual batch chua terminalize dung")
    n = await admin_conn.fetchval(
        "SELECT count(*) FROM m4_stage0p_transcript_signing_keys "
        "WHERE key_version = $1 AND retired_at IS NULL", TRANSCRIPT_KEY_VERSION)
    if n:
        problems.append("transcript signing key CHUA duoc retire")
    n = await admin_conn.fetchval(
        "SELECT count(*) FROM m4_stage0p_signing_auth_keys "
        "WHERE key_version = $1 AND retired_at IS NULL", _SIGNING_AUTH_KEY_VERSION)
    if n:
        problems.append("signing-auth key CHUA duoc retire")
    return (len(problems) == 0), problems


async def _do_cleanup(admin_conn, pool, *, operator_staff_id: int, operator_pin: str,
                      state: RehearsalState, lifecycle_failed: bool) -> dict[str, bool]:
    """5 buoc cleanup, best-effort — tra dict step->bool. TACH RIENG khoi _run_execute() (F-M4-
    RH-R3-02/05) de co the goi TRUC TIEP tu test that (khong phai copy tay logic).

    F-M4-RH-R3-02: capture-off doc TRANG THAI THAT tu DB (`read_capture_enabled`) — KHONG con
    dua vao `state.capture_turned_on`. Ly do CA chi ro: neu tien trinh bi ngat DUNG giua luc
    `set_capture_enabled(True)` da commit va luc dong `state.capture_turned_on = True` chay,
    cleanup cu (dua vao co nho) se BO QUA buoc tat capture du DB dang thuc su ON. Co nho gio CHI
    con dung lam telemetry/log, khong con la dieu kien "co nen thu tat khong"."""
    cleanup_step_ok: dict[str, bool] = {}
    try:
        capture_now = await read_capture_enabled(admin_conn)
        if capture_now:
            async with pinned_actor_session(
                pool, staff_id=operator_staff_id, pin_secret=operator_pin,
                business_role=Stage0PBusinessRole.CONTROL_PLANE,
            ) as ctrl_conn:
                await set_capture_enabled(ctrl_conn, enabled=False, approval_ref=None)
            _log("capture_enabled_off_in_finally")
        else:
            _log("capture_off_skip_already_off", state_flag_was=state.capture_turned_on)
        cleanup_step_ok["capture_off"] = True
    except Exception as e:  # noqa: BLE001 — cleanup phai tiep tuc du buoc nay loi
        cleanup_step_ok["capture_off"] = False
        _log("cleanup_capture_off_failed", error_type=type(e).__name__, error=str(e))

    try:
        keys_conn = await asyncpg.connect(_db_url())
        try:
            await _retire_key(keys_conn, "m4_stage0p_transcript_signing_keys", TRANSCRIPT_KEY_VERSION)
            await _retire_key(keys_conn, "m4_stage0p_signing_auth_keys", _SIGNING_AUTH_KEY_VERSION)
            _log("keys_retired_in_finally")
        finally:
            await keys_conn.close()
        cleanup_step_ok["keys_retired"] = True
    except Exception as e:  # noqa: BLE001
        cleanup_step_ok["keys_retired"] = False
        _log("cleanup_key_retire_failed", error_type=type(e).__name__, error=str(e))

    try:
        await _purge_synthetic(admin_conn, state)
        cleanup_step_ok["purge"] = True
    except Exception as e:  # noqa: BLE001
        cleanup_step_ok["purge"] = False
        _log("cleanup_purge_failed", error_type=type(e).__name__, error=str(e))

    try:
        if lifecycle_failed:
            terminal_status = await _terminalize_batch(admin_conn, state)
            _log("batch_terminalized", batch_id=str(state.batch_id) if state.batch_id else None,
                 status=terminal_status)
        cleanup_step_ok["batch_terminalized"] = True
    except Exception as e:  # noqa: BLE001 — F-A08-EXEC-02: buoc nay THIEU hoan toan o Amendment 08,
        # gio la 1 buoc cleanup doc lap co the that bai rieng ma khong lam mat cac buoc khac.
        cleanup_step_ok["batch_terminalized"] = False
        _log("cleanup_batch_terminalize_failed", error_type=type(e).__name__, error=str(e))

    try:
        redis_check = await _postcheck_redis_nonces(window_seconds=120)
        _log("redis_nonce_postcheck", **redis_check)
        cleanup_step_ok["redis_postcheck"] = True
    except Exception as e:  # noqa: BLE001
        cleanup_step_ok["redis_postcheck"] = False
        _log("cleanup_redis_postcheck_failed", error_type=type(e).__name__, error=str(e))

    return cleanup_step_ok


async def _do_cleanup_and_verify(
        admin_conn, pool, *, operator_staff_id: int, operator_pin: str, state: RehearsalState,
        lifecycle_failed: bool) -> tuple[bool, list[str], dict[str, bool]]:
    """F-M4-RH-R3-03/04: chay `_do_cleanup()` roi xac minh hau dieu kien qua
    `_verify_cleanup_postconditions()` — nhung KHONG con tin 2 nguon nay mot cach ngay tho:

    - R3-03: Redis postcheck gio la HAU DIEU KIEN BAT BUOC — neu `_do_cleanup()` bao
      `redis_postcheck=False` (mat ket noi/scan loi), `postcondition_ok` BI EP THANH False du
      truy van DB co sach hay khong (khong con chi la 1 dong log tham khao).
    - R3-04: ban than `_verify_cleanup_postconditions()` cung duoc boc trong try/except — neu NO
      tu loi (vd mat ket noi DB giua chung), coi la "KHONG THE XAC MINH duoc an toan" = that bai
      fail-closed, phat 1 alert chuan hoa, KHONG de traceback thoat thang ra ngoai ham nay ma
      khong co ket luan CLEANUP_FAILED ro rang.
    - F-A08-EXEC-02/A08-COR-03: `lifecycle_failed` truyen xuong ca 2 ham — `_do_cleanup` chi
      terminalize batch khi lifecycle THAT BAI, `_verify_cleanup_postconditions` doi chieu dung
      trang thai terminal ky vong (aborted vs evaluation_completed) thay vi chi dem residual
      content nhu truoc (dieu chinh xac da bo lot batch 'locked' o Amendment 08)."""
    cleanup_step_ok = await _do_cleanup(admin_conn, pool, operator_staff_id=operator_staff_id,
                                        operator_pin=operator_pin, state=state,
                                        lifecycle_failed=lifecycle_failed)

    try:
        postcondition_ok, postcondition_problems = await _verify_cleanup_postconditions(
            admin_conn, state, lifecycle_failed=lifecycle_failed)
    except Exception as e:  # noqa: BLE001 — R3-04: verifier tu loi = khong the xac minh an toan
        postcondition_ok = False
        postcondition_problems = [
            f"BAN THAN postcondition verifier loi ({type(e).__name__}: {e}) - KHONG THE XAC "
            "MINH duoc trang thai an toan, coi nhu THAT BAI (fail-closed, khong doan an toan)"]
        _log("cleanup_postcondition_verifier_failed", error_type=type(e).__name__, error=str(e))

    if not cleanup_step_ok.get("redis_postcheck", False):
        postcondition_ok = False
        postcondition_problems = [*postcondition_problems,
                                  "Redis nonce postcheck KHONG hoan tat (loi ket noi/scan) - "
                                  "khong xac nhan duoc chinh sach nonce da duyet, coi nhu chua "
                                  "an toan (F-M4-RH-R3-03)"]

    return postcondition_ok, postcondition_problems, cleanup_step_ok


async def _run_execute(args, manifest: list[dict]) -> int:
    _assert_distinct_principals(args.operator_staff_id, args.reviewer_staff_id)

    # F-A13-01: Cap A phai fail TRUOC MOI WRITE — dat o day, TRUOC ca `asyncpg.connect`, nen khong
    # co ket noi/transaction/seed/capture nao duoc mo neu manifest vuot cap. O Amendment 13, cho
    # duy nhat chan duoc la DB CHECK tai INSERT m4_selection_batches — GIUA lifecycle, sau khi da
    # ghi 315 hang synthetic va da bat capture. Chan som nhu day khien lan sau khong con ghi 1 hang
    # nao vao production truoc khi biet manifest khong dung duoc.
    cap_a_problem = _cap_a_problem(manifest)
    if cap_a_problem:
        raise SystemExit(f"CAP A PRECHECK FAIL (F-A13-01): {cap_a_problem}")

    operator_pin = _require_env("STAGE0P_REHEARSAL_OPERATOR_PIN")
    reviewer_pin = _require_env("STAGE0P_REHEARSAL_REVIEWER_PIN")

    admin_conn = await asyncpg.connect(_db_url())
    pool = await create_stage0p_pool(_db_url())
    state = RehearsalState()
    start_ts = time.monotonic()
    main_exc: BaseException | None = None
    try:
        if await read_capture_enabled(admin_conn):
            raise SystemExit("PRECHECK FAIL: capture_enabled da la true TRUOC khi rehearsal bat "
                             "dau - abort, khong ro trang thai he thong")

        # F-M4-RH-R2-03: kiem tra lai approval window NGAY TRUOC khi bat capture (khong chi dua
        # vao 1 lan dry-run truoc do co the da cu/het han giua luc dry-run va luc execute that).
        # F-M4-RH-R2-02: doi chieu recorded_by THAT (khong chi 2 CLI argument operator/reviewer).
        approval_ok, recorded_by, approval_problems = await _check_approval_active(
            admin_conn, args.approval_ref)
        if not approval_ok:
            raise SystemExit(f"APPROVAL PRECHECK FAIL (F-R2-03): {approval_problems}")
        _assert_distinct_principals(recorded_by, args.operator_staff_id, args.reviewer_staff_id)

        await _seed_synthetic(admin_conn, manifest, state)
        await _assert_batch_isolated(admin_conn, state)

        # --- capture ON (operator) ---
        async with pinned_actor_session(
            pool, staff_id=args.operator_staff_id, pin_secret=operator_pin,
            business_role=Stage0PBusinessRole.CONTROL_PLANE,
        ) as ctrl_conn:
            before = await set_capture_enabled(ctrl_conn, enabled=True, approval_ref=args.approval_ref)
            _log("capture_enabled_on", before_enabled=before)
        state.capture_turned_on = True

        # --- lock batch qua allowlist tracked (F-01), KHONG select_eligible_conversations ---
        # window_start/window_end o day CHI de thoa CHECK m4_batch_window_valid (window_end >
        # window_start) - KHONG dung de truy van eligible-by-window (co che fence chinh la
        # `selected` chi den tu state.conversation_ids da tracked, xem duoi day).
        window_start = datetime.now(timezone.utc)
        window_end = window_start + timedelta(seconds=1)
        norm_conn = await pool.acquire()
        try:
            normalization_version = await get_current_normalization_version(norm_conn)
        finally:
            await pool.release(norm_conn)

        selected = [{"conversation_id": cid, "customer_id": state.conversation_id_to_customer_id[cid]}
                   for cid in state.conversation_ids]
        lock_conn = await asyncpg.connect(_db_url())
        try:
            # INSERT tren m4_selection_batches chi GRANT cho alpha3s_m4_sample_collector (dung
            # role goc cua lock_batch() trong stage0p_sampling.py) - KHONG phai control_plane.
            await lock_conn.execute("SET ROLE alpha3s_m4_sample_collector")
            row = await lock_conn.fetchrow(
                """
                INSERT INTO m4_selection_batches
                  (window_start, window_end, eligible_count, selected_count, algorithm_seed,
                   locked_conversation_ids, purpose_code, status, retention_days, normalization_version)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'locked', $8, $9)
                RETURNING batch_id
                """,
                window_start, window_end, len(selected), len(selected),
                SELECTION_SEED_LABEL + "-rehearsal-v1",
                [s["conversation_id"] for s in selected], PURPOSE_CODE, RETENTION_DAYS,
                normalization_version,
            )
            state.batch_id = row["batch_id"]
        finally:
            await lock_conn.close()
        _log("batch_locked_via_allowlist", batch_id=str(state.batch_id), count=len(selected))

        # --- collector (F-M4-RH-R1-01: reuse run_collector nguyen ven, khong sua) ---
        collector_result = await _run_collector_with_retry(state.batch_id)
        _log("collector_done", **collector_result)
        if collector_result["permanent_failed"] > 0:
            raise SystemExit(f"COLLECTOR FAIL: {collector_result['permanent_failed']} candidate "
                             "permanent_failed - zero-tolerance (T6-03), abort truoc labeling")
        if not collector_result["collection_closed"]:
            raise SystemExit("COLLECTOR FAIL: collection_closed=False - batch chua o trang thai "
                             "cho phep seal, abort")

        # --- labeling (reviewer, F-03) ---
        async with pinned_actor_session(
            pool, staff_id=args.reviewer_staff_id, pin_secret=reviewer_pin,
            business_role=Stage0PBusinessRole.SAMPLE_REVIEWER_API,
        ) as reviewer_conn:
            labeled_count = await _label_samples(reviewer_conn, manifest, state)
            _log("labeling_done", labeled_count=labeled_count)
            seal_result = await seal_labels(reviewer_conn, batch_id=state.batch_id)
            _log("labels_sealed", **seal_result)

        # --- prediction writer (khong can pinned actor - xem stage0p_prediction.py) ---
        pred_conn = await asyncpg.connect(_db_url())
        try:
            await pred_conn.execute("SET ROLE alpha3s_m4_prediction_writer")
            pred_result = await run_prediction_writer(
                pred_conn, batch_id=state.batch_id, evaluation_batch=EVALUATION_BATCH_LABEL)
            _log("predictions_written", **pred_result)
        except PredictionNotAllowedError as e:
            raise SystemExit(f"PREDICTION FAIL: {e} - kiem tra exclusion gate 10%/200 "
                             "(F-M4-RH-R1-05: manifest can >=200 non-excluded conversation)") from e
        finally:
            await pred_conn.close()

        # --- evaluate (reviewer/evaluator - dung reviewer_staff_id, permission evaluate rieng) ---
        async with pinned_actor_session(
            pool, staff_id=args.reviewer_staff_id, pin_secret=reviewer_pin,
            business_role=Stage0PBusinessRole.SAMPLE_EVALUATOR,
        ) as eval_conn:
            eval_result = await complete_evaluation(
                eval_conn, batch_id=state.batch_id, expected_result_hash=pred_result["result_hash"])
            _log("evaluation_completed", completed_at=str(eval_result["completed_at"]),
                 report_hash=eval_result["report_hash"], metrics=eval_result["metrics"])

        _log("rehearsal_lifecycle_succeeded", note="chua ket luan overall exit - cho cleanup + "
             "postcondition verification (F-M4-RH-R2-01) o duoi")
    except BaseException as e:  # noqa: BLE001 — luon re-raise (main_exc) o cuoi, khong nuot loi;
        # can bat BaseException (khong chi Exception) de ca CancelledError cung buoc qua cleanup
        # thay vi bo qua thang, giong ly do da dung trong stage0p_pool.py __aenter__ (T11-01).
        main_exc = e
        _log("rehearsal_lifecycle_failed", error_type=type(e).__name__, error=str(e))

    # F-M4-RH-R1-04/R2-01/R3-02/03/04: cleanup+verify tach thanh 2 ham co the goi TRUC TIEP tu
    # test (_do_cleanup/_do_cleanup_and_verify) - khong con logic cleanup nao chi ton tai "gan
    # lien" trong _run_execute ma test phai copy tay moi kiem duoc.
    try:
        postcondition_ok, postcondition_problems, cleanup_step_ok = await _do_cleanup_and_verify(
            admin_conn, pool, operator_staff_id=args.operator_staff_id, operator_pin=operator_pin,
            state=state, lifecycle_failed=(main_exc is not None))
    finally:
        # F-M4-RH-R3-04: dong connection/pool bang finally VO DIEU KIEN - ke ca neu ban than
        # _do_cleanup_and_verify raise (khong ky vong, no da tu bao ve rieng, nhung day la lop
        # phong thu THEM, khong phai duong duy nhat).
        await admin_conn.close()
        await pool.close()

    if not postcondition_ok:
        _log("CLEANUP_FAILED", problems=postcondition_problems, cleanup_step_results=cleanup_step_ok,
             lifecycle_error=(f"{type(main_exc).__name__}: {main_exc}" if main_exc else None))
        raise SystemExit(
            f"CLEANUP_FAILED (F-M4-RH-R2-01): he thong CHUA o trang thai an toan sau rehearsal - "
            f"{postcondition_problems} - day la trang thai NGUY HIEM NHAT (co the con capture ON "
            "hoac du lieu/key chua don dep), KHONG duoc bao cao thanh cong du lifecycle chinh co "
            "thanh cong hay khong")
    if main_exc is not None:
        raise main_exc
    elapsed = time.monotonic() - start_ts
    _log("rehearsal_execute_succeeded", elapsed_seconds=round(elapsed, 1))
    return 0


async def _run_dry_run(args, manifest: list[dict]) -> int:
    """Preflight - KHONG ghi gi vao DB. Kiem: capture hien OFF, khong synthetic row du sot lai,
    manifest hop le, approval_ref con hieu luc THAT SU (F-M4-RH-R2-03: valid_from<=now<valid_
    until, requested_enabled=true, dung purpose, chua revoke - khong chi log thong tin roi bo
    qua), va 3 principal (approval recorder THAT/operator/reviewer) phan biet (F-M4-RH-R2-02)."""
    _assert_distinct_principals(args.operator_staff_id, args.reviewer_staff_id)
    admin_conn = await asyncpg.connect(_db_url())
    try:
        capture_now = await read_capture_enabled(admin_conn)
        leftover = await admin_conn.fetchval(
            "SELECT count(*) FROM customers WHERE psid LIKE $1", f"{PSID_PREFIX}%")
        approval_ok, recorded_by, approval_problems = await _check_approval_active(
            admin_conn, args.approval_ref)
        gate_eligible = sum(1 for r in manifest if r["expect_gate"])
        # F-A13-02: TRUOC day dry-run CHI kiem san duoi (>=200) va khong he kiem tran tren, nen
        # manifest 315 van tra `dry_run_ready` — false green da dan thang toi abort giua lifecycle
        # o Amendment 13. Gio kiem CA HAI dau.
        cap_a_problem = _cap_a_problem(manifest)
        _log("dry_run_report",
             capture_currently_enabled=capture_now,
             leftover_synthetic_customers=leftover,
             approval_active=approval_ok,
             approval_recorded_by=recorded_by,
             approval_problems=approval_problems,
             manifest_conversation_count=len(manifest),
             manifest_gate_eligible_count=gate_eligible,
             manifest_meets_200_floor=gate_eligible >= 200,
             manifest_cap_a_limit=MAX_CONVERSATIONS,
             manifest_within_cap_a=cap_a_problem is None,
             operator_staff_id=args.operator_staff_id,
             reviewer_staff_id=args.reviewer_staff_id,
             note="DRY RUN - khong ghi gi, chi bao cao")
        problems = list(approval_problems)
        if capture_now:
            problems.append("capture_enabled dang true - phai OFF truoc rehearsal")
        if leftover:
            problems.append(f"con {leftover} customer synthetic sot lai tu lan chay truoc")
        if gate_eligible < 200:
            problems.append(f"manifest chi co {gate_eligible} gate-eligible conversation (<200)")
        if cap_a_problem:
            problems.append(cap_a_problem)
        if recorded_by is not None:
            problems.extend(_principal_conflict_problems(
                recorded_by, args.operator_staff_id, args.reviewer_staff_id))
        if problems:
            for p in problems:
                _log("dry_run_problem", problem=p)
            return 1
        _log("dry_run_ready", note="tat ca precondition OK (bao gom approval window/principal "
             "binding that su) - san sang execute trong approval window")
        return 0
    finally:
        await admin_conn.close()


def cmd_run(args) -> int:
    manifest = _load_manifest(Path(args.manifest))
    if args.dry_run:
        return asyncio.run(_run_dry_run(args, manifest))
    return asyncio.run(_run_execute(args, manifest))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_approve = sub.add_parser("record-approval")
    p_approve.add_argument("--approval-staff-id", type=int, required=True)
    p_approve.add_argument("--approval-ref", required=True)
    p_approve.add_argument("--valid-from")
    p_approve.add_argument("--valid-until")
    p_approve.add_argument("--note")
    p_approve.add_argument("--revoke", action="store_true")
    p_approve.add_argument("--reason")
    p_approve.set_defaults(func=lambda a: asyncio.run(cmd_record_approval(a)))

    p_prov = sub.add_parser("provision-keys")
    p_prov.set_defaults(func=lambda a: asyncio.run(cmd_provision_keys(a)))

    p_retire = sub.add_parser("retire-keys")
    p_retire.set_defaults(func=lambda a: asyncio.run(cmd_retire_keys(a)))

    p_run = sub.add_parser("run")
    p_run.add_argument("--manifest", required=True)
    p_run.add_argument("--approval-ref", required=True)
    p_run.add_argument("--operator-staff-id", type=int, required=True)
    p_run.add_argument("--reviewer-staff-id", type=int, required=True)
    p_run.add_argument("--dry-run", action="store_true")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
