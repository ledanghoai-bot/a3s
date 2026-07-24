"""Loi agent: nhan tin nhan, sinh cau tra loi bang DeepSeek + RAG + tool calling.

Luong:
1. Lay lich su hoi thoai tu Redis (TTL 24h)
2. Tim top-4 chunks lien quan tu knowledge base (RAG) - kien thuc san pham tinh
   (cach pha, huong vi...), KHONG dung cho gia/ton kho/don hang.
3. Goi DeepSeek voi system prompt + RAG context + lich su + tool schema (TOOL_DEFINITIONS)
4. Neu model tra ve tool_calls: thuc thi tool that (DB that qua app/services/tools.py),
   nap ket qua tool nguoc lai cho model, lap lai toi da MAX_TOOL_ITERATIONS vong
5. Luu tin nhan (user + cau tra loi cuoi cung) vao Redis - KHONG luu buoc trung gian
   tool_calls de lich su gon nhe. Dong thoi ghi vao Postgres (bang messages) qua
   app/services/conversation_log.py de dashboard (#8) doc lai duoc lich su lau dai.
6. Tra ve cau tra loi cuoi cung
"""

import json
from pathlib import Path

import redis.asyncio as aioredis
from openai import AsyncOpenAI

from app.config import settings
from app.services import conversation_log, handoff, products, tools
from app.services.messenger_profile import get_user_profile
from app.services.nlu_hint import get_nlu_hint
from app.services.rag import search_knowledge

SYSTEM_PROMPT = (
    Path(__file__).resolve().parents[1] / "prompts" / "system_prompt.md"
).read_text(encoding="utf-8")

MAX_HISTORY = 10  # so luot chat giu lai (moi luot = 1 user + 1 assistant)
MAX_TOOL_ITERATIONS = 4  # chan vong lap tool_calls vo han neu model lien tuc goi tool

# Kenh BAT BUOC khai bao "tro ly tu dong" o tin dau (yeu cau Meta App Review cho
# Messenger). Cac kenh khac (telegram/zalo/web) chi KHUYEN NGHI - xem mo ta bom
# vao system prompt ben duoi + docs/META-APP-REVIEW-VI.md §7. Truyen channel
# TUONG MINH tu tung caller (khong suy tu prefix sender_id) - bai hoc CLAUDE.md.
DISCLOSURE_REQUIRED_CHANNELS = {"messenger"}

# Dau hieu reply DANG BAO da tao don (dung de chan bia don - xem guard trong
# handle_message). Model chi duoc noi cac cum nay khi create_order that su tra
# ve order_id trong luot hien tai.
_ORDER_CLAIM_MARKERS = (
    "mã đơn",
    "đơn hàng đã được tạo",
    "đơn đã được tạo",
    "đơn của anh đã được tạo",
    "đơn của chị đã được tạo",
    "đã tạo đơn",
    "tạo đơn thành công",
    "đặt hàng thành công",
    "lên đơn thành công",
    "đơn hàng thành công",
)


def _reply_claims_order_created(reply: str) -> bool:
    """True neu reply co dau hieu bao KHACH rang don da duoc tao (de doi chieu
    voi viec create_order co that su chay thanh cong trong luot nay hay khong)."""
    low = reply.lower()
    return any(marker in low for marker in _ORDER_CLAIM_MARKERS)


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


