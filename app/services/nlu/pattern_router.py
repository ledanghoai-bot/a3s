"""Pattern/Exact Router (Alpha3S NLU layer - Bat B, nang cap 18/7 voi
routing-rules.yaml chinh thuc tu team Knowledge).

Buoc 3 trong NLU-INTEGRATION-GUIDE.md: "Exact and Pattern Router" - thu Exact
phrase truoc, roi High-Precision Rules (RTE-*, xem high_precision_rules.py),
roi Token/phrase combination, tra ve NGAY neu dat threshold cao, BO QUA
Semantic Router de tiet kiem thoi gian.

MVP Bat B goc: dung CHINH 300+ utterance lam nguon pattern (data-driven),
khong hardcode regex tay nhu kb_router.py (M3 cua Knowledge Base V2).

KET QUA TEST THAT (18/7) - quan trong de hieu dung pham vi Bat B:
- Tren 60 test held-out (co chu dich dung tu vung KHAC han utterance train):
  chi 2/60 match duoc (ca 2 DUNG, 0 SAI) o nguong overlap=0.6 - phan lon can
  Semantic Router hoac High-Precision Rules moi (RTE-*) xu ly.
- Nguong 0.6 dam bao 0 SAI tren tap held-out (khong doan bua khi khong chac
  chan) - dung tinh than "Confidence thap phai clarify hoac fallback; khong
  ep route" trong ADR-NLU-001.

v1.1 (routing-rules.yaml): `vocative_prefixes` gio uu tien dung DANH SACH
THAT tu file (day du hon: co ca "admin oi", "ad oi", "ben minh oi" ma danh
sach hardcode cu khong co) - fallback ve danh sach hardcode neu khong co
config.
"""

from dataclasses import dataclass, field

from app.services.nlu.high_precision_rules import match_high_precision_rules
from app.services.nlu.normalizer import normalize, strip_diacritics

DEFAULT_MIN_OVERLAP = 0.6

# Danh sach DU PHONG - dung khi khong co routing_rules_config (vd script cu
# chua cap nhat). Uu tien dung get_vocative_prefixes() tu routing-rules.yaml
# that (day du hon: co "admin oi", "ad oi", "ben minh oi").
_FALLBACK_GREETING_PREFIX_PHRASES = [
    "shop oi", "chao shop", "chao ban", "xin chao", "alo", "chao", "hi", "hello",
]
# Tu xung ho/hat nhan don le - neu phan con lai SAU KHI bo prefix chi gom
# cac tu nay thi KHONG tinh la "co noi dung thuc chat" (vd "xin chao a" ->
# con lai chi "a", van la thuan chao hoi).
_TRIVIAL_REMAINDER_TOKENS = {"a", "oi", "e", "em", "anh", "chi", "shop", "ban"}


def strip_greeting_prefix(
    message: str, vocative_prefixes: list[str] | None = None
) -> tuple[str, bool]:
    """Tra ve (phan_con_lai, co_tim_thay_prefix_chao). Neu KHONG tim thay
    prefix chao nao o DAU cau, tra ve (message.strip(), False).

    vocative_prefixes: danh sach tuy chinh (uu tien tu routing-rules.yaml
    that qua high_precision_rules.get_vocative_prefixes()) - neu khong
    truyen, dung _FALLBACK_GREETING_PREFIX_PHRASES.
    """
    prefixes = vocative_prefixes if vocative_prefixes else _FALLBACK_GREETING_PREFIX_PHRASES
    stripped_diac = strip_diacritics(message.strip())
    for phrase in sorted(prefixes, key=len, reverse=True):
        phrase_diac = strip_diacritics(phrase)
        if stripped_diac.startswith(phrase_diac):
            remainder = message.strip()[len(phrase_diac):]
            remainder = remainder.lstrip(" ,.!?-").strip()
            return remainder, True
    return message.strip(), False


def is_substantive(text: str) -> bool:
    """True neu phan con lai co NOI DUNG thuc chat (khong chi la tu
    dem/xung ho ngan nhu "a", "oi"). Public vi duoc dung lai o
    semantic_router.py (nhat quan hanh vi tach greeting prefix giua Pattern
    va Semantic Router)."""
    words = strip_diacritics(text).split()
    meaningful = [w for w in words if w not in _TRIVIAL_REMAINDER_TOKENS]
    return len(meaningful) >= 1


@dataclass
class PatternMatch:
    intent: str
    confidence: float
    matched_by: str  # "exact_phrase" | "high_precision_rule" | "token_overlap"
    matched_utterance_id: str | None = None
    matched_rule_id: str | None = None


@dataclass
class PatternIndex:
    exact: dict[str, dict] = field(default_factory=dict)
    token: list[tuple[frozenset, str, str]] = field(default_factory=list)


