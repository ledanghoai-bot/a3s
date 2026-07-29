"""I-B M4 Stage 0P — prediction writer (sau-labeling, F-M4-0P-05A CLOSED AT DESIGN LEVEL).

Chay detector tren `encrypted_message` GIAI MA TAM THOI trong bo nho (plaintext KHONG BAO GIO
log/return ra ngoai ham nay) — ghi `predicted_slots` CUNG format `labeled_slots` (co offset).

Rang buoc CAU TRUC chong thien lech xac nhan (§5.4): TU CHOI chay neu con BAT KY row nao trong
batch chua `label_status='labeled'` — khong phai quy uoc quy trinh, la kiem tra bat buoc truoc
khi ghi bat ky gi.
"""

import json

from app.services.pii.crypto import decrypt_sample_value
from app.services.pii.detector import detect
from app.services.pii.stage0p_evaluation import span_to_dict
from app.services.pii.stage0p_sampling import NORMALIZATION_VERSION
from app.services.pii.taxonomy import DETECTOR_VERSION


class PredictionNotAllowedError(Exception):
    """Batch con row unlabeled — chong thien lech xac nhan (§5.4)."""


def _log(event: str, **fields) -> None:
    print("[m4-stage0p-prediction] " + json.dumps({"event": event, **fields},
                                                   ensure_ascii=False, sort_keys=True))


async def run_prediction_writer(conn, *, batch_id: str, evaluation_batch: str) -> dict:
    """`conn` phai xac thuc bang role `alpha3s_m4_prediction_writer`. Tra {updated, skipped}."""
    unlabeled = await conn.fetchval(
        "SELECT count(*) FROM m4_shadow_review_samples "
        "WHERE selection_batch = $1 AND label_status <> 'labeled'",
        batch_id,
    )
    if unlabeled > 0:
        _log("m4_prediction_refused", batch_id=str(batch_id), unlabeled_count=unlabeled)
        raise PredictionNotAllowedError(
            f"batch {batch_id} con {unlabeled} row chua labeled — tu choi chay du doan"
        )

    rows = await conn.fetch(
        "SELECT sample_id, encrypted_message, customer_ref, conversation_ref, "
        "canonical_text_len, normalization_version FROM m4_shadow_review_samples "
        "WHERE selection_batch = $1 AND predicted_slots IS NULL",
        batch_id,
    )

    updated = skipped_version_mismatch = 0
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
        await conn.execute(
            "UPDATE m4_shadow_review_samples SET predicted_slots = $1::jsonb, "
            "detector_version = $2, evaluation_batch = $3 WHERE sample_id = $4",
            json.dumps(spans), DETECTOR_VERSION, evaluation_batch, row["sample_id"],
        )
        updated += 1

    _log("m4_prediction_done", batch_id=str(batch_id), updated=updated,
         skipped_version_mismatch=skipped_version_mismatch)
    return {"updated": updated, "skipped_version_mismatch": skipped_version_mismatch}
