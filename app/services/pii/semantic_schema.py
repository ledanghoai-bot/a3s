"""I-B M4-S2 — schema-bounded external model output (spec §9).

Model (mock/local trong development — KHONG vendor call) chi duoc tra ve dung 4
truong allowlist; moi thu khac la violation -> fail closed:

    {
      "intent": <ALLOWED_INTENTS>,
      "missing_slot_types": [<phone|name|address>],
      "response_candidate": <str, co the chua placeholder [PII_*]>,
      "context": {"items": [{"sku": str, "qty": int>0}, ...]}   # non-PII allowlist
    }

Bat bien enforce tai day (spec §5):
- #2 model KHONG chon customer_ref/conversation_ref: moi key dinh danh xuat hien
  BAT KY dau trong output -> violation.
- #3 model KHONG dieu khien rehydration thanh tool argument: schema KHONG co
  truong tool/argument nao; placeholder trong response_candidate chi duoc echo.
- Response candidate KHONG duoc chua PII tho (detector quet) — chi placeholder.
"""

from dataclasses import dataclass, field

from app.services.pii.detector import detect
from app.services.pii.masking import find_placeholders

ALLOWED_INTENTS = {"order.create", "order.status", "product.question", "smalltalk", "other"}
# Slot ma model duoc phep BAO THIEU (allowlist §9 "missing slot types"):
ASKABLE_SLOTS = {"phone", "name", "address"}
_ALLOWED_TOP_KEYS = {"intent", "missing_slot_types", "response_candidate", "context"}
_ALLOWED_CONTEXT_KEYS = {"items"}
_ALLOWED_ITEM_KEYS = {"sku", "qty"}
# Key dinh danh/nguy hiem — xuat hien o BAT KY tang nao cua output la violation
_FORBIDDEN_KEYS = {
    "customer_ref", "conversation_ref", "customer_id", "conversation_id", "psid",
    "sender_id", "slot_id", "phone", "address", "name", "tool", "tool_calls",
    "tool_args", "arguments", "sql", "query",
}
_MAX_ITEMS = 20
_MAX_CANDIDATE_LEN = 2000
_MAX_SKU_LEN = 40


class SchemaViolation(Exception):
    """Output model ngoai schema — message CHI chua reason code, khong echo payload."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__(",".join(reasons))


@dataclass
class SemanticResult:
    intent: str
    missing_slot_types: list[str] = field(default_factory=list)
    response_candidate: str = ""
    items: list[dict] = field(default_factory=list)


def _scan_forbidden_keys(obj, reasons: list[str], path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in _FORBIDDEN_KEYS:
                reasons.append(f"forbidden_key:{k.lower()}")
            _scan_forbidden_keys(v, reasons, path + "/" + str(k))
    elif isinstance(obj, list):
        for v in obj:
            _scan_forbidden_keys(v, reasons, path + "[]")


def validate_semantic_output(raw) -> SemanticResult:
    """Fail-closed validation. Raise SchemaViolation (chi reason codes)."""
    reasons: list[str] = []
    if not isinstance(raw, dict):
        raise SchemaViolation(["not_a_dict"])

    unknown = set(raw) - _ALLOWED_TOP_KEYS
    if unknown:
        reasons.append("unknown_top_keys")
    _scan_forbidden_keys(raw, reasons)

    intent = raw.get("intent")
    if not isinstance(intent, str) or intent not in ALLOWED_INTENTS:
        reasons.append("intent_invalid")

    missing = raw.get("missing_slot_types", [])
    if not isinstance(missing, list) or any(
        not isinstance(s, str) or s not in ASKABLE_SLOTS for s in missing
    ):
        reasons.append("missing_slots_invalid")

    candidate = raw.get("response_candidate", "")
    if not isinstance(candidate, str) or len(candidate) > _MAX_CANDIDATE_LEN:
        reasons.append("candidate_invalid")
        candidate = ""
    else:
        # Model KHONG duoc tu sinh PII tho trong response — chi placeholder.
        cand_scan = detect(candidate)
        real_spans = []
        if cand_scan.spans:
            # loai span trung voi placeholder (vd [PII_PHONE_1] khong phai PII)
            ph_ranges = []
            pos = 0
            for ph in find_placeholders(candidate):
                i = candidate.find(ph, pos)
                ph_ranges.append((i, i + len(ph)))
                pos = i + len(ph)
            real_spans = [s for s in cand_scan.spans
                          if not any(a <= s.start and s.end <= b for a, b in ph_ranges)]
        if real_spans:
            reasons.append("pii_in_candidate")

    context = raw.get("context", {})
    items: list[dict] = []
    if context is None:
        context = {}
    if not isinstance(context, dict) or set(context) - _ALLOWED_CONTEXT_KEYS:
        reasons.append("context_invalid")
    else:
        raw_items = context.get("items", [])
        if not isinstance(raw_items, list) or len(raw_items) > _MAX_ITEMS:
            reasons.append("items_invalid")
        else:
            for it in raw_items:
                if (not isinstance(it, dict) or set(it) != _ALLOWED_ITEM_KEYS
                        or not isinstance(it.get("sku"), str)
                        or not (0 < len(it["sku"]) <= _MAX_SKU_LEN)
                        or not isinstance(it.get("qty"), int)
                        or isinstance(it.get("qty"), bool)
                        or not (0 < it["qty"] <= 1000)):
                    reasons.append("items_invalid")
                    break
                items.append({"sku": it["sku"], "qty": it["qty"]})

    if reasons:
        raise SchemaViolation(sorted(set(reasons)))
    return SemanticResult(intent=intent, missing_slot_types=list(missing),
                          response_candidate=candidate, items=items)
