"""Semantic Router (Alpha3S NLU layer - Bat C).

Buoc 4 trong NLU-INTEGRATION-GUIDE.md: "Semantic Router" - CHI chay khi
Pattern Router (Bat B) khong dat threshold, search trong "Intent Index nho"
(khong phai Knowledge Index cua Knowledge Base V2).

Luu embedding TRONG BO NHO (numpy array) - KHONG qua Postgres/pgvector nhu
Knowledge Base V2 (M2), vi "Intent Index" chi co 300 utterance (rat nho so
voi Knowledge Base), giu trong RAM tinh cosine similarity qua matrix
multiplication se nhanh hon nhieu so voi round-trip DB moi lan goi - dung
tinh than "cache-warm execution" trong spec.

QUAN TRONG - gioi han da biet: da test KY logic thuat toan (argsort, dedup
theo intent, sap xep dung thu tu) qua vector gia lap trong sandbox (khong co
mang de tai model ML that trong moi truong dev cua Claude). CHUA verify duoc
do chinh xac THAT tren 60 held-out - can chay tren may that (co model that)
truoc khi ket luan Bat C dat bao nhieu % (xem ISSUES-VI.md).
"""

from dataclasses import dataclass, field

import numpy as np

from app.services.nlu.nlu_embedder import nlu_embed_async
from app.services.nlu.normalizer import normalize
from app.services.nlu.pattern_router import is_substantive, strip_greeting_prefix


@dataclass
class SemanticIndex:
    vectors: np.ndarray
    intents: list[str]
    ids: list[str]


async def build_semantic_index(utterances: list[dict]) -> SemanticIndex:
    """Tinh embedding cho toan bo utterance - goi 1 LAN luc khoi dong (KHONG
    phai moi request), tai su dung cho moi lan route_semantic() sau do."""
    vectors = []
    intents = []
    ids = []
    for u in utterances:
        text = u.get("normalized_text") or u.get("text", "")
        vec = await nlu_embed_async(text)
        vectors.append(vec)
        intents.append(u["intent"])
        ids.append(u["id"])
    return SemanticIndex(vectors=np.array(vectors), intents=intents, ids=ids)


@dataclass
class SemanticCandidate:
    intent: str
    confidence: float
    utterance_id: str


async def route_semantic(
    message: str,
    rules: list[dict],
    index: SemanticIndex,
    top_k: int = 3,
    protected_phrases: list[dict] | None = None,
    routing_rules_config: dict | None = None,
) -> list[SemanticCandidate]:
    """Tra ve toi da top_k candidate, MOI candidate 1 intent KHAC NHAU (dedup),
    sap xep giam dan theo do tuong dong cosine cua utterance khop nhat trong
    tung intent. Dung theo Buoc 4: "Tra top candidates cung confidence. Mac
    dinh giu toi da top 3 de rerank."

    QUAN TRONG: message duoc normalize() TRUOC khi embed - dung KHONG GIAN
    bieu dien voi utterance trong index (cung da embed theo normalized_text
    trong build_semantic_index()). Bug thuc te 18/7: ban dau embed message
    THO (chua normalize), lech "khong gian" so voi utterance da chuan hoa -
    gop phan khien nhieu ket qua sai/tu tin nham (vd cau hoi san pham bi
    khop nham thanh greeting voi confidence 0.84).

    v1.1: cung TACH LOI CHAO/XUNG HO O DAU CAU truoc khi embed, giong het
    pattern_router.route_pattern() - dam bao nhat quan hanh vi giua 2 tang
    (Pattern + Semantic) cho cung 1 loai cau "shop oi + noi dung". Dung
    vocative_prefixes tu routing_rules_config (routing-rules.yaml that) neu
    co, fallback ve danh sach hardcode neu khong.

    embedder.py da normalize_embeddings=True nen cosine similarity = dot
    product don gian (khong can chia norm rieng).
    """
    vocative_prefixes = routing_rules_config.get("vocative_prefixes") if routing_rules_config else None
    remainder, found_prefix = strip_greeting_prefix(message, vocative_prefixes)
    message_to_embed = remainder if (found_prefix and is_substantive(remainder)) else message
    normalized_message = normalize(message_to_embed, rules, protected_phrases)
    query_vec = np.array(await nlu_embed_async(normalized_message))
    sims = index.vectors @ query_vec
    order = np.argsort(-sims)

    best_by_intent: dict[str, SemanticCandidate] = {}
    for i in order:
        intent = index.intents[i]
        if intent not in best_by_intent:
            best_by_intent[intent] = SemanticCandidate(
                intent=intent, confidence=round(float(sims[i]), 4), utterance_id=index.ids[i]
            )
        if len(best_by_intent) >= top_k:
            break

    return list(best_by_intent.values())


@dataclass
class ConfidenceDecision:
    action: str  # "accept" | "context_check" | "clarify"
    intent: str | None
    confidence: float
    candidates: list[SemanticCandidate] = field(default_factory=list)


def decide_confidence(candidates: list[SemanticCandidate], intent_catalog: dict) -> ConfidenceDecision:
    """Ap dung Buoc 7 "Confidence Decision" trong NLU-INTEGRATION-GUIDE.md
    v1.1 (cong thuc doi so voi v1.0 - them dieu kien MARGIN):

        Top-1 >= threshold VA (Top-1 - Top-2) >= required_margin -> accept
        Top-1 >= low_confidence_threshold (nhung khong dat 1 trong 2 dieu
            kien tren)                                            -> context_check
        Top-1 < low_confidence_threshold                           -> clarify

    LY DO co margin (v1.1): tranh accept nham khi Top-1 va Top-2 qua sat
    nhau - vi du Top-1=0.90 nhung Top-2=0.87 (margin chi 0.03) nghia la
    model KHONG THUC SU chac chan giua 2 lua chon, du Top-1 rieng le co ve
    "cao". Da test logic nay bang du lieu gia lap truoc khi dua vao code
    chinh thuc (xem ISSUES-VI.md).

    Dung threshold RIENG cho tung intent (intent-catalog.yaml co the ghi de
    default 0.85) - da xac nhan du lieu that: intent rui ro cao co threshold
    CAO HON (health_question=0.95, ask_order_status=0.95, complaint=0.90),
    intent it rui ro co threshold THAP HON (greeting=0.80).
    """
    defaults = intent_catalog.get("defaults", {})
    default_threshold = defaults.get("confidence_threshold", 0.85)
    low_threshold = defaults.get("low_confidence_threshold", 0.65)
    margin_required = defaults.get("required_margin", 0.10)

    intent_thresholds = {
        it["intent"]: it.get("confidence_threshold", default_threshold)
        for it in intent_catalog.get("intents", [])
    }

    if not candidates:
        return ConfidenceDecision(action="clarify", intent=None, confidence=0.0, candidates=[])

    top = candidates[0]
    threshold = intent_thresholds.get(top.intent, default_threshold)
    margin = (top.confidence - candidates[1].confidence) if len(candidates) > 1 else top.confidence

    if top.confidence >= threshold and margin >= margin_required:
        return ConfidenceDecision(
            action="accept", intent=top.intent, confidence=top.confidence, candidates=candidates
        )
    if top.confidence >= low_threshold:
        return ConfidenceDecision(
            action="context_check", intent=top.intent, confidence=top.confidence, candidates=candidates
        )
    return ConfidenceDecision(
        action="clarify", intent=None, confidence=top.confidence, candidates=candidates
    )
