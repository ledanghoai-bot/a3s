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

from app.services.nlu.pattern_router import PatternIndex, route_pattern
from app.services.nlu.semantic_router import SemanticIndex, decide_confidence, route_semantic


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
    semantic_index: SemanticIndex,
    intent_catalog: dict,
    protected_phrases: list[dict] | None = None,
    routing_rules_config: dict | None = None,
) -> NluDecision:
    """Pipeline hoan chinh: Pattern Router truoc (uu tien, khong can model),
    Semantic Router la fallback (chi chay khi Pattern khong khop gi)."""
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

    candidates = await route_semantic(
        message, rules, semantic_index,
        protected_phrases=protected_phrases, routing_rules_config=routing_rules_config,
    )
    decision = decide_confidence(candidates, intent_catalog)
    return NluDecision(
        intent=decision.intent, confidence=decision.confidence,
        action=decision.action, matched_by="semantic", detail=None,
    )
