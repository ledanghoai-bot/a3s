"""I-B M4-S0 — shadow scan: chay detector SONG SONG, chi quan sat, khong doi flow.

Hop dong voi orchestrator (giong nlu_hint va reply_guard M1-shadow):
- CHI duoc goi khi settings.m4_pii_shadow bat (orchestrator kiem flag; ham nay
  kiem lai lan nua — defense in depth, config missing => OFF).
- KHONG BAO GIO raise: moi exception cua detector bi nuot tai day, chi emit mot
  dong metric loi (khong co noi dung tin nhan, khong ca str(e) vi message loi
  co the chua manh van ban khach).
- Metric emit theo mau observability.log_event: 1 dong JSON prefix [m4-shadow],
  CHI counts/enum/latency/do dai — KHONG plaintext, KHONG offset, KHONG sender_id.
"""

import json
import time

from app.config import settings
from app.services.pii.detector import DetectionResult, detect
from app.services.pii.taxonomy import DETECTOR_VERSION, FailureCode, SlotType


def build_shadow_metrics(result: DetectionResult, latency_ms: float, text_len: int) -> dict:
    """Bien DetectionResult thanh payload metric an toan PII (chi so dem/enum)."""
    slots: dict[str, dict] = {}
    for span in result.spans:
        entry = slots.setdefault(
            span.slot_type.value, {"count": 0, "max_confidence": span.confidence.value}
        )
        entry["count"] += 1
        # giu confidence cao nhat cho tung slot type (high > medium > low)
        order = {"high": 2, "medium": 1, "low": 0}
        if order[span.confidence.value] > order[entry["max_confidence"]]:
            entry["max_confidence"] = span.confidence.value
    return {
        "event": "m4_shadow_scan",
        "detector_version": DETECTOR_VERSION,
        "risk_class": result.risk_class.value,
        "slots": slots,
        "sensitive_categories": sorted(c.value for c in result.sensitive_categories),
        "vendor_would_block": result.risk_class.value == "D2"
        or any(s.slot_type in (SlotType.NATIONAL_ID, SlotType.BANK_ACCOUNT)
               for s in result.spans),
        "latency_ms": round(latency_ms, 2),
        "text_len": text_len,
    }


def shadow_scan(text: str) -> dict | None:
    """Quet 1 tin nhan o che do shadow. Tra payload metric (de test) hoac None.

    Thuan CPU (regex, khong I/O) nen goi dong bo tu orchestrator la du re;
    latency thuc te do o evidence script (p95 << 5ms).
    """
    if not settings.m4_pii_shadow:
        return None
    try:
        t0 = time.perf_counter()
        result = detect(text)
        latency_ms = (time.perf_counter() - t0) * 1000
        payload = build_shadow_metrics(result, latency_ms, len(text or ""))
        print("[m4-shadow] " + json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return payload
    except Exception as e:  # noqa: BLE001 — containment la hop dong cua shadow
        try:
            print("[m4-shadow] " + json.dumps({
                "event": "m4_shadow_error",
                "detector_version": DETECTOR_VERSION,
                "failure": FailureCode.DETECTOR_EXCEPTION.value,
                # CHI ten class exception — KHONG str(e) (co the chua van ban khach)
                "error_type": type(e).__name__,
            }))
        except Exception:  # noqa: BLE001
            pass
        return None
