"""CLI test Prompt Assembly (Knowledge Base V2, M4 Bat 4) - ghep dung
kb_router.classify() (M3) + kb_retrieval.search_kb() (M2) that, roi lap rap
prompt hoan chinh de xem bang mat.

Cach dung:
    docker compose exec api python scripts/kb_prompt_test.py "cau hoi cua ban"
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.kb_prompt_assembly import assemble_prompt  # noqa: E402
from app.services.kb_retrieval import search_kb  # noqa: E402
from app.services.kb_router import classify  # noqa: E402


async def main() -> None:
    if len(sys.argv) < 2:
        print('Dung: python scripts/kb_prompt_test.py "cau hoi"')
        return

    query = " ".join(sys.argv[1:])

    route = classify(query)
    print("=== BUOC 1: Intent/Risk Router (M3) ===")
    print(f"intent={route.intent}  route={route.route}  "
          f"requires_handoff={route.requires_handoff}  requires_tool={route.requires_tool}")
    print(f"allowed_domains={route.allowed_domains}")
    print()

    units = []
    if route.route == "knowledge":
        print("=== BUOC 2: Knowledge Retrieval (M2) ===")
        units = await search_kb(query, top_k=3, allowed_domains=route.allowed_domains or None)
        for u in units:
            print(f"  {u['ku_id']} (score={u['score']}) - {u['heading']}")
        print()
    else:
        print(f"=== BUOC 2: BO QUA retrieval (route='{route.route}' khong can Knowledge) ===\n")

    # Mo phong Tool result gia lap cho route=tool (chua goi Tool that - Bat sau)
    tool_results = None
    if route.requires_tool:
        tool_results = {"ghi_chu": "[MO PHONG] Day la cho ket qua Tool that se dien vao (chua tich hop)"}

    assembled = assemble_prompt(
        route, query, knowledge_units=units, tool_results=tool_results,
    )

    print("=== BUOC 3: Prompt Assembly (M4) ===")
    print(f"blocks_used: {assembled.blocks_used}")
    print(f"source_ids_used: {assembled.source_ids_used}")
    print()
    print("=== PROMPT HOAN CHINH ===")
    print(assembled.prompt)


if __name__ == "__main__":
    asyncio.run(main())
