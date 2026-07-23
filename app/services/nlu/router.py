"""Combined NLU Router (Alpha3S NLU layer - Bat D) - ghep Pattern Router
(Bat B) + Semantic Router (Bat C) thanh 1 pipeline hoan chinh, dung theo
dung thu tu Buoc 3->4 trong NLU-INTEGRATION-GUIDE.md: "Neu dat threshold
cao, tra route ngay va BO QUA semantic classifier".

Pattern Router chay TRUOC (nhanh, khong can model ML) - neu khop (exact/
high_precision_rule/token_overlap), CHAP NHAN NGAY khong can qua Semantic
Router. Chi khi Pattern Router tra ve None (khong khop gi) moi roi xuong
Semantic Router (can model, cham hon).

Day la lan DAU TIEN do duoc accuracy THAT cua toan bo NLU layer (Bat A->D)
tren 150 test held-out - cac lan truoc chi do TUNG TANG rieng le.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.nlu.pattern_router import PatternIndex, route_pattern

if TYPE_CHECKING:  # chi cho type hint - KHONG import that luc runtime
    from app.services.nlu.semantic_router import SemanticIndex

# LUU Y RAM: KHONG import semantic_router o cap module - import do keo theo
# sentence_transformers/torch (~300MB RSS) vao MOI process import router.py,
# ke ca khi ENABLE_SEMANTIC_ROUTER=false. Import that duoc di chuyen vao
# nhanh semantic trong route() ben duoi (chi chay khi semantic_index != None).


@dataclass
class NluDecision:
    intent: str | None
    confidence: float
    action: str  # "accept" | "context_check" | "clarify"
    matched_by: str  # "exact_phrase" | "high_precision_rule" | "token_overlap" | "semantic"
    detail: str | None = None  # utterance_id hoac rule_id, dung de truy vet


async def route(
    message: str,
    rules: list[dict],
    pattern_index: PatternIndex,
    semantic_index: "SemanticIndex | None",
    intent_catalog: dict,
    protected_phrases: list[dict] | None = None,
    routing_rules_config: dict | None = None,
) -> NluDecision:
    """Pipeline hoan chinh: Pattern Router truoc (uu tien, khong can model),
    Semantic Router la fallback (chi chay khi Pattern khong khop gi).

    semantic_index=None (quyet dinh PO 23/7, ENABLE_SEMANTIC_ROUTER=false):
    tang Semantic bi TAT hoan toan - cau Pattern khong khop se tra ve
    action="clarify" (khong du tin cay, khong co hint) thay vi doan bang
    model. Xem docs/KB_NLU_RESOURCE_ASSESSMENT-VI.md PA2-5a."""
    pattern_match = route_pattern(
        message, rules, pattern_index,
        protected_phrases=protected_phrases, routing_rules_config=routing_rules_config,
    )
    if pattern_match:
        # Pattern Router da chung minh chinh xac cao (2% sai tren 150 test
        # held-out, xem ISSUES-VI.md) - CHAP NHAN NGAY, khong can Semantic
        # Router (dung tinh than "Neu dat threshold cao, bo qua semantic
        # classifier" trong NLU-INTEGRATION-GUIDE.md).
        return NluDecision(
            intent=pattern_match.intent, confidence=pattern_match.confidence,
            action="accept", matched_by=pattern_match.matched_by,
            detail=pattern_match.matched_utterance_id or pattern_match.matched_rule_id,
        )

    if semantic_index is None:
        # Semantic Router tat - khong doan, tra ve "khong du tin cay" ro rang
        # (nlu_hint se khong bom hint intent; van con nhanh Context-aware
        # Resolution phia sau neu la cau noi tiep).
        return NluDecision(
            intent=None, confidence=0.0, action="clarify", matched_by="none",
        )

    from app.services.nlu.semantic_router import decide_confidence, route_semantic

    candidates = await route_semantic(
        message, rules, semantic_index,
        protected_phrases=protected_phrases, routing_rules_config=routing_rules_config,
    )
    decision = decide_confidence(candidates, intent_catalog)
    return NluDecision(
        intent=decision.intent, confidence=decision.confidence,
        action=decision.action, matched_by="semantic", detail=None,
    )
