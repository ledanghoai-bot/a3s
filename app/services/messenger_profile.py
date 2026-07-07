"""Lay thong tin profile khach hang tu Messenger Graph API.

User Profile API chi tra ve first_name, last_name, profile_pic voi
Page Access Token co ban (field gender da bi Meta ngung cung cap).
Ket qua cache trong Redis 7 ngay de tranh goi API lap lai.
"""

import json

import httpx

from app.config import settings

GRAPH_URL = "https://graph.facebook.com/v19.0"
CACHE_TTL = 7 * 86400  # 7 ngay


def _cache_key(psid: str) -> str:
    return f"profile:{psid}"


async def get_user_profile(redis, psid: str) -> dict:
    """Tra ve {'first_name': ..., 'last_name': ...} hoac {} neu khong lay duoc."""
    # 1. Thu cache truoc
    cached = await redis.get(_cache_key(psid))
    if cached:
        return json.loads(cached)

    # 2. Goi Graph API
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{GRAPH_URL}/{psid}",
                params={
                    "fields": "first_name,last_name",
                    "access_token": settings.page_access_token,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            profile = {
                "first_name": data.get("first_name", ""),
                "last_name": data.get("last_name", ""),
            }
    except Exception as e:
        print(f"[messenger_profile] Khong lay duoc profile {psid}: {e}")
        profile = {}

    # 3. Cache (ke ca rong, TTL ngan hon de retry sau)
    ttl = CACHE_TTL if profile else 3600
    await redis.set(_cache_key(psid), json.dumps(profile, ensure_ascii=False), ex=ttl)
    return profile
