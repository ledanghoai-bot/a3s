"""Context-aware Resolution (Buoc 5, NLU-INTEGRATION-GUIDE.md) - dung
conversation_state (luu Redis, TTL giong lich su chat trong orchestrator.py)
de ho tro giai quyet cau hoi NOI TIEP khong ro rang, vi du:

    Khach: Loai nay pha lanh duoc khong?
    Khach: Vay hai muong thi sao?

Cau thu 2 tu than khong du ngu canh de phan loai chac chan - nhung neu biet
cau truoc do la ve "pha lanh", co the goi y day la cau hoi tiep noi cung
chu de.

QUAN TRONG - dung dung tinh than guide: "Khong dung state de ghi de intent
ro rang cua tin nhan hien tai". State CHI duoc tham khao khi Router (Pattern+
Semantic, #12 Bat B-D) DA KHONG CHAC CHAN (action != accept) - va ket qua
CHI la 1 doan hint tham khao them cho LLM (giong toan bo thiet ke nlu_hint.py),
KHONG bao gio ep buoc/ghi de quyet dinh routing.

An toan: moi ham deu tu bat loi Redis/JSON, tra ve None/khong lam gi thay vi
raise - dung nguyen tac "khong bao gio lam vo flow chinh" da ap dung xuyen
suot Lop NLU tich hop vao production.
"""

import json

import redis.asyncio as aioredis

from app.config import settings

_TTL_SECONDS = 86400  # giong TTL lich su chat trong orchestrator.py (24h)

# Cum tu bao hieu cau hoi NOI TIEP - CO Y NGHIA RO RANG hon "vậy" dung rieng
# le (qua pho bien nhu tro tu cuoi cau binh thuong, vd "3S Coffee la gi vay"
# la cau HOAN CHINH, khong phai noi tiep - da test va sua bang sandbox truoc
# khi dua vao code chinh thuc).
_CONTINUATION_MARKERS = ["vậy còn", "còn thì sao", "thì sao", "còn thì"]

# Tu khoa bao hieu cau NGAN nhung VAN la cau hoan chinh, doc lap (khong tinh
# la noi tiep du it tu) - tranh false positive cho cac cau ngan nhung ro
# rang thuong gap.
_STANDALONE_SHORT_PHRASES = ["giá", "còn hàng", "cách pha", "khuyến mãi"]


def _state_key(sender_id: str) -> str:
    return f"nlu_state:{sender_id}"


async def get_conversation_state(sender_id: str) -> dict | None:
    """Tra ve {"previous_intent": ..., "active_domain": [...]} hoac None neu
    chua co/loi (an toan, khong raise)."""
    try:
        redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            raw = await redis.get(_state_key(sender_id))
            return json.loads(raw) if raw else None
        finally:
            await redis.aclose()
    except Exception as e:
        print(f"[context_state] Khong doc duoc state (bo qua): {e}")
        return None


async def save_conversation_state(sender_id: str, intent: str, domains: list[str]) -> None:
    """Luu lai intent/domain vua xac dinh CHAC CHAN (route.action == accept)
    de lam ngu canh cho tin nhan tiep theo. Loi bi bat, khong raise."""
    try:
        redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            state = {"previous_intent": intent, "active_domain": domains}
            await redis.set(_state_key(sender_id), json.dumps(state, ensure_ascii=False), ex=_TTL_SECONDS)
        finally:
            await redis.aclose()
    except Exception as e:
        print(f"[context_state] Khong luu duoc state (bo qua): {e}")


def looks_like_continuation(message: str) -> bool:
    """Heuristic don gian: co cum tu bao hieu noi tiep RO RANG, HOAC cau qua
    ngan (<=4 tu) MA KHONG phai 1 trong cac cau hoan chinh thuong gap. Da
    verify 7/7 test qua sandbox truoc khi dua vao code chinh thuc, dam bao
    khong bao "3S Coffee la gi vay"/"Gia bao nhieu"/"Con hang khong" la
    cau noi tiep (day la cau HOAN CHINH thuong gap, khong can ngu canh truoc)."""
    text_lower = message.strip().lower()
    if any(m in text_lower for m in _CONTINUATION_MARKERS):
        return True
    words = message.strip().split()
    if len(words) <= 4 and not any(kw in text_lower for kw in _STANDALONE_SHORT_PHRASES):
        return True
    return False
