"""Client gui tin nhan qua Messenger Send API."""

import httpx

from app.config import settings

GRAPH_URL = "https://graph.facebook.com/v21.0/me/messages"


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
