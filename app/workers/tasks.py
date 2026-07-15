"""Worker arq: xu ly tin nhan bat dong bo sau khi webhook da tra 200."""

from arq.connections import RedisSettings

from app.config import settings
from app.services.handoff import is_bot_paused
from app.services.messenger import send_text
from app.services.orchestrator import handle_message


async def process_message(ctx: dict, event: dict) -> None:
    message = event.get("message") or {}

    # Bo qua echo cua chinh Page (tin nhan Page vua gui se duoc Meta echo nguoc
    # lai qua webhook neu subscribe field message_echoes) - tranh bot tu tra loi
    # chinh minh. (Fix ke thu tu #2, tien tay sua vi dang dong file nay cho #7.)
    if message.get("is_echo"):
        return

    sender_id = (event.get("sender") or {}).get("id")
    text = message.get("text")
    if not sender_id or not text:
        return  # bo qua su kien khong phai tin nhan van ban (delivery, read...)

    # Human handoff (issue #7): hoi thoai dang bot_paused (nhan vien da tiep
    # quan qua escalate_to_human) -> bot im lang, KHONG tu dong tra loi chong
    # len nhan vien.
    if await is_bot_paused(sender_id):
        print(f"[worker] Bot dang paused cho {sender_id}, bo qua (nhan vien dang xu ly).")
        return

    reply = await handle_message(sender_id, text)
    await send_text(sender_id, reply)


class WorkerSettings:
    functions = [process_message]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 20