def build_pattern_index(
    utterances: list[dict], rules: list[dict], protected_phrases: list[dict] | None = None
) -> PatternIndex:
    """Xay index tu utterance library - goi 1 LAN luc khoi dong (khong phai
    moi request), tai su dung cho moi lan route_pattern().

    Danh index theo CA `text` goc LAN `normalized_text` (neu co ca 2, khac
    nhau) - tang kha nang khop chinh xac, vi khach co the go dung y het
    `text` (thuong dang thong tuc trong utterance) ma khong can normalize()
    tai tao lai dung `normalized_text` (dang chuan).
    """
    exact: dict[str, dict] = {}
    token: list[tuple[frozenset, str, str]] = []

    for u in utterances:
        candidates = set()
        if u.get("text"):
            candidates.add(u["text"])
        if u.get("normalized_text"):
            candidates.add(u["normalized_text"])
        for raw in candidates:
            norm = normalize(raw, rules, protected_phrases).strip().lower()
            if norm and norm not in exact:
                exact[norm] = {"intent": u["intent"], "id": u["id"]}

        # token index dung 1 ban dai dien (uu tien normalized_text) de tranh
        # dem trung 2 lan cho cung 1 utterance khi tinh overlap.
        rep = u.get("normalized_text") or u.get("text", "")
        norm_rep = normalize(rep, rules, protected_phrases).strip().lower()
        tokens = frozenset(norm_rep.split())
        if tokens:
            token.append((tokens, u["intent"], u["id"]))

    return PatternIndex(exact=exact, token=token)


def match_exact(
    message: str, rules: list[dict], index: PatternIndex, protected_phrases: list[dict] | None = None
) -> PatternMatch | None:
    norm = normalize(message, rules, protected_phrases).strip().lower()
    hit = index.exact.get(norm)
    if hit:
        return PatternMatch(
            intent=hit["intent"], confidence=1.0, matched_by="exact_phrase",
            matched_utterance_id=hit["id"],
        )
    return None


def match_token_overlap(
    message: str,
    rules: list[dict],
    index: PatternIndex,
    min_overlap: float = DEFAULT_MIN_OVERLAP,
    protected_phrases: list[dict] | None = None,
) -> PatternMatch | None:
    """So sanh tap tu (Jaccard) cua message voi tung utterance da index -
    tra ve intent cua utterance overlap CAO NHAT neu >= min_overlap.

    min_overlap=0.6 la nguong da TEST THAT tren 60 held-out case: dam bao
    0 SAI (co the giam so luong match duoc, nhung KHONG doan sai) - uu tien
    an toan hon do phu, dung tinh than ADR-NLU-001.
    """
    norm = normalize(message, rules, protected_phrases).strip().lower()
    msg_tokens = set(norm.split())
    if not msg_tokens:
        return None

    best: tuple[str, str] | None = None
    best_score = 0.0
    for tokens, intent, uid in index.token:
        if not tokens:
            continue
        overlap = len(msg_tokens & tokens) / len(msg_tokens | tokens)
        if overlap > best_score:
            best_score = overlap
            best = (intent, uid)

    if best and best_score >= min_overlap:
        return PatternMatch(
            intent=best[0], confidence=round(0.65 + best_score * 0.25, 3),
            matched_by="token_overlap", matched_utterance_id=best[1],
        )
    return None


def route_pattern(
    message: str,
    rules: list[dict],
    index: PatternIndex,
    min_overlap: float = DEFAULT_MIN_OVERLAP,
    protected_phrases: list[dict] | None = None,
    routing_rules_config: dict | None = None,
) -> PatternMatch | None:
    """Thu Exact -> High-Precision Rules (RTE-*, neu co routing_rules_config)
    -> Token overlap, dung thu tu Buoc 3 trong NLU-INTEGRATION-GUIDE.md.
    Tra ve None neu khong dat nguong nao - caller se chuyen sang Semantic
    Router.

    v1.1: TACH LOI CHAO/XUNG HO O DAU CAU truoc khi match (dung
    vocative_prefixes tu routing_rules_config neu co) - neu phan con lai co
    noi dung thuc chat, uu tien route theo phan con lai (thay vi ca cau) de
    tranh nham thanh 'greeting' (bug thuc te 18/7: "shop oi don cua minh da
    gui chua" tung bi nham thanh greeting khi chua co buoc nay).
    """
    vocative_prefixes = None
    if routing_rules_config:
        vocative_prefixes = routing_rules_config.get("vocative_prefixes")

    remainder, found_prefix = strip_greeting_prefix(message, vocative_prefixes)
    target_message = remainder if (found_prefix and is_substantive(remainder)) else message

    # 1. Exact phrase (utterance library) - tren PHAN DA XU LY (bo prefix
    # neu co noi dung thuc chat).
    result = match_exact(target_message, rules, index, protected_phrases)
    if result:
        return result

    # 2. High-Precision Rules (RTE-*, routing-rules.yaml) - CHI chay tren
    # ca cau GOC (khong phai target_message da bo prefix) vi cac rule nay
    # tu than da xu ly duoc ca vocative prefix roi (vd RTE-018 greeting tu
    # co "shop oi" trong message_is_only_any). Message duoc normalize()
    # TRUOC (khoi phuc dau/viet tat) nhung KHONG bo dau khi so khop - xem
    # canh bao bug "chưa"/"chua" dong am trong docstring high_precision_rules.py.
    if routing_rules_config:
        from app.services.nlu.entity_extraction import extract_entities
        normalized_for_hp = normalize(message, rules, protected_phrases)
        entities = extract_entities(normalized_for_hp)
        hp_match = match_high_precision_rules(normalized_for_hp, routing_rules_config, entities)
        if hp_match:
            return PatternMatch(
                intent=hp_match.intent, confidence=0.95, matched_by="high_precision_rule",
                matched_rule_id=hp_match.rule_id,
            )

    # 3. Token overlap (utterance library) - tren PHAN DA XU LY, giong buoc 1.
    return match_token_overlap(target_message, rules, index, min_overlap, protected_phrases)
