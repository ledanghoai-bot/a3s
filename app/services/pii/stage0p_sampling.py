"""I-B M4 Stage 0P — sampling 2 pha (F-M4-0P-03B, CLOSED AT DESIGN LEVEL).

Pha 1 (metadata-only, KHONG doc messages.content):
  1a. select_eligible_conversations — conversations.created_at PHAI trong CUNG cua so voi
      orders.created_at (khong chi qua customer_id — tranh keo hoi thoai cu/khong lien quan).
  1b. loai pending-deletion qua is_pending_deletion() (interface hep, PSID khong roi scope).
  1c. select_sample — cap 260, seed co dinh cong khai SHA256("m4-stage0p-v1") khi vuot cap.
  1d. lock_batch — khoa vao m4_selection_batches; TU DAY collector CHI biet batch_id.

Pha 2 (collector — doc noi dung qua ham SECURITY DEFINER, MA HOA + GHI):
  run_collector — REV3 (T2-01/T2-06): peek (khong lock) -> pending-check ngoai fence -> fenced
  unit (fetch+recheck+record_sample, boc `asyncio.wait_for(FENCE_UNIT_DEADLINE_SECONDS)`).

  REV4 (CA Technical Review #3, T3-01/T3-02): 2 thay doi cau truc:
    - `m4_stage0p_record_sample` REV4 KHONG con nhan customer_ref/conversation_ref/retention_days/
      normalization_version tu Python — ham TU DERIVE customer_ref/conversation_ref tu DB va TU
      DOC retention_days/normalization_version tu chinh batch row (dat 1 lan luc lock_batch).
    - Khi `peek_next_candidate` bao 'exhausted' (het ung vien THAT SU, khong phai do loi/control
      off), `run_collector` goi `m4_stage0p_close_collection` — chuyen batch sang trang thai
      'collection_closed', DIEU KIEN BAT BUOC truoc khi reviewer duoc seal labels.

  REV5 (CA Technical Review #4, T4-01/T4-03): 2 thay doi cau truc them:
    - T4-01: capability "token" REV4 la custom GUC (`set_config`/`current_setting`) — CA chi ro
      GUC khong phai secret/privileged storage, caller co the tu `set_config` roi goi
      `record_sample` doc lap. Sua o phia DB: bang moi `m4_stage0p_fetch_capability` (khong GRANT
      cho role m4 nao) — `fetch_message_content` INSERT 1 row (txid_current(), caller khong the
      tu chon), `record_sample` DELETE...RETURNING dung row do TRONG CUNG transaction. Phia
      Python KHONG doi (van goi 2 ham trong `async with collector_conn.transaction():` nhu cu —
      co che moi hoan toan trong suot voi caller).
    - T4-03: collector REV4 `continue` khi fence timeout — candidate do bien mat khoi vong lap ma
      KHONG BAO GIO dat trang thai terminal nao, va batch van co the dong (close_collection) du
      candidate do chua duoc xu ly xong. Sua: bang moi `m4_stage0p_capture_progress` (1 row/
      candidate, state machine 5 gia tri) — `run_collector()` goi `m4_stage0p_seed_capture_progress`
      1 LAN luc bat dau (truoc vong lap), `peek_next_candidate` gio CHI nhan `batch_id` (doc tu
      bang progress, khong con cursor after_conv/after_msg — bang progress LA cursor). Fence
      timeout -> `m4_stage0p_mark_candidate_outcome(...,'fence_timeout',...)` (retryable_failed,
      >=3 lan -> permanent_failed, terminal). Pending-deletion (ca 3 nhanh: cache-hit, pre-fence
      check, recheck trong fence) -> `mark_candidate_outcome(...,'pending_deletion',...)` (->
      excluded, terminal ngay). `close_collection` gio TU CHOI neu con row pending/retryable_failed
      — chi dong khi MOI candidate that su dat trang thai terminal.
  Advisory lock don-writer 4013002 (session-scoped) giu nguyen — chan 2 tien trinh collector chay
  dong thoi tren CUNG batch.
"""

import asyncio
import hashlib
import json
import random
import uuid

from app.config import settings

