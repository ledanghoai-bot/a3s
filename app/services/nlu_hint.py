"""Cau noi giua Lop NLU (#12, app/services/nlu/) va orchestrator.py - CHI tao
HINT/CONTEXT bo sung cho system prompt, KHONG bao gio thay the hay chan flow
hien tai. Dung theo dung "Orchestrator Responsibilities" trong
NLU-INTEGRATION-GUIDE.md Muc 6: NLU chi tra route hint, Orchestrator (module
nay) moi quyet dinh hanh dong that.

AN TOAN TUYET DOI CHO PRODUCTION: MOI loi xay ra trong duong NLU (load file
thieu, model chua tai duoc, key khong khop...) deu bi bat va tra ve chuoi
rong ("") - KHONG BAO GIO raise loi ra ngoai orchestrator.py. Neu
`get_nlu_hint()` fail, bot van tra loi binh thuong nhu chua bat NLU Router.

Index (pattern + semantic) duoc TINH 1 LAN DUY NHAT va cache trong bo nho
tien trinh (module-level state) - khong tinh lai moi tin nhan (embedding
380 utterance mat vai giay, chi chap nhan duoc 1 lan luc khoi dong, khong
phai moi request).
"""

from pathlib import Path

from app.services.nlu.high_precision_rules import get_vocative_prefixes  # noqa: F401 (doc de ro nguon)

_NLU_ROOT = Path(__file__).resolve().parents[2] / "datasets" / "nlu"

# Cache module-level - None cho toi khi load lan dau thanh cong.
_state: dict = {
    "loaded": False,
    "catalog": None,
    "rules": None,
    "protected_phrases": None,
    "routing_rules_config": None,
    "pattern_index": None,
    "semantic_index": None,
}


async def _ensure_loaded() -> bool:
    """Tra ve True neu da (hoac vua) load thanh cong, False neu khong the load
    (vd thieu file datasets/nlu/) - KHONG raise loi."""
    if _state["loaded"]:
        return True
    try:
        from app.services.nlu.loader import (
            load_intent_catalog,
            load_normalization_rules,
            load_protected_phrases,
            load_routing_rules,
            load_utterances,
        )
        from app.services.nlu.pattern_router import build_pattern_index
        from app.services.nlu.semantic_router import build_semantic_index

        catalog = load_intent_catalog(_NLU_ROOT / "intent-catalog.yaml")
        rules = load_normalization_rules(_NLU_ROOT / "normalization.yaml")
        protected_phrases = load_protected_phrases(_NLU_ROOT / "protected-phrases.yaml")
        routing_rules_config = load_routing_rules(_NLU_ROOT / "routing-rules.yaml")
        utterances = load_utterances(_NLU_ROOT / "utterances")

        pattern_index = build_pattern_index(utterances, rules, protected_phrases)
        semantic_index = await build_semantic_index(utterances)

        _state.update(
            catalog=catalog, rules=rules, protected_phrases=protected_phrases,
            routing_rules_config=routing_rules_config,
            pattern_index=pattern_index, semantic_index=semantic_index,
            loaded=True,
        )
        return True
    except Exception as e:
        print(f"[nlu_hint] Khong load duoc du lieu NLU (bo qua, dung flow cu): {e}")
        return False


def _build_hint_text(decision, resolved) -> str:
    """Ghep hint text theo type route - CHI la GOI Y, khong ra lenh tuyet doi
    cho LLM (LLM van tu quyet dinh cuoi cung, giu dung tinh than "Minimal
    Context Builder" cua guide)."""
    lines = [
        f"He thong NLU phat hien y dinh khach hang: '{decision.intent}' "
        f"(do tin cay {decision.confidence}, qua {decision.matched_by})."
    ]

    if resolved is None:
        return "\n".join(lines)

    if resolved.type == "tool" and resolved.real_tool_name:
        lines.append(
            f"Day la cau hoi ro rang thuoc loai can du lieu dong - LUON goi tool "
            f"'{resolved.real_tool_name}' de tra loi chinh xac, khong tu suy doan."
        )
    elif resolved.type == "handoff":
        lines.append(
            "Day co the la tinh huong can chuyen nguoi that xu ly (khieu nai/doi "
            "tra/hoan tien) - can nhac goi escalate_to_human neu phu hop voi noi "
            "dung cau hoi that su cua khach."
        )
    elif resolved.type == "knowledge":
        lines.append(
            "Cau hoi lien quan toi kien thuc san pham/thuong hieu - uu tien dung "
            "thong tin tham khao da co san trong prompt, khong bia them."
        )

    return "\n".join(lines)


async def get_nlu_hint(message: str, sender_id: str | None = None) -> str:
    """Ham DUY NHAT orchestrator.py can goi. Tra ve chuoi rong "" neu:
    - NLU chua load duoc (loi file/model), HOAC
    - Router khong du tin cay (action != "accept") VA khong co goi y ngu
      canh nao tu Context-aware Resolution (Buoc 5) de bo sung.
    Neu co hint, tra ve 1 doan text ngan de orchestrator.py tu ghep vao
    system prompt (giong cach dang lam voi rag_context/agent_notes).

    sender_id: TUY CHON - neu co, ho tro Context-aware Resolution (Buoc 5):
    luu lai intent xac nhan chac chan de lam ngu canh cho tin nhan sau, va
    tham khao ngu canh do khi tin nhan hien tai khong ro rang (chi la GOI Y
    tham khao, khong ghi de intent ro rang cua tin nhan hien tai - dung theo
    guide).
    """
    ok = await _ensure_loaded()
    if not ok:
        return ""

    try:
        from app.services.nlu.route_resolution import resolve_route
        from app.services.nlu.router import route

        decision = await route(
            message,
            _state["rules"],
            _state["pattern_index"],
            _state["semantic_index"],
            _state["catalog"],
            protected_phrases=_state["protected_phrases"],
            routing_rules_config=_state["routing_rules_config"],
        )

        if decision.action == "accept":
            resolved = resolve_route(decision.intent, _state["catalog"])
            if sender_id:
                from app.services.nlu.context_state import save_conversation_state
                domains = resolved.targets if (resolved and resolved.type == "knowledge") else []
                await save_conversation_state(sender_id, decision.intent, domains)
            return _build_hint_text(decision, resolved)

        # Router khong du tin cay - thu Context-aware Resolution (Buoc 5)
        # truoc khi tra ve rong hoan toan. CHI la goi y tham khao, KHONG ep
        # buoc theo intent cu - dung theo guide "khong ghi de intent ro rang
        # cua tin nhan hien tai".
        if sender_id:
            from app.services.nlu.context_state import get_conversation_state, looks_like_continuation
            if looks_like_continuation(message):
                state = await get_conversation_state(sender_id)
                if state and state.get("previous_intent"):
                    return (
                        f"Tin nhan nay ngan/chua ro y dinh - co the la cau hoi NOI TIEP "
                        f"tu ngu canh truoc do (chu de gan nhat: '{state['previous_intent']}'). "
                        f"Can nhac ngu canh nay khi tra loi, nhung KHONG bat buoc phai theo neu "
                        f"noi dung cau hien tai ro rang la chu de khac."
                    )
        return ""
    except Exception as e:
        print(f"[nlu_hint] Loi khi chay NLU Router (bo qua, dung flow cu): {e}")
        return ""
