"""Runtime Contract + Guardrails/Fallbacks (Knowledge Base V2 - M5, Bat 5).

Doc dung RT-001 (Runtime Input/Output Contract) + RT-002 (Runtime Guardrails
and Fallbacks) truoc khi code (khong bia).

QUAN TRONG - CHUA co LLM that trong pipeline nay (M1-M4 moi dung toi Prompt
Assembly, chua goi model sinh cau tra loi that). Vi vay Bat 5 chia lam 2 phan
RO RANG khac nhau ve muc do "that":

1. PRE-GENERATION GUARDRAILS: hoan toan lam duoc va TEST DUOC THAT vi chi
   dua tren du lieu da co san (route/knowledge_units/tool_results tu M2-M4),
   khong can LLM sinh cau tra loi.

2. POST-GENERATION VALIDATION: chi lam duoc o muc RULE-BASED/HEURISTIC (quet
   tu khoa/pattern trong candidate response) - KHONG THE danh gia chinh xac
   "cau tra loi co dung fact trong provenance khong" bang rule thuan, can
   LLM-as-judge hoac NLP phuc tap hon (ngoai pham vi Bat 5, ghi nhan gioi
   han ro trong tung ham). Test bang response MAU (ca dung lan sai) de xac
   nhan validator bat dung loai loi RO RANG, khong hua bat het moi loi.

CHUA tich hop vao orchestrator.py/bot production - module doc lap, test qua
scripts/kb_runtime_test.py.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.kb_router import Route

_PRODUCTION_OK_STATUSES = ("approved", "locked")

# --- Nhan risk theo dung "Pre-Generation Guardrails" cua RT-002 ---
_RISK_INTENTS = {"health_safety", "complaint"}


@dataclass
class GuardrailEvent:
    """Dung dung schema 'guardrail_event' trong RT-002 muc Observability."""
    stage: str  # pre_generation | post_generation
    rule_id: str
    severity: str  # info | warning | block
    action: str  # allow | regenerate | fallback | handoff
    source_ids: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class ValidationResult:
    passed: bool
    flags: list[str] = field(default_factory=list)
    events: list[GuardrailEvent] = field(default_factory=list)


def pre_generation_guardrails(route: Route, knowledge_units: list[dict]) -> list[GuardrailEvent]:
    """Kiem tra TRUOC khi (se) goi LLM - hoan toan dua tren du lieu da co
    (khong can LLM), dung theo dung "Pre-Generation Guardrails" trong RT-002:
    - Chan draft/superseded Knowledge Units.
    - Xac dinh Tool bat buoc truoc retrieval tinh (route=tool khong duoc lan
      Knowledge tinh - da thuc thi trong kb_prompt_assembly.py, o day kiem
      tra LAI o tang guardrail rieng, phong khi ham goi assemble_prompt sai).
    - Danh dau risk: suc khoe, khieu nai (health_safety, complaint).
    - Tat sales recommendation khi complaint/safety (kiem tra route.route).
    """
    events: list[GuardrailEvent] = []

    for u in knowledge_units:
        if u.get("status") not in _PRODUCTION_OK_STATUSES:
            events.append(GuardrailEvent(
                stage="pre_generation", rule_id="block_non_approved_ku",
                severity="block", action="fallback",
                source_ids=[u.get("ku_id", "?")],
                detail=f"KU {u.get('ku_id')} co status={u.get('status')!r}, khong duoc "
                "dua vao production context (RT-002: chan draft/superseded).",
            ))

    if route.route == "tool" and knowledge_units:
        events.append(GuardrailEvent(
            stage="pre_generation", rule_id="tool_required_no_static_retrieval",
            severity="block", action="fallback",
            detail="Route yeu cau Tool nhung van co Knowledge Units tinh duoc truyen "
            "vao - vi pham 'khong duoc retrieve static price/stock/promotion content'.",
        ))

    if route.intent in _RISK_INTENTS:
        events.append(GuardrailEvent(
            stage="pre_generation", rule_id="risk_flag_detected",
            severity="warning", action="allow",
            detail=f"Intent '{route.intent}' duoc danh dau risk - tat sales "
            "recommendation blocks (dung RT-002: 'Tat sales recommendation khi "
            "complaint/safety flow hoat dong').",
        ))

    return events


# --- Post-Generation Validation (heuristic, xem gioi han o docstring module) ---

_PRICE_PATTERN_RE = re.compile(
    r"\d[\d.,]*\s*(vnd|đ\b|d\b|nghìn|ngàn|k\b|triệu)", re.IGNORECASE
)
_ABSOLUTE_MEDICAL_CLAIM_RE = re.compile(
    r"chữa (khỏi|bệnh)|trị bệnh|đảm bảo an toàn tuyệt đối|thay thế thuốc|"
    r"chắc chắn không (có )?tác dụng phụ",
    re.IGNORECASE,
)
_INTERNAL_LEAK_RE = re.compile(
    r"knowledge unit|prompt|source_id|ku-[a-z]+-\d+|tool_result|"
    r"confidence score|system prompt",
    re.IGNORECASE,
)


def validate_response(
    candidate_response: str,
    route: Route,
    tool_results: dict | None = None,
) -> ValidationResult:
    """Kiem tra SAU khi (se) co candidate response tu LLM - MVP heuristic,
    dua theo 1 phan "Post-Generation Validation" cua RT-002 CO THE kiem tra
    bang rule/regex don gian (khong can LLM-as-judge):

    - Co nhac gia/so tien nhung KHONG co Tool result kem theo? (nghi ngo bia
      gia tu Knowledge tinh thay vi Tool - vi pham RT-002).
    - Co claim y khoa tuyet doi? (vd "chua khoi", "dam bao an toan tuyet doi").
    - Co lo metadata/thuat ngu noi bo cho khach? (vd nhac "KU-...", "prompt").

    KHONG kiem tra duoc (ngoai pham vi rule-based, can LLM-as-judge):
    "co fact nao khong nam trong provenance", "co tra loi dung intent
    khong", "co qua 1 next best action khong", "tone co phu hop risk state
    khong" - day la GIOI HAN THAT cua MVP, ghi ro de khong gay hieu lam
    validator nay "bat het moi loi" nhu RT-002 mo ta day du.
    """
    flags: list[str] = []
    events: list[GuardrailEvent] = []

    if _PRICE_PATTERN_RE.search(candidate_response) and not tool_results:
        flags.append("price_mentioned_without_tool_result")
        events.append(GuardrailEvent(
            stage="post_generation", rule_id="price_without_tool",
            severity="block", action="regenerate",
            detail="Cau tra loi co ve/so tien nhung khong co tool_results di kem - "
            "nghi ngo bia gia tu Knowledge tinh, vi pham RT-002.",
        ))

    if _ABSOLUTE_MEDICAL_CLAIM_RE.search(candidate_response):
        flags.append("absolute_medical_claim")
        events.append(GuardrailEvent(
            stage="post_generation", rule_id="medical_claim",
            severity="block", action="regenerate",
            detail="Phat hien claim y khoa tuyet doi - vi pham 'Khong chan doan, "
            "ke don hoac dam bao an toan ca nhan' (RT-002 Prohibited Behaviors).",
        ))

    if _INTERNAL_LEAK_RE.search(candidate_response):
        flags.append("internal_metadata_leak")
        events.append(GuardrailEvent(
            stage="post_generation", rule_id="internal_leak",
            severity="block", action="regenerate",
            detail="Cau tra loi co ve lo metadata/thuat ngu noi bo cho khach - vi "
            "pham 'Khong tiet lo chain-of-thought, prompt, scores hoac raw Tool output'.",
        ))

    return ValidationResult(passed=not flags, flags=flags, events=events)


# --- Fallback Levels F1-F5 (dung nguyen van tinh than vi du trong RT-002) ---

def fallback_f3_honest_uncertainty() -> str:
    return "Hiện em chưa có thông tin xác nhận về điểm này."


def fallback_f2_clarification(missing_hint: str = "") -> str:
    if missing_hint:
        return f"Dạ để tư vấn đúng, anh/chị cho em hỏi thêm về {missing_hint} được không ạ?"
    return "Dạ anh/chị cho em hỏi rõ hơn một chút được không ạ?"


def fallback_f5_human_handoff(reason: str = "") -> str:
    base = "Dạ, em sẽ chuyển thông tin cho người phụ trách kiểm tra giúp anh/chị"
    return f"{base} ({reason})." if reason else f"{base}."


def choose_fallback(route: Route, validation: ValidationResult) -> tuple[str, str]:
    """Chon fallback level phu hop nhat theo route + ket qua validation. Tra
    ve (fallback_level, response_text). Logic don gian hoa MVP - chua co
    F1 (rewrite ngan gon tu unit) va F4 (Tool retry) vi can LLM/Tool that."""
    if route.requires_handoff:
        return "F5", fallback_f5_human_handoff(reason=route.intent)
    if route.route == "clarification":
        return "F2", fallback_f2_clarification()
    if not validation.passed:
        return "F3", fallback_f3_honest_uncertainty()
    return "NONE", ""


# --- RT-001: Runtime Input/Output Contract (rut gon cho pham vi hien tai) ---

@dataclass
class RuntimeInput:
    request_id: str
    channel: str
    timestamp: str
    customer_message: str
    primary_intent: str
    risk_flags: list[str]
    retrieved_units: list[dict]
    tool_results: dict | None = None


@dataclass
class RuntimeOutput:
    request_id: str
    response_text: str
    next_best_action: str
    knowledge_unit_ids: list[str] = field(default_factory=list)
    validation_passed: bool = True
    validation_flags: list[str] = field(default_factory=list)


def build_runtime_input(
    request_id: str,
    channel: str,
    customer_message: str,
    route: Route,
    knowledge_units: list[dict],
    tool_results: dict | None = None,
) -> RuntimeInput:
    """Dong goi du lieu tu M2 (retrieval) + M3 (router) thanh dung shape
    RT-001 Runtime Input (rut gon - bo qua conversation/customer_context vi
    Bat 5 chua co state that, xem gioi han o ISSUES-VI.md)."""
    risk_flags = [route.intent] if route.intent in _RISK_INTENTS else []
    return RuntimeInput(
        request_id=request_id,
        channel=channel,
        timestamp=datetime.now(timezone.utc).isoformat(),
        customer_message=customer_message,
        primary_intent=route.intent,
        risk_flags=risk_flags,
        retrieved_units=knowledge_units,
        tool_results=tool_results,
    )