# REV11 T10-01/T10-02: canonicalize/truncate KHONG con dung TRUC TIEP trong module nay (chuyen
# vao trong signing service, tien trinh RIENG) — re-export giu tuong thich cho
# `m4_stage0p_sampling_test.py` (dung `s._truncate`/`s.MAX_CHARS`/`s.MAX_BYTES` kiem thuat toan
# thuan tuy, KHONG di qua collector path).
from app.services.pii.canonicalize import MAX_BYTES, MAX_CHARS  # noqa: F401
from app.services.pii.canonicalize import truncate_canonical as _truncate  # noqa: F401
from app.services.pii.stage0p_eligibility import is_pending_deletion
from app.services.pii.stage0p_signing_client import (
    SigningServiceError,
    request_signature,
)

MAX_CONVERSATIONS = 260
SELECTION_SEED_LABEL = "m4-stage0p-v1"
RETENTION_DAYS = 45
PURPOSE_CODE = "P12_PII_DETECTOR_EVAL"
# REV6 T5-04: KHONG con hang so o day — nguon THAT DUY NHAT la bang DB
# m4_stage0p_normalization_registry (tranh "hardcode kep" REV5 doi hoi con nguoi bump ca DB lan
# Python). Xem `get_current_normalization_version()` duoi day.
# Rieng voi LOCK_KEY 4013001 cua scripts/migrate.py va 4013003 (control fence, xem migration 039
# §5) — 3 namespace doc lap, khong dung tranh nhau.
ADVISORY_LOCK_KEY = 4013002

# REV3 T2-01: cac cận thoi gian tuong minh cho fenced work unit — khong con "vo han".
DB_STATEMENT_TIMEOUT_SECONDS = 2.0
PENDING_CHECK_TIMEOUT_SECONDS = 1.5   # kiem pending TRUOC khi giu fence
PENDING_RECHECK_TIMEOUT_SECONDS = 0.5  # recheck NGAN BEN TRONG fence (dong Redis, phai nhanh)
FENCE_UNIT_DEADLINE_SECONDS = 5.0     # tran TUYET DOI cho 1 don vi fenced (fetch+recheck+insert)


def _log(event: str, **fields) -> None:
    print("[m4-stage0p-sampling] " + json.dumps({"event": event, **fields},
                                                 ensure_ascii=False, sort_keys=True))


def _seed_int() -> int:
    """Seed nguyen tu SHA256(nhan seed) — cong khai, tai lap doc lap duoc."""
    h = hashlib.sha256(SELECTION_SEED_LABEL.encode()).digest()
    return int.from_bytes(h[:8], "big")


async def select_eligible_conversations(collector_conn, pending_conn, *,
                                        window_start, window_end) -> list[dict]:
    """Pha 1a+1b: metadata-only, loai pending-deletion. Tra [{conversation_id, customer_id}]."""
    rows = await collector_conn.fetch(
        """
        SELECT DISTINCT c.id AS conversation_id, c.customer_id
        FROM conversations c
        JOIN orders o ON o.customer_id = c.customer_id
        WHERE o.created_at >= $1 AND o.created_at < $2
          AND c.created_at >= $1 AND c.created_at < $2
        ORDER BY c.id
        """,
        window_start, window_end,
    )
    eligible_raw = len(rows)
    result: list[dict] = []
    excluded_pending = 0
    seen_customers: dict[int, bool] = {}
    for r in rows:
        cust_id = r["customer_id"]
        if cust_id not in seen_customers:
            seen_customers[cust_id] = await is_pending_deletion(pending_conn, cust_id)
        if seen_customers[cust_id]:
            excluded_pending += 1
            continue
        result.append({"conversation_id": r["conversation_id"], "customer_id": cust_id})
    _log("m4_eligibility", eligible_raw=eligible_raw, excluded_pending=excluded_pending,
         eligible_final=len(result))
    return result


def select_sample(eligible: list[dict], cap: int = MAX_CONVERSATIONS) -> list[dict]:
    """Pha 1c: <=cap phan tu. Duoi cap -> lay het. Tren cap -> permutation seed co dinh cong
    khai, deterministic (cung input + cung seed => cung ket qua, kiem chung doc lap duoc)."""
    if len(eligible) <= cap:
        return list(eligible)
    rng = random.Random(_seed_int())
    chosen = rng.sample(eligible, cap)
    chosen.sort(key=lambda e: e["conversation_id"])
    return chosen


async def get_current_normalization_version(conn) -> str:
    """REV6 T5-04, REV7 T6-04: doc normalization version hien hanh tu bang DB
    `m4_stage0p_normalization_registry` — nguon THAT DUY NHAT (khong con hardcode song song o
    Python). REV7: bang gio la versioned/append-only (PK=version, cot is_current), doc row
    is_current=true thay vi row id=1 singleton REV6. `conn` can SELECT tren bang nay (da GRANT cho
    collector/prediction_writer)."""
    version = await conn.fetchval(
        "SELECT version FROM m4_stage0p_normalization_registry WHERE is_current")
    if not version:
        raise RuntimeError("m4_stage0p_normalization_registry: chua co entry is_current")
    return version


