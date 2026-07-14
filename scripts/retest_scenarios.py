"""
Chay lai 1 tap con scenario (mac dinh: 10 va 14) tu data/knowledge/scenarios_20.md,
dung de retest nhanh sau khi sua system_prompt.md, khong can chay lai ca 20 kich ban.

Tai su dung toan bo logic parse/run/report/cleanup tu scripts/test_scenarios.py,
chi them buoc loc theo id truoc khi chay.

Vi tri file (dung logic voi project):
    alpha3s/
    ├── app/
    ├── data/knowledge/scenarios_20.md
    └── scripts/
        ├── test_scenarios.py
        └── retest_scenarios.py   <- file nay

Cach chay:
    docker compose exec api python scripts/retest_scenarios.py
    docker compose exec api python scripts/retest_scenarios.py --ids 10,14
    docker compose exec api python scripts/retest_scenarios.py --ids 10,13,14 --out results_retest.md
"""

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_scenarios import (  # noqa: E402
    cleanup_redis,
    parse_scenarios,
    run_scenarios,
    write_report,
)

DEFAULT_SCENARIOS_FILE = PROJECT_ROOT / "data" / "knowledge" / "scenarios_20.md"
DEFAULT_OUT_FILE = PROJECT_ROOT / "results_retest.md"
DEFAULT_IDS = ["10", "14"]


def main():
    parser = argparse.ArgumentParser(description="Retest 1 tap con scenario theo id")
    parser.add_argument("--file", default=str(DEFAULT_SCENARIOS_FILE), help="File markdown chua kich ban")
    parser.add_argument("--out", default=str(DEFAULT_OUT_FILE), help="File markdown ghi ket qua")
    parser.add_argument(
        "--ids", default=",".join(DEFAULT_IDS),
        help="Danh sach id scenario can chay, cach nhau boi dau phay, vd: 10,14",
    )
    parser.add_argument(
        "--keep-history", action="store_true",
        help="Khong xoa lich su Redis sau khi chay (mac dinh se xoa)",
    )
    args = parser.parse_args()

    # Chuan hoa id ve dang 2 chu so ("10" -> "10", "5" -> "05") de khop dung
    # format "# Scenario 05 — ..." trong scenarios_20.md
    wanted_ids = {i.strip().zfill(2) for i in args.ids.split(",") if i.strip()}

    md_text = Path(args.file).read_text(encoding="utf-8")
    all_scenarios = parse_scenarios(md_text)
    scenarios = [sc for sc in all_scenarios if sc["id"] in wanted_ids]

    found_ids = {sc["id"] for sc in scenarios}
    missing = wanted_ids - found_ids
    if missing:
        print(f"[canh bao] Khong tim thay scenario id: {', '.join(sorted(missing))}")
    if not scenarios:
        print(f"Khong co scenario nao khop voi --ids {args.ids} trong {args.file}.")
        return

    print(f"Se chay lai {len(scenarios)} scenario: {', '.join(sc['id'] for sc in scenarios)}")
    results = asyncio.run(run_scenarios(scenarios))
    write_report(results, Path(args.out))

    if not args.keep_history:
        asyncio.run(cleanup_redis(results))
        print("Da xoa lich su chat test khoi Redis.")


if __name__ == "__main__":
    main()
