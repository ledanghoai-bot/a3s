"""I-B M4 Stage 0P — prediction writer (sau-labeling, F-M4-0P-05A CLOSED AT DESIGN LEVEL).

Chay detector tren `encrypted_message` GIAI MA TAM THOI trong bo nho (plaintext KHONG BAO GIO
log/return ra ngoai ham nay) — ghi `predicted_slots` CUNG format `labeled_slots` (co offset).

REV 2 (CA Technical Review #1, T1-03): rang buoc CAU TRUC chong thien lech xac nhan (§5.4)
KHONG con la 1 kiem tra Python (`unlabeled count`) roi UPDATE truc tiep — do la TOCTOU, va role
`alpha3s_m4_prediction_writer` truoc day co UPDATE truc tiep tren cot du doan nen co the bi bypass
bang SQL truc tiep hoac bug. Gio: `run_prediction_writer` CHI doc (decrypt + detect trong bo
nho), roi ghi TAT CA prediction qua 1 loi goi DUY NHAT den ham SECURITY DEFINER
`m4_stage0p_write_predictions` (migration 039 §5d) — ham DO tu kiem tra ATOMIC la batch DA
`labels_sealed_at IS NOT NULL` (seal qua `stage0p_evaluation.seal_labels`) truoc khi ghi bat ky
gi; role nay khong con UPDATE truc tiep tren `predicted_slots`/`detector_version`/
`evaluation_batch` (chi con EXECUTE ham).
"""

import json

from app.services.pii.crypto import decrypt_sample_value
from app.services.pii.detector import detect
from app.services.pii.stage0p_evaluation import span_to_dict
from app.services.pii.stage0p_sampling import NORMALIZATION_VERSION
from app.services.pii.taxonomy import DETECTOR_VERSION


class PredictionNotAllowedError(Exception):
    """Batch chua sealed (con row unlabeled, hoac chua goi seal_labels) — DB tu choi ghi."""


def _log(event: str, **fields) -> None:
    print("[m4-stage0p-prediction] " + json.dumps({"event": event, **fields},
                                                   ensure_ascii=False, sort_keys=True))


async def run_prediction_writer(conn, *, batch_id: str, evaluation_batch: str) -> dict:
    """`conn` phai xac thuc bang role `alpha3s_m4_prediction_writer`. Doc + decrypt + chay
    detector cho MOI row chua co prediction (Python-side, khong ghi gi trong buoc nay), roi ghi
    TAT CA prediction qua 1 loi goi `m4_stage0p_write_predictions` — ham DO tu choi (raise
    Postgres error, boc lai thanh `PredictionNotAllowedError` o day) neu batch chua sealed.
    Tra {updated, skipped_version_mismatch}."""
    rows = await conn.fetch(
        "SELECT sample_id, encrypted_message, customer_ref, conversation_ref, "
        "canonical_text_len, normalization_version FROM m4_shadow_review_samples "
        "WHERE selection_batch = $1 AND predicted_slots IS NULL",
        batch_id,
    )

    predictions: list[dict] = []
    skipped_version_mismatch = 0
    for row in rows:
        if row["normalization_version"] != NORMALIZATION_VERSION:
            skipped_version_mismatch += 1
            _log("m4_prediction_skip_version_mismatch", sample_id=str(row["sample_id"]))
            continue

        plaintext = decrypt_sample_value(
            bytes(row["encrypted_message"]), customer_ref=row["customer_ref"],
            conversation_ref=row["conversation_ref"], sample_id=str(row["sample_id"]),
        )
        result = detect(plaintext)
        # plaintext KHONG duoc dua vao bien nao khac tu day tro di — chi span (offset/enum)
        spans = [span_to_dict(s) for s in result.spans]
        predictions.append({"sample_id": str(row["sample_id"]), "predicted_slots": spans})

    if not predictions:
        _log("m4_prediction_done", batch_id=str(batch_id), updated=0,
             skipped_version_mismatch=skipped_version_mismatch)
        return {"updated": 0, "skipped_version_mismatch": skipped_version_mismatch}

    try:
        write_row = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1, $2::jsonb, $3, $4)",
            batch_id, json.dumps(predictions), DETECTOR_VERSION, evaluation_batch,
        )
    except Exception as e:  # noqa: BLE001 — boc loi DB (chua sealed, v.v.) thanh loi ro rang
        _log("m4_prediction_refused", batch_id=str(batch_id), error=str(e))
        raise PredictionNotAllowedError(str(e)) from e

    updated = write_row["updated_count"]
    _log("m4_prediction_done", batch_id=str(batch_id), updated=updated,
         skipped_version_mismatch=skipped_version_mismatch)
    return {"updated": updated, "skipped_version_mismatch": skipped_version_mismatch}
