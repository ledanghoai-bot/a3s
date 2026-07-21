"""Loader cho NLU dataset (Alpha3S NLU layer - Bat A).

Doc dung cau truc canonical trong depository team Knowledge gui
(datasets/nlu/, xem NLU-INTEGRATION-GUIDE.md muc 2 + datasets/nlu/README.md)
- khong tu bia schema khac.
"""

from pathlib import Path

import yaml


def load_intent_catalog(path: Path) -> dict:
    """Doc intent-catalog.yaml - tra ve nguyen dict (defaults, route_types,
    entities, intents[])."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_normalization_rules(path: Path) -> list[dict]:
    """Doc normalization.yaml - tra ve list rule {id, source, target, match}."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("rules", [])


def load_protected_phrases(path: Path) -> list[dict]:
    """Doc protected-phrases.yaml (file rieng tu team Knowledge, 18/7) -
    tra ve list {id, canonical, variants, category, match,
    case_sensitive, restore_before_output}. Neu file khong ton tai (chua
    giai nen/dat dung cho), tra ve list rong - CALLER (script) tu quyet
    dinh co fallback ve DEFAULT_PROTECTED_PHRASES trong normalizer.py hay
    khong bang cach truyen None thay vi [] cho tham so protected_phrases."""
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("protected_phrases", [])


def load_routing_rules(path: Path) -> dict:
    """Doc routing-rules.yaml (file rieng tu team Knowledge, 18/7) - tra ve
    nguyen dict (execution_order, vocative_prefixes, policies, rules[],
    margin_policy). Tra ve dict rong neu file khong ton tai."""
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_utterances(dir_path: Path) -> list[dict]:
    """Doc toan bo utterances/*.yaml, gop thanh 1 list. Them `_source_file`
    vao moi utterance de truy vet khi bao loi validation."""
    utterances = []
    for f in sorted(dir_path.glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        for u in data.get("utterances", []):
            u["_source_file"] = f.name
            utterances.append(u)
    return utterances


def load_test_cases(dir_path: Path) -> dict[str, list[dict]]:
    """Doc toan bo tests/*.yaml (intent-routing-tests.yaml,
    normalization-tests.yaml...) - tra ve {ten_bo_test: [test, ...]}.

    v1.1: neu 1 file co truong `acceptance.combine_with: <ten_file>.yaml`
    (vd `intent-routing-tests-v1.1-additions.yaml` tro ve
    `intent-routing-tests.yaml`), GOP test cua file do vao DUNG key cua file
    duoc tro toi, thay vi tao 1 bo test rieng - dung theo cach team
    Knowledge cong bo file bo sung 90 test moi (tong 150 test held-out).
    """
    result: dict[str, list[dict]] = {}
    for f in sorted(dir_path.glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        tests = data.get("tests", [])
        combine_with = data.get("acceptance", {}).get("combine_with")
        key = combine_with.rsplit(".", 1)[0] if combine_with else f.stem
        result.setdefault(key, []).extend(tests)
    return result
