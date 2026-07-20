"""CLI test nhanh 1 cau hoi qua Knowledge Base V2 (M2 retrieval) - KHONG qua
bot/orchestrator, chi goi thang search_kb() de xem ket qua + provenance.

Cach dung:
    docker compose exec api python scripts/kb_search_test.py "cau hoi cua ban"
    docker compose exec api python scripts/kb_search_test.py "cau hoi" --top-k 3
    docker compose exec api python scripts/kb_search_test.py "cau hoi" --include-draft
    docker compose exec api python scripts/kb_search_test.py "cau hoi" --domains faq,product
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.kb_retrieval import search_kb  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test retrieval Knowledge Base V2")
    parser.add_argument("query", help="Cau hoi can test")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--include-draft", action="store_true")
    parser.add_argument("--domains", default=None, help="vd: faq,product (cach nhau boi dau phay)")
    args = parser.parse_args()

    allowed_domains = args.domains.split(",") if args.domains else None

    results = await search_kb(
        args.query,
        top_k=args.top_k,
        allowed_domains=allowed_domains,
        include_draft=args.include_draft,
    )

    if not results:
        print("Khong co ket qua nao. Kiem tra da chay kb_ingest.py + kich hoat")
        print("kb_config['active_index_version'] chua (xem huong dan cuoi kb_ingest.py).")
        return

    print(f"Cau hoi: {args.query!r}\n")
    for i, r in enumerate(results, start=1):
        print(f"--- #{i} (score={r['score']}) ---")
        print(f"KU: {r['ku_id']}  |  Asset: {r['asset_id']} ({r['asset_title']})")
        print(f"Domain: {r['domain']}  |  Status: {r['status']}  |  Priority: {r['priority']}")
        print(f"Source: {r['source_path']}")
        print(f"Heading: {r['heading']}")
        print(f"Content:\n{r['content'][:400]}{'...' if len(r['content']) > 400 else ''}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
