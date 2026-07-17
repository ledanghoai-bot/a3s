"""Dev utility: xoa lich su hoi thoai dang luu trong Redis (chi Redis, KHONG
dung toi Postgres/messages - lich su lau dai tren dashboard van giu nguyen).

Van de thuc te hay gap trong giai doan dev (17/7): sua xong bug hanh vi bot
(system_prompt.md, orchestrator.py, tools.py...) roi test lai DUNG 1 cuoc chat
cu - bot van "trung thanh" voi cau tra loi SAI ma chinh no da tung noi truoc
do, vi turn_messages luon ghep them history cu tu Redis (TTL 24h) sau system
prompt moi. Xoa key Redis tuong ung la cach nhanh nhat de test sach, khong
can doi 24h TTL tu het.

Cach dung (chay trong container api, da co san REDIS_URL qua .env):
    docker compose exec api python scripts/clear_chat_history.py
        -> xoa TOAN BO lich su chat dang luu (moi key "chat:*")

    docker compose exec api python scripts/clear_chat_history.py tg:5913051767
        -> chi xoa DUNG 1 sender_id cu the (khong can go prefix "chat:",
           script tu them vao). Dung cho PSID Facebook thi go nguyen PSID.

    docker compose exec api python scripts/clear_chat_history.py --list
        -> chi liet ke cac key dang co, KHONG xoa gi ca (dung de tim dung
           sender_id truoc khi xoa 1 cuoc cu the)

CANH BAO: chi dung script nay o moi truong DEV/TEST. Tren production that,
xoa lich su Redis se lam bot "quen" ngu canh 24h gan nhat cua khach that dang
chat do - KHONG chay script nay tren production khi he thong da co khach that.
"""

import asyncio
import sys
from pathlib import Path

import redis.asyncio as aioredis

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402


async def main() -> None:
    redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        args = sys.argv[1:]

        if args and args[0] == "--list":
            keys = await redis.keys("chat:*")
            if not keys:
                print("Hien khong co lich su chat nao dang luu trong Redis.")
                return
            print(f"Dang co {len(keys)} cuoc hoi thoai luu trong Redis:")
            for k in sorted(keys):
                ttl = await redis.ttl(k)
                print(f"  {k}  (con han {ttl}s)")
            return

        if args:
            sender_id = args[0]
            key = sender_id if sender_id.startswith("chat:") else f"chat:{sender_id}"
            deleted = await redis.delete(key)
            if deleted:
                print(f"Da xoa lich su chat cho: {key}")
            else:
                print(f"Khong tim thay key nao ten '{key}' (co the da het TTL hoac go sai sender_id).")
            return

        keys = await redis.keys("chat:*")
        if not keys:
            print("Khong co lich su chat nao dang luu - khong can xoa gi ca.")
            return
        deleted = await redis.delete(*keys)
        print(f"Da xoa TOAN BO {deleted} cuoc hoi thoai dang luu trong Redis:")
        for k in sorted(keys):
            print(f"  {k}")
        print("\nLuu y: day chi xoa cache Redis (ngu canh cho LLM) - lich su tin nhan")
        print("lau dai tren dashboard (bang messages trong Postgres) KHONG bi anh huong.")
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
