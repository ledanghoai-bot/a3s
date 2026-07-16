"""Ghi log hoi thoai/tin nhan vao Postgres (issue #8 - dashboard).

Redis (`chat:{sender_id}`) chi giu lich su 24h de lam ngu canh cho LLM - khong
du de dashboard hien thi lich su lau dai. Module nay ghi CAU HOI/CAU TRA LOI
cuoi cung cua moi luot vao bang messages (Postgres, khong TTL) de dashboard
doc lai duoc.

Dung asyncpg thuan, cung convention voi rag.py/tools.py/handoff.py.
"""

import asyncpg

from app.config import settings


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def ensure_conversation(psid: str) -> int:
    """Lay hoac tao customer + conversation cho 1 psid, tra ve conversation_id.

    Don gian hoa: moi khach chi giu 1 conversation "dang hoat dong" (lay ban ghi
    moi nhat) - chua ho tro tach nhieu phien rieng biet theo thoi gian, du cho
    quy mo hien tai cua du an.
    """
    conn = await asyncpg.connect(_db_url())
    try:
        customer = await conn.fetchrow("SELECT id FROM customers WHERE psid = $1", psid)
        if customer is None:
            customer_id = await conn.fetchval(
                "INSERT INTO customers (psid) VALUES ($1) RETURNING id", psid
            )
        else:
            customer_id = customer["id"]

        conversation = await conn.fetchrow(
            "SELECT id FROM conversations WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 1",
            customer_id,
        )
        if conversation is None:
            conversation_id = await conn.fetchval(
                "INSERT INTO conversations (customer_id) VALUES ($1) RETURNING id", customer_id
            )
        else:
            conversation_id = conversation["id"]
        return conversation_id
    finally:
        await conn.close()


async def log_message(conversation_id: int, role: str, content: str) -> None:
    """Ghi 1 tin nhan vao bang messages. role phai la 'customer', 'bot', hoac 'agent'."""
    if role not in ("customer", "bot", "agent"):
        role = "bot"
    conn = await asyncpg.connect(_db_url())
    try:
        await conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1, $2, $3)",
            conversation_id,
            role,
            content,
        )
    finally:
        await conn.close()


async def get_recent_agent_messages(psid: str, limit: int = 10) -> list[dict]:
    """Lay cac tin nhan role='agent' gan nhat cua 1 khach (ca reply that cua
    nhan vien qua Messenger trong luc paused, lan ghi chu tuong minh luc resume)
    - dung de bom nguoc vao system prompt cho LLM, tranh bot noi trai thoa thuan
    nhan vien/sep da chot voi khach (xem ISSUES.md #8 - phan xu ly tin nhan luc handover).

    Doc tu Postgres (khong phai Redis) vi Redis history chi giu 24h va co the bi
    trim boi MAX_HISTORY - thong tin thoa thuan quan trong khong duoc phep mat.

    QUAN TRONG: KHONG loc theo cot `handled` - bot van phai biet toan bo thoa
    thuan du staff da bam "Da xu ly" tren dashboard hay chua, vi "handled" chi
    la co gon giao dien cho staff, khong lam mat hieu luc thoa thuan (xem
    ISSUES.md #8 - dong y 16/7 voi anh Hoai).
    """
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            """
            SELECT m.content, m.created_at
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            JOIN customers cu ON cu.id = c.customer_id
            WHERE cu.psid = $1 AND m.role = 'agent'
            ORDER BY m.created_at DESC
            LIMIT $2
            """,
            psid,
            limit,
        )
        return [dict(r) for r in reversed(rows)]  # tra ve theo thu tu thoi gian tang dan
    finally:
        await conn.close()


async def list_unhandled_notes(psid: str) -> list[dict]:
    """Lay TAT CA note/tin nhan agent CHUA duoc danh dau xu ly (handled=FALSE)
    cua 1 khach, kem id de dashboard gan nut "Da xu ly" cho tung dong rieng
    (issue #8 - nang cap UX 16/7, thay the viec chi hien note gan nhat).
    """
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            """
            SELECT m.id, m.content, m.created_at
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            JOIN customers cu ON cu.id = c.customer_id
            WHERE cu.psid = $1 AND m.role = 'agent' AND m.handled = FALSE
            ORDER BY m.created_at DESC
            """,
            psid,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def count_unhandled_notes(psid: str) -> int:
    """So note chua xu ly - dung cho nhan "/n(N)" tren dashboard."""
    conn = await asyncpg.connect(_db_url())
    try:
        return await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            JOIN customers cu ON cu.id = c.customer_id
            WHERE cu.psid = $1 AND m.role = 'agent' AND m.handled = FALSE
            """,
            psid,
        )
    finally:
        await conn.close()


async def mark_message_handled(message_id: int) -> bool:
    """Danh dau 1 note (message) la da xu ly. Tra ve True neu tim thay va cap nhat."""
    conn = await asyncpg.connect(_db_url())
    try:
        result = await conn.execute(
            "UPDATE messages SET handled = TRUE WHERE id = $1 AND role = 'agent'", message_id
        )
        return result != "UPDATE 0"
    finally:
        await conn.close()


async def list_all_agent_messages(psid: str) -> list[dict]:
    """Lay TOAN BO note/tin nhan agent cua 1 khach (ca da xu ly lan chua),
    khong loc/an - de dashboard hien lai lich su du da xu ly xong (issue #8 -
    nang cap UX 16/7 lan 5, thay vi lam bien mat khoi giao dien nhu ban truoc).
    """
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            """
            SELECT m.id, m.content, m.handled, m.created_at
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            JOIN customers cu ON cu.id = c.customer_id
            WHERE cu.psid = $1 AND m.role = 'agent'
            ORDER BY m.created_at DESC
            """,
            psid,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()
