"""Loi agent: nhan tin nhan, sinh cau tra loi bang DeepSeek + RAG + tool calling.

Luong:
1. Lay lich su hoi thoai tu Redis (TTL 24h)
2. Tim top-4 chunks lien quan tu knowledge base (RAG) - kien thuc san pham tinh
   (cach pha, huong vi...), KHONG dung cho gia/ton kho/don hang.
3. Goi DeepSeek voi system prompt + RAG context + lich su + tool schema (TOOL_DEFINITIONS)
4. Neu model tra ve tool_calls: thuc thi tool that (DB that qua app/services/tools.py),
   nap ket qua tool nguoc lai cho model, lap lai toi da MAX_TOOL_ITERATIONS vong
5. Luu tin nhan (user + cau tra loi cuoi cung) vao Redis - KHONG luu buoc trung gian
   tool_calls de lich su gon nhe
6. Tra ve cau tra loi cuoi cung
"""

import json
from pathlib import Path

import redis.asyncio as aioredis
from openai import AsyncOpenAI

from app.config import settings
from app.services import handoff, tools
from app.services.messenger_profile import get_user_profile
from app.services.rag import search_knowledge

SYSTEM_PROMPT = (
    Path(__file__).resolve().parents[1] / "prompts" / "system_prompt.md"
).read_text(encoding="utf-8")

MAX_HISTORY = 10  # so luot chat giu lai (moi luot = 1 user + 1 assistant)
MAX_TOOL_ITERATIONS = 4  # chan vong lap tool_calls vo han neu model lien tuc goi tool


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


async def _execute_tool(name: str, args: dict, sender_id: str, last_message: str) -> dict:
    """Dispatch 1 tool call toi ham that trong app/services/tools.py.

    psid (sender_id) va last_message duoc bom o day, KHONG lay tu args model
    tra ve - tranh model tu bia/nham lan sender_id hoac tin nhan goc cua khach.
    """
    try:
        if name == "search_products":
            return await tools.search_products(**args)
        if name == "check_stock":
            return await tools.check_stock(**args)
        if name == "create_order":
            return await tools.create_order(psid=sender_id, **args)
        if name == "escalate_to_human":
            return await tools.escalate_to_human(psid=sender_id, last_message=last_message, **args)
        return {"error": f"Tool khong ton tai: {name}"}
    except TypeError as e:
        # Model truyen sai/thieu tham so so voi schema
        return {"error": f"Tham so khong hop le cho tool '{name}': {e}"}
    except Exception as e:
        print(f"[orchestrator] Tool '{name}' loi: {e}")
        return {"error": f"Loi he thong khi chay tool '{name}', vui long thu lai."}


async def handle_message(sender_id: str, text: str) -> str:
    # Ket noi Redis
    redis = await aioredis.from_url(settings.redis_url, decode_responses=True)

    try:
        # 0. Luoi an toan deterministic: khach CHU DONG doi gap nguoi that ->
        # escalate ngay, KHONG di qua LLM (khong phu thuoc LLM co nho goi tool
        # dung luc hay khong - xem ghi chu "rui ro cao nhat" o ISSUES.md #7).
        if handoff.wants_human(text):
            await tools.escalate_to_human(
                psid=sender_id,
                reason="Khach chu dong yeu cau gap nhan vien",
                last_message=text,
            )
            reply = (
                "Dạ, em đã chuyển yêu cầu này cho nhân viên hỗ trợ rồi ạ, "
                "sẽ có người liên hệ anh/chị ngay nhé."
            )
            history = await _get_history(redis, sender_id)
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": reply})
            await _save_history(redis, sender_id, history)
            return reply

        # 1. Lay lich su + profile khach (ten tu Messenger)
        history = await _get_history(redis, sender_id)
        profile = await get_user_profile(redis, sender_id)

        # 2. RAG: tim chunks lien quan (kien thuc san pham tinh, khong phai gia/ton kho)
        chunks = await search_knowledge(text, top_k=4)
        rag_context = "\n\n".join(chunks) if chunks else ""

        # 3. Xay dung messages cho LLM
        system = SYSTEM_PROMPT
        full_name = f"{profile.get('last_name', '')} {profile.get('first_name', '')}".strip()
        if full_name:
            system += (
                f"\n\n## Thong tin khach hang\nTen tren Messenger: {full_name}. "
                "Dung ten nay de suy doan gioi tinh va danh xung phu hop "
                "(theo quy tac 'Cach goi khach')."
            )
        if rag_context:
            system += f"\n\n## Thong tin tham khao lien quan\n{rag_context}"

        # messages cho vong lap tool-calling cua luot nay - khong dinh vao history
        # da luu tru khi con tool_calls trung gian
        turn_messages = [{"role": "system", "content": system}]
        turn_messages += history
        turn_messages.append({"role": "user", "content": text})

        client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

        reply = ""
        for _ in range(MAX_TOOL_ITERATIONS):
            response = await client.chat.completions.create(
                model=settings.llm_model,
                messages=turn_messages,
                tools=tools.TOOL_DEFINITIONS,
                tool_choice="auto",
                max_tokens=512,
                temperature=0.3,
            )
            message = response.choices[0].message

            if not message.tool_calls:
                reply = (message.content or "").strip()
                break

            # Ghi lai message cua assistant (co tool_calls) vao messages de model
            # thay duoc ngu canh no vua goi tool gi o vong sau
            turn_messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
            )

            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await _execute_tool(tc.function.name, args, sender_id, text)
                turn_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        else:
            # Het MAX_TOOL_ITERATIONS ma van con tool_calls - tra loi an toan thay vi treo
            print(f"[orchestrator] Vuot qua {MAX_TOOL_ITERATIONS} vong tool_calls cho {sender_id}")
            reply = "Đội ngũ 3S Coffee sẽ kiểm tra và phản hồi bạn sớm nhất."

        if not reply:
            reply = "Đội ngũ 3S Coffee sẽ kiểm tra và phản hồi bạn sớm nhất."

        # Safety net: loc ky hieu markdown lot luoi (Messenger khong render markdown)
        reply = (
            reply.replace("**", "")
            .replace("###", "")
            .replace("##", "")
            .replace("`", "")
        )

        # 5. Luu lich su - CHI luot user/assistant cuoi cung, khong luu buoc tool_calls
        # trung gian (giu Redis gon nhe, dung format cu tuong thich nguoc)
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        await _save_history(redis, sender_id, history)

        return reply

    except Exception as e:
        # Fallback an toan neu LLM loi
        print(f"[orchestrator] LLM error: {e}")
        return "Đội ngũ 3S Coffee sẽ phản hồi bạn ngay."

    finally:
        await redis.aclose()
