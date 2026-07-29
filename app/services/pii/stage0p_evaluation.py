"""I-B M4 Stage 0P — evaluation methodology (F-M4-0P-05A, CLOSED AT DESIGN LEVEL).

Rut lai instance-count-only (S0): count theo (message, slot_type) co the bao TP khi detector
khoanh SAI vi tri/thuc the mien so luong/loai khop (vd 2 so dien thoai, detector bat trung so
#1 hai lan, bo sot so #2 — count-only van bao "2 khop 2"). **Exact-span la gate chinh**;
overlap/IoU la metric PHU (nguong can PO/CA duyet, Dev khong tu chon); count-only ha xuong tham
khao. Khong dung `PIISpan.as_safe_dict()` (S0) — do la cho log live-traffic (boi canh rui ro
khac han), offset KHONG phai plaintext PII nen an toan luu trong jsonb restricted-access nay.
"""

import hashlib
from collections import defaultdict


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


def evaluation_hash(*, detector_version: str, normalization_version: str,
                    evaluation_batch: str) -> str:
    """Dinh danh DUY NHAT 1 lan cham diem — tai lap/audit lai duoc (F-M4-0P-05A)."""
    raw = f"{detector_version}|{normalization_version}|{evaluation_batch}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
