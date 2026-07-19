"""Ghi log hoi thoai/tin nhan vao Postgres (issue #8 - dashboard).

Redis (`chat:{sender_id}`) chi giu lich su 24h de lam ngu canh cho LLM - khong
du de dashboard hien thi lich su lau dai. Module nay ghi CAU HOI/CAU TRA LOI
cuoi cung cua moi luot vao bang messages (Postgres, khong TTL) de dashboard
doc lai duoc.

Tu issue #9 (Bat 1): dung POOL dung chung (`app/db_pool.py`) thay vi tu mo
connection moi moi lan goi - module nay la 1 trong 2 duong goi nhieu nhat moi
luot chat (ensure_conversation + log_message x2 + get_recent_agent_messages
deu chay o MOI tin nhan), nen duoc uu tien chuyen sang pool truoc.
"""

from app.db_pool import get_pool


async def ensure_conversation(psid: str) -> int:
    """Lay hoac tao customer + conversation cho 1 psid, tra ve conversation_id.

    Don gian hoa: moi khach chi giu 1 conversation "dang hoat dong" (lay ban ghi
    moi nhat) - chua ho tro tach nhieu phien rieng biet theo thoi gian, du cho
    quy mo hien tai cua du an.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
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


async def log_message(conversation_id: int, role: str, content: str) -> None:
    """Ghi 1 tin nhan vao bang messages. role phai la 'customer', 'bot', hoac 'agent'."""
    if role not in ("customer", "bot", "agent"):
        role = "bot"
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1, $2, $3)",
            conversation_id,
            role,
            content,
        )


async def get_recent_agent_messages(psid: str, limit: int = 10) -> list[dict]:
    """Lay cac tin nhan role='agent' gan nhat cua 1 khach (ca reply that cua
    nhan vien qua Messenger trong luc paused, lan ghi chu tuong minh luc resume)
    - dung de bom nguoc vao system prompt cho LLM, tranh bot noi trai thoa thuan
    nhan vien/sep da chot voi khach (xem ISSUES-VI.md #8 - phan xu ly tin nhan luc handover).

    Doc tu Postgres (khong phai Redis) vi Redis history chi giu 24h va co the bi
    trim boi MAX_HISTORY - thong tin thoa thuan quan trong khong duoc phep mat.

    QUAN TRONG: KHONG loc theo cot `handled` - bot van phai biet toan bo thoa
    thuan du staff da bam "Da xu ly" tren dashboard hay chua, vi "handled" chi
    la co gon giao dien cho staff, khong lam mat hieu luc thoa thuan.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
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


async def list_unhandled_notes(psid: str) -> list[dict]:
    """Lay TAT CA note/tin nhan agent CHUA duoc danh dau xu ly (handled=FALSE)
    cua 1 khach, kem id de dashboard gan nut "Da xu ly" cho tung dong rieng
    (issue #8 - nang cap UX 16/7, thay the viec chi hien note gan nhat).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
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


async def count_unhandled_notes(psid: str) -> int:
    """So note chua xu ly - dung cho nhan "/n(N)" tren dashboard."""
    pool = await get_pool()
    async with pool.acquire() as conn:
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


async def mark_message_handled(message_id: int) -> bool:
    """Danh dau 1 note (message) la da xu ly. Tra ve True neu tim thay va cap nhat."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE messages SET handled = TRUE WHERE id = $1 AND role = 'agent'", message_id
        )
        return result != "UPDATE 0"


async def list_all_agent_messages(psid: str) -> list[dict]:
    """Lay TOAN BO note/tin nhan agent cua 1 khach (ca da xu ly lan chua),
    khong loc/an - de dashboard hien lai lich su du da xu ly xong (issue #8 -
    nang cap UX 16/7 lan 5, thay vi lam bien mat khoi giao dien nhu ban truoc).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
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
