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

REV 4 (CA Technical Review #3, T3-03): `write_predictions` gio con nhan them
`p_current_normalization_version` — DB TU XAC MINH dieu kien "normalization_version_mismatch" la
THAT (so voi gia tri nay) chu khong tin caller khai bao dung; reason exclusion cung phai nam
trong allowlist DB-side.

REV 5 (CA Technical Review #4, T4-02/T4-05): CA chi ro `p_current_normalization_version` REV4
VAN la tham so caller tu khai — caller co the truyen gia tri gia de ep moi row thanh "mismatch".
Sua: XOA HAN tham so nay — DB tu so sanh voi hang so HARDCODE trong than ham
`m4_stage0p_write_predictions`. T4-05: nguong exclusion (>50% REV4, Dev tu chon, chua duyet) doi
thanh doc tu bang `m4_stage0p_exclusion_gate` (2 dieu kien: ty le + so conversation toi thieu) —
seed dung de xuat CA Review #4 (10%/200), CHUA co PO decision record chinh thuc.

REV 6 (CA Technical Review #5, T5-04, P2): hang so HARDCODE REV5 van ton tai o CA 2 NOI (DB
literal + Python `NORMALIZATION_VERSION`) — khong phai 1 nguon that su, doi hoi con nguoi "bump ca
2 noi". Sua: XOA HAN module constant — pre-filter duoi day doc `current_version` tu bang DB
`m4_stage0p_normalization_registry` (nguon THAT DUY NHAT, cung bang ma `m4_stage0p_write_
predictions` doc — xem `stage0p_sampling.get_current_normalization_version()`).

REV 8 (CA Technical Review #7, T7-03, P2): pre-filter REV6 doc "current" TOAN CUC tu registry —
SAI authority cho 1 batch DANG CHAY neu registry doi SAU khi batch lock/capture nhung TRUOC
prediction (batch hop le theo version DA KHOA co the bi loai hang loat mot cach sai lech). Sua:
doc `normalization_version` da khoa TREN CHINH batch row (tu luc `lock_batch`, FK dam bao luon
ton tai trong registry) thay vi goi lai `get_current_normalization_version()` — "current" toan
cuc gio CHI con quyet dinh version cho batch MOI (xem `stage0p_sampling.lock_batch`), khong phai
authority cho batch dang chay. `m4_stage0p_write_predictions` (DB) sua tuong tu, doc
`v_batch.normalization_version` thay vi row `is_current=true`.
"""

import json

from app.services.pii.crypto import decrypt_sample_value
from app.services.pii.detector import detect
from app.services.pii.stage0p_evaluation import span_to_dict
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
        "SELECT labels_sealed_hash, normalization_version FROM m4_selection_batches WHERE batch_id = $1",
        batch_id)
    if batch_row is None or batch_row["labels_sealed_hash"] is None:
        raise PredictionNotAllowedError(f"batch {batch_id} chua sealed hoac khong ton tai")
    expected_hash = batch_row["labels_sealed_hash"]

    # REV8 T7-03: dung version DA KHOA cua CHINH batch (tu luc lock_batch), khong con doc "current"
    # toan cuc — CA chi ro registry co the doi SAU khi batch lock/capture nhung TRUOC prediction,
    # luc do "current" toan cuc KHONG con la authority dung cho batch DANG CHAY nay (DB-side cung
    # sua tuong tu trong m4_stage0p_write_predictions, xem migration 039 REV8).
    current_normalization_version = batch_row["normalization_version"]

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

        if row["normalization_version"] != current_normalization_version:
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
    except Exception as e:  # noqa: BLE001 — boc loi DB (validation/coverage/immutability/gate) ro rang
        _log("m4_prediction_refused", batch_id=str(batch_id), error=str(e))
        raise PredictionNotAllowedError(str(e)) from e

    updated = write_row["updated_count"]
    excluded = write_row["excluded_count"]
    result_hash = write_row["result_hash"]
    _log("m4_prediction_done", batch_id=str(batch_id), updated=updated,
         skipped_version_mismatch=excluded, result_hash=result_hash,
         non_excluded_conversation_count=write_row["non_excluded_conversation_count"],
         gate_version=write_row["gate_version"])
    return {"updated": updated, "skipped_version_mismatch": excluded, "result_hash": result_hash,
            "non_excluded_conversation_count": write_row["non_excluded_conversation_count"],
            "gate_version": write_row["gate_version"]}