async def lock_batch(conn, *, window_start, window_end, eligible_count,
                     selected: list[dict]) -> str:
    """Pha 1d: khoa batch. TU THOI DIEM NAY collector CHI biet batch_id, khong tu do truy van
    conversation_id (F-M4-0P-02A/02B)."""
    conversation_ids = [s["conversation_id"] for s in selected]
    normalization_version = await get_current_normalization_version(conn)
    row = await conn.fetchrow(
        """
        INSERT INTO m4_selection_batches
          (window_start, window_end, eligible_count, selected_count, algorithm_seed,
           locked_conversation_ids, purpose_code, status, retention_days, normalization_version)
        VALUES ($1,$2,$3,$4,$5,$6,$7,'locked',$8,$9)
        RETURNING batch_id
        """,
        window_start, window_end, eligible_count, len(conversation_ids), SELECTION_SEED_LABEL,
        conversation_ids, PURPOSE_CODE, RETENTION_DAYS, normalization_version,
    )
    _log("m4_batch_locked", batch_id=str(row["batch_id"]), selected_count=len(conversation_ids))
    return row["batch_id"]


async def _run_fenced_unit(collector_conn, pending_conn, *, batch_id, conversation_id,
                           message_id, customer_id) -> dict:
    """REV3 T2-01: 1 don vi fenced DUY NHAT cho 1 message da biet truoc (conversation_id,
    message_id) — fetch content (fence 4013003) + recheck pending NGAN + encrypt + record_sample,
    tat ca trong CUNG 1 transaction Python. Goi ham nay PHAI duoc boc trong
    `asyncio.wait_for(FENCE_UNIT_DEADLINE_SECONDS)` boi caller (xem run_collector) — asyncpg huy
    (cancel) query dang cho tren server khi task Python bi huy, nen KHONG can tu dong/close
    connection thu cong o day; lock 4013003 tu dong nha khi transaction abort do cancel.

    Tra {"status": "ok"|"control_off"|"pending", "truncated": bool}."""
    async with collector_conn.transaction():
        # REV13 T12-02: sample_id gio PHAI sinh TRUOC khi goi fetch_message_content — DB can biet
        # gia tri nay de buoc vao signing authorization no tu ky TRONG CUNG loi goi/transaction.
        sample_id = str(uuid.uuid4())
        fetched = await collector_conn.fetchrow(
            "SELECT * FROM m4_stage0p_fetch_message_content($1, $2, $3, $4)",
            batch_id, conversation_id, message_id, sample_id,
            timeout=DB_STATEMENT_TIMEOUT_SECONDS,
        )
        if fetched["status"] == "control_off":
            return {"status": "control_off", "truncated": False}

        # T2-01: recheck NGAN BEN TRONG fence de dong cua so dua con lai — timeout ngat han hon
        # (fail-closed = pending) de khong giu lock lau hon can thiet.
        if await is_pending_deletion(pending_conn, customer_id,
                                     timeout=PENDING_RECHECK_TIMEOUT_SECONDS):
            return {"status": "pending", "truncated": False}

        customer_ref = str(customer_id)
        conversation_ref = str(conversation_id)
        # REV10 T8-02 (CA Review #9 §4, Huong 3): txid_current() la "one-time capability nonce/
        # transaction identity" dua vao transcript — CUNG gia tri fetch_message_content da dung
        # noi bo (cung 1 transaction Python dang mo), record_sample doi chieu lai luc verify.
        txid = await collector_conn.fetchval("SELECT txid_current()")
        # REV11 T10-01/T10-02: collector KHONG con tu canonicalize/tu tinh digest — gui RAW
        # content (`fetched["content"]`, da la `left(content,2000)` tu DB) sang signing service
        # (tien trinh RIENG, xem stage0p_signing_client.py/stage0p_signing_service.py). Service
        # TU canonicalize + TU tinh digest/length/truncated + ma hoa + ky — collector chi RELAY
        # ket qua, khong con giu/thay doi gia tri nao trong so do.
        if not settings.m4_stage0p_signing_socket:
            raise SigningServiceError(
                "m4_stage0p_signing_socket chua duoc cau hinh - tu choi (fail closed, khong "
                "fallback ve ky trong-process, T10-02)")
        signed = await request_signature(
            settings.m4_stage0p_signing_socket, batch_id=batch_id,
            conversation_id=conversation_id, message_id=message_id, sample_id=sample_id,
            raw_content=fetched["content"], customer_ref=customer_ref,
            conversation_ref=conversation_ref, purpose_code=PURPOSE_CODE, txid=txid,
            # REV13 T12-02: relay nguyen ven token DB da ky - collector khong tu tao/sua duoc.
            signing_authorization=fetched["signing_authorization"],
            db_char_truncated=bool(fetched["char_truncated"]))
        await collector_conn.fetchrow(
            "SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
            batch_id, conversation_id, message_id, sample_id, signed.ciphertext,
            signed.canonical_len, signed.truncated, signed.canonical_digest,
            signed.transcript, signed.signature, signed.key_version,
            timeout=DB_STATEMENT_TIMEOUT_SECONDS,
        )
        return {"status": "ok", "truncated": signed.truncated}


