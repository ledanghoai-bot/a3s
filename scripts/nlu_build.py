"""CLI build/validate NLU dataset (Bat A) - doc datasets/nlu/, chay validator,
demo normalize() voi vai cau mau.

Cach dung:
    docker compose exec api python scripts/nlu_build.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.nlu.loader import (  # noqa: E402
    load_intent_catalog,
    load_normalization_rules,
    load_protected_phrases,
    load_test_cases,
    load_utterances,
)
from app.services.nlu.normalizer import normalize  # noqa: E402
from app.services.nlu.validator import (  # noqa: E402
    validate_intent_catalog,
    validate_no_train_test_leakage,
    validate_normalization_rules,
    validate_utterances,
)

NLU_ROOT = Path(__file__).resolve().parent.parent / "datasets" / "nlu"
TESTS_ROOT = Path(__file__).resolve().parent.parent / "datasets" / "tests"


def main() -> None:
    if not NLU_ROOT.is_dir():
        print(f"Loi: khong thay thu muc {NLU_ROOT}. Giai nen datasets.zip vao dung vi tri nay.")
        return

    catalog = load_intent_catalog(NLU_ROOT / "intent-catalog.yaml")
    rules = load_normalization_rules(NLU_ROOT / "normalization.yaml")
    protected_phrases = load_protected_phrases(NLU_ROOT / "protected-phrases.yaml")
    utterances = load_utterances(NLU_ROOT / "utterances")
    test_cases = load_test_cases(TESTS_ROOT) if TESTS_ROOT.is_dir() else {}

    print(f"Da doc: {len(catalog.get('intents', []))} intent, {len(rules)} rule, "
          f"{len(protected_phrases)} protected phrase, "
          f"{len(utterances)} utterance, {sum(len(v) for v in test_cases.values())} test case.\n")

    errors: list[str] = []
    errors += validate_intent_catalog(catalog)

    valid_intents = {it["intent"] for it in catalog.get("intents", [])}
    errors += validate_utterances(utterances, valid_intents)
    errors += validate_normalization_rules(rules)

    # QUAN TRONG: chi kiem tra leakage cho DUNG suite "intent-routing-tests"
    # (test phan loai intent) - KHONG ap dung cho "normalization-tests" vi
    # ban chat khac han (test ham normalize(), duong nhien trung cau voi
    # utterance vi ca 2 cung lay mau cach viet thong tuc - khong phai leak
    # thuc su, xem ISSUES-VI.md).
    if "intent-routing-tests" in test_cases:
        errors += validate_no_train_test_leakage(
            utterances, {"intent-routing-tests": test_cases["intent-routing-tests"]}
        )

    if errors:
        print(f"CO {len(errors)} LOI VALIDATION:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("VALIDATION: 0 loi - du lieu sach.")

    print("\n=== Demo normalize() ===")
    samples = [
        "shop oi hũ này bn z",
        "gia nhiu shop oi",
        "sp con ko",
        "3S Coffee gia sao",
        "robanme la ai vay",
    ]
    for s in samples:
        print(f"  {s!r} -> {normalize(s, rules, protected_phrases)!r}")


if __name__ == "__main__":
    main()
