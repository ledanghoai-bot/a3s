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

from app.services.nlu.high_precision_rules import (
    get_vocative_prefixes,  # noqa: F401 (doc de ro nguon)
)

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

        catalog = load_intent_catalog(_NLU_ROOT / "intent-catalog.yaml")
        rules = load_normalization_rules(_NLU_ROOT / "normalization.yaml")
        protected_phrases = load_protected_phrases(_NLU_ROOT / "protected-phrases.yaml")
        routing_rules_config = load_routing_rules(_NLU_ROOT / "routing-rules.yaml")
        utterances = load_utterances(_NLU_ROOT / "utterances")

        pattern_index = build_pattern_index(utterances, rules, protected_phrases)

        # Semantic Router (model mpnet ~1.1GB RAM) - CHI build khi flag bat
        # (quyet dinh PO 23/7: mac dinh TAT, xem config.py va
        # docs/KB_NLU_RESOURCE_ASSESSMENT-VI.md PA2-5a). Khi tat: import
        # semantic_router KHONG xay ra o day -> mpnet khong bao gio duoc load.
        from app.config import settings
        if settings.enable_semantic_router:
            from app.services.nlu.semantic_router import build_semantic_index
            semantic_index = await build_semantic_index(utterances)
        else:
            semantic_index = None
            print("[nlu_hint] Semantic Router TAT (ENABLE_SEMANTIC_ROUTER=false) - "
                  "chi dung Pattern Router + Rules + Entity, khong load model mpnet.")

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
    """Ghep phan hint KHONG can Knowledge Base (tool/handoff) - phan
    knowledge duoc xu ly rieng trong _build_knowledge_hint() vi can await."""
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
            "dung cau hoi that su cua khach. LUU Y tuan thu THU TU trong system "
            "prompt: neu la khieu nai ma khach CHUA cung cap ma don/chi tiet su "
            "viec, phai HOI truoc (ghi nhan cam xuc + xin loi + hoi ma don) roi "
            "moi escalate o luot sau - TRU khi khach doi gap nhan vien truc tiep."
        )

    return "\n".join(lines)


async def _build_knowledge_hint(message: str) -> str:
    """Goi THAT Knowledge Base V2 (#11, M1-M6) qua kb_retrieval.search_kb()
    de lay noi dung Knowledge Unit that.

    v1.1 (18/7) - CHI cho phep domain "brand"/"product"/"faq" - da xac nhan
    nhieu lan qua session nay day la noi dung THAT SU danh cho khach (FAQ-
    BREW-001, FAQ-BRAND-001, thong tin freeze-dried...). LOAI TRU domain
    "sales"/"conversation"/"customer_service"/"playbook" - phat hien thuc te:
    `SKL-SAL-002` (domain="sales") hoa ra la 1 tai lieu PLAYBOOK NOI BO
    nguyen ven (26 muc: "Purpose", "Priority rules", "Do"/"Don't",
    "Escalation", "Traceability"...) - khong phai noi dung tra loi khach
    hang, nhung van bi lay ra vi tinh co nhac toi "nguyen lieu" nhu vi du
    minh hoa trong tai lieu. Da kiem tra qua SQL: ca 5 asset trong domain
    "sales" (SKL-SAL-001..005) deu cung dang playbook - loai het domain nay
    la an toan.
    """
    try:
        from app.services.kb_retrieval import search_kb
        units = await search_kb(message, top_k=2, allowed_domains=["brand", "product", "faq"])
        if not units:
            return (
                "Cau hoi lien quan toi kien thuc san pham/thuong hieu nhung khong tim "
                "thay noi dung tham khao cu the trong Knowledge Base - tra loi than "
                "trong, khong bia."
            )
        lines = ["Kien thuc lien quan tu Knowledge Base (dung dung noi dung nay, khong bia them):"]
        for u in units:
            content_snippet = u["content"][:500]
            lines.append(f"[{u['asset_id']}] {u['heading']}: {content_snippet}")
        return "\n".join(lines)
    except Exception as e:
        print(f"[nlu_hint] Loi khi goi Knowledge Base V2 (bo qua, dung hint chung): {e}")
        return (
            "Cau hoi lien quan toi kien thuc san pham/thuong hieu - uu tien dung thong "
            "tin tham khao da co san trong prompt, khong bia them."
        )


# Nguong cosine distance cho fallback knowledge hint (PO duyet 23/7 qua
# Telegram). Chon tu SO DO THAT (scripts probe, KB index v1): cau lien quan
# d=0.354-0.531, cau khong lien quan d=0.530-0.727. 0.55 = uu tien bat du cau
# kien thuc (ke ca go khong dau, d~0.48), chap nhan ca bien "cho anh 5 hu"
# (d=0.530) lot hint FAQ nhe - preamble da dan LLM bo qua neu lac de.
_KB_FALLBACK_MAX_DIST = 0.55


