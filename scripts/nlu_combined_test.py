"""CLI test Combined NLU Router (Bat D) - do accuracy THAT dau-cuoi cua
toan bo pipeline (Pattern Router -> Semantic Router) tren 150 test held-out.

Cach dung:
    docker compose exec api python scripts/nlu_combined_test.py "cau hoi cua ban"
    docker compose exec api python scripts/nlu_combined_test.py --eval
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.nlu.loader import (  # noqa: E402
    load_intent_catalog,
    load_normalization_rules,
    load_protected_phrases,
    load_routing_rules,
    load_test_cases,
    load_utterances,
)
from app.services.nlu.pattern_router import build_pattern_index  # noqa: E402
from app.services.nlu.router import route  # noqa: E402
from app.services.nlu.semantic_router import build_semantic_index  # noqa: E402

NLU_ROOT = Path(__file__).resolve().parent.parent / "datasets" / "nlu"
TESTS_ROOT = Path(__file__).resolve().parent.parent / "datasets" / "tests"


async def main() -> None:
    catalog = load_intent_catalog(NLU_ROOT / "intent-catalog.yaml")
    rules = load_normalization_rules(NLU_ROOT / "normalization.yaml")
    protected_phrases = load_protected_phrases(NLU_ROOT / "protected-phrases.yaml")
    routing_rules_config = load_routing_rules(NLU_ROOT / "routing-rules.yaml")
    utterances = load_utterances(NLU_ROOT / "utterances")

    pattern_index = build_pattern_index(utterances, rules, protected_phrases)
    print(f"Dang tinh embedding cho {len(utterances)} utterance (lan dau se cham hon do phai tai model)...")
    semantic_index = await build_semantic_index(utterances)
    print("Xong.\n")

    if len(sys.argv) < 2:
        print('Dung: python scripts/nlu_combined_test.py "cau hoi"')
        print("  hoac: python scripts/nlu_combined_test.py --eval")
        return

    if sys.argv[1] == "--eval":
        test_cases = load_test_cases(TESTS_ROOT)
        tests = test_cases.get("intent-routing-tests", [])

        correct, wrong, clarify = 0, 0, 0
        via_pattern, via_semantic = 0, 0
        for t in tests:
            decision = await route(
                t["input"], rules, pattern_index, semantic_index, catalog,
                protected_phrases=protected_phrases, routing_rules_config=routing_rules_config,
            )
            if decision.matched_by == "semantic":
                via_semantic += 1
            else:
                via_pattern += 1

            if decision.action == "clarify":
                clarify += 1
            elif decision.intent == t["expected_intent"]:
                correct += 1
            else:
                wrong += 1
                print(f"  SAI: '{t['input']}' -> {decision.intent} (via={decision.matched_by}, "
                      f"conf={decision.confidence}, action={decision.action}) | ky vong {t['expected_intent']}")

        total = len(tests)
        print(f"\n=== KET QUA PIPELINE HOAN CHINH tren {total} test held-out ===")
        print(f"  Dung: {correct} ({correct/total*100:.1f}%)")
        print(f"  Sai: {wrong} ({wrong/total*100:.1f}%)")
        print(f"  Clarify: {clarify} ({clarify/total*100:.1f}%)")
        print(f"\n  Xu ly qua Pattern Router: {via_pattern} ({via_pattern/total*100:.1f}%)")
        print(f"  Xu ly qua Semantic Router (fallback): {via_semantic} ({via_semantic/total*100:.1f}%)")
        return

    query = " ".join(sys.argv[1:])
    decision = await route(
        query, rules, pattern_index, semantic_index, catalog,
        protected_phrases=protected_phrases, routing_rules_config=routing_rules_config,
    )
    print(f"intent={decision.intent}  confidence={decision.confidence}  action={decision.action}  "
          f"matched_by={decision.matched_by}  detail={decision.detail}")


if __name__ == "__main__":
    asyncio.run(main())
