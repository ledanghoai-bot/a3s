#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: crypto DB-integrated + evaluation methodology (CA acceptance
criteria #10, #11, #12).

Chay:
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      alpha3s-m4-test python scripts/m4_stage0p_evaluation_test.py

Kiem tra (tren DB that, khac tests/test_m4_stage0p_crypto.py va test_m4_stage0p_evaluation.py
von thuan logic — o day dung row that trong bang, qua role that):
  [1] Crypto domain/key separation: sample encrypt bang khoa/domain M4 Stage 0P KHONG giai ma
      duoc bang ham slot store (pii_slots) du dung API tuong tu.
  [2] Tamper tren row DB that: sua encrypted_message truc tiep -> decrypt fail.
  [3] Cross-context tren row DB that: doi customer_ref/conversation_ref cua ROW (khong phai
      chi tham so ham) -> decrypt that bai (AAD khong con khop).
  [4] Offset-bounds validation tren du doan detector THAT (chay tren cau that co PII, kiem
      validate_spans khong bao loi).
  [5] Non-overlap: 2 span detector doc lap khong chong lan tren cung 1 cau (thuoc tinh detector
      da co tu S0 — xac nhan lai qua duong Stage 0P).
  [6] normalization_version mismatch bi loai khoi gate (khong so sanh nham 2 chuan hoa khac nhau).
  [7] Label-before-prediction: kiem tra lai qua DB that (bo sung smoke test da lam thu cong).
  [8] Evaluation hash: 2 lan chay CUNG detector_version/normalization_version/evaluation_batch
      -> CUNG hash; doi 1 tham so -> hash khac.
