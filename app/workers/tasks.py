"""Worker arq: xu ly tin nhan bat dong bo sau khi webhook da tra 200."""

from arq.connections import RedisSettings

from app.config import settings
from app.services.messenger import send_text
from app.services.orchestrator import handle_message


async def process_message(ctx: dict, event: dict) -> None:
    sender_id = (event.get("sender") or {}).get("id")
    text = (event.get("message") or {}).get("text")
    if not sender_id or not text:
        return  # bo qua su kien khong phai tin nhan van ban (delivery, read...)
    reply = await handle_message(sender_id, text)
    await send_text(sender_id, reply)


class WorkerSettings:
    functions = [process_message]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 20
