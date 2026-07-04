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


@router.post("/webhook")
async def receive(request: Request) -> dict:
    payload = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _valid_signature(payload, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    data = json.loads(payload)
    redis = await _get_redis()
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            await redis.enqueue_job("process_message", event)
    return {"status": "received"}
