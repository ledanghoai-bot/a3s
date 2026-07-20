"""CLI test nhanh Intent/Risk Router (Knowledge Base V2, M3 Bat 3) - KHONG qua
bot/orchestrator, chi goi thang kb_router.classify().

Cach dung:
    docker compose exec api python scripts/kb_router_test.py "cau hoi cua ban"

    docker compose exec api python scripts/kb_router_test.py --suite
        -> chay bo cau hoi mau co san (co dau + khong dau), in ket qua tung dong
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.kb_router import classify  # noqa: E402

_SAMPLE_QUERIES = [
    "Chào shop",
    "hu 100g gia bao nhieu",
    "còn hàng không em",
    "cho anh đặt 5 hũ",
    "sản phẩm này khiến anh bị dị ứng",
    "shop giao sai hàng cho tôi rồi",
    "pha thế nào vậy em",
    "vị có đắng không",
    "khác gì hũ 100g",
    "3S Coffee là gì vậy",
    "em tư vấn giúp anh loại nào hợp",
    "bạn có bán sỉ không",
    "asdkjaskdj random text",
]


def _print_route(query: str) -> None:
    r = classify(query)
    print(f"Cau hoi: {query!r}")
    print(f"  intent={r.intent}  route={r.route}  "
          f"requires_handoff={r.requires_handoff}  requires_tool={r.requires_tool}")
    print(f"  allowed_domains={r.allowed_domains}")
    print(f"  ly do: {r.reason}")
    print()


def main() -> None:
    if len(sys.argv) < 2:
        print("Dung: python scripts/kb_router_test.py \"cau hoi\"")
        print("  hoac: python scripts/kb_router_test.py --suite")
        return

    if sys.argv[1] == "--suite":
        for q in _SAMPLE_QUERIES:
            _print_route(q)
        return

    query = " ".join(sys.argv[1:])
    _print_route(query)


if __name__ == "__main__":
    main()
