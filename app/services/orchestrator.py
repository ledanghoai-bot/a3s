"""Loi agent: nhan tin nhan, sinh cau tra loi bang DeepSeek + RAG.

Luong:
1. Lay lich su hoi thoai tu Redis (TTL 24h)
2. Tim top-4 chunks lien quan tu knowledge base (RAG)
3. Goi DeepSeek voi system prompt + RAG context + lich su
4. Luu tin nhan moi vao Redis
5. Tra ve cau tra loi
"""

import json
from pathlib import Path

import redis.asyncio as aioredis
from openai import AsyncOpenAI

from app.config import settings
from app.services.rag import search_knowledge

SYSTEM_PROMPT = (
    Path(__file__).resolve().parents[1] / "prompts" / "system_prompt.md"
).read_text(encoding="utf-8")

MAX_HISTORY = 10  # so luot chat giu lai (moi luot = 1 user + 1 assistant)


def _redis_key(sender_id: str) -> str:
    return f"chat:{sender_id}"


async def _get_history(redis, sender_id: str) -> list[dict]:
    raw = await redis.get(_redis_key(sender_id))
    if not raw:
        return []
    return json.loads(raw)


async def _save_history(redis, sender_id: str, history: list[dict]) -> None:
    # Giu toi da MAX_HISTORY luot, TTL 24h
    trimmed = history[-(MAX_HISTORY * 2):]
    await redis.set(_redis_key(sender_id), json.dumps(trimmed, ensure_ascii=False), ex=86400)


async def handle_message(sender_id: str, text: str) -> str:
    # Ket noi Redis
    redis = await aioredis.from_url(settings.redis_url, decode_responses=True)

    try:
        # 1. Lay lich su
        history = await _get_history(redis, sender_id)

        # 2. RAG: tim chunks lien quan
        chunks = await search_knowledge(text, top_k=4)
        rag_context = "\n\n".join(chunks) if chunks else ""

        # 3. Xay dung messages cho LLM
        system = SYSTEM_PROMPT
        if rag_context:
            system += f"\n\n## Thong tin tham khao lien quan\n{rag_context}"

        messages = [{"role": "system", "content": system}]
        messages += history
        messages.append({"role": "user", "content": text})

        # 4. Goi DeepSeek
        client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            max_tokens=512,
            temperature=0.3,
        )
        reply = response.choices[0].message.content.strip()

        # 5. Luu lich su
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        await _save_history(redis, sender_id, history)

        return reply

    except Exception as e:
        # Fallback an toan neu LLM loi
        print(f"[orchestrator] LLM error: {e}")
        return "\u0110\u1ed9i ng\u0169 3S Coffee s\u1ebd ph\u1ea3n h\u1ed3i b\u1ea1n ngay."

    finally:
        await redis.aclose()
