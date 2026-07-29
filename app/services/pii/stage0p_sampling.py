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
      DOC retention_days/normalization_version tu chinh batch row (dat 1 lan luc lock_batch). Ham
      con doi hoi 1 "capability token" transaction-scoped ma CHI `m4_stage0p_fetch_message_content`
      dat duoc khi thanh cong — dong hoan toan duong goi record_sample DOC LAP voi du lieu tu bia
      (T3-01: truoc day la mot lo hong that, role collector co the EXECUTE record_sample truc
      tiep, bo qua toan bo authorization).
    - Khi `peek_next_candidate` bao 'exhausted' (het ung vien THAT SU, khong phai do loi/control
      off), `run_collector` goi `m4_stage0p_close_collection` — chuyen batch sang trang thai
      'collection_closed', DIEU KIEN BAT BUOC truoc khi reviewer duoc seal labels (T3-02: seal
      khong con dong duoc collection tu no — phai co buoc dong tuong minh, doi chieu
      captured_count vs so row that truoc khi cho dong).
  Advisory lock don-writer 4013002 (session-scoped) giu nguyen — chan 2 tien trinh collector chay
  dong thoi tren CUNG batch.
"""

import asyncio
import hashlib
import json
import random
import uuid

from app.services.pii.crypto import encrypt_sample_value
from app.services.pii.normalize import nfc
from app.services.pii.stage0p_eligibility import is_pending_deletion

MAX_CONVERSATIONS = 260
MAX_CHARS = 2000
MAX_BYTES = 8000
SELECTION_SEED_LABEL = "m4-stage0p-v1"
RETENTION_DAYS = 45
PURPOSE_CODE = "P12_PII_DETECTOR_EVAL"
NORMALIZATION_VERSION = "nfc-v1"
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


def _truncate(text: str) -> tuple[str, bool]:
    """MAX_CHARS truoc, MAX_BYTES sau — UTF-8-safe CA HAI buoc (F-M4-0P-03B).

    Buoc 1: cat theo code point (string slicing luon an toan UTF-8).
    Buoc 2: encode UTF-8, neu qua MAX_BYTES thi cat tren BYTES da encode roi decode voi
    errors='ignore' — CHI loai bo dung phan byte KHONG HOAN CHINH bi chen dot o cuoi, khong
    lam hong bat ky ky tu nao dung truoc do."""
    truncated = False
    s = text
    if len(s) > MAX_CHARS:
        s = s[:MAX_CHARS]
        truncated = True
    encoded = s.encode("utf-8")
    if len(encoded) > MAX_BYTES:
        s = encoded[:MAX_BYTES].decode("utf-8", errors="ignore")
        truncated = True
    return s, truncated


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


async def lock_batch(conn, *, window_start, window_end, eligible_count,
                     selected: list[dict]) -> str:
    """Pha 1d: khoa batch. TU THOI DIEM NAY collector CHI biet batch_id, khong tu do truy van
    conversation_id (F-M4-0P-02A/02B)."""
    conversation_ids = [s["conversation_id"] for s in selected]
    row = await conn.fetchrow(
        """
        INSERT INTO m4_selection_batches
          (window_start, window_end, eligible_count, selected_count, algorithm_seed,
           locked_conversation_ids, purpose_code, status, retention_days, normalization_version)
        VALUES ($1,$2,$3,$4,$5,$6,$7,'locked',$8,$9)
        RETURNING batch_id
        """,
        window_start, window_end, eligible_count, len(conversation_ids), SELECTION_SEED_LABEL,
        conversation_ids, PURPOSE_CODE, RETENTION_DAYS, NORMALIZATION_VERSION,
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
        fetched = await collector_conn.fetchrow(
            "SELECT * FROM m4_stage0p_fetch_message_content($1, $2, $3)",
            batch_id, conversation_id, message_id, timeout=DB_STATEMENT_TIMEOUT_SECONDS,
        )
        if fetched["status"] == "control_off":
            return {"status": "control_off", "truncated": False}

        # T2-01: recheck NGAN BEN TRONG fence de dong cua so dua con lai — timeout ngat han hon
        # (fail-closed = pending) de khong giu lock lau hon can thiet.
        if await is_pending_deletion(pending_conn, customer_id,
                                     timeout=PENDING_RECHECK_TIMEOUT_SECONDS):
            return {"status": "pending", "truncated": False}

        text, was_truncated = _truncate(nfc(fetched["content"]))
        was_truncated = was_truncated or bool(fetched["char_truncated"])
        sample_id = str(uuid.uuid4())
        customer_ref = str(customer_id)
        conversation_ref = str(conversation_id)
        blob = encrypt_sample_value(text, customer_ref=customer_ref,
                                    conversation_ref=conversation_ref, sample_id=sample_id)
        # REV4 T3-01: khong con truyen customer_ref/conversation_ref/retention_days/
        # normalization_version — ham DB tu derive/doc lai (xem docstring module). Capability
        # token da duoc dat boi fetch_message_content o tren, trong CUNG transaction nay.
        await collector_conn.fetchrow(
            "SELECT * FROM m4_stage0p_record_sample($1,$2,$3,$4,$5,$6,$7)",
            batch_id, conversation_id, message_id, sample_id, blob, len(text), was_truncated,
            timeout=DB_STATEMENT_TIMEOUT_SECONDS,
        )
        return {"status": "ok", "truncated": was_truncated}


async def run_collector(collector_conn, pending_conn, *, batch_id) -> dict:
    """Pha 2. REV3 (CA Technical Review #2, T2-01/T2-06): xem docstring module cho thiet ke day
    du. `collector_conn` role alpha3s_m4_sample_collector, `pending_conn` role
    alpha3s_m4_pending_checker.

    Don-writer bang advisory lock session-scoped 4013002 (F-M4-0P-03B) — tien trinh thu 2
    fail-fast, giu nguyen tu ban goc."""
    got_lock = await collector_conn.fetchval("SELECT pg_try_advisory_lock($1)", ADVISORY_LOCK_KEY)
    if not got_lock:
        _log("m4_collector_lock_failed")
        return {"inserted": 0, "skipped_pending": 0, "truncated": 0,
                "aborted_control_off": False, "lock_failed": True, "fence_timeout": False}

    inserted = skipped_pending = truncated_count = 0
    pending_customers: set[int] = set()
    aborted_control_off = False
    fence_timeout_hit = False
    naturally_exhausted = False
    after_conv, after_msg = -1, -1

    try:
        while True:
            peek = await collector_conn.fetchrow(
                "SELECT * FROM m4_stage0p_peek_next_candidate($1, $2, $3)",
                batch_id, after_conv, after_msg, timeout=DB_STATEMENT_TIMEOUT_SECONDS,
            )
            if peek["status"] == "exhausted":
                naturally_exhausted = True
                break

            conv_id = peek["conversation_id"]
            msg_id = peek["message_id"]
            customer_id = peek["customer_id"]
            after_conv, after_msg = conv_id, msg_id  # cursor/progress state — TACH BIET captured_count (T2-06)

            if customer_id in pending_customers:
                skipped_pending += 1
                continue

            # T2-01: pending-check TRUOC khi giu fence — timeout bounded, KHONG cham lock 4013003.
            if await is_pending_deletion(pending_conn, customer_id,
                                         timeout=PENDING_CHECK_TIMEOUT_SECONDS):
                pending_customers.add(customer_id)
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
                _log("m4_collector_fence_timeout", conversation_id=conv_id, message_id=msg_id)
                continue

            if unit["status"] == "control_off":
                _log("m4_collector_stopped_control_off", inserted=inserted)
                aborted_control_off = True
                break
            if unit["status"] == "pending":
                pending_customers.add(customer_id)
                skipped_pending += 1
                continue
            inserted += 1
            if unit["truncated"]:
                truncated_count += 1

        collection_closed = False
        if naturally_exhausted:
            # REV4 T3-02: het ung vien THAT SU (khong phai do control OFF/fence timeout) -> dong
            # collection ngay — dieu kien bat buoc truoc khi reviewer duoc seal labels. Ham DB tu
            # doi chieu captured_count vs so row that (RAISE neu lech, dau hieu bug can dieu tra
            # thay vi am tham dong 1 batch khong nhat quan).
            close_row = await collector_conn.fetchrow(
                "SELECT * FROM m4_stage0p_close_collection($1)", batch_id,
                timeout=DB_STATEMENT_TIMEOUT_SECONDS,
            )
            collection_closed = close_row["status"] == "collection_closed"

        _log("m4_collector_done", inserted=inserted, skipped_pending=skipped_pending,
             truncated=truncated_count, aborted_control_off=aborted_control_off,
             fence_timeout=fence_timeout_hit, collection_closed=collection_closed)
        return {"inserted": inserted, "skipped_pending": skipped_pending,
                "truncated": truncated_count, "aborted_control_off": aborted_control_off,
                "lock_failed": False, "fence_timeout": fence_timeout_hit,
                "collection_closed": collection_closed}
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
