"""CLI test Pattern/Exact Router (NLU layer, Bat B) - build index tu 300
utterance that, test cau bat ky hoac chay toan bo 60 test held-out de do
% Bat B tu phu duoc (chua tinh Semantic Router - Bat C).

Cach dung:
    docker compose exec api python scripts/nlu_pattern_test.py "cau hoi cua ban"
    docker compose exec api python scripts/nlu_pattern_test.py --eval
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.nlu.loader import (  # noqa: E402
    load_normalization_rules,
    load_protected_phrases,
    load_routing_rules,
    load_test_cases,
    load_utterances,
)
from app.services.nlu.pattern_router import build_pattern_index, route_pattern  # noqa: E402

NLU_ROOT = Path(__file__).resolve().parent.parent / "datasets" / "nlu"
TESTS_ROOT = Path(__file__).resolve().parent.parent / "datasets" / "tests"


def main() -> None:
    rules = load_normalization_rules(NLU_ROOT / "normalization.yaml")
    protected_phrases = load_protected_phrases(NLU_ROOT / "protected-phrases.yaml")
    routing_rules_config = load_routing_rules(NLU_ROOT / "routing-rules.yaml")
    utterances = load_utterances(NLU_ROOT / "utterances")
    index = build_pattern_index(utterances, rules, protected_phrases)
    print(f"Index: {len(index.exact)} exact entries, {len(index.token)} token entries "
          f"(tu {len(utterances)} utterance, {len(protected_phrases)} protected phrase, "
          f"{len(routing_rules_config.get('rules', []))} high-precision rule).\n")

    if len(sys.argv) < 2:
        print('Dung: python scripts/nlu_pattern_test.py "cau hoi"')
        print("  hoac: python scripts/nlu_pattern_test.py --eval")
        return

    if sys.argv[1] == "--eval":
        test_cases = load_test_cases(TESTS_ROOT)
        tests = test_cases.get("intent-routing-tests", [])
        matched, correct, wrong = 0, 0, 0
        for t in tests:
            m = route_pattern(
                t["input"], rules, index, protected_phrases=protected_phrases,
                routing_rules_config=routing_rules_config,
            )
            if m:
                matched += 1
                if m.intent == t["expected_intent"]:
                    correct += 1
                else:
                    wrong += 1
                    print(f"  SAI: '{t['input']}' -> {m.intent} (via={m.matched_by}, conf={m.confidence}) | ky vong {t['expected_intent']}")
        print(f"\nKET QUA tren {len(tests)} test held-out:")
        print(f"  Co match: {matched} | Dung: {correct} | Sai: {wrong}")
        print(f"  Pattern Router (Bat B) tu phu duoc: {correct}/{len(tests)} = {correct/len(tests)*100:.1f}%")
        print(f"  (Phan con lai se can Semantic Router - Bat C, chua lam)")
        return

    query = " ".join(sys.argv[1:])
    m = route_pattern(
        query, rules, index, protected_phrases=protected_phrases,
        routing_rules_config=routing_rules_config,
    )
    if m:
        print(f"intent={m.intent}  confidence={m.confidence}  matched_by={m.matched_by}  "
              f"utterance_id={m.matched_utterance_id}")
    else:
        print("Khong match duoc (se can Semantic Router - Bat C, chua lam).")


if __name__ == "__main__":
    main()