async def _mark_outcome(collector_conn, *, batch_id, conversation_id, message_id, outcome, reason):
    """REV5 T4-03: goi `m4_stage0p_mark_candidate_outcome` — chuyen candidate progress row sang
    trang thai terminal/retry tuong ung. Tra ve row (new_status, attempt_count)."""
    return await collector_conn.fetchrow(
        "SELECT * FROM m4_stage0p_mark_candidate_outcome($1,$2,$3,$4,$5)",
        batch_id, conversation_id, message_id, outcome, reason,
        timeout=DB_STATEMENT_TIMEOUT_SECONDS,
    )


async def run_collector(collector_conn, pending_conn, *, batch_id) -> dict:
    """Pha 2. REV3 (CA Technical Review #2, T2-01/T2-06); REV5 (CA Technical Review #4, T4-03):
    xem docstring module cho thiet ke day du. `collector_conn` role alpha3s_m4_sample_collector,
    `pending_conn` role alpha3s_m4_pending_checker.

    Don-writer bang advisory lock session-scoped 4013002 (F-M4-0P-03B) — tien trinh thu 2
    fail-fast, giu nguyen tu ban goc."""
    got_lock = await collector_conn.fetchval("SELECT pg_try_advisory_lock($1)", ADVISORY_LOCK_KEY)
    if not got_lock:
        _log("m4_collector_lock_failed")
        return {"inserted": 0, "skipped_pending": 0, "truncated": 0,
                "aborted_control_off": False, "lock_failed": True, "fence_timeout": False,
                "permanent_failed": 0, "collection_closed": False}

    # T4-03: seed toan bo candidate 1 LAN (idempotent — resume 1 batch da seed truoc do khong
    # tao trung row) TRUOC vong lap — bang capture_progress la nguon THAT cho "con lai bao nhieu
    # candidate", thay cho cursor Python cu.
    seed_row = await collector_conn.fetchrow(
        "SELECT * FROM m4_stage0p_seed_capture_progress($1)", batch_id,
        timeout=DB_STATEMENT_TIMEOUT_SECONDS,
    )
    _log("m4_collector_seeded", batch_id=str(batch_id), candidate_count=seed_row["candidate_count"])

    inserted = skipped_pending = truncated_count = permanent_failed = 0
    pending_customers: set[int] = set()
    aborted_control_off = False
    fence_timeout_hit = False
    naturally_exhausted = False

    try:
        while True:
            peek = await collector_conn.fetchrow(
                "SELECT * FROM m4_stage0p_peek_next_candidate($1)",
                batch_id, timeout=DB_STATEMENT_TIMEOUT_SECONDS,
            )
            if peek["status"] == "exhausted":
                naturally_exhausted = True
                break

            conv_id = peek["conversation_id"]
            msg_id = peek["message_id"]
            customer_id = peek["customer_id"]

            if customer_id in pending_customers:
                await _mark_outcome(collector_conn, batch_id=batch_id, conversation_id=conv_id,
                                    message_id=msg_id, outcome="pending_deletion",
                                    reason="customer_in_pending_cache")
                skipped_pending += 1
                continue

            # T2-01: pending-check TRUOC khi giu fence — timeout bounded, KHONG cham lock 4013003.
            if await is_pending_deletion(pending_conn, customer_id,
                                         timeout=PENDING_CHECK_TIMEOUT_SECONDS):
                pending_customers.add(customer_id)
                await _mark_outcome(collector_conn, batch_id=batch_id, conversation_id=conv_id,
                                    message_id=msg_id, outcome="pending_deletion",
                                    reason="pending_check_before_fence")
                skipped_pending += 1
                continue

            try:
                unit = await asyncio.wait_for(
                    _run_fenced_unit(collector_conn, pending_conn, batch_id=batch_id,
                                     conversation_id=conv_id, message_id=msg_id,
                                     customer_id=customer_id),
                    timeout=FENCE_UNIT_DEADLINE_SECONDS,
                )
            except asyncio.TimeoutError:
                fence_timeout_hit = True
                outcome_row = await _mark_outcome(collector_conn, batch_id=batch_id,
                                                  conversation_id=conv_id, message_id=msg_id,
                                                  outcome="fence_timeout",
                                                  reason="asyncio_wait_for_timeout")
                if outcome_row["new_status"] == "permanent_failed":
                    permanent_failed += 1
                _log("m4_collector_fence_timeout", conversation_id=conv_id, message_id=msg_id,
                     new_status=outcome_row["new_status"], attempt_count=outcome_row["attempt_count"])
                continue

            if unit["status"] == "control_off":
                _log("m4_collector_stopped_control_off", inserted=inserted)
                aborted_control_off = True
                break
            if unit["status"] == "pending":
                pending_customers.add(customer_id)
                await _mark_outcome(collector_conn, batch_id=batch_id, conversation_id=conv_id,
                                    message_id=msg_id, outcome="pending_deletion",
                                    reason="pending_recheck_inside_fence")
                skipped_pending += 1
                continue
            # status == "ok" -> record_sample da chuyen progress row -> 'committed' TRONG CUNG
            # transaction voi INSERT sample (xem m4_stage0p_record_sample, migration 039 §5c).
            inserted += 1
            if unit["truncated"]:
                truncated_count += 1

        collection_closed = False
        if naturally_exhausted:
            # T3-02/T4-03: het ung vien THAT SU (khong phai do control OFF) -> thu dong collection
            # ngay. Ham DB tu choi neu con row pending/retryable_failed (T4-03) HOAC captured_count/
            # so row that/so row committed khong khop nhau (T3-02) — dau hieu bug can dieu tra
            # thay vi am tham dong 1 batch khong nhat quan.
            close_row = await collector_conn.fetchrow(
                "SELECT * FROM m4_stage0p_close_collection($1)", batch_id,
                timeout=DB_STATEMENT_TIMEOUT_SECONDS,
            )
            collection_closed = close_row["status"] == "collection_closed"

        _log("m4_collector_done", inserted=inserted, skipped_pending=skipped_pending,
             truncated=truncated_count, aborted_control_off=aborted_control_off,
             fence_timeout=fence_timeout_hit, permanent_failed=permanent_failed,
             collection_closed=collection_closed)
        return {"inserted": inserted, "skipped_pending": skipped_pending,
                "truncated": truncated_count, "aborted_control_off": aborted_control_off,
                "lock_failed": False, "fence_timeout": fence_timeout_hit,
                "permanent_failed": permanent_failed, "collection_closed": collection_closed}
    finally:
        await collector_conn.execute("SELECT pg_advisory_unlock($1)", ADVISORY_LOCK_KEY)


async def purge_expired(conn) -> int:
    """Retention RET-11b: `eval completed (m4_selection_batches.evaluation_completed_at) OR 45
    ngay tu captured_at, tuy dieu kien nao truoc`. REV2 (CA Technical Review #1, T1-06): JOIN
    sang m4_selection_batches — KHONG con suy trang thai "eval xong" tu label_status/
    predicted_slots cap-row (finding cu: prediction-writer chay xong CHUA co nghia evaluator da
    chay/report da seal; 1 scheduler purge xen ke co the xoa corpus TRUOC KHI eval thuc su hoan
    tat). `conn` phai xac thuc bang role `alpha3s_m4_sample_purge`. Log counts-only (khong
    sample_id/customer_ref trong log). DELETE la vo hai neu khop 0 row — idempotent tu nhien."""
    result = await conn.execute(
        """
        DELETE FROM m4_shadow_review_samples s
        USING m4_selection_batches b
        WHERE s.selection_batch = b.batch_id
          AND (s.expires_at <= now() OR b.evaluation_completed_at IS NOT NULL)
        """
    )
    count = int(result.split()[-1]) if result.startswith("DELETE") else 0
    _log("m4_purge_done", count=count)
    return count
