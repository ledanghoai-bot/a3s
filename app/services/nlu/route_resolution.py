"""Route Resolution (Buoc 8, NLU-INTEGRATION-GUIDE.md) - tra ve hanh dong cu
the (loai + target) cho 1 intent da duoc NLU Router (#12) phan loai, dua
tren truong `route` cua tung intent trong intent-catalog.yaml. Day la phan
"Orchestrator Responsibilities" theo dung Muc 6 cua guide (NLU tu no KHONG
duoc goi Tool truc tiep - chi tra route hint, Orchestrator moi la noi thuc
thi).

QUAN TRONG - phat hien khi doi chieu voi tools.py that (18/7): nhieu `target`
trong intent-catalog.yaml (vd get_payment_options, get_cod_policy,
get_shipping_quote, get_delivery_estimate, get_tracking_information) CHUA
CO tool thuc su tuong ung trong production hien tai - chi co DUNG 3 cap
khop that (xem TOOL_NAME_MAP ben duoi). Voi cac target chua co tool that,
Route Resolution van tra ve dung ket qua (type=tool + target), nhung
Orchestrator (noi goi ham nay) PHAI tu quyet dinh KHONG ep goi mot tool
khong ton tai - chi dung nhu 1 tin hieu/goi y bo sung cho LLM tu quyet dinh
nhu cu, khong duoc thay the flow hien tai.
"""

from dataclasses import dataclass, field

# Anh xa DUY NHAT 3 cap ten target trong intent-catalog.yaml sang ten ham
# THAT trong app/services/tools.py (da test/hoat dong san xuat qua issue #6).
# Cac target khac (get_payment_options, get_cod_policy, get_shipping_quote,
# get_delivery_estimate, get_order_status, get_tracking_information) CHUA CO
# tool that - KHONG dua vao map nay, de Orchestrator tu biet ma khong ep goi.
TOOL_NAME_MAP: dict[str, str] = {
    "get_current_price": "search_products",
    "get_current_stock": "check_stock",
    "create_or_confirm_order": "create_order",
}


@dataclass
class ResolvedRoute:
    type: str  # knowledge | tool | playbook | handoff | clarify | out_of_scope
    targets: list[str] = field(default_factory=list)  # SKL-* hoac ten target trong catalog
    real_tool_name: str | None = None  # ten ham THAT trong tools.py, None neu chua co
    requires_identity_verification: bool = False
    handoff_mode: str | None = None  # "conditional" neu co
    missing_entity_action: dict | None = None


def resolve_route(intent: str, intent_catalog: dict) -> ResolvedRoute | None:
    """Tra ve None neu khong tim thay intent trong catalog (khong nen xay ra
    neu NLU Router chi tra ve intent hop le, nhung van kiem tra ro rang)."""
    for it in intent_catalog.get("intents", []):
        if it["intent"] != intent:
            continue
        route = it.get("route", {})
        route_type = route.get("type", "clarify")
        targets = route.get("targets") or ([route["target"]] if route.get("target") else [])
        real_tool_name = None
        if route_type == "tool" and targets:
            real_tool_name = TOOL_NAME_MAP.get(targets[0])
        return ResolvedRoute(
            type=route_type,
            targets=targets,
            real_tool_name=real_tool_name,
            requires_identity_verification=route.get("requires_identity_verification", False),
            handoff_mode=route.get("handoff"),
            missing_entity_action=it.get("missing_entity_action"),
        )
    return None