async def handle_message(sender_id: str, text: str, channel: str = "messenger") -> str:
    # channel: kenh goi toi (tuong minh, do caller truyen) - quyet dinh muc do
    # bat buoc khai bao "tro ly tu dong". Mac dinh "messenger" (kenh chinh).
    # Ket noi Redis
    redis = await aioredis.from_url(settings.redis_url, decode_responses=True)

    try:
        # -1. Dam bao co conversation trong Postgres cho dashboard (issue #8) -
        # doc lai duoc lich su lau dai, khac voi Redis chi giu 24h.
        conversation_id = await conversation_log.ensure_conversation(sender_id)

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
            await conversation_log.log_message(conversation_id, "customer", text)
            await conversation_log.log_message(conversation_id, "bot", reply)
            return reply

        # 1. Lay lich su + profile khach (ten tu Messenger Graph API - CHI goi
        # cho khach Messenger that; cac kenh khac nhu Telegram (sender_id dang
        # "tg:<chat_id>") khong co Graph API tuong duong nen bo qua, tranh goi
        # API that vo ich moi luot chat - issue "nhieu kenh" phat sinh tu vu Meta
        # khoa test user, xem ISSUES.md.
        history = await _get_history(redis, sender_id)
        if sender_id.startswith("tg:") or sender_id.startswith("manual:"):
            profile = {}
        else:
            profile = await get_user_profile(redis, sender_id)

        # 2. Kien thuc tham khao: Knowledge Base V2 (#11) THAY THE RAG cu (#4)
        # tu 23/7 theo chi dao PO ("cach pha phai tuan theo quy trinh KB V2") -
        # phat hien XUNG DOT kien thuc khi test Telegram that: RAG cu
        # (data/knowledge, vd "dinh luong chuan 2g/ly", "muong 2g") lech voi
        # KB V2 da duyet ("1 muong ~ 1g", khong dua cong thuc cung, caffeine
        # 4,1%). KB V2 phu rong hon han (BRAND/PRD/ORD/TASTE/BREW/CAF/HEALTH,
        # 364 unit vs 51 chunk). Chi lay domain danh cho khach (bai hoc Bat 5:
        # sales/playbook la tai lieu noi bo). rag.py/knowledge_chunks GIU
        # NGUYEN lam duong lui khi KB V2 loi - khong xoa.
        try:
            from app.services.kb_retrieval import search_kb
            units = await search_kb(text, top_k=4, allowed_domains=["brand", "product", "faq"])
            rag_context = "\n\n".join(
                f"[{u['asset_id']}] {u['heading']}:\n{u['content'][:600]}" for u in units
            )
        except Exception as e:
            print(f"[orchestrator] KB V2 loi, dung tam RAG cu: {e}")
            chunks = await search_knowledge(text, top_k=4)
            rag_context = "\n\n".join(chunks) if chunks else ""

        # 3. Xay dung messages cho LLM
        system = SYSTEM_PROMPT

        # Boi canh phien: kenh + co phai tin dau khong + muc do bat buoc khai bao
        # tro ly tu dong. Lich su rong = tin dau cua phien 24h (cung xap xi
        # "sau khoang lang dai" theo yeu cau Meta). Quy tac chi tiet o
        # system_prompt.md muc "Khai bao la tro ly tu dong".
        is_first_turn = len(history) == 0
        disclosure_level = (
            "BAT BUOC" if channel in DISCLOSURE_REQUIRED_CHANNELS else "KHUYEN NGHI"
        )
        system += (
            "\n\n## Boi canh phien hien tai\n"
            f"- Kenh dang phuc vu: {channel}\n"
            f"- Day la tin nhan DAU TIEN cua khach trong phien nay: "
            f"{'CO' if is_first_turn else 'KHONG'}\n"
            f"- Muc do yeu cau khai bao tro ly tu dong o tin dau: {disclosure_level}\n"
        )

        full_name = f"{profile.get('last_name', '')} {profile.get('first_name', '')}".strip()
        if full_name:
            system += (
                f"\n\n## Thong tin khach hang\nTen tren Messenger: {full_name}. "
                "Dung ten nay de suy doan gioi tinh va danh xung phu hop "
                "(theo quy tac 'Cach goi khach')."
            )
        if rag_context:
            system += f"\n\n## Thong tin tham khao lien quan\n{rag_context}"

        # 2.5. Lop NLU (issue #12) - CHI khi bat co ENABLE_NLU_ROUTER, CHI bo
        # sung THEM 1 doan hint ngan cho LLM, KHONG thay the/chan flow hien
        # tai. An toan tuyet doi: get_nlu_hint() tu bat moi loi ben trong,
        # khong bao gio raise ra day - xem app/services/nlu_hint.py.
        if settings.enable_nlu_router:
            nlu_hint = await get_nlu_hint(text, sender_id=sender_id)
            if nlu_hint:
                system += f"\n\n## Goi y tu he thong phan loai NLU (tham khao, khong bat buoc)\n{nlu_hint}"

        # Bom THANG danh sach SKU vao system prompt moi luot chat - KHONG phu
        # thuoc viec LLM co tu quyet dinh goi search_products hay khong (bug
        # 17/7: du prompt/tool schema da nhac goi tool, DeepSeek van tung
        # khang dinh sai "chi co 1 SKU" nhieu lan lien tiep trong 1 hoi thoai,
        # ke ca khi khach phan bac). Day la nguon that ve SU TON TAI cua SKU -
        # gia/ton kho/bac gia chi tiet van phai qua search_products/check_stock.
        sku_summary = await products.get_sku_summary_text()
        system += (
            "\n\n## Danh sach SKU hien co (nguon that DUY NHAT va DAY DU, LUON\n"
            "dung, khong duoc noi trai hay phu nhan du lieu nay du lich su hoi\n"
            "thoai truoc do co the da noi sai)\n"
            f"{sku_summary}\n\n"
            "TUYET DOI KHONG duoc bia them BAT KY SKU nao ngoai danh sach tren,\n"
            "ke ca khi nghe co ve hop ly voi nhu cau khach (vd khach hoi 'co loai\n"
            "nao dong goi lon/thung/bao khong' ma danh sach tren khong co loai do\n"
            "-> phai noi that la CHUA CO, KHONG duoc tu dat ten 1 SKU moi nghe hop ly).\n\n"
            "QUAN TRONG - THU TU UU TIEN khi co mau thuan: danh sach tren la du\n"
            "lieu SONG, luon duoc lay lai moi luot chat - LUON dung hon lich su\n"
            "hoi thoai o duoi (ke ca cau tra loi TRUOC DAY cua chinh ban). Neu ban\n"
            "thay minh (hoac lich su) tung noi 1 SKU KHONG co trong danh sach nay,\n"
            "hay TIN THEO danh sach nay (SKU do CO THAT), KHONG duoc tu 'sua lai'\n"
            "thanh phu nhan no chi vi muon nghe nhat quan voi cau truoc - chi duoc\n"
            "phep thay doi ket luan khi VUA goi lai tool va nhan ket qua khac.\n"
            "Van phai goi search_products de lay gia/bac gia/ton kho chi tiet cho\n"
            "tung SKU truoc khi bao gia cu the."
        )

        # Bom nguoc tin nhan/ghi chu that cua nhan vien trong luc handover (neu co) -
        # doc tu Postgres (khong phai Redis) de KHONG bao gio mat, tranh bot noi
        # trai thoa thuan sep/nhan vien da chot voi khach (issue #8 - xu ly tin
        # nhan luc handover). Xem app/services/conversation_log.py:get_recent_agent_messages.
        agent_notes = await conversation_log.get_recent_agent_messages(sender_id, limit=10)
        if agent_notes:
            notes_text = "\n".join(f"- {n['content']}" for n in agent_notes)
            system += (
                "\n\n## Ghi chu/thoa thuan tu nhan vien trong qua trinh handover\n"
                "(KHONG doc nguyen van cho khach, chi dung de hieu boi canh va "
                "KHONG duoc noi trai nhung gi nhan vien/sep da chot voi khach)\n"
                f"{notes_text}"
            )

        # messages cho vong lap tool-calling cua luot nay - khong dinh vao history
        # da luu tru khi con tool_calls trung gian
        turn_messages = [{"role": "system", "content": system}]
        turn_messages += history
        turn_messages.append({"role": "user", "content": text})

        client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

        reply = ""
        created_order_ids: list = []  # order_id create_order tra ve THAT trong luot nay
        for _ in range(MAX_TOOL_ITERATIONS):
            response = await client.chat.completions.create(
                model=settings.llm_model,
                messages=turn_messages,
                tools=tools.TOOL_DEFINITIONS,
                tool_choice="auto",
                max_tokens=512,
                temperature=0.1,
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
                if (
                    tc.function.name == "create_order"
                    and isinstance(result, dict)
                    and result.get("order_id")
                    and not result.get("error")
                ):
                    created_order_ids.append(result["order_id"])
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

        # GUARD CHONG BIA DON (lop code, khong chi dua vao prompt): neu model bao
        # KHACH rang don da duoc tao ("ma don #...", "dat hang thanh cong"...) nhung
        # KHONG co create_order thanh cong nao trong luot nay -> gan nhu chac chan
        # bia (da gap that: bot tu che "Ma don #3" ma khong goi tool -> DB khong co
        # don, khach tuong da mua). Chuyen human that su + tra loi an toan, KHONG de
        # khach tin nham la da dat hang thanh cong.
        if not created_order_ids and _reply_claims_order_created(reply):
            print(
                f"[orchestrator] CHAN BIA DON: reply bao da tao don nhung khong co "
                f"create_order thanh cong trong luot nay. sender={sender_id} "
                f"reply_goc={reply[:200]!r}"
            )
            try:
                await tools.escalate_to_human(
                    psid=sender_id,
                    reason=(
                        "Nghi bia xac nhan don: model bao da tao don nhung khong "
                        "goi create_order thanh cong trong luot nay"
                    ),
                    last_message=text,
                )
            except Exception as e:  # noqa: BLE001 - escalate loi khong duoc lam sap luong
                print(f"[orchestrator] escalate sau chan bia don loi: {e}")
            reply = (
                "Dạ để em kiểm tra lại cho chắc chắn rồi xác nhận đơn với anh/chị "
                "ngay ạ. Đội ngũ 3S Coffee sẽ liên hệ anh/chị trong ít phút để chốt đơn."
            )

        # 5. Luu lich su - CHI luot user/assistant cuoi cung, khong luu buoc tool_calls
        # trung gian (giu Redis gon nhe, dung format cu tuong thich nguoc)
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        await _save_history(redis, sender_id, history)
        await conversation_log.log_message(conversation_id, "customer", text)
        await conversation_log.log_message(conversation_id, "bot", reply)

        return reply

    except Exception as e:
        # Fallback an toan neu LLM loi
        print(f"[orchestrator] LLM error: {e}")
        return "Đội ngũ 3S Coffee sẽ phản hồi bạn ngay."

    finally:
        await redis.aclose()
