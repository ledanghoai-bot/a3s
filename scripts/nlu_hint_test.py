"""CLI test `app/services/nlu_hint.py` - ham cau noi giua Lop NLU (#12) va
orchestrator.py. Cho phep kiem tra hint sinh ra TRUOC KHI bat
ENABLE_NLU_ROUTER=true that trong bot production.

Cach dung:
    docker compose exec api python scripts/nlu_hint_test.py "cau hoi cua ban"
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.nlu_hint import get_nlu_hint  # noqa: E402


async def main() -> None:
    if len(sys.argv) < 2:
        print('Dung: python scripts/nlu_hint_test.py "cau hoi"')
        return

    query = " ".join(sys.argv[1:])
    print(f"Dang goi get_nlu_hint('{query}')...")
    print("(lan dau se cham hon do phai tinh embedding cho utterance library)\n")

    hint = await get_nlu_hint(query)

    if hint:
        print("=== HINT SE DUOC BOM VAO SYSTEM PROMPT ===")
        print(hint)
    else:
        print("=== KHONG CO HINT (rong) ===")
        print("Ly do co the: NLU chua load duoc du lieu, HOAC Router khong du")
        print("tin cay (action != 'accept') cho cau nay - day la hanh vi DUNG,")
        print("khong phai loi (chu dinh khong bom hint mo ho vao prompt).")


if __name__ == "__main__":
    asyncio.run(main())
