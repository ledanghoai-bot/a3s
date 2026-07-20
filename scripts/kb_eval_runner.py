"""P1 Smoke Suite runner (Knowledge Base V2, M6) - doc test case tu
tests/kb_eval/*.yaml, chay that qua M2 (search_kb) + M3 (classify) + M5
(pre_generation_guardrails), in bao cao pass/fail theo severity + xac dinh
"Release Gate" (dung EV-001: block release neu con S0/S1 mo).

CHUA test duoc: response.must_convey/must_not_claim, next_best_action - can
LLM sinh cau tra loi that (ngoai pham vi M1-M5 hien tai, xem ghi chu trong
tests/kb_eval/smoke.yaml).

Cach dung:
    docker compose exec api python scripts/kb_eval_runner.py
    docker compose exec api python scripts/kb_eval_runner.py --suite routing
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from app.services.kb_retrieval import search_kb  # noqa: E402
from app.services.kb_router import classify  # noqa: E402
from app.services.kb_runtime import pre_generation_guardrails  # noqa: E402

TESTS_DIR = Path(__file__).resolve().parent.parent / "tests" / "kb_eval"


def load_test_cases(suite_filter: str | None = None) -> list[dict]:
    cases = []
    for f in sorted(TESTS_DIR.glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or []
        for case in data:
            if suite_filter and suite_filter not in case.get("suite", []):
                continue
            cases.append(case)
    return cases


async def run_case(case: dict) -> tuple[bool, list[str]]:
    """Chay 1 test case, tra ve (passed, details) - details la danh sach ly
    do fail (rong neu pass)."""
    message = case["input"]["message"]
    expected = case["expected"]
    details: list[str] = []
    passed = True

    route = classify(message)

    if "route" in expected and route.route != expected["route"]:
        passed = False
        details.append(f"route: ky vong '{expected['route']}', thuc te '{route.route}'")

    if "requires_handoff" in expected and route.requires_handoff != expected["requires_handoff"]:
        passed = False
        details.append(
            f"requires_handoff: ky vong {expected['requires_handoff']}, thuc te {route.requires_handoff}"
        )

    if expected.get("static_answer_allowed") is False and route.route == "knowledge":
        passed = False
        details.append(
            "static_answer_allowed=false nhung route lai la 'knowledge' "
            "(dang lay Knowledge tinh thay vi bat buoc qua Tool)"
        )

    retrieved_units: list[dict] = []
    if route.route == "knowledge":
        retrieved_units = await search_kb(message, top_k=5, allowed_domains=route.allowed_domains or None)

        source_ids = expected.get("source_ids", {})
        must_include = source_ids.get("must_include", [])
        must_not_include = source_ids.get("must_not_include", [])
        retrieved_asset_ids = {u["asset_id"] for u in retrieved_units}

        if must_include and not any(sid in retrieved_asset_ids for sid in must_include):
            passed = False
            details.append(
                f"source_ids.must_include: khong thay asset nao trong {must_include} "
                f"(thuc te lay duoc: {sorted(retrieved_asset_ids)})"
            )

        for sid in must_not_include:
            if sid in retrieved_asset_ids:
                passed = False
                details.append(f"source_ids.must_not_include: '{sid}' khong duoc co nhung lai xuat hien")

    guardrail_events = pre_generation_guardrails(route, retrieved_units)
    blocking = [e for e in guardrail_events if e.severity == "block"]
    if blocking:
        passed = False
        for e in blocking:
            details.append(f"guardrail block: {e.rule_id} - {e.detail}")

    return passed, details


async def main() -> None:
    parser = argparse.ArgumentParser(description="P1 Smoke Suite runner (Knowledge Base V2, M6)")
    parser.add_argument("--suite", default=None, help="Loc theo 1 suite (vd: smoke, routing, retrieval, safety)")
    args = parser.parse_args()

    cases = load_test_cases(args.suite)
    if not cases:
        print(f"Khong tim thay test case nao (suite filter={args.suite!r}).")
        return

    results = []
    for case in cases:
        passed, details = await run_case(case)
        results.append((case, passed, details))
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {case['id']} - {case['title']}")
        if not passed:
            for d in details:
                print(f"    - {d}")

    print()
    total = len(results)
    passed_count = sum(1 for _, p, _ in results if p)
    failed = [(c, d) for c, p, d in results if not p]

    print(f"=== KET QUA: {passed_count}/{total} PASS ===")

    if failed:
        print("\n=== RELEASE GATE (theo EV-001) ===")
        s0_s1 = [c for c, _ in failed if c.get("severity_if_failed") in ("S0", "S1")]
        if s0_s1:
            print(f"BLOCK RELEASE - {len(s0_s1)} test fail voi severity S0/S1:")
            for c in s0_s1:
                print(f"   - {c['id']} ({c['severity_if_failed']}): {c['title']}")
        else:
            print("Co test fail nhung chi o muc S2/S3 - co the release voi ngoai le da duoc PO/QA duyet.")
    else:
        print("\nRELEASE GATE: PASS - khong co test nao fail.")


if __name__ == "__main__":
    asyncio.run(main())
