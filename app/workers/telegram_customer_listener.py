"""Telegram bot cho KHACH HANG (khac han bot admin trong telegram_listener.py) -
kenh du phong khi Messenger bi gian doan (vd Meta khoa tai khoan test - xem
ISSUES.md). Dung TOKEN RIENG (TELEGRAM_CUSTOMER_BOT_TOKEN), KHONG dung chung
voi bot admin, vi bot nay phai tra loi BAT KY AI nhan tin toi (khac bot admin
chi xu ly dung 1 chat_id da cau hinh).

sender_id dua vao he thong dang "tg:<telegram_chat_id>" (co prefix) de KHONG
bao gio trung voi PSID Facebook that (PSID luon la chuoi so dai 15-17 chu so,
Telegram chat_id thuong ngan hon nhieu, nhung van prefix cho chac chan va de
phan biet nguon goc khi doc log/DB).

Dung LONG POLLING (khong can HTTPS public/domain - #9 deploy that chua xong),
y het cau truc voi telegram_listener.py.

Chay tay de test:
    python -m app.workers.telegram_customer_listener
"""

import asyncio

import httpx

from app.config import settings
from app.services import conversation_log
from app.services.handoff import is_bot_paused
from app.services.orchestrator import handle_message

API_BASE = "https://api.telegram.org"
POLL_TIMEOUT = 30


def _configured() -> bool:
    return bool(settings.telegram_customer_bot_token)


async def _send_reply(client: httpx.AsyncClient, chat_id: int, text: str) -> None:
    url = f"{API_BASE}/bot{settings.telegram_customer_bot_token}/sendMessage"
    try:
        await client.post(url, json={"chat_id": chat_id, "text": text}, timeout=10.0)
    except Exception as e:
        print(f"[telegram_customer_listener] Gui tin nhan that bai: {e}")


async def _handle_customer_message(client: httpx.AsyncClient, chat_id: int, text: str) -> None:
    sender_id = f"tg:{chat_id}"

    # Human handoff (issue #7/#8): dung y het logic worker Messenger
    # (app/workers/tasks.py) - neu dang bot_paused thi CHI log, khong tra loi,
    # tranh chong len nhan vien.
    if await is_bot_paused(sender_id):
        conversation_id = await conversation_log.ensure_conversation(sender_id)
        await conversation_log.log_message(conversation_id, "customer", text)
        print(f"[telegram_customer_listener] Bot dang paused cho {sender_id}, chi log.")
        return

    reply = await handle_message(sender_id, text, channel="telegram")
    await _send_reply(client, chat_id, reply)


async def _poll_loop() -> None:
    offset = None

    async with httpx.AsyncClient(timeout=POLL_TIMEOUT + 10) as client:
        try:
            await client.post(f"{API_BASE}/bot{settings.telegram_customer_bot_token}/deleteWebhook")
        except Exception as e:
            print(f"[telegram_customer_listener] deleteWebhook loi (bo qua): {e}")

        print("[telegram_customer_listener] Da ket noi, bat dau long-polling (kenh khach hang)...")

        while True:
            try:
                params = {"timeout": POLL_TIMEOUT}
                if offset is not None:
                    params["offset"] = offset
                resp = await client.get(
                    f"{API_BASE}/bot{settings.telegram_customer_bot_token}/getUpdates", params=params
                )
                resp.raise_for_status()
                data = resp.json()

                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    message = update.get("message") or {}
                    chat_id = (message.get("chat") or {}).get("id")
                    text = message.get("text")

                    if not chat_id or not text:
                        continue  # bo qua sticker/anh/lenh he thong khac

                    await _handle_customer_message(client, chat_id, text)

            except httpx.HTTPError as e:
                print(f"[telegram_customer_listener] Loi goi Telegram API: {e}, thu lai sau 5s")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"[telegram_customer_listener] Loi khong xac dinh: {e}, thu lai sau 5s")
                await asyncio.sleep(5)


async def main() -> None:
    if not _configured():
        print(
            "[telegram_customer_listener] Thieu TELEGRAM_CUSTOMER_BOT_TOKEN trong .env - "
            "khong khoi dong. Tao bot moi qua @BotFather (KHAC bot admin) roi cau hinh."
        )
        return
    await _poll_loop()


if __name__ == "__main__":
    asyncio.run(main())
