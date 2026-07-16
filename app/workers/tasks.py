"""Worker arq: xu ly tin nhan bat dong bo sau khi webhook da tra 200."""

from arq.connections import RedisSettings

from app.config import settings
from app.services import conversation_log
from app.services.handoff import is_bot_paused
from app.services.messenger import send_text
from app.services.orchestrator import handle_message


async def process_message(ctx: dict, event: dict) -> None:
    message = event.get("message") or {}
    text = message.get("text")
    if not text:
        return  # bo qua su kien khong phai tin nhan van ban (delivery, read...)

    is_echo = message.get("is_echo", False)

    if is_echo:
        # Echo cua 1 tin nhan GUI DEN khach - trong echo, "sender" la chinh Page,
        # "recipient" moi la PSID khach that (nguoc voi tin nhan thuong).
        psid = (event.get("recipient") or {}).get("id")
        if not psid:
            return

        paused = await is_bot_paused(psid)
        if not paused:
            # Khong paused -> day la echo cua chinh bot vua tu gui qua send_text()
            # (da duoc orchestrator log roi voi role='bot'). Bo qua, tranh trung/loop.
            return

        # DANG paused ma van co echo -> bot chac chan KHONG tu gui gi trong luc
        # nay (worker return som, khong goi handle_message/send_text) => day
        # chinh la tin nhan THAT cua nhan vien/sep tu tay reply qua Messenger
        # Inbox. "Timetrap": chinh cai cua so bot_paused=TRUE la dieu kien loc,
        # khong can them cot timestamp rieng.
        conversation_id = await conversation_log.ensure_conversation(psid)
        await conversation_log.log_message(conversation_id, "agent", text)
        print(f"[worker] Da ghi tin nhan that cua nhan vien cho {psid} (luc dang paused).")
        return

    # Tin nhan thuong tu khach
    sender_id = (event.get("sender") or {}).get("id")
    if not sender_id:
        return

    # Human handoff (issue #7): hoi thoai dang bot_paused (nhan vien da tiep
    # quan qua escalate_to_human) -> bot im lang, KHONG tu dong tra loi chong
    # len nhan vien. NHUNG van ghi log tin khach de khong mat doan hoi thoai
    # trong dashboard (issue #8 - nang cap hien thi day du luc handover).
    if await is_bot_paused(sender_id):
        conversation_id = await conversation_log.ensure_conversation(sender_id)
        await conversation_log.log_message(conversation_id, "customer", text)
        print(f"[worker] Bot dang paused cho {sender_id}, chi log, khong tra loi (nhan vien dang xu ly).")
        return

    reply = await handle_message(sender_id, text)
    await send_text(sender_id, reply)


class WorkerSettings:
    functions = [process_message]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 20
