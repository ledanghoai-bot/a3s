"""I-B M4 Stage 0P — evaluation methodology (F-M4-0P-05A, CLOSED AT DESIGN LEVEL).

Rut lai instance-count-only (S0): count theo (message, slot_type) co the bao TP khi detector
khoanh SAI vi tri/thuc the mien so luong/loai khop (vd 2 so dien thoai, detector bat trung so
#1 hai lan, bo sot so #2 — count-only van bao "2 khop 2"). **Exact-span la gate chinh**;
overlap/IoU la metric PHU (nguong can PO/CA duyet, Dev khong tu chon); count-only ha xuong tham
khao. Khong dung `PIISpan.as_safe_dict()` (S0) — do la cho log live-traffic (boi canh rui ro
khac han), offset KHONG phai plaintext PII nen an toan luu trong jsonb restricted-access nay.

REV 2 (CA Technical Review #1, T1-03/T1-04): them 2 nhom ham:
  - `label_set_hash` + `seal_labels` — khoa ground truth qua ham DB `m4_stage0p_seal_labels`
    (migration 039 §5c) TRUOC khi cho phep prediction writer chay (T1-03).
  - `corpus_manifest_hash`/`result_hash`/`report_hash` — THAY THE HOAN TOAN `evaluation_hash()`
    cu (da XOA — CA chi ro no chi hash 3 chuoi roi `detector_version|normalization_version|
    evaluation_batch`, 2 corpus khac nhau cung 3 tham so nay se ra CUNG hash, khong chung minh
    duoc report tai lap dung tren CHINH tap du lieu da seal). 3 ham moi bind THAT noi dung: sample
    ids + tung ground-truth hash + normalization_version (corpus), + detector_version + du doan
    theo thu tu (result), + matching-rule/aggregation version + metrics (report).
"""

import hashlib
import json
from collections import defaultdict

MATCHING_RULE_VERSION = "exact-span-v1"
AGGREGATION_VERSION = "micro-v1"


