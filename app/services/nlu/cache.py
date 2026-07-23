"""Cache (Buoc 10, NLU-INTEGRATION-GUIDE.md) - CHI cache "Normalized query ->
intent candidate" dung theo DUNG danh sach duoc phep trong guide:

    Cache duoc phep luu:
    - Normalized query -> intent candidate.
    - Intent -> static route configuration.
    - Compiled normalization mappings.

    Khong cache nhu du lieu tinh:
    - Gia. Ton kho. Khuyen mai. Tracking. Trang thai don. Du lieu ca nhan.

CHI cache ket qua "accept" (Router THAT SU chac chan) - KHONG cache
context_check/clarify vi cac ket qua nay it on dinh hon, phu thuoc ngu canh
tung luot chat (Context-aware Resolution, Bat 3) nen cache co the gay sai
lech ngu canh giua cac khach hang khac nhau.

KHONG cache noi dung Knowledge Base (kb_retrieval.search_kb() ket qua) -
luon lay MOI, tranh cache noi dung co the thay doi khi team Knowledge cap
nhat du lieu.

TTL ngan (1h) - du giam tai cho cau hoi lap lai trong ngay (vd "gia bao
nhieu" duoc hoi rat nhieu lan tu nhieu khach khac nhau -> cung 1 ket qua
intent classification), khong qua dai de tranh cache "chai" khi
utterance/rule duoc cap nhat.

An toan: moi loi Redis deu bi bat, tra ve None/khong luu duoc thay vi raise -
cache MISS duoc coi la binh thuong, khong lam vo flow.
"""

import json

import redis.asyncio as aioredis

from app.config import settings

_TTL_SECONDS = 3600  # 1h


def _cache_key(normalized_message: str) -> str:
    return f"nlu_route_cache:{normalized_message.strip().lower()}"


async def get_cached_decision(normalized_message: str) -> dict | None:
    """Tra ve dict {intent, confidence, action, matched_by, detail} hoac
    None neu cache miss/loi (an toan, khong raise)."""
    try:
        redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            raw = await redis.get(_cache_key(normalized_message))
            return json.loads(raw) if raw else None
        finally:
            await redis.aclose()
    except Exception as e:
        print(f"[nlu_cache] Khong doc duoc cache (bo qua): {e}")
        return None


async def set_cached_decision(normalized_message: str, decision_dict: dict) -> None:
    """Luu ket qua route "accept" vao cache. Loi bi bat, khong raise."""
    try:
        redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis.set(
                _cache_key(normalized_message),
                json.dumps(decision_dict, ensure_ascii=False),
                ex=_TTL_SECONDS,
            )
        finally:
            await redis.aclose()
    except Exception as e:
        print(f"[nlu_cache] Khong ghi duoc cache (bo qua): {e}")
