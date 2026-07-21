"""High-Precision Rules (Alpha3S NLU layer - nang cap 18/7 tu
routing-rules.yaml chinh thuc team Knowledge gui).

Trien khai Buoc 3.3 ("Regex da review") + mot phan 3.4 ("Entity-aware rule")
trong NLU-INTEGRATION-GUIDE.md - 25 rule (RTE-001..025) uu tien theo
`priority`, cao hon Pattern Router (exact/token-overlap) cu.

BUG THUC TE NGHIEM TRONG PHAT HIEN KHI TEST (18/7): ban dau dung
strip_diacritics() (bo dau) de so khop `any_phrases`, GIONG HET cach lam o
kb_router.py/normalizer.py - nhung lan nay gay HAU QUA NANG hon nhieu: "chua"
(tu RTE-012, nghia "vi chua") va "chưa" (tu rat thong dung, nghia "not yet")
DEU tro thanh "chua" sau khi bo dau - va vi CA HAI deu la 1 TU HOAN CHINH
(khong phai substring nam trong tu khac), them `\\b` ranh gioi tu KHONG GIAI
QUYET duoc (khac han bug "hong" trong "khong" o kb_router.py - do la
substring-trong-tu, con day la DONG AM sau khi bo dau o cap do CA TU). Ket
qua: gan NHU MOI cau chua "chưa" (cuc ky pho bien) deu bi khop nham thanh
ask_taste qua RTE-012 - 16/25 case that (`nlu_pattern_test.py --eval`) bi
sai vi dung 1 nguyen nhan nay.

FIX: KHONG bo dau khi so khop `any_phrases`/`message_is_only_any` - GIU
NGUYEN dau tieng Viet, chi so sanh khong phan biet hoa/thuong + ranh gioi tu
(\\b). Hop ly vi routing-rules.yaml da viet dung chinh ta co dau, va message
NEN duoc normalize() truoc (khoi phuc dau tu viet tat) truoc khi vao ham
nay - xem cach goi trong pattern_router.route_pattern().

Da verify: tu 16/25 CHECK (voi ban co bo dau) giam con 2/25 CHECK (voi ban
giu dau) - 2 case con lai la MO HO NGU NGHIA THAT cua chinh rule (vd "giống"
vua co nghia "tuong tu" (RTE-013 compare_coffee) vua co nghia "chung loai"
(can rule rieng cho ask_ingredients) - can bao lai team Knowledge, khong tu
doan sua rule thay ho.

QUAN TRONG - CHUA ho tro entity-gated rules: 3 rule (RTE-006, RTE-008,
RTE-009) co dieu kien `entity_any`/`required_entity_any` - CAN Entity
Extraction (Buoc 6 NLU-INTEGRATION-GUIDE.md), chua duoc trien khai trong
pham vi hien tai. Cac rule nay BI BO QUA RO RANG (khong doan bua entity co
mat hay khong) - xem ISSUES-VI.md.

Co che chon-theo-priority-cao-nhat TU DONG thoa man ca 2 policy trong
routing-rules.yaml ma khong can code rieng:
- RTE-POL-002 (explicit_action_overrides_general_complaint): request_refund
  (98) va request_return (97) da duoc gan priority CAO HON complaint (85).
- Cac intent rui ro cao (health_question=99) da duoc gan priority CAO NHAT.
"""

import re
from dataclasses import dataclass

_ENTITY_GATED_FIELDS = ("entity_any", "required_entity_any")


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


def match_high_precision_rules(
    message: str, routing_rules_config: dict
) -> HighPrecisionMatch | None:
    """Tra ve rule khop co priority CAO NHAT, hoac None neu khong rule nao khop.

    LUU Y: `message` NEN da qua normalize() (khoi phuc dau/viet tat) truoc
    khi goi ham nay - xem pattern_router.route_pattern() cho cach goi dung.
    """
    msg_lower = message.strip().lower()
    best: HighPrecisionMatch | None = None

    for rule in routing_rules_config.get("rules", []):
        if any(f in rule for f in _ENTITY_GATED_FIELDS):
            continue  # chua ho tro entity extraction - bo qua ro rang, khong doan

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
