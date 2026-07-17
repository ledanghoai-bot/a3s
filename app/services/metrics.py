"""Metrics/analytics cho dashboard (issue #8, Bat 3) - tan dung hoan toan du
lieu san co trong messages/conversations/orders, KHONG them bang moi.

3 chi so theo dung yeu cau:
1. Tin nhan/ngay (tach theo role) - list_messages_per_day()
2. Ty le hoi thoai -> don (% khach co it nhat 1 don) - get_conversion_rate()
3. Top cau hoi bot khong tra loi duoc - list_unanswered_questions()

Dung asyncpg thuan, cung convention voi cac service khac.
"""

import asyncpg

from app.config import settings

# Chuoi con duy nhat, khop dung cau fallback co dinh trong system_prompt.md
# muc "Khi khong co thong tin": "Hien chung toi chua co thong tin xac nhan..."
# Dung ILIKE substring thay vi khop nguyen van ca cau, de van bat duoc neu
# LLM doi nhe cach dien dat xung quanh (dau cau, khoang trang...).
FALLBACK_PHRASE = "chưa có thông tin xác nhận"


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def list_messages_per_day(days: int = 14) -> list[dict]:
    """So tin nhan theo tung ngay, tach theo role (customer/bot/agent), N
    ngay gan nhat (mac dinh 14). Ngay khong co tin nhan nao se KHONG xuat
    hien trong ket qua (khong tu dien 0) - frontend tu xu ly hien thi."""
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            """
            SELECT
                DATE(created_at) AS day,
                COUNT(*) FILTER (WHERE role = 'customer') AS customer_count,
                COUNT(*) FILTER (WHERE role = 'bot') AS bot_count,
                COUNT(*) FILTER (WHERE role = 'agent') AS agent_count,
                COUNT(*) AS total
            FROM messages
            WHERE created_at >= now() - ($1 || ' days')::interval
            GROUP BY DATE(created_at)
            ORDER BY day DESC
            """,
            str(days),
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def get_conversion_rate() -> dict:
    """Ty le khach co it nhat 1 don hang tren tong so khach da tung chat.
    Don gian hoa: dem theo customer_id (khong phan biet theo thoi gian) -
    "co bao nhieu % khach tung chat cuoi cung co dat don chua", khong phai
    ty le theo tung ngay/tuan (qua phuc tap cho ban dau, co the mo rong sau).
    """
    conn = await asyncpg.connect(_db_url())
    try:
        total_customers = await conn.fetchval("SELECT COUNT(*) FROM customers")
        customers_with_orders = await conn.fetchval(
            "SELECT COUNT(DISTINCT customer_id) FROM orders"
        )
        rate = (customers_with_orders / total_customers * 100) if total_customers > 0 else 0
        return {
            "total_customers": total_customers,
            "customers_with_orders": customers_with_orders,
            "conversion_rate_pct": round(rate, 1),
        }
    finally:
        await conn.close()


async def list_unanswered_questions(limit: int = 20) -> list[dict]:
    """Top cau hoi khach da hoi ma bot phai dung cau fallback co dinh (khong
    co du lieu de tra loi). Lay dung cau hoi KHACH goi NGAY TRUOC tin fallback
    do trong cung 1 conversation, gom nhom theo noi dung cau hoi (chuan hoa
    thuong/trim khoang trang) de dem tan suat cau hoi giong/gan giong nhau.

    Luu y: gom nhom bang string khop CHINH XAC sau khi chuan hoa - khong dung
    NLP/fuzzy matching (qua phuc tap cho pham vi hien tai) - 2 cau hoi khac
    nhau du cung y nghia se bi dem rieng neu khac chu.
    """
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            """
            SELECT
                (
                    SELECT m2.content
                    FROM messages m2
                    WHERE m2.conversation_id = f.conversation_id
                      AND m2.role = 'customer'
                      AND m2.created_at < f.created_at
                    ORDER BY m2.created_at DESC
                    LIMIT 1
                ) AS question,
                f.created_at
            FROM messages f
            WHERE f.role = 'bot' AND f.content ILIKE '%' || $1 || '%'
            ORDER BY f.created_at DESC
            """,
            FALLBACK_PHRASE,
        )

        grouped: dict[str, dict] = {}
        for r in rows:
            question = r["question"]
            if not question:
                continue  # tin fallback dau tien trong hoi thoai, khong co cau hoi truoc do
            key = question.strip().lower()
            if key not in grouped:
                grouped[key] = {
                    "question": question.strip(),
                    "count": 0,
                    "last_seen": r["created_at"],
                }
            grouped[key]["count"] += 1
            if r["created_at"] > grouped[key]["last_seen"]:
                grouped[key]["last_seen"] = r["created_at"]

        result = sorted(grouped.values(), key=lambda x: x["count"], reverse=True)
        return result[:limit]
    finally:
        await conn.close()