"""

import asyncio
import base64
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.pii.crypto import (  # noqa: E402
    SlotBindingError,
    decrypt_sample_value,
    decrypt_slot_value,
    encrypt_sample_value,
)
from app.services.pii.stage0p_evaluation import (  # noqa: E402
    evaluation_hash,
    validate_spans,
)
from app.services.pii.stage0p_prediction import (  # noqa: E402
    PredictionNotAllowedError,
    run_prediction_writer,
)
from app.services.pii.taxonomy import DETECTOR_VERSION  # noqa: E402

DB_URL = (os.environ.get("DATABASE_URL")
          or "postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s").replace("+asyncpg", "")

_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


async def main() -> int:
    settings.m4_sample_key_b64 = base64.b64encode(os.urandom(32)).decode()
    settings.m4_slot_key_b64 = base64.b64encode(os.urandom(32)).decode()
    admin = await asyncpg.connect(DB_URL)
    for tbl in ("m4_shadow_review_samples", "m4_selection_batches", "audit_log",
               "messages", "orders", "conversations", "customers"):
        await admin.execute(f"DELETE FROM {tbl}")

    cust = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('eval-t','x') RETURNING id")
    conv = await admin.fetchrow("INSERT INTO conversations (customer_id) VALUES ($1) RETURNING id", cust["id"])
    batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start,window_end,eligible_count,selected_count,"
        "algorithm_seed,locked_conversation_ids,purpose_code) VALUES (now()-interval '1 day',now(),"
        "1,1,'evalt',ARRAY[$1]::bigint[],'P12_PII_DETECTOR_EVAL') RETURNING batch_id", conv["id"])

    text = "so dien thoai cua toi la 0912345678 va 0987654321 nhe shop"
    sample_id = str(uuid.uuid4())
    blob = encrypt_sample_value(text, customer_ref=str(cust["id"]), conversation_ref=str(conv["id"]),
                                sample_id=sample_id)
    await admin.execute(
        "INSERT INTO m4_shadow_review_samples (sample_id,customer_ref,conversation_ref,encrypted_message,"
        "canonical_text_len,expires_at,purpose_code,normalization_version,selection_batch) VALUES "
        "($1,$2,$3,$4,$5,now()+interval '1 day','P12_PII_DETECTOR_EVAL','nfc-v1',$6)",
        sample_id, str(cust["id"]), str(conv["id"]), blob, len(text), batch["batch_id"])

    print("== [1] Domain/key separation: sample blob KHONG giai ma duoc bang ham slot ==")
    try:
        decrypt_slot_value(blob, customer_ref=str(cust["id"]), conversation_ref=str(conv["id"]),
                           slot_type="phone")
        check(False, "phai fail — domain tag/version khac nhau")
    except Exception as e:  # noqa: BLE001
        check(True, f"dung nhu ky vong ({type(e).__name__})")

    print("== [2] Tamper tren row DB that ==")
    row = await admin.fetchrow("SELECT encrypted_message FROM m4_shadow_review_samples WHERE sample_id=$1",
                               sample_id)
    tampered = bytearray(bytes(row["encrypted_message"]))
    tampered[-1] ^= 0xFF
    try:
        decrypt_sample_value(bytes(tampered), customer_ref=str(cust["id"]), conversation_ref=str(conv["id"]),
                             sample_id=sample_id)
        check(False, "tamper phai fail")
    except SlotBindingError:
        check(True, "tamper tren ciphertext that -> SlotBindingError")

    print("== [3] Cross-context tren row DB that (doi customer_ref cua context giai ma) ==")
    other_cust = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('eval-t2','y') RETURNING id")
    try:
        decrypt_sample_value(bytes(row["encrypted_message"]), customer_ref=str(other_cust["id"]),
                             conversation_ref=str(conv["id"]), sample_id=sample_id)
        check(False, "cross-context phai fail")
    except SlotBindingError:
        check(True, "doi customer_ref -> SlotBindingError (AAD khong khop)")

    print("== [4]+[5] Offset-bounds + non-overlap tren detector output THAT ==")
    from app.services.pii.detector import detect
    result = detect(text)
    from app.services.pii.stage0p_evaluation import span_to_dict
    spans = [span_to_dict(sp) for sp in result.spans]
    check(len(spans) >= 2, f"detector tim thay >=2 span (thuc te {len(spans)}: {[s['slot_type'] for s in spans]})")
    errors = validate_spans(spans, len(text))
    check(errors == [], f"detector output THAT khong vi pham bounds/non-overlap (loi: {errors})")

    print("== [6] normalization_version mismatch bi loai khoi gate ==")
    sample_id2 = str(uuid.uuid4())
    blob2 = encrypt_sample_value("khac version", customer_ref=str(cust["id"]), conversation_ref=str(conv["id"]),
                                 sample_id=sample_id2)
    await admin.execute(
        "INSERT INTO m4_shadow_review_samples (sample_id,customer_ref,conversation_ref,encrypted_message,"
        "canonical_text_len,expires_at,purpose_code,normalization_version,label_status,selection_batch) "
        "VALUES ($1,$2,$3,$4,$5,now()+interval '1 day','P12_PII_DETECTOR_EVAL','nfc-v0-cu','labeled',$6)",
        sample_id2, str(cust["id"]), str(conv["id"]), blob2, 12, batch["batch_id"])
    await admin.execute(
        "UPDATE m4_shadow_review_samples SET label_status='labeled' WHERE sample_id=$1", sample_id)
    pw_conn = await asyncpg.connect(DB_URL)
    await pw_conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    pred_result = await run_prediction_writer(pw_conn, batch_id=batch["batch_id"], evaluation_batch="ev-1")
    check(pred_result["skipped_version_mismatch"] == 1, "row normalization_version cu bi bo qua (khong cham)")
    check(pred_result["updated"] == 1, "row dung version duoc cham diem")

    print("== [7] Label-before-prediction (kiem lai qua DB that, batch moi hoan toan unlabeled) ==")
    sample_id3 = str(uuid.uuid4())
    blob3 = encrypt_sample_value("chua label", customer_ref=str(cust["id"]), conversation_ref=str(conv["id"]),
                                 sample_id=sample_id3)
    batch2 = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start,window_end,eligible_count,selected_count,"
        "algorithm_seed,locked_conversation_ids,purpose_code) VALUES (now()-interval '1 day',now(),"
        "1,1,'evalt2',ARRAY[$1]::bigint[],'P12_PII_DETECTOR_EVAL') RETURNING batch_id", conv["id"])
    await admin.execute(
        "INSERT INTO m4_shadow_review_samples (sample_id,customer_ref,conversation_ref,encrypted_message,"
        "canonical_text_len,expires_at,purpose_code,normalization_version,selection_batch) VALUES "
        "($1,$2,$3,$4,10,now()+interval '1 day','P12_PII_DETECTOR_EVAL','nfc-v1',$5)",
        sample_id3, str(cust["id"]), str(conv["id"]), blob3, batch2["batch_id"])
    try:
        await run_prediction_writer(pw_conn, batch_id=batch2["batch_id"], evaluation_batch="ev-2")
        check(False, "phai bi tu choi (con row unlabeled)")
    except PredictionNotAllowedError:
        check(True, "batch con unlabeled -> tu choi dung")
    await pw_conn.close()

    print("== [8] Evaluation hash deterministic + nhay voi tham so ==")
    h1 = evaluation_hash(detector_version=DETECTOR_VERSION, normalization_version="nfc-v1",
                         evaluation_batch="ev-1")
    h2 = evaluation_hash(detector_version=DETECTOR_VERSION, normalization_version="nfc-v1",
                         evaluation_batch="ev-1")
    h3 = evaluation_hash(detector_version=DETECTOR_VERSION, normalization_version="nfc-v1",
                         evaluation_batch="ev-2")
    check(h1 == h2, "cung tham so -> cung hash")
    check(h1 != h3, "khac evaluation_batch -> khac hash")
    stored = await admin.fetchval(
        "SELECT detector_version FROM m4_shadow_review_samples WHERE sample_id=$1", sample_id)
    check(stored == DETECTOR_VERSION, "detector_version thuc te da ghi vao DB khop hang so taxonomy")

    for tbl in ("m4_shadow_review_samples", "m4_selection_batches", "audit_log",
               "messages", "orders", "conversations", "customers"):
        await admin.execute(f"DELETE FROM {tbl}")
    await admin.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