def _canonical_json(obj) -> str:
    """Serialize doc lap: sort_keys + separator co dinh, khong khoang trang thua."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def span_to_dict(span) -> dict:
    """PIISpan -> dict CO offset — dung cho labeled_slots/predicted_slots (KHAC
    PIISpan.as_safe_dict() cua S0, xem docstring module)."""
    return {
        "slot_type": span.slot_type.value,
        "start": span.start,
        "end": span.end,
        "confidence": span.confidence.value,
        "reason": span.reason.value,
    }


def validate_spans(spans: list[dict], canonical_text_len: int) -> list[str]:
    """Offset bounds (0<=start<end<=len) + non-overlap TRONG CUNG 1 tap nhan. Tra list loi
    (rong = hop le). Vi pham -> loai row khoi gate, khong phai 'gate=false' nhu truncated —
    day la bug can dieu tra."""
    errors: list[str] = []
    for s in spans:
        if not (0 <= s["start"] < s["end"] <= canonical_text_len):
            errors.append(f"offset_out_of_bounds:{s.get('slot_type')}:{s['start']}-{s['end']}")
    ordered = sorted(spans, key=lambda s: s["start"])
    for a, b in zip(ordered, ordered[1:]):
        if a["end"] > b["start"]:
            errors.append(f"overlap:{a.get('slot_type')}-{b.get('slot_type')}")
    return errors


def exact_span_match(ground_truth: list[dict], predicted: list[dict]) -> dict:
    """Gate chinh (F-M4-0P-05A): slot_type + start + end khop CHINH XAC, 1-1 matching (1
    prediction chi khop toi da 1 ground-truth va nguoc lai)."""
    matched_gt: set[int] = set()
    matched_pred: set[int] = set()
    for i, g in enumerate(ground_truth):
        for j, p in enumerate(predicted):
            if j in matched_pred:
                continue
            if (g["slot_type"] == p["slot_type"] and g["start"] == p["start"]
                    and g["end"] == p["end"]):
                matched_gt.add(i)
                matched_pred.add(j)
                break
    tp = len(matched_gt)
    return {"tp": tp, "fn": len(ground_truth) - tp, "fp": len(predicted) - tp}


def _iou(a: dict, b: dict) -> float:
    if a["slot_type"] != b["slot_type"]:
        return 0.0
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = (a["end"] - a["start"]) + (b["end"] - b["start"]) - inter
    return inter / union if union else 0.0


def overlap_match(ground_truth: list[dict], predicted: list[dict], *, threshold: float) -> dict:
    """Metric PHU (khong phai gate) — nguong `threshold` PHAI do PO/CA duyet truoc khi dung
    cho bat ky quyet dinh gate nao (Dev khong tu chon trong ham nay)."""
    matched_gt: set[int] = set()
    matched_pred: set[int] = set()
    for i, g in enumerate(ground_truth):
        best_j, best_score = None, 0.0
        for j, p in enumerate(predicted):
            if j in matched_pred:
                continue
            score = _iou(g, p)
            if score >= threshold and score > best_score:
                best_j, best_score = j, score
        if best_j is not None:
            matched_gt.add(i)
            matched_pred.add(best_j)
    tp = len(matched_gt)
    return {"tp": tp, "fn": len(ground_truth) - tp, "fp": len(predicted) - tp}


def count_only_match(ground_truth: list[dict], predicted: list[dict]) -> dict:
    """Metric THAM KHAO (ha tu gate S0-style xuong phu — F-M4-0P-05A). Theo slot_type, KHONG
    xet vi tri — giu de doi chieu nhung KHONG duoc dung de gate."""
    from collections import Counter
    gt_counts = Counter(s["slot_type"] for s in ground_truth)
    pred_counts = Counter(s["slot_type"] for s in predicted)
    tp = fn = fp = 0
    for slot in set(gt_counts) | set(pred_counts):
        g, p = gt_counts.get(slot, 0), pred_counts.get(slot, 0)
        tp += min(g, p)
        fn += max(0, g - p)
        fp += max(0, p - g)
    return {"tp": tp, "fn": fn, "fp": fp}


def aggregate_micro(per_row_results: list[dict]) -> dict:
    """Gop TP/FN/FP toan batch (theo slot_type) TRUOC khi tinh recall/precision — micro
    aggregation, khong dung macro (tranh row it slot co trong so bat thuong)."""
    agg: dict[str, dict] = defaultdict(lambda: {"tp": 0, "fn": 0, "fp": 0})
    for row in per_row_results:
        for slot, counts in row.items():
            agg[slot]["tp"] += counts["tp"]
            agg[slot]["fn"] += counts["fn"]
            agg[slot]["fp"] += counts["fp"]
    metrics = {}
    for slot, c in agg.items():
        denom_r = c["tp"] + c["fn"]
        denom_p = c["tp"] + c["fp"]
        metrics[slot] = {
            **c,
            "recall": (c["tp"] / denom_r) if denom_r else None,
            "precision": (c["tp"] / denom_p) if denom_p else None,
        }
    return metrics


def match_by_slot_type(ground_truth: list[dict], predicted: list[dict], *,
                       matcher=exact_span_match) -> dict:
    """Chay 1 matcher (exact_span_match mac dinh) THEO TUNG slot_type rieng — tra dict
    slot_type -> {tp,fn,fp}, dung truc tiep cho aggregate_micro."""
    slots = {s["slot_type"] for s in ground_truth} | {s["slot_type"] for s in predicted}
    result = {}
    for slot in slots:
        g = [s for s in ground_truth if s["slot_type"] == slot]
        p = [s for s in predicted if s["slot_type"] == slot]
        result[slot] = matcher(g, p)
    return result


def label_set_hash(rows: list[dict]) -> str:
    """Hash canonical tap ground truth DUNG DE SEAL (`rows`: [{"sample_id":...,
    "labeled_slots":...}]) — sap xep theo sample_id de doc lap voi thu tu tra ve tu DB. Dung
    lam `p_labels_hash` cho `m4_stage0p_seal_labels` (khong tinh lai trong SQL — xem ghi chu
    trong migration 039 §5c, atomicity that su nam o kiem tra unlabeled=0 BEN TRONG ham DB,
    khong phai o noi tinh hash)."""
    ordered = sorted(rows, key=lambda r: str(r["sample_id"]))
    canonical = _canonical_json([
        {"sample_id": str(r["sample_id"]), "labeled_slots": r["labeled_slots"]} for r in ordered
    ])
    return hashlib.sha256(("m4-stage0p-label-hash-v1|" + canonical).encode("utf-8")).hexdigest()


async def seal_labels(conn, *, batch_id: str, actor_staff_id: int) -> dict:
    """REV2 (T1-03): khoa ground truth truoc khi cho phep prediction. `conn` phai xac thuc bang
    role `alpha3s_m4_sample_reviewer_api`. Doc toan bo (sample_id, labeled_slots) cua batch, tinh
    `label_set_hash`, roi goi ham SECURITY DEFINER `m4_stage0p_seal_labels` — ham DO kiem tra
    LAI, ATOMIC, la tat ca row da `label_status='labeled'` truoc khi cho seal (khong phu thuoc
    Python da doc dung). Sau khi return, trigger DB (migration 039 §4) chan MOI sua doi them tren
    labeled_slots/label_status cua batch nay, bat ke role nao."""
    rows = await conn.fetch(
        "SELECT sample_id, labeled_slots FROM m4_shadow_review_samples WHERE selection_batch = $1",
        batch_id,
    )
    h = label_set_hash([dict(r) for r in rows])
    result = await conn.fetchrow(
        "SELECT * FROM m4_stage0p_seal_labels($1, $2, $3)", batch_id, actor_staff_id, h,
    )
    return {"labels_sealed_hash": result["sealed_hash"], "sample_count": result["sample_count"]}


def corpus_manifest_hash(*, batch_id: str, samples: list[dict], normalization_version: str) -> str:
    """REV2 (T1-04): rang buoc THAT tap corpus da seal — batch_id + sample_ids (sap xep) + hash
    rieng cho TUNG sample (sample_id + labeled_slots + truncated) + normalization_version. 2
    corpus KHAC NHAU se cho hash KHAC NHAU du dung chung detector_version/evaluation_batch (khac
    `evaluation_hash()` cu da XOA — chi hash 3 chuoi roi, khong bind noi dung thuc te).

    `samples`: [{"sample_id":..., "labeled_slots":..., "truncated": bool}]."""
    ordered = sorted(samples, key=lambda s: str(s["sample_id"]))
    per_sample_hash = [
        hashlib.sha256(_canonical_json({
            "sample_id": str(s["sample_id"]),
            "labeled_slots": s["labeled_slots"],
            "truncated": bool(s.get("truncated", False)),
        }).encode("utf-8")).hexdigest()
        for s in ordered
    ]
    manifest = _canonical_json({
        "batch_id": str(batch_id),
        "sample_ids": [str(s["sample_id"]) for s in ordered],
        "per_sample_hash": per_sample_hash,
        "normalization_version": normalization_version,
    })
    return hashlib.sha256(("m4-stage0p-corpus-manifest-v1|" + manifest).encode("utf-8")).hexdigest()


def result_hash(*, corpus_hash: str, detector_version: str, ordered_predictions: list[dict]) -> str:
    """REV2 (T1-04): bind detector_version + corpus_hash + du doan THEO THU TU sample_id — 2 lan
    chay CUNG detector tren CUNG corpus da seal phai ra CUNG hash; doi BAT KY 1 prediction se doi
    hash. `ordered_predictions`: [{"sample_id":..., "predicted_slots":...}]."""
    canonical = _canonical_json({
        "corpus_hash": corpus_hash,
        "detector_version": detector_version,
        "predictions": [
            {"sample_id": str(p["sample_id"]), "predicted_slots": p["predicted_slots"]}
            for p in sorted(ordered_predictions, key=lambda p: str(p["sample_id"]))
        ],
    })
    return hashlib.sha256(("m4-stage0p-result-hash-v1|" + canonical).encode("utf-8")).hexdigest()


def report_hash(*, corpus_hash: str, result_hash_value: str, metrics: dict) -> str:
    """REV2 (T1-04): hash CUOI CUNG cho report — bind matching-rule/aggregation version (hang so
    module nay, Dev khong tu chon o goi ham) + corpus_hash + result_hash + metrics (canonical
    JSON tu `aggregate_micro`). Gia tri nay luu vao `m4_selection_batches.evaluation_report_hash`
    qua `complete_evaluation`."""
    canonical = _canonical_json({
        "matching_rule_version": MATCHING_RULE_VERSION,
        "aggregation_version": AGGREGATION_VERSION,
        "corpus_hash": corpus_hash,
        "result_hash": result_hash_value,
        "metrics": metrics,
    })
    return hashlib.sha256(("m4-stage0p-report-hash-v1|" + canonical).encode("utf-8")).hexdigest()


async def complete_evaluation(conn, *, batch_id: str, actor_staff_id: int,
                              report_hash_value: str) -> dict:
    """REV2 (T1-06): trang thai "eval xong" TACH BIET "prediction da ghi". `conn` phai xac thuc
    bang role `alpha3s_m4_sample_evaluator`. Goi ham SECURITY DEFINER
    `m4_stage0p_complete_evaluation` — ham DO kiem tra ATOMIC la batch da sealed VA tat ca sample
    da co `predicted_slots` truoc khi cho phep danh dau hoan tat; `purge_expired()`
    (stage0p_sampling.py) doi CHINH cot nay, khong con suy tu label_status/predicted_slots
    cap-row."""
    row = await conn.fetchrow(
        "SELECT * FROM m4_stage0p_complete_evaluation($1, $2, $3)",
        batch_id, actor_staff_id, report_hash_value,
    )
    return {"completed_at": row["completed_at"]}
