"""Loi agent: nhan tin nhan, sinh cau tra loi.

Giai doan 1 (hien tai): echo bot de kiem tra pipeline end-to-end.
Giai doan 2+: LLM + RAG (app/services/rag.py) + tool calling
(search_products, check_stock, create_order, escalate_to_human).
Xem cac issue [Tuan 3-4] va [Tuan 5-6] cua project.
"""

from pathlib import Path

SYSTEM_PROMPT = (
    Path(__file__).resolve().parents[1] / "prompts" / "system_prompt.md"
).read_text(encoding="utf-8")


async def handle_message(sender_id: str, text: str) -> str:
    # TODO(Tuan 3-4): goi LLM voi SYSTEM_PROMPT + context RAG + lich su hoi thoai.
    # TODO(Tuan 5-6): tool calling de chot don va human handoff.
    return (
        "Chúng tôi đã nhận tin nhắn của bạn: "
        f"{text!r}. Đội ngũ 3S Coffee sẽ phản hồi ngay."
    )
