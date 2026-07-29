"""I-B M4 Stage 0P — sampling 2 pha (F-M4-0P-03B, CLOSED AT DESIGN LEVEL).

Pha 1 (metadata-only, KHONG doc messages.content):
  1a. select_eligible_conversations — conversations.created_at PHAI trong CUNG cua so voi
      orders.created_at (khong chi qua customer_id — tranh keo hoi thoai cu/khong lien quan).
  1b. loai pending-deletion qua is_pending_deletion() (interface hep, PSID khong roi scope).
  1c. select_sample — cap 260, seed co dinh cong khai SHA256("m4-stage0p-v1") khi vuot cap.
  1d. lock_batch — khoa vao m4_selection_batches; TU DAY collector CHI biet batch_id.

Pha 2 (collector — doc noi dung qua ham SECURITY DEFINER, MA HOA + GHI):
  run_collector — 1 checkpoint DUY NHAT truoc MOI INSERT: (a) capture control con ON? (doc
  tuoi qua stage0p_control, F-M4-0P-01B) (b) khach khong pending-deletion? (re-check rang chong
  race, F-M4-0P-02B). Advisory lock don-writer (F-M4-0P-03B, tai dung pattern scripts/migrate.py
  nhung LOCK_KEY rieng). MAX_CHARS/MAX_BYTES cat truoc khi ma hoa, UTF-8-safe 2 buoc.
"""

import hashlib
import json
import random
import uuid

from app.services.pii.crypto import encrypt_sample_value
from app.services.pii.normalize import nfc
from app.services.pii.stage0p_control import read_capture_enabled
from app.services.pii.stage0p_eligibility import is_pending_deletion

MAX_CONVERSATIONS = 260
MAX_CHARS = 2000
MAX_BYTES = 8000
SELECTION_SEED_LABEL = "m4-stage0p-v1"
RETENTION_DAYS = 45
PURPOSE_CODE = "P12_PII_DETECTOR_EVAL"
NORMALIZATION_VERSION = "nfc-v1"
# Rieng voi LOCK_KEY 4013001 cua scripts/migrate.py — khac namespace, khong dung tranh nhau.
ADVISORY_LOCK_KEY = 4013002


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
           locked_conversation_ids, purpose_code, status)
        VALUES ($1,$2,$3,$4,$5,$6,$7,'locked')
        RETURNING batch_id
        """,
        window_start, window_end, eligible_count, len(conversation_ids), SELECTION_SEED_LABEL,
        conversation_ids, PURPOSE_CODE,
    )
    _log("m4_batch_locked", batch_id=str(row["batch_id"]), selected_count=len(conversation_ids))
    return row["batch_id"]


async def run_collector(collector_conn, control_conn, pending_conn, *, batch_id) -> dict:
    """Pha 2. `collector_conn`/`control_conn`/`pending_conn` PHAI la 3 connection XAC THUC
    BANG 3 ROLE KHAC NHAU (alpha3s_m4_sample_collector / bat ky role co the doc control /
    alpha3s_m4_pending_checker) — dung 1 connection chung cho ca 3 se lam mat y nghia tach
    quyen. Don-writer bang advisory lock (F-M4-0P-03B) — tien trinh thu 2 fail-fast."""
    got_lock = await collector_conn.fetchval("SELECT pg_try_advisory_lock($1)", ADVISORY_LOCK_KEY)
    if not got_lock:
        _log("m4_collector_lock_failed")
        return {"inserted": 0, "skipped_pending": 0, "truncated": 0,
                "aborted_control_off": False, "lock_failed": True}

    try:
        rows = await collector_conn.fetch(
            "SELECT * FROM m4_stage0p_fetch_batch_content($1)", batch_id
        )
        conv_ids = sorted({r["conversation_id"] for r in rows})
        cust_map: dict[int, int] = {}
        if conv_ids:
            cust_rows = await collector_conn.fetch(
                "SELECT id, customer_id FROM conversations WHERE id = ANY($1)", conv_ids
            )
            cust_map = {r["id"]: r["customer_id"] for r in cust_rows}

        inserted = skipped_pending = truncated_count = 0
        pending_customers: set[int] = set()
        aborted = False

        for row in rows:
            # 1 checkpoint duy nhat truoc MOI INSERT: control ON? khach khong pending?
            if not await read_capture_enabled(control_conn):
                _log("m4_collector_stopped_control_off", inserted=inserted)
                aborted = True
                break

            customer_id = cust_map.get(row["conversation_id"])
            if customer_id in pending_customers:
                skipped_pending += 1
                continue
            if await is_pending_deletion(pending_conn, customer_id):
                pending_customers.add(customer_id)
                skipped_pending += 1
                continue

            text, was_truncated = _truncate(nfc(row["content"]))
            if was_truncated:
                truncated_count += 1
            sample_id = str(uuid.uuid4())
            customer_ref = str(customer_id)
            conversation_ref = str(row["conversation_id"])
            blob = encrypt_sample_value(text, customer_ref=customer_ref,
                                        conversation_ref=conversation_ref, sample_id=sample_id)
            await collector_conn.execute(
                """
                INSERT INTO m4_shadow_review_samples
                  (sample_id, customer_ref, conversation_ref, encrypted_message,
                   canonical_text_len, truncated, expires_at, purpose_code,
                   normalization_version, selection_batch)
                VALUES ($1,$2,$3,$4,$5,$6, now() + make_interval(days => $7), $8, $9, $10)
                """,
                sample_id, customer_ref, conversation_ref, blob, len(text), was_truncated,
                RETENTION_DAYS, PURPOSE_CODE, NORMALIZATION_VERSION, batch_id,
            )
            inserted += 1

        _log("m4_collector_done", inserted=inserted, skipped_pending=skipped_pending,
             truncated=truncated_count, aborted_control_off=aborted)
        return {"inserted": inserted, "skipped_pending": skipped_pending,
                "truncated": truncated_count, "aborted_control_off": aborted,
                "lock_failed": False}
    finally:
        await collector_conn.execute("SELECT pg_advisory_unlock($1)", ADVISORY_LOCK_KEY)


async def purge_expired(conn) -> int:
    """Retention RET-11b: `eval completed OR 45 ngay, tuy dieu kien nao truoc`. `conn` phai
    xac thuc bang role `alpha3s_m4_sample_purge`. Log counts-only (khong sample_id/customer_ref
    trong log). DELETE la vo hai neu khop 0 row — idempotent tu nhien."""
    result = await conn.execute(
        "DELETE FROM m4_shadow_review_samples "
        "WHERE expires_at <= now() "
        "   OR (label_status = 'labeled' AND predicted_slots IS NOT NULL)"
    )
    count = int(result.split()[-1]) if result.startswith("DELETE") else 0
    _log("m4_purge_done", count=count)
    return count
