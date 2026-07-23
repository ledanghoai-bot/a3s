"""CLI test Entity Extraction (NLU layer, Buoc 6) - kiem tra extract_entities,
trong tam la _extract_location sau ban va 18/7 (khop dia danh khong dau,
vd "Ca Mau" -> "cà mau").

Cach dung:
    docker compose exec api python scripts/nlu_entity_test.py "cau hoi cua ban"
    docker compose exec api python scripts/nlu_entity_test.py --eval
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.nlu.entity_extraction import extract_entities  # noqa: E402

# Case that (khong phai gia dinh) - moi dia danh test CA HAI chieu co dau/
# khong dau theo quy tac tieng Viet cua du an (CLAUDE.md muc 6).
_EVAL_CASES = [
    # (input, {entity: expected_value})
    ("ship về Cà Mau giúp em", {"location": "cà mau"}),
    ("ship ve Ca Mau giup em", {"location": "cà mau"}),
    ("giao hàng đi Đà Nẵng", {"location": "đà nẵng"}),
    ("giao hang di da nang", {"location": "đà nẵng"}),
    ("ship về Huế được không", {"location": "huế"}),
    ("ship ve hue duoc khong", {"location": "huế"}),
    ("mình ở Buôn Ma Thuột", {"location": "buôn ma thuột"}),
    ("minh o buon ma thuot", {"location": "buôn ma thuột"}),
    # Ranh gioi tu - khong duoc khop substring dinh lien
    ("toi thich camau khong", {"location": None}),
    # Cac entity khac van chay binh thuong (khong bi vo sau ban va)
    ("cho mình 2 hũ 100g", {"quantity": "2", "unit": "hũ", "product": "100g"}),
    ("đơn A123 chuyển khoản", {"order_id": "A123", "payment_method": "chuyển khoản"}),
]


def main() -> None:
    if len(sys.argv) < 2:
        print('Dung: python scripts/nlu_entity_test.py "cau hoi"')
        print("  hoac: python scripts/nlu_entity_test.py --eval")
        return

    if sys.argv[1] == "--eval":
        fail = 0
        for text, expected in _EVAL_CASES:
            got = extract_entities(text)
            for name, want in expected.items():
                actual = got[name].value if name in got else None
                ok = actual == want
                if not ok:
                    fail += 1
                print(f"  {'PASS' if ok else 'FAIL'} | '{text}' -> {name}={actual!r} (ky vong {want!r})")
        total = sum(len(e) for _, e in _EVAL_CASES)
        print(f"\nKET QUA: {total - fail}/{total} PASS")
        sys.exit(0 if fail == 0 else 1)

    entities = extract_entities(sys.argv[1])
    if not entities:
        print("(khong tim thay entity nao)")
        return
    for name, ent in entities.items():
        print(f"  {name}: {ent.value!r} (source={ent.source})")


if __name__ == "__main__":
    main()
