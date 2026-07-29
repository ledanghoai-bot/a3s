#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: crypto DB-integrated + evaluation methodology (CA acceptance
criteria #10, #11, #12; REV2 CA Technical Review #1 T1-03/T1-04/T1-06).

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
  [6] REV2 (T1-03): seal_labels() qua DB — chong thien lech xac nhan van dung sau khi chuyen
      sang ham SECURITY DEFINER (khong con Python-level unlabeled-count check).
  [7] REV2 (T1-03): write_predictions() tu choi tren batch CHUA sealed (goi qua Python wrapper
      run_prediction_writer, khong phai goi SQL truc tiep nhu permissions_test.py — chung minh
      wrapper Python truyen dung loi tu DB len thanh PredictionNotAllowedError).
  [8] normalization_version mismatch bi loai khoi gate (khong so sanh nham 2 chuan hoa khac nhau)
      — chay SAU KHI batch da sealed (T1-03 doi thu tu: sealed truoc, predict sau).
  [9] REV2 (T1-04): corpus_manifest_hash/result_hash/report_hash — deterministic + nhay voi noi
      dung THAT (khac evaluation_hash() cu da XOA).
  [10] REV2 (T1-06): complete_evaluation() qua DB — evaluation_completed_at duoc set DUNG SAU
      KHI tat ca prediction da ghi; purge_expired() ton trong cot nay (kiem lai o
      m4_stage0p_permissions_test.py cho phan tu choi, o day kiem luong THANH CONG completo).
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
    complete_evaluation,
    corpus_manifest_hash,
    report_hash,
    result_hash,
    seal_labels,
    validate_spans,
)
from app.services.pii.stage0p_prediction import (  # noqa: E402
    PredictionNotAllowedError,
    run_prediction_writer,
)
from app.services.pii.stage0p_sampling import purge_expired  # noqa: E402
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
               "messages", "orders", "conversations", "customers", "staff_users"):
        await admin.execute(f"DELETE FROM {tbl}")

    staff = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ('m4-eval-test-staff', 'x', 'x', true) RETURNING id")

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

    print("== [7] REV2 T1-03: write_predictions tu choi tren batch CHUA sealed (qua Python wrapper) ==")
    pw_conn = await asyncpg.connect(DB_URL)
    await pw_conn.execute("SET ROLE alpha3s_m4_prediction_writer")
    try:
        await run_prediction_writer(pw_conn, batch_id=batch["batch_id"], evaluation_batch="ev-unsealed")
        check(False, "batch chua sealed -> run_prediction_writer phai raise PredictionNotAllowedError")
    except PredictionNotAllowedError:
        check(True, "batch chua sealed -> PredictionNotAllowedError dung (loi DB duoc boc lai dung)")

    print("== [6] REV2 T1-03: seal_labels() qua DB — chong thien lech xac nhan ==")
    reviewer_conn = await asyncpg.connect(DB_URL)
    await reviewer_conn.execute("SET ROLE alpha3s_m4_sample_reviewer_api")
    try:
        await seal_labels(reviewer_conn, batch_id=batch["batch_id"], actor_staff_id=staff["id"])
        check(False, "sample chua labeled -> seal_labels phai raise")
    except asyncpg.PostgresError:
        check(True, "sample chua labeled -> seal_labels tu choi dung")
    await admin.execute(
        "UPDATE m4_shadow_review_samples SET label_status='labeled', labeled_slots=$1::jsonb "
        "WHERE sample_id=$2", '[]', sample_id)
    seal_result = await seal_labels(reviewer_conn, batch_id=batch["batch_id"], actor_staff_id=staff["id"])
    check(seal_result["sample_count"] == 1, "sau khi labeled -> seal_labels thanh cong (sample_count=1)")
    corpus_hash_1 = seal_result["labels_sealed_hash"]
    sealed_batch_row = await admin.fetchrow(
        "SELECT labels_sealed_at, labels_sealed_hash FROM m4_selection_batches WHERE batch_id=$1",
        batch["batch_id"])
    check(sealed_batch_row["labels_sealed_at"] is not None, "labels_sealed_at duoc set tren DB")
    check(sealed_batch_row["labels_sealed_hash"] == corpus_hash_1, "labels_sealed_hash tren DB khop gia tri tra ve")
    await reviewer_conn.close()

    print("== [8] normalization_version mismatch bi loai khoi gate (SAU KHI batch da sealed) ==")
    sample_id2 = str(uuid.uuid4())
    blob2 = encrypt_sample_value("khac version", customer_ref=str(cust["id"]), conversation_ref=str(conv["id"]),
                                 sample_id=sample_id2)
    batch2 = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start,window_end,eligible_count,selected_count,"
        "algorithm_seed,locked_conversation_ids,purpose_code) VALUES (now()-interval '1 day',now(),"
        "1,1,'evalt2',ARRAY[$1]::bigint[],'P12_PII_DETECTOR_EVAL') RETURNING batch_id", conv["id"])
    await admin.execute(
        "INSERT INTO m4_shadow_review_samples (sample_id,customer_ref,conversation_ref,encrypted_message,"
        "canonical_text_len,expires_at,purpose_code,normalization_version,label_status,labeled_slots,"
        "selection_batch) "
        "VALUES ($1,$2,$3,$4,$5,now()+interval '1 day','P12_PII_DETECTOR_EVAL','nfc-v0-cu','labeled',"
        "'[]'::jsonb,$6)",
        sample_id2, str(cust["id"]), str(conv["id"]), blob2, 12, batch2["batch_id"])
    reviewer_conn2 = await asyncpg.connect(DB_URL)
    await reviewer_conn2.execute("SET ROLE alpha3s_m4_sample_reviewer_api")
    await seal_labels(reviewer_conn2, batch_id=batch2["batch_id"], actor_staff_id=staff["id"])
    await reviewer_conn2.close()
    pred_result = await run_prediction_writer(pw_conn, batch_id=batch2["batch_id"], evaluation_batch="ev-1")
    check(pred_result["skipped_version_mismatch"] == 1, "row normalization_version cu bi bo qua (khong cham)")
    check(pred_result["updated"] == 0, "khong co row nao duoc cham diem trong batch2 (chi 1 row, bi skip)")

    print("== write_predictions THANH CONG tren batch1 (da sealed o buoc [6]) ==")
    pred_result_1 = await run_prediction_writer(pw_conn, batch_id=batch["batch_id"], evaluation_batch="ev-main")
    check(pred_result_1["updated"] == 1, "batch1 da sealed -> prediction ghi thanh cong (updated=1)")
    predicted_row = await admin.fetchrow(
        "SELECT predicted_slots, detector_version FROM m4_shadow_review_samples WHERE sample_id=$1", sample_id)
    check(predicted_row["detector_version"] == DETECTOR_VERSION, "detector_version thuc te khop hang so taxonomy")
    await pw_conn.close()

    print("== [9] REV2 T1-04: corpus_manifest_hash/result_hash/report_hash — deterministic + nhay noi dung ==")
    samples_for_hash = [{"sample_id": sample_id, "labeled_slots": [], "truncated": False}]
    ch1 = corpus_manifest_hash(batch_id=str(batch["batch_id"]), samples=samples_for_hash,
                               normalization_version="nfc-v1")
    ch2 = corpus_manifest_hash(batch_id=str(batch["batch_id"]), samples=samples_for_hash,
                               normalization_version="nfc-v1")
    check(ch1 == ch2, "corpus_manifest_hash deterministic tren CUNG corpus")
    samples_diff = [{"sample_id": sample_id, "labeled_slots": [{"slot_type": "phone", "start": 0, "end": 3,
                                                                "confidence": "high", "reason": "x"}],
                     "truncated": False}]
    ch3 = corpus_manifest_hash(batch_id=str(batch["batch_id"]), samples=samples_diff,
                               normalization_version="nfc-v1")
    check(ch1 != ch3, "corpus KHAC noi dung -> hash KHAC (CA T1-04: khong con chi hash 3 chuoi roi)")

    predictions_for_hash = [{"sample_id": sample_id, "predicted_slots": predicted_row["predicted_slots"]}]
    rh1 = result_hash(corpus_hash=ch1, detector_version=DETECTOR_VERSION,
                      ordered_predictions=predictions_for_hash)
    rh2 = result_hash(corpus_hash=ch1, detector_version=DETECTOR_VERSION,
                      ordered_predictions=predictions_for_hash)
    check(rh1 == rh2, "result_hash deterministic")
    metrics = {"phone": {"tp": 2, "fn": 0, "fp": 0, "recall": 1.0, "precision": 1.0}}
    rep1 = report_hash(corpus_hash=ch1, result_hash_value=rh1, metrics=metrics)
    rep2 = report_hash(corpus_hash=ch1, result_hash_value=rh1, metrics=metrics)
    check(rep1 == rep2, "report_hash deterministic")
    metrics_diff = {"phone": {"tp": 1, "fn": 1, "fp": 0, "recall": 0.5, "precision": 1.0}}
    rep3 = report_hash(corpus_hash=ch1, result_hash_value=rh1, metrics=metrics_diff)
    check(rep1 != rep3, "metrics KHAC -> report_hash KHAC")

    print("== [10] REV2 T1-06: complete_evaluation() — evaluation_completed_at set dung sau khi predict xong ==")
    evaluator_conn = await asyncpg.connect(DB_URL)
    await evaluator_conn.execute("SET ROLE alpha3s_m4_sample_evaluator")
    complete_result = await complete_evaluation(evaluator_conn, batch_id=batch["batch_id"],
                                                actor_staff_id=staff["id"], report_hash_value=rep1)
    check(complete_result["completed_at"] is not None, "complete_evaluation tra ve completed_at")
    batch_after = await admin.fetchrow(
        "SELECT evaluation_completed_at, evaluation_report_hash, status FROM m4_selection_batches "
        "WHERE batch_id=$1", batch["batch_id"])
    check(batch_after["evaluation_completed_at"] is not None, "evaluation_completed_at duoc set tren DB")
    check(batch_after["evaluation_report_hash"] == rep1, "evaluation_report_hash tren DB khop gia tri truyen vao")
    check(batch_after["status"] == "closed", "batch chuyen status='closed' sau complete_evaluation")
    await evaluator_conn.close()

    print("== purge_expired() ton trong evaluation_completed_at (T1-06) ==")
    purge_conn = await asyncpg.connect(DB_URL)
    await purge_conn.execute("SET ROLE alpha3s_m4_sample_purge")
    purged = await purge_expired(purge_conn)
    check(purged >= 1, f"batch1 da eval-completed -> sample bi purge (thuc te {purged})")
    remaining = await admin.fetchval(
        "SELECT count(*) FROM m4_shadow_review_samples WHERE selection_batch=$1", batch["batch_id"])
    check(remaining == 0, "sample cua batch1 (da eval-completed) da bi xoa het")
    remaining2 = await admin.fetchval(
        "SELECT count(*) FROM m4_shadow_review_samples WHERE selection_batch=$1", batch2["batch_id"])
    check(remaining2 == 1, "sample cua batch2 (CHUA eval-completed, chua het han) KHONG bi purge")
    await purge_conn.close()

    for tbl in ("m4_shadow_review_samples", "m4_selection_batches", "audit_log",
               "messages", "orders", "conversations", "customers", "staff_users"):
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
