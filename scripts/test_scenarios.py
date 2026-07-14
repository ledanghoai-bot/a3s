"""
Chay bo kich ban tu data/knowledge/scenarios_20.md truc tiep qua orchestrator
(khong can webhook/fanpage that).

Vi tri file (dung logic voi project):
    alpha3s/
    ├── app/
    ├── data/knowledge/scenarios_20.md   <- file kich ban
    └── scripts/test_scenarios.py        <- file nay

Cach chay (xem huong dan chi tiet o cuoi file / tin nhan kem theo):
    docker compose exec api python scripts/test_scenarios.py
    docker compose exec api python scripts/test_scenarios.py --file data/knowledge/scenarios_20.md --out results.md

Yeu cau: Redis + Postgres dang chay (vi handle_message() doc/ghi ca hai), va da chay
`docker compose exec api python scripts/ingest.py` it nhat 1 lan de co du lieu RAG.
"""

import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

# Script nam trong scripts/, app/ nam o project root -> can .parents[1] (giong scripts/ingest.py)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.orchestrator import handle_message  # noqa: E402

# Duong dan mac dinh toi file kich ban, tinh tuyet doi tu project root de chay dung
# du cwd la project root hay thu muc scripts/
DEFAULT_SCENARIOS_FILE = PROJECT_ROOT / "data" / "knowledge" / "scenarios_20.md"
DEFAULT_OUT_FILE = PROJECT_ROOT / "results.md"

SCENARIO_RE = re.compile(
    r"^#\s*Scenario\s*(\d+)\s*—\s*(.+?)\s*$", re.MULTILINE
)


def parse_scenarios(md_text: str) -> list[dict]:
    """Tach file markdown thanh danh sach kich ban: {id, title, group, criteria, turns}."""
    # Cat theo tung khoi bat dau bang "# Scenario"
    blocks = re.split(r"(?=^# Scenario\s)", md_text, flags=re.MULTILINE)
    scenarios = []
    for block in blocks:
        m = SCENARIO_RE.search(block)
        if not m:
            continue  # bo qua phan header/comment truoc kich ban dau tien
        scenario_id, title = m.group(1), m.group(2)

        group_m = re.search(r"^Nh[óo]m:\s*(.+)$", block, re.MULTILINE)
        criteria_m = re.search(r"^Ti[êe]u ch[íi] k[ỳy] v[ọo]ng:\s*(.+)$", block, re.MULTILINE)
        turns = re.findall(r"^-\s*Kh[áa]ch:\s*(.+)$", block, re.MULTILINE)

        if not turns:
            print(f"[canh bao] Scenario {scenario_id} khong co luot 'Khach:' nao, bo qua.")
            continue

        scenarios.append(
            {
                "id": scenario_id,
                "title": title,
                "group": group_m.group(1).strip() if group_m else "",
                "criteria": criteria_m.group(1).strip() if criteria_m else "",
                "turns": [t.strip() for t in turns],
            }
        )
    return scenarios


async def run_scenarios(scenarios: list[dict]) -> list[dict]:
    """Chay tung kich ban qua handle_message(), tra ve ket qua kem cau tra loi cua bot."""
    results = []
    for sc in scenarios:
        sender_id = f"test_scn_{sc['id']}"
        print(f"\n=== Scenario {sc['id']} — {sc['title']} ===")
        transcript = []
        for turn in sc["turns"]:
            reply = await handle_message(sender_id, turn)
            print(f"Khach: {turn}")
            print(f"Bot:   {reply}\n")
            transcript.append({"user": turn, "bot": reply})
        results.append({**sc, "transcript": transcript, "sender_id": sender_id})
    return results


def write_report(results: list[dict], out_path: Path) -> None:
    """Ghi ket qua ra file markdown, kem o trong de cham Pass/Fail."""
    lines = [
        f"# Ket qua test scenarios — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"Tong so kich ban: {len(results)}",
        "",
    ]
    for r in results:
        lines.append(f"## Scenario {r['id']} — {r['title']}")
        if r["group"]:
            lines.append(f"**Nhom:** {r['group']}")
        if r["criteria"]:
            lines.append(f"**Tieu chi ky vong:** {r['criteria']}")
        lines.append("")
        for t in r["transcript"]:
            lines.append(f"- **Khach:** {t['user']}")
            lines.append(f"  **Bot:** {t['bot']}")
        lines.append("")
        lines.append("**Ket qua cham:** [ ] Pass  [ ] Fail — Ghi chu: ___________")
        lines.append("")
        lines.append("---")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nDa ghi ket qua vao {out_path}")


async def cleanup_redis(results: list[dict]) -> None:
    """Xoa lich su chat test khoi Redis de lan chay sau khong bi dinh kich ban cu."""
    import redis.asyncio as aioredis
    from app.config import settings

    redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        for r in results:
            await redis.delete(f"chat:{r['sender_id']}")
    finally:
        await redis.aclose()


def main():
    parser = argparse.ArgumentParser(description="Chay bo kich ban tu file markdown")
    parser.add_argument("--file", default=str(DEFAULT_SCENARIOS_FILE), help="File markdown chua kich ban")
    parser.add_argument("--out", default=str(DEFAULT_OUT_FILE), help="File markdown ghi ket qua")
    parser.add_argument(
        "--keep-history", action="store_true",
        help="Khong xoa lich su Redis sau khi chay (mac dinh se xoa)",
    )
    args = parser.parse_args()

    md_text = Path(args.file).read_text(encoding="utf-8")
    scenarios = parse_scenarios(md_text)
    if not scenarios:
        print(f"Khong tim thay kich ban nao trong {args.file}. Kiem tra lai format.")
        return

    print(f"Da doc {len(scenarios)} kich ban tu {args.file}.")
    results = asyncio.run(run_scenarios(scenarios))
    write_report(results, Path(args.out))

    if not args.keep_history:
        asyncio.run(cleanup_redis(results))
        print("Da xoa lich su chat test khoi Redis.")


if __name__ == "__main__":
    main()
