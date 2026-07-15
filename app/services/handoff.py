"""Human handoff (issue #7): kiem tra/bat lai bot_paused, thong bao admin qua
Telegram, va nhan dien deterministic khi khach chu dong doi gap nguoi that.

Dung asyncpg thuan, cung convention voi rag.py/tools.py.
"""

import re

import asyncpg
import httpx

from app.config import settings

# Cac cum tu pho bien khi khach CHU DONG doi gap nguoi that. Day la luoi an toan
# thu 2, khong phu thuoc hoan toan vao viec LLM co goi escalate_to_human dung luc
# hay khong (xem ghi chu "rui ro cao nhat" o ISSUES.md #7).
_HUMAN_REQUEST_RE = re.compile(
    r"g[ặa]p nh[âa]n vi[êe]n|g[ặa]p ng[ưu][ờo]i th[ậa]t|"
    r"n[óo]i chuy[ệe]n v[ớo]i nh[âa]n vi[êe]n|chuy[ểe]n nh[âa]n vi[êe]n|"
    r"g[ọo]i nh[âa]n vi[êe]n|cho g[ặa]p admin|g[ặa]p qu[ảa]n l[ýy]",
    re.IGNORECASE,
)


def wants_human(text: str) -> bool:
    """True neu tin nhan chua cum tu doi gap nguoi that ro rang."""
    return bool(_HUMAN_REQUEST_RE.search(text))


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def is_bot_paused(psid: str) -> bool:
    """True neu hoi thoai gan nhat cua khach dang bot_paused=TRUE (nhan vien da
    tiep quan). Khach moi/chua co conversation nao -> mac dinh False."""
    conn = await asyncpg.connect(_db_url())
    try:
        row = await conn.fetchrow(
            """
            SELECT c.bot_paused
            FROM conversations c
            JOIN customers cu ON cu.id = c.customer_id
            WHERE cu.psid = $1
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
            psid,
        )
        return bool(row["bot_paused"]) if row else False
    finally:
        await conn.close()


async def resume_bot(psid: str) -> bool:
    """Bat lai bot cho hoi thoai gan nhat cua khach. Tra ve True neu tim thay
    conversation de resume, False neu khach chua tung co conversation nao."""
    conn = await asyncpg.connect(_db_url())
    try:
        row = await conn.fetchrow(
            """
            SELECT c.id
            FROM conversations c
            JOIN customers cu ON cu.id = c.customer_id
            WHERE cu.psid = $1
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
            psid,
        )
        if row is None:
            return False
        await conn.execute("UPDATE conversations SET bot_paused = FALSE WHERE id = $1", row["id"])
        return True
    finally:
        await conn.close()


async def get_customer_contact(psid: str) -> dict:
    """Lay ten/sdt khach da luu (neu co) de dinh kem vao thong bao admin."""
    conn = await asyncpg.connect(_db_url())
    try:
        row = await conn.fetchrow("SELECT name, phone FROM customers WHERE psid = $1", psid)
        return {"name": row["name"], "phone": row["phone"]} if row else {}
    finally:
        await conn.close()


async def log_escalation(conversation_id: int, reason: str) -> None:
    """Ghi log ly do escalate vao bang escalations (de sau nay xem lai, cai thien prompt)."""
    conn = await asyncpg.connect(_db_url())
    try:
        await conn.execute(
            "INSERT INTO escalations (conversation_id, reason) VALUES ($1, $2)",
            conversation_id,
            reason,
        )
    finally:
        await conn.close()


async def list_paused_conversations() -> list[dict]:
    """Liet ke tat ca hoi thoai dang bot_paused=TRUE, kem ten/sdt khach va ly do
    escalate gan nhat - dung cho trang admin UI (khoi phai nho psid bang cach thu cong)."""
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            """
            SELECT
                cu.psid, cu.name, cu.phone,
                (SELECT reason FROM escalations e WHERE e.conversation_id = c.id
                 ORDER BY e.created_at DESC LIMIT 1) AS reason,
                (SELECT created_at FROM escalations e WHERE e.conversation_id = c.id
                 ORDER BY e.created_at DESC LIMIT 1) AS escalated_at
            FROM conversations c
            JOIN customers cu ON cu.id = c.customer_id
            WHERE c.bot_paused = TRUE
            ORDER BY escalated_at DESC NULLS LAST
            """
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def notify_admin(psid: str, reason: str, last_message: str) -> None:
    """Gui thong bao Telegram cho admin. Neu chua cau hinh TELEGRAM_BOT_TOKEN /
    TELEGRAM_ADMIN_CHAT_ID thi bo qua im lang - KHONG duoc raise loi lam gian
    doan luong tra loi khach chi vi thieu cau hinh thong bao."""
    if not settings.telegram_bot_token or not settings.telegram_admin_chat_id:
        print("[handoff] Telegram chua cau hinh (TELEGRAM_BOT_TOKEN/TELEGRAM_ADMIN_CHAT_ID), bo qua thong bao.")
        return

    contact = await get_customer_contact(psid)
    contact_line = ""
    if contact.get("name") or contact.get("phone"):
        contact_line = f"\nKhach: {contact.get('name') or '(chua co ten)'} - {contact.get('phone') or '(chua co sdt)'}"

    text = (
        "\U0001F514 3S Coffee - can nhan vien ho tro\n"
        f"PSID: {psid}{contact_line}\n"
        f"Ly do: {reason}\n"
        f"Tin nhan gan nhat: {last_message[:300]}\n\n"
        "Mo Trang > Hop thu, tim theo ten/SDT hoac PSID o tren de tra loi truc tiep."
    )

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json={"chat_id": settings.telegram_admin_chat_id, "text": text})
            resp.raise_for_status()
    except Exception as e:
        # Loi gui thong bao KHONG duoc lam sap luong tra loi khach - chi log.
        print(f"[handoff] Gui Telegram that bai: {e}")
