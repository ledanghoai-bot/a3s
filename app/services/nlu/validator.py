"""Validator cho NLU dataset (Bat A) - dung dung "Source-of-Truth Rules" +
"Prohibited Practices" trong datasets/nlu/README.md (khong tu bia rule moi):
- Intent chi duoc dinh nghia tai intent-catalog.yaml.
- 1 utterance 1 ID duy nhat.
- Test utterances phai duoc giu NGOAI tap train/reference (khong duoc leak).

Da test ca 4 kiem tra nay voi du lieu THAT team Knowledge gui (300 utterance,
30 intent, 60 test case) truoc khi dua vao code chinh thuc - ket qua sach
hoan toan (0 loi ca 4 muc), xem ISSUES-VI.md.
"""


def validate_intent_catalog(catalog: dict) -> list[str]:
    """Kiem tra intent-catalog.yaml: thieu truong bat buoc, intent trung ten."""
    errors: list[str] = []
    intents = catalog.get("intents", [])
    seen: set[str] = set()
    for it in intents:
        name = it.get("intent")
        if not name:
            errors.append(f"Co intent thieu truong 'intent' (ten): {it}")
            continue
        if name in seen:
            errors.append(f"Intent trung ten: '{name}'")
        seen.add(name)
        if "route" not in it:
            errors.append(f"Intent '{name}' thieu truong 'route'")
        if "priority" not in it:
            errors.append(f"Intent '{name}' thieu truong 'priority'")
    return errors


def validate_utterances(utterances: list[dict], valid_intents: set[str]) -> list[str]:
    """Kiem tra utterances/*.yaml: ID trung, tham chieu intent khong ton tai,
    text trung nhau (co the la duplicate vo tinh)."""
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_texts: dict[str, str] = {}

    for u in utterances:
        uid = u.get("id")
        source = u.get("_source_file", "?")
        if not uid:
            errors.append(f"[{source}] Utterance thieu 'id': {u.get('text', '?')!r}")
            continue
        if uid in seen_ids:
            errors.append(f"[{source}] Utterance ID trung: '{uid}'")
        seen_ids.add(uid)

        intent = u.get("intent")
        if intent not in valid_intents:
            errors.append(
                f"[{source}] Utterance '{uid}' tham chieu intent khong ton tai trong "
                f"intent-catalog.yaml: '{intent}'"
            )

        text = (u.get("text") or "").strip().lower()
        if text:
            if text in seen_texts:
                errors.append(
                    f"[{source}] Utterance '{uid}' co text TRUNG voi '{seen_texts[text]}': {text!r}"
                )
            else:
                seen_texts[text] = uid

    return errors


def validate_no_train_test_leakage(
    utterances: list[dict], test_cases: dict[str, list[dict]]
) -> list[str]:
    """Kiem tra text trong tests/ KHONG duoc trung voi text trong
    utterances/ (train/validation) - dung theo yeu cau "Test utterances phai
    duoc giu ngoai tap train/reference" trong README.md."""
    errors: list[str] = []
    train_texts = {(u.get("text") or "").strip().lower() for u in utterances}

    for suite_name, tests in test_cases.items():
        for t in tests:
            input_text = (t.get("input") or "").strip().lower()
            if input_text and input_text in train_texts:
                errors.append(
                    f"[{suite_name}] Test '{t.get('id')}' co input TRUNG voi 1 utterance "
                    f"trong tap train - vi pham train/test leakage: {input_text!r}"
                )

    return errors


def validate_normalization_rules(rules: list[dict]) -> list[str]:
    """Kiem tra normalization.yaml: ID trung, thieu truong bat buoc, match
    khong hop le."""
    errors: list[str] = []
    seen_ids: set[str] = set()
    for r in rules:
        rid = r.get("id")
        if not rid:
            errors.append(f"Rule thieu 'id': {r}")
            continue
        if rid in seen_ids:
            errors.append(f"Rule ID trung: '{rid}'")
        seen_ids.add(rid)
        if r.get("match") not in ("phrase", "token"):
            errors.append(f"Rule '{rid}' co 'match' khong hop le: {r.get('match')!r}")
        if not r.get("source") or not r.get("target"):
            errors.append(f"Rule '{rid}' thieu 'source' hoac 'target'")
    return errors
