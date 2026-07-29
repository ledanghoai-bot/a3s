"""I-B M4 Stage 0P — prediction writer (sau-labeling, F-M4-0P-05A CLOSED AT DESIGN LEVEL).

Chay detector tren `encrypted_message` GIAI MA TAM THOI trong bo nho (plaintext KHONG BAO GIO
log/return ra ngoai ham nay) — ghi `predicted_slots` CUNG format `labeled_slots` (co offset).

REV 2 (T1-03): ghi prediction CHI qua ham SECURITY DEFINER `m4_stage0p_write_predictions`.

REV 3 (CA Technical Review #2, T2-02/T2-03/T2-04): 2 sua doi lon:
  - T2-02: KHONG con SELECT+decrypt truc tiep tren bang truoc khi biet batch sealed (REV2 van
    con lam vay — DB chi tu choi o buoc GHI cuoi cung, nhung role prediction_writer da doc/giai
    ma xong het corpus tu truoc do). Gio doc TUNG sample qua ham SECURITY DEFINER
    `m4_stage0p_fetch_sealed_message` — ham DO kiem `labels_sealed_at IS NOT NULL` TRUOC KHI tra
    BAT KY `encrypted_message` nao; batch chua sealed -> 0 row nao roi khoi ham (0 raw fetch,
    khong chi 0 write).
  - T2-03/T2-04: `write_predictions` gio doi hoi PHU DUNG toan bo corpus — sample bi loai vi
    normalization_version khong khop duoc dua vao `exclusions` (co ly do ro rang) thay vi chi
    "bo qua am tham"; va phai truyen `expected_labels_sealed_hash` (doc tu batch row TRUOC) de DB
    doi chieu, tu choi neu stale/forged.
"""

import json

from app.services.pii.crypto import decrypt_sample_value
from app.services.pii.detector import detect
from app.services.pii.stage0p_evaluation import span_to_dict
from app.services.pii.stage0p_sampling import NORMALIZATION_VERSION
from app.services.pii.taxonomy import DETECTOR_VERSION


class PredictionNotAllowedError(Exception):
    """DB tu choi ghi prediction — batch chua sealed / labels_sealed_hash khong khop / da ghi
    prediction truoc do (bat bien) / payload khong hop le (schema/bounds/coverage)."""


def _log(event: str, **fields) -> None:
    print("[m4-stage0p-prediction] " + json.dumps({"event": event, **fields},
                                                   ensure_ascii=False, sort_keys=True))


async def run_prediction_writer(conn, *, batch_id: str, evaluation_batch: str) -> dict:
    """`conn` phai xac thuc bang role `alpha3s_m4_prediction_writer`. REV3: doc TUNG sample qua
    `m4_stage0p_fetch_sealed_message` (KHONG con SELECT truc tiep — xem docstring module),
    decrypt + chay detector trong bo nho, roi ghi TAT CA (predictions + exclusions) qua 1 loi
    goi `m4_stage0p_write_predictions`. Tra {updated, skipped_version_mismatch, result_hash}."""
    batch_row = await conn.fetchrow(
        "SELECT labels_sealed_hash FROM m4_selection_batches WHERE batch_id = $1", batch_id)
    if batch_row is None or batch_row["labels_sealed_hash"] is None:
        raise PredictionNotAllowedError(f"batch {batch_id} chua sealed hoac khong ton tai")
    expected_hash = batch_row["labels_sealed_hash"]

    predictions: list[dict] = []
    exclusions: list[dict] = []
    after_sample_id = None
    while True:
        try:
            row = await conn.fetchrow(
                "SELECT * FROM m4_stage0p_fetch_sealed_message($1, $2)", batch_id, after_sample_id,
            )
        except Exception as e:  # noqa: BLE001 — boc loi DB (batch chua sealed, v.v.) ro rang cho caller
            _log("m4_prediction_fetch_sealed_failed", batch_id=str(batch_id), error=str(e))
            raise PredictionNotAllowedError(str(e)) from e

        if row["status"] == "exhausted":
            break
        after_sample_id = row["sample_id"]

        if row["normalization_version"] != NORMALIZATION_VERSION:
            exclusions.append({"sample_id": str(row["sample_id"]), "reason": "normalization_version_mismatch"})
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

    if not predictions and not exclusions:
        _log("m4_prediction_done", batch_id=str(batch_id), updated=0, skipped_version_mismatch=0)
        return {"updated": 0, "skipped_version_mismatch": 0, "result_hash": None}

    try:
        write_row = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_write_predictions($1, $2, $3::jsonb, $4::jsonb, $5, $6)",
            batch_id, expected_hash, json.dumps(predictions), json.dumps(exclusions),
            DETECTOR_VERSION, evaluation_batch,
        )
    except Exception as e:  # noqa: BLE001 — boc loi DB (validation/coverage/immutability) ro rang
        _log("m4_prediction_refused", batch_id=str(batch_id), error=str(e))
        raise PredictionNotAllowedError(str(e)) from e

    updated = write_row["updated_count"]
    excluded = write_row["excluded_count"]
    result_hash = write_row["result_hash"]
    _log("m4_prediction_done", batch_id=str(batch_id), updated=updated,
         skipped_version_mismatch=excluded, result_hash=result_hash)
    return {"updated": updated, "skipped_version_mismatch": excluded, "result_hash": result_hash}