async def _build_knowledge_fallback_hint(message: str) -> str:
    """Fallback khi Pattern Router KHONG khop (PO duyet 23/7): thay vi im lang
    hoan toan (hanh vi ngay sau khi chop Semantic Router), thu search_kb()
    bang MiniLM - model VON DA load cho KB V2, khong ton them RAM (~65ms/cau).
    Dung RETRIEVAL thay CLASSIFICATION: khong doan intent, chi kiem tra "co
    noi dung KB gan cau nay khong" qua cosine distance that.

    Khac _build_knowledge_hint() (duong intent da xac nhan): ham nay KHONG
    biet cau co phai cau hoi kien thuc hay khong -> loc bang nguong distance,
    khong tim thay thi tra ve "" (im lang), TUYET DOI khong tra hint chung
    chung kieu "cau hoi lien quan kien thuc" vi chua chac dung.
    """
    try:
        from app.services.kb_retrieval import search_kb
        # top_k=4 (khong phai 2 nhu duong intent da xac nhan): fallback khong co
        # intent dan duong nen can luoi rong hon - so do that 23/7: cau khong dau
        # "3s coffee la thuong hieu cua cong ty nao" co dap an chuan
        # (KU-FAQ-001-003/FAQ-BRAND-001, dist=0.5156) xep hang 4; ban co dau xep
        # hang 3. Nguong distance van loc noi dung lac de o duoi.
        units = await search_kb(message, top_k=4, allowed_domains=["brand", "product", "faq"])
        units = [
            u for u in units
            if u.get("vector_distance") is not None
            and u["vector_distance"] <= _KB_FALLBACK_MAX_DIST
        ]
        if not units:
            return ""
        lines = [
            "He thong tim thay noi dung Knowledge Base CO THE lien quan toi tin nhan "
            "nay (chua chac chan - CHI dung neu dung chu de cau hoi cua khach, lac de "
            "thi bo qua hoan toan, khong bia them):"
        ]
        for u in units:
            lines.append(f"[{u['asset_id']}] {u['heading']}: {u['content'][:500]}")
        return "\n".join(lines)
    except Exception as e:
        print(f"[nlu_hint] Loi fallback knowledge hint (bo qua): {e}")
        return ""


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
        # Buoc 10 (Cache) - kiem tra cache truoc, CHI cho ket qua "accept"
        # da tung xac nhan (dung theo danh sach duoc phep trong guide:
        # "Normalized query -> intent candidate"). Cache MISS la binh thuong,
        # khong phai loi - van tiep tuc route() binh thuong.
        from app.services.nlu.cache import get_cached_decision, set_cached_decision
        from app.services.nlu.normalizer import normalize
        from app.services.nlu.route_resolution import resolve_route
        from app.services.nlu.router import route
        normalized_msg = normalize(message, _state["rules"], _state["protected_phrases"])

        cached = await get_cached_decision(normalized_msg)
        if cached:
            from app.services.nlu.router import NluDecision
            decision = NluDecision(**cached)
        else:
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
                await set_cached_decision(normalized_msg, {
                    "intent": decision.intent, "confidence": decision.confidence,
                    "action": decision.action, "matched_by": decision.matched_by,
                    "detail": decision.detail,
                })

        if decision.action == "accept":
            resolved = resolve_route(decision.intent, _state["catalog"])
            if sender_id:
                from app.services.nlu.context_state import save_conversation_state
                domains = resolved.targets if (resolved and resolved.type == "knowledge") else []
                await save_conversation_state(sender_id, decision.intent, domains)

            if resolved and resolved.type == "knowledge":
                base = _build_hint_text(decision, resolved)
                kb_part = await _build_knowledge_hint(message)
                return f"{base}\n{kb_part}"
            return _build_hint_text(decision, resolved)

        # Router khong du tin cay - thu Context-aware Resolution (Buoc 5)
        # truoc khi tra ve rong hoan toan. CHI la goi y tham khao, KHONG ep
        # buoc theo intent cu - dung theo guide "khong ghi de intent ro rang
        # cua tin nhan hien tai".
        if sender_id:
            from app.services.nlu.context_state import (
                get_conversation_state,
                looks_like_continuation,
            )
            if looks_like_continuation(message):
                state = await get_conversation_state(sender_id)
                if state and state.get("previous_intent"):
                    return (
                        f"Tin nhan nay ngan/chua ro y dinh - co the la cau hoi NOI TIEP "
                        f"tu ngu canh truoc do (chu de gan nhat: '{state['previous_intent']}'). "
                        f"Can nhac ngu canh nay khi tra loi, nhung KHONG bat buoc phai theo neu "
                        f"noi dung cau hien tai ro rang la chu de khac."
                    )

        # Fallback cuoi (PO duyet 23/7): cau khong khop pattern, khong phai cau
        # noi tiep -> thu tim noi dung KB gan ve ngu nghia (loc bang cosine
        # distance) truoc khi chiu im lang. Xem _build_knowledge_fallback_hint().
        return await _build_knowledge_fallback_hint(message)
    except Exception as e:
        print(f"[nlu_hint] Loi khi chay NLU Router (bo qua, dung flow cu): {e}")
        return ""
