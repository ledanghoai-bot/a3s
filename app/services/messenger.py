"""Client gui tin nhan qua Messenger Send API."""

import httpx

from app.config import settings
from app.services.safe_log import safe_exc

GRAPH_URL = "https://graph.facebook.com/v21.0/me/messages"
TAKE_THREAD_CONTROL_URL = "https://graph.facebook.com/v21.0/me/take_thread_control"


async def send_text(recipient_id: str, text: str) -> None:
    payload = {
        "recipient": {"id": recipient_id},
        "messaging_type": "RESPONSE",
        "message": {"text": text},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            GRAPH_URL,
            params={"access_token": settings.page_access_token},
            json=payload,
        )
        resp.raise_for_status()


async def take_thread_control(recipient_id: str) -> None:
    """Handover Protocol: gianh/giu quyen so huu thread truoc Page Inbox mac dinh cua Meta.

    Boi canh: page co Page Inbox (Business Suite) luon ton tai nhu mot receiver. Sau khi bot
    tra loi tin DAU, Page Inbox tu gianh thread control -> tin THU 2 tro di route ve Inbox, bot
    khong nhan duoc ("1 tin roi chan"). Goi take_thread_control moi khi bot chuan bi tra loi de
    app (primary receiver theo routing) giu quyen so huu -> nhan duoc MOI tin trong hoi thoai.

    BEST-EFFORT: loi o day (vd bot da la owner -> Meta tra 400) KHONG duoc lam vo luong tra loi;
    caller phai boc try/except. Chi dung cho Messenger (khong lien quan Telegram)."""
    payload = {"recipient": {"id": recipient_id}, "metadata": "bot_auto_reply"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            TAKE_THREAD_CONTROL_URL,
            params={"access_token": settings.page_access_token},
            json=payload,
        )
        resp.raise_for_status()


async def try_take_thread_control(recipient_id: str) -> bool:
    """Wrapper best-effort cho take_thread_control: nuot loi (log redacted), tra True/False.
    KHONG bao gio raise -> an toan goi trong luong tra loi chinh."""
    try:
        await take_thread_control(recipient_id)
        return True
    except Exception as e:  # noqa: BLE001 - handover loi khong duoc lam vo luong reply
        print(f"[messenger] take_thread_control bo qua (khong lam vo reply): {safe_exc(e)}")
        return False
