"""CLI test Runtime Guardrails (Knowledge Base V2, M5 Bat 5) - noi tron ven
M2 (Retrieval) + M3 (Router) + M5 (Guardrails), demo ca pre-generation
guardrails THAT lan post-generation validation voi candidate response MAU
(vi CHUA co LLM that trong pipeline).

Cach dung:
    docker compose exec api python scripts/kb_runtime_test.py "cau hoi cua ban"
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.kb_retrieval import search_kb  # noqa: E402
from app.services.kb_router import classify  # noqa: E402
from app.services.kb_runtime import (  # noqa: E402
    build_runtime_input,
    choose_fallback,
    pre_generation_guardrails,
    validate_response,
)

# Candidate response MAU de test post-generation validation (vi chua goi
# LLM that) - co the doi bang tay de thu cac truong hop khac nhau.
_SAMPLE_CANDIDATE_RESPONSES = {
    "clean": "Dạ pha nóng khoảng 85 độ, khuấy nhẹ 15 giây là tan hết ạ.",
    "bad_price": "Dạ sản phẩm này giá 170.000đ 1 hũ ạ.",
    "bad_medical": "Dạ sản phẩm này chữa khỏi bệnh dạ dày hoàn toàn ạ.",
    "bad_leak": "Dạ theo KU-FAQ-003-001 thì anh nên pha nóng ạ.",
}


async def main() -> None:
    if len(sys.argv) < 2:
        print('Dung: python scripts/kb_runtime_test.py "cau hoi"')
        print("Them --candidate=clean|bad_price|bad_medical|bad_leak de doi cau tra loi mau test")
        return

    args = [a for a in sys.argv[1:] if not a.startswith("--candidate=")]
    candidate_key = "clean"
    for a in sys.argv[1:]:
        if a.startswith("--candidate="):
            candidate_key = a.split("=", 1)[1]
    query = " ".join(args)
    candidate_response = _SAMPLE_CANDIDATE_RESPONSES.get(candidate_key, _SAMPLE_CANDIDATE_RESPONSES["clean"])

    route = classify(query)
    print("=== M3: Intent/Risk Router ===")
    print(f"intent={route.intent}  route={route.route}  requires_handoff={route.requires_handoff}")
    print()

    units = []
    if route.route == "knowledge":
        units = await search_kb(query, top_k=3, allowed_domains=route.allowed_domains or None)
        print(f"=== M2: Retrieval ({len(units)} KU) ===")
        for u in units:
            print(f"  {u['ku_id']} (status={u['status']}) - {u['heading']}")
        print()

    tool_results = {"gia": "170000 VND/hu"} if route.requires_tool else None

    print("=== M5: Pre-Generation Guardrails ===")
    pre_events = pre_generation_guardrails(route, units)
    if not pre_events:
        print("  (khong co canh bao nao)")
    for e in pre_events:
        print(f"  [{e.severity}] {e.rule_id} -> action={e.action} | {e.detail}")
    print()

    print(f"=== M5: Post-Generation Validation (candidate='{candidate_key}') ===")
    print(f"  Candidate response mau: {candidate_response!r}")
    validation = validate_response(candidate_response, route, tool_results)
    print(f"  passed={validation.passed}  flags={validation.flags}")
    print()

    level, fallback_text = choose_fallback(route, validation)
    print("=== M5: Fallback Decision ===")
    if level == "NONE":
        print("  Khong can fallback - candidate response duoc chap nhan.")
    else:
        print(f"  Level={level}")
        print(f"  Text: {fallback_text}")
    print()

    ri = build_runtime_input("req-test", "messenger", query, route, units, tool_results)
    print("=== RT-001: Runtime Input (rut gon) ===")
    print(f"  request_id={ri.request_id}  primary_intent={ri.primary_intent}  risk_flags={ri.risk_flags}")


if __name__ == "__main__":
    asyncio.run(main())
