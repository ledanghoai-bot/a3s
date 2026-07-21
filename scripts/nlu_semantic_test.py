"""CLI test Semantic Router (NLU layer, Bat C) - build embedding index tu 300
utterance that (can model ML that, chay ~vai chuc giay lan dau), test cau
bat ky hoac chay toan bo 60 test held-out de do % PHU THEM (so voi Bat B
Pattern Router).

Cach dung:
    docker compose exec api python scripts/nlu_semantic_test.py "cau hoi cua ban"
    docker compose exec api python scripts/nlu_semantic_test.py --eval
    docker compose exec api python scripts/nlu_semantic_test.py --sweep
        -> tinh embedding 1 LAN DUY NHAT, roi thu NHIEU gia tri
           low_confidence_threshold khac nhau de xem duong danh doi
           Dung/Sai/Clarify - nhanh hon nhieu so voi chay --eval lap lai
           tung nguong rieng le (khong phai tinh lai embedding moi lan).
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
from app.services.nlu.semantic_router import (  # noqa: E402
    build_semantic_index,
    decide_confidence,
    route_semantic,
)

NLU_ROOT = Path(__file__).resolve().parent.parent / "datasets" / "nlu"
TESTS_ROOT = Path(__file__).resolve().parent.parent / "datasets" / "tests"


def _summarize(tests, results_with_candidates, catalog):
    correct, wrong, clarify = 0, 0, 0
    details = []
    for t, candidates in results_with_candidates:
        decision = decide_confidence(candidates, catalog)
        if decision.action == "clarify":
            clarify += 1
            status = "CLARIFY"
        elif decision.intent == t["expected_intent"]:
            correct += 1
            status = "DUNG"
        else:
            wrong += 1
            status = "SAI"
        details.append((status, t, decision))
    return correct, wrong, clarify, details


async def main() -> None:
    catalog = load_intent_catalog(NLU_ROOT / "intent-catalog.yaml")
    rules = load_normalization_rules(NLU_ROOT / "normalization.yaml")
    protected_phrases = load_protected_phrases(NLU_ROOT / "protected-phrases.yaml")
    routing_rules_config = load_routing_rules(NLU_ROOT / "routing-rules.yaml")
    utterances = load_utterances(NLU_ROOT / "utterances")

    print(f"Dang tinh embedding cho {len(utterances)} utterance (lan dau se cham hon do phai tai model)...")
    index = await build_semantic_index(utterances)
    print("Xong.\n")

    if len(sys.argv) < 2:
        print('Dung: python scripts/nlu_semantic_test.py "cau hoi"')
        print("  hoac: python scripts/nlu_semantic_test.py --eval")
        print("  hoac: python scripts/nlu_semantic_test.py --sweep")
        return

    if sys.argv[1] == "--eval":
        test_cases = load_test_cases(TESTS_ROOT)
        tests = test_cases.get("intent-routing-tests", [])
        results_with_candidates = []
        for t in tests:
            candidates = await route_semantic(
                t["input"], rules, index, protected_phrases=protected_phrases,
                routing_rules_config=routing_rules_config,
            )
            results_with_candidates.append((t, candidates))

        correct, wrong, clarify, details = _summarize(tests, results_with_candidates, catalog)
        for status, t, decision in details:
            if status != "DUNG":
                print(f"  [{status}] '{t['input']}' -> {decision.intent} (conf={decision.confidence}, action={decision.action}) | ky vong {t['expected_intent']}")

        total = len(tests)
        print(f"\nKET QUA tren {total} test held-out:")
        print(f"  Dung: {correct} ({correct/total*100:.1f}%)")
        print(f"  Sai: {wrong} ({wrong/total*100:.1f}%)")
        print(f"  Clarify (khong du tu tin): {clarify} ({clarify/total*100:.1f}%)")
        return

    if sys.argv[1] == "--sweep":
        test_cases = load_test_cases(TESTS_ROOT)
        tests = test_cases.get("intent-routing-tests", [])
        print(f"Dang tinh candidate cho {len(tests)} test (chi 1 lan, tai su dung cho moi nguong)...")
        results_with_candidates = []
        for t in tests:
            candidates = await route_semantic(
                t["input"], rules, index, protected_phrases=protected_phrases,
                routing_rules_config=routing_rules_config,
            )
            results_with_candidates.append((t, candidates))
        print("Xong.\n")

        total = len(tests)
        default_low = catalog.get("defaults", {}).get("low_confidence_threshold", 0.65)
        print(f"low_confidence_threshold mac dinh hien tai: {default_low}\n")
        print(f"{'low_threshold':>14} | {'Dung':>12} | {'Sai':>12} | {'Clarify':>12}")
        print("-" * 60)
        for low_threshold in [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
            modified_catalog = dict(catalog)
            modified_defaults = dict(catalog.get("defaults", {}))
            modified_defaults["low_confidence_threshold"] = low_threshold
            modified_catalog["defaults"] = modified_defaults

            correct, wrong, clarify, _ = _summarize(tests, results_with_candidates, modified_catalog)
            marker = "  <- mac dinh" if abs(low_threshold - default_low) < 1e-9 else ""
            print(f"{low_threshold:>14.2f} | {correct:>4} ({correct/total*100:>4.1f}%) | "
                  f"{wrong:>4} ({wrong/total*100:>4.1f}%) | {clarify:>4} ({clarify/total*100:>4.1f}%){marker}")
        return

    query = " ".join(sys.argv[1:])
    candidates = await route_semantic(
        query, rules, index, protected_phrases=protected_phrases,
        routing_rules_config=routing_rules_config,
    )
    decision = decide_confidence(candidates, catalog)
    print(f"action={decision.action}  intent={decision.intent}  confidence={decision.confidence}")
    print("Candidates:")
    for c in decision.candidates:
        print(f"  {c.intent} (confidence={c.confidence}, utterance={c.utterance_id})")


if __name__ == "__main__":
    asyncio.run(main())
