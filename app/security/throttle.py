"""Login throttling da chieu (I-B M0.5, CA-REVIEW-IMPL-M0 §12.3).

- per-IP + per-normalized-username + global safety threshold (Redis counters, TTL cua so).
- Fail-OPEN khi Redis loi: KHONG khoa toan bo login (tranh lockout admin) + phat security event log.
- Thong bao loi (o router) KHONG tiet lo tai khoan co ton tai.
"""
import redis.asyncio as aioredis

from app.config import settings
from app.services.safe_log import mask_ref, safe_exc

_WINDOW = 900          # 15 phut
_MAX_PER_USER = 5
_MAX_PER_IP = 15
_MAX_GLOBAL = 200


def normalize_username(u: str) -> str:
    return (u or "").strip().lower()


async def _client():
    return await aioredis.from_url(settings.redis_url, decode_responses=True)


async def is_locked(username_norm: str, ip: str) -> bool:
    try:
        r = await _client()
        try:
            u = int(await r.get(f"lg:u:{username_norm}") or 0)
            i = int(await r.get(f"lg:i:{ip}") or 0)
            g = int(await r.get("lg:g") or 0)
            locked = u >= _MAX_PER_USER or i >= _MAX_PER_IP or g >= _MAX_GLOBAL
            if locked:
                print(f"[security] login throttled user={mask_ref(username_norm)} ip={mask_ref(ip)} (u={u} i={i} g={g})")
            return locked
        finally:
            await r.aclose()
    except Exception as e:  # noqa: BLE001 - FAIL-OPEN (CA §9.3)
        print(f"[security] throttle Redis loi -> FAIL-OPEN: {safe_exc(e)}")
        return False


async def record_failure(username_norm: str, ip: str) -> None:
    try:
        r = await _client()
        try:
            for k in (f"lg:u:{username_norm}", f"lg:i:{ip}", "lg:g"):
                pipe = r.pipeline()
                pipe.incr(k)
                pipe.expire(k, _WINDOW)
                await pipe.execute()
        finally:
            await r.aclose()
    except Exception as e:  # noqa: BLE001
        print(f"[security] throttle record loi (bo qua): {safe_exc(e)}")


async def reset_user(username_norm: str) -> None:
    try:
        r = await _client()
        try:
            await r.delete(f"lg:u:{username_norm}")
        finally:
            await r.aclose()
    except Exception:  # noqa: BLE001
        pass
