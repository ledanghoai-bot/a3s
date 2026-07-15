"""Telegram bot listener: nhan lenh/nut bam tu admin de resume bot ngay tren
Telegram, khong can mo dashboard (issue #8 - nang cap resume qua Telegram).

Dung LONG POLLING (khong can HTTPS public/domain - #9 deploy that chua xong),
chi chap nhan lenh/nut bam tu DUNG chat_id da cau hinh trong TELEGRAM_ADMIN_CHAT_ID -
moi chat khac (ke ca neu bot bi add vao group la, hoac ai do doan duoc bot)
deu bi bo qua im lang, khong xu ly.

Cach resume (2 cach, chon 1):
  1. Bam nut "Resume bot ngay" ngay duoi tin nhan thong bao escalate (nhanh nhat,
     khong can go/copy gi) - xu ly qua callback_query.
  2. Go lenh /resume <ma_kh_hoac_psid> thu cong.

Ma khach hang NGAN (customers.id, vd "42") dung thay the cho PSID Facebook dai/
kho copy tren mobile - xem app/services/handoff.py:resolve_psid(). Van nhan PSID
day du neu ai quen go (tuong thich nguoc).

Lenh ho tro:
  /resume <ma_kh|psid>            - bat lai bot cho 1 hoi thoai
  /resume <ma_kh|psid> <ghi chu>  - resume kem ghi chu thoa thuan
  /note <ma_kh|psid> <ghi chu>    - them ghi chu BAT KY LUC NAO (khong dung resume)
  /list                           - liet ke hoi thoai dang cho, kem nut resume nhanh
  /help                           - huong dan

Chay doc lap nhu 1 service rieng (xem docker-compose.yml: service telegram_bot).

Cach chay tay (ngoai docker, vd de test nhanh):
    python -m app.workers.telegram_listener
"""

import asyncio

import httpx

from app.config import settings
from app.services.handoff import list_paused_conversations, log_note, resolve_psid, resume_bot

API_BASE = "https://api.telegram.org"
POLL_TIMEOUT = 30  # giay cho long-polling moi request getUpdates


def _configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_admin_chat_id)


async def _send(client: httpx.AsyncClient, text: str, reply_markup: dict | None = None) -> None:
    url = f"{API_BASE}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {"chat_id": settings.telegram_admin_chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        await client.post(url, json=payload, timeout=10.0)
    except Exception as e:
        print(f"[telegram_listener] Gui tin nhan that bai: {e}")


async def _answer_callback(client: httpx.AsyncClient, callback_query_id: str, text: str) -> None:
    """Bat buoc goi sau moi lan bam nut, neu khong Telegram se giu icon 'dang tai'
    tren nut do mai (UX xau) du server da xu ly xong."""
    url = f"{API_BASE}/bot{settings.telegram_bot_token}/answerCallbackQuery"
    try:
        await client.post(
            url, json={"callback_query_id": callback_query_id, "text": text}, timeout=10.0
        )
    except Exception as e:
        print(f"[telegram_listener] answerCallbackQuery that bai: {e}")


async def _do_resume(client: httpx.AsyncClient, psid: str, note: str | None = None) -> str:
    """Goi lai dung handoff.resume_bot() - logic resume KHONG doi, chi them kenh goi.
    Neu co note, ghi kem qua handoff.log_note() - se duoc bom nguoc vao context
    cua bot cho cac luot chat sau (xem orchestrator.py)."""
    found = await resume_bot(psid)
    if not found:
        return f"⚠️ Không tìm thấy hội thoại nào cho `{psid}`."
    if note and note.strip():
        await log_note(psid, note)
        return (
            f"✅ Đã resume bot cho `{psid}` kèm ghi chú:\n"
            f"“{note.strip()}”\n"
            "Bot sẽ dùng ghi chú này khi trả lời khách ở các lượt sau."
        )
    return f"✅ Đã resume bot cho `{psid}`. Bot sẽ tự trả lời khách bình thường trở lại."


