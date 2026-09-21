"""Webhook Messenger: xac thuc Meta va day su kien vao queue.

Nguyen tac: KHONG xu ly AI trong request webhook. Chi validate + enqueue
roi tra 200 ngay de Meta khong retry.
"""

import hashlib
import hmac
import json

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.config import settings

router = APIRouter()

_redis_pool = None


async def _get_redis():
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _redis_pool


@router.get("/webhook")
async def verify(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
) -> Response:
    """Meta goi khi dang ky webhook: phai echo lai hub.challenge."""
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


def _valid_signature(payload: bytes, signature: str) -> bool:
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.meta_app_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


# CA Directive 264 §3.1: cac container su kien inbound co the chua tin nhan. `messaging` = app la primary
# receiver; `standby` = app la SECONDARY receiver (Page Inbox/Business Suite dang giu thread) — tin van co
# noi dung, worker se try_take_thread_control roi xu ly (khi khong paused). Source marker SERVER-DERIVED tu
# ten container, KHONG tin field tuy y trong payload.
_INBOUND_CONTAINERS = ("messaging", "standby")


def _has_message(event: object) -> bool:
    """Chi enqueue su kien co object `message` (tin that hoac echo). delivery/read/handover metadata KHONG
    co `message` -> khong bien thanh customer message (CA 264 §3.1). Echo van enqueue: worker phan biet
    is_echo va KHONG coi la customer message."""
    return isinstance(event, dict) and isinstance(event.get("message"), dict)


@router.post("/webhook")
async def receive(request: Request) -> dict:
    payload = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _valid_signature(payload, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        # CA 264 §3.1: malformed payload KHONG lam endpoint crash, KHONG log noi dung nhay cam.
        print("[webhook] payload khong phai JSON hop le — bo qua", flush=True)
        return {"status": "ignored", "reason": "malformed_json"}

    redis = await _get_redis()
    counts = {"messaging": 0, "standby": 0}
    enqueued = 0
    n_entry = 0
    for entry in (data.get("entry") or []):
        n_entry += 1
        for source in _INBOUND_CONTAINERS:
            events = entry.get(source) or []
            counts[source] += len(events)
            for event in events:
                if _has_message(event):
                    # Source truyen tuong minh -> worker biet day la standby de handover dung cach.
                    await redis.enqueue_job("process_message", event, source)
                    enqueued += 1
    # CA 264 §3.2: structured metadata-only log (KHONG text/psid/token/signature/raw payload). flush=True de
    # doc duoc du api chay --no-access-log.
    print(f"[webhook] entries={n_entry} messaging={counts['messaging']} standby={counts['standby']} "
          f"enqueued={enqueued} ignored={counts['messaging'] + counts['standby'] - enqueued}", flush=True)
    return {"status": "received"}
