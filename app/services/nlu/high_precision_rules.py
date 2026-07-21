"""High-Precision Rules (Alpha3S NLU layer - nang cap 18/7 tu
routing-rules.yaml chinh thuc team Knowledge gui).

Trien khai Buoc 3.3 ("Regex da review") + Buoc 3.4 ("Entity-aware rule")
trong NLU-INTEGRATION-GUIDE.md - 25 rule (RTE-001..025) uu tien theo
`priority`, cao hon Pattern Router (exact/token-overlap) cu.

v1.2 (18/7): TICH HOP Entity Extraction (Buoc 6, entity_extraction.py) -
MO KHOA 2/3 rule truoc do bi bo qua hoan toan (RTE-008, RTE-009 - dieu
kien order_id, gio da co the trich xuat that). RTE-006 (dieu kien location)
VAN CHUA mo khoa duoc vi entity nay chua co gazetteer dia danh - tiep tuc
bi bo qua RO RANG (khong doan bua), xem entity_extraction.py.

BUG DONG AM da fix truoc do (18/7): "chua"(RTE-012, vi chua) va "chưa"(rat
pho bien, "not yet") deu thanh "chua" sau khi bo dau, gay khop nham hang
loat - fix: so khop `any_phrases`/`message_is_only_any` GIU NGUYEN DAU
tieng Viet, chi so sanh khong phan biet hoa/thuong + ranh gioi tu.

Co che chon-theo-priority-cao-nhat TU DONG thoa man ca 2 policy trong
routing-rules.yaml ma khong can code rieng:
- RTE-POL-002 (explicit_action_overrides_general_complaint): request_refund
  (98) va request_return (97) da duoc gan priority CAO HON complaint (85).
- Cac intent rui ro cao (health_question=99) da duoc gan priority CAO NHAT.
"""

import re
from dataclasses import dataclass

# Entity type CHUA ho tro trich xuat (thieu gazetteer/du lieu) - rule co
# dieu kien entity thuoc nhom nay se TIEP TUC bi bo qua ro rang, khong
# doan bua entity co mat hay khong. Xem entity_extraction.py.
_ENTITY_UNSUPPORTED = {"location", "product", "taste_preference", "brewing_method"}


@dataclass
class HighPrecisionMatch:
    intent: str
    rule_id: str
    priority: int


def _phrase_matches(phrase: str, message_lower: str) -> bool:
    """Khop CA CUM (co the nhieu tu) voi RANH GIOI TU o 2 dau, GIU NGUYEN
    DAU tieng Viet (khong bo dau) - tranh dong am sau khi bo dau (vd "chưa"
    va "chua" deu thanh "chua"). Chi so sanh khong phan biet hoa/thuong."""
    pattern = re.compile(r"\b" + re.escape(phrase.lower()) + r"\b", re.UNICODE)
    return bool(pattern.search(message_lower))


def _entity_condition_met(rule: dict, entities: dict) -> bool:
    """Tra ve True neu dieu kien entity cua rule (neu co) duoc thoa man boi
    entities da trich xuat (tu entity_extraction.py). Rule KHONG co dieu
    kien entity -> True (khong bi anh huong). Neu dieu kien entity DUNG
    NHUNG entity type do CHUA duoc ho tro trich xuat (vd location) -> False
    (an toan, khong doan bua thay vi gia dinh co/khong)."""
    entity_any = rule.get("entity_any") or rule.get("required_entity_any")
    if not entity_any:
        return True
    for etype in entity_any:
        if etype in _ENTITY_UNSUPPORTED:
            continue  # chua ho tro trich xuat entity nay - khong the xac nhan
        if etype in entities:
            return True
    return False


def match_high_precision_rules(
    message: str, routing_rules_config: dict, entities: dict | None = None
) -> HighPrecisionMatch | None:
    """Tra ve rule khop co priority CAO NHAT, hoac None neu khong rule nao khop.

    entities: dict tra ve tu entity_extraction.extract_entities(message) -
    truyen None neu chua co (rule co dieu kien entity se tu dong bi bo qua,
    giong hanh vi cu truoc khi co Entity Extraction).

    LUU Y: `message` NEN da qua normalize() (khoi phuc dau/viet tat) truoc
    khi goi ham nay - xem pattern_router.route_pattern() cho cach goi dung.
    """
    entities = entities if entities is not None else {}
    msg_lower = message.strip().lower()
    best: HighPrecisionMatch | None = None

    for rule in routing_rules_config.get("rules", []):
        if not _entity_condition_met(rule, entities):
            continue

        matched = False
        if "message_is_only_any" in rule:
            for phrase in rule["message_is_only_any"]:
                if msg_lower == phrase.strip().lower():
                    matched = True
                    break
        elif "any_phrases" in rule:
            for phrase in rule["any_phrases"]:
                if _phrase_matches(phrase, msg_lower):
                    matched = True
                    break

        if matched and (best is None or rule["priority"] > best.priority):
            best = HighPrecisionMatch(intent=rule["intent"], rule_id=rule["id"], priority=rule["priority"])

    return best


def get_vocative_prefixes(routing_rules_config: dict | None) -> list[str]:
    """Tra ve danh sach vocative_prefixes tu routing-rules.yaml (day du hon
    danh sach hardcode cu trong pattern_router.py) - fallback ve danh sach
    rong neu khong co config (caller tu quyet dinh dung danh sach du phong nao)."""
    if not routing_rules_config:
        return []
    return routing_rules_config.get("vocative_prefixes", [])