async def _handle_command(client: httpx.AsyncClient, text: str) -> None:
    text = text.strip()

    if text.startswith("/resume"):
        parts = text.split(maxsplit=2)
        if len(parts) < 2 or not parts[1].strip():
            await _send(client, "Dùng đúng cú pháp: /resume <mã KH hoặc psid> [ghi chú tuỳ chọn]")
            return
        psid = await resolve_psid(parts[1].strip())
        note = parts[2].strip() if len(parts) > 2 else None
        await _send(client, await _do_resume(client, psid, note))
        return

    if text.startswith("/note"):
        parts = text.split(maxsplit=2)
        if len(parts) < 3 or not parts[2].strip():
            await _send(client, "Dùng đúng cú pháp: /note <mã KH hoặc psid> <nội dung ghi chú>")
            return
        psid = await resolve_psid(parts[1].strip())
        note = parts[2].strip()
        await log_note(psid, note)
        await _send(
            client,
            f"📝 Đã ghi chú cho `{psid}`:\n“{note}”\nBot sẽ dùng ghi chú này ở các lượt chat sau, "
            "kể cả khi bot đang trả lời bình thường (không cần resume lại).",
        )
        return

    if text.startswith("/list"):
        paused = await list_paused_conversations()
        if not paused:
            await _send(client, "Hiện không có hội thoại nào đang chờ nhân viên.")
            return
        # Moi hoi thoai la 1 tin nhan rieng kem nut resume - de bam thang, khong
        # can go/copy gi (an toan hon gop chung 1 tin: callback_data luon dung
        # 1-1 voi psid, khong phu thuoc hien thi).
        for c in paused:
            name = c.get("name") or "(chưa có tên)"
            phone = c.get("phone") or "(chưa có sđt)"
            reason = c.get("reason") or "(không rõ lý do)"
            code = c.get("customer_id")
            text_msg = (
                f"{name} - {phone}\n"
                f"Mã KH: `{code}` (dùng cho /note, /resume)\n"
                f"Lý do: {reason}"
            )
            keyboard = {
                "inline_keyboard": [[{"text": "▶️ Resume ngay", "callback_data": f"resume:{c['psid']}"}]]
            }
            await _send(client, text_msg, reply_markup=keyboard)
        return

    if text.startswith("/help") or text.startswith("/start"):
        await _send(
            client,
            "Lệnh hỗ trợ (dùng mã KH ngắn như `42` thay vì PSID dài cho gọn):\n"
            "/resume <mã KH> - bật lại bot cho 1 hội thoại\n"
            "/resume <mã KH> <ghi chú> - resume kèm ghi chú thoả thuận\n"
            "/note <mã KH> <ghi chú> - thêm ghi chú BẤT KỲ LÚC NÀO, không cần "
            "resume kèm theo (dùng được cả khi bot đang trả lời bình thường)\n"
            "/list - xem danh sách hội thoại đang chờ, kèm mã KH và nút resume nhanh\n\n"
            "Khi có khách mới cần hỗ trợ, bot sẽ tự nhắn kèm mã KH và nút "
            "\"Resume bot ngay\" — bấm thẳng vào đó là nhanh nhất.",
        )
        return

    # Lenh khong nhan dien duoc - im lang, khong spam tra loi cho moi tin nhan la


async def _handle_callback(client: httpx.AsyncClient, callback_query: dict) -> None:
    callback_id = callback_query.get("id")
    data = callback_query.get("data") or ""

    if data.startswith("resume:"):
        psid = data.split(":", 1)[1]
        result_text = await _do_resume(client, psid)
        await _answer_callback(client, callback_id, "Đã xử lý")
        await _send(client, result_text)
        return

    await _answer_callback(client, callback_id, "Lệnh không nhận diện được")


async def _poll_loop() -> None:
    admin_chat_id = str(settings.telegram_admin_chat_id)
    offset = None

    async with httpx.AsyncClient(timeout=POLL_TIMEOUT + 10) as client:
        # Xoa webhook cu (neu tung set) de long-polling hoat dong dung
        try:
            await client.post(f"{API_BASE}/bot{settings.telegram_bot_token}/deleteWebhook")
        except Exception as e:
            print(f"[telegram_listener] deleteWebhook loi (bo qua): {e}")

        await _send(client, "🤖 Telegram resume bot đã kết nối. Gõ /help để xem lệnh.")
        print("[telegram_listener] Da ket noi, bat dau long-polling...")

        while True:
            try:
                params = {"timeout": POLL_TIMEOUT}
                if offset is not None:
                    params["offset"] = offset
                resp = await client.get(
                    f"{API_BASE}/bot{settings.telegram_bot_token}/getUpdates", params=params
                )
                resp.raise_for_status()
                data = resp.json()

                for update in data.get("result", []):
                    offset = update["update_id"] + 1

                    # Nut bam (callback_query) - uu tien xu ly truoc vi khong co "text" o cap nay
                    callback_query = update.get("callback_query")
                    if callback_query:
                        chat_id = str(
                            ((callback_query.get("message") or {}).get("chat") or {}).get("id", "")
                        )
                        if chat_id != admin_chat_id:
                            print(f"[telegram_listener] Bo qua callback tu chat la (chat_id={chat_id})")
                            continue
                        await _handle_callback(client, callback_query)
                        continue

                    # Tin nhan van ban thuong (lenh /resume, /note, /list, /help)
                    message = update.get("message") or {}
                    chat_id = str((message.get("chat") or {}).get("id", ""))
                    text = message.get("text")

                    if not text:
                        continue

                    # BAO MAT: chi xu ly lenh tu DUNG chat admin da cau hinh -
                    # moi chat khac bo qua im lang, khong phan hoi gi ca.
                    if chat_id != admin_chat_id:
                        print(f"[telegram_listener] Bo qua tin nhan tu chat la (chat_id={chat_id})")
                        continue

                    await _handle_command(client, text)

            except httpx.HTTPError as e:
                print(f"[telegram_listener] Loi goi Telegram API: {e}, thu lai sau 5s")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"[telegram_listener] Loi khong xac dinh: {e}, thu lai sau 5s")
                await asyncio.sleep(5)


async def main() -> None:
    if not _configured():
        print(
            "[telegram_listener] Thieu TELEGRAM_BOT_TOKEN/TELEGRAM_ADMIN_CHAT_ID trong .env - "
            "khong khoi dong listener. Cau hinh xong roi chay lai service nay."
        )
        return
    await _poll_loop()


if __name__ == "__main__":
    asyncio.run(main())
