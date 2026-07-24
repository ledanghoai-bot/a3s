"""Worker arq: xu ly tin nhan bat dong bo sau khi webhook da tra 200.

Issue #9 (Bat 1): them dedupe theo `mid` (Meta co the gui trung webhook event)
va retry + dead-letter (khi Send API/LLM loi lien tuc).
"""

import json

from arq.connections import RedisSettings

from app.config import settings
from app.services import conversation_log
from app.services.handoff import is_bot_paused
from app.services.messenger import send_text
from app.services.orchestrator import handle_message

DEDUP_TTL_SECONDS = 24 * 60 * 60  # 24h - du lon hon cua so retry cua Meta
DEAD_LETTER_KEY = "dead_letter:messages"


async def process_message(ctx: dict, event: dict) -> None:
    """Wrapper ben ngoai: dedupe + bat exception de ghi dead-letter o lan thu
    cuoi cung truoc khi de arq bao that bai that su (van raise lai, KHONG nuot
    loi - arq can biet job that bai de tinh dung so lan retry/metric)."""
    message = event.get("message") or {}
    mid = message.get("mid")
    if mid:
        redis = ctx["redis"]
        # SET ... NX EX: chi thanh cong (tra ve True) neu KEY CHUA TUNG TON TAI -
        # tuc la lan dau gap mid nay. Meta gui trung se bi chan ngay o day,
        # tranh tao 2 cau tra loi cho cung 1 tin nhan khach.
        is_first_time = await redis.set(f"dedup:mid:{mid}", "1", nx=True, ex=DEDUP_TTL_SECONDS)
        if not is_first_time:
            print(f"[worker] Bo qua tin nhan trung (mid={mid} da xu ly truoc do).")
            return

    try:
        await _process_message_inner(event)
    except Exception:
        job_try = ctx.get("job_try", 1)
        max_tries = ctx.get("max_tries", 3)
        if job_try >= max_tries:
            # Lan thu CUOI CUNG that bai - arq se KHONG retry them nua, ghi lai
            # "dead letter" de sau nay xem lai/xu ly tay, tranh mat tin nhan
            # am tham khong ai biet.
            redis = ctx["redis"]
            await redis.lpush(
                DEAD_LETTER_KEY,
                json.dumps({"event": event, "job_try": job_try}, ensure_ascii=False),
            )
            print(f"[worker] DEAD-LETTER sau {job_try} lan thu that bai, event: {event}")
        raise


async def _process_message_inner(event: dict) -> None:
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

    reply = await handle_message(sender_id, text, channel="messenger")
    await send_text(sender_id, reply)


class WorkerSettings:
    functions = [process_message]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 20
    max_tries = 3  # issue #9 Bat 1: khai bao ro rang thay vi dua vao default cua arq
