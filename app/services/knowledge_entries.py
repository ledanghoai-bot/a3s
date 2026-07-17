"""CRUD cho FAQ qua dashboard - tu dong dong bo RAG (issue #8, Bat 2).

Khac voi noi dung tinh trong data/knowledge/*.md (nap 1 lan qua scripts/ingest.py,
source la ten file), FAQ tao/sua qua day luon co source='dashboard:faq' va gan
dung 1 dong knowledge_chunks qua faq_entry_id. Sua/xoa entry se tu dong xoa chunk
cu + tao lai (tinh embedding moi) - khong bao gio bi "lech" giua noi dung hien
thi tren dashboard va noi dung bot thuc su dung de tra loi.

Dung asyncpg thuan, cung convention voi cac service khac. embed() la ham dong
bo/CPU-bound (xem app/services/embedder.py) - da biet la gioi han hieu nang khi
nhieu request cung luc, xem docs/BACKEND_API-VI.md muc "Gioi han da biet".
"""

import asyncpg

from app.config import settings
from app.services.embedder import embed

SOURCE_LABEL = "dashboard:faq"


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _vec_str(vec: list[float]) -> str:
    return "[" + ",".join(str(x) for x in vec) + "]"


async def list_faq() -> list[dict]:
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            "SELECT id, question, answer, created_at, updated_at FROM faq_entries ORDER BY id"
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def create_faq(question: str, answer: str) -> dict:
    """Tao FAQ moi + tinh embedding + insert knowledge_chunks ngay lap tuc -
    bot co the dung ngay tu cau hoi ke tiep, khong can cho batch ingest nao."""
    content = f"{question}\n{answer}"
    vec_str = _vec_str(embed(content))

    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            entry_id = await conn.fetchval(
                "INSERT INTO faq_entries (question, answer) VALUES ($1, $2) RETURNING id",
                question,
                answer,
            )
            await conn.execute(
                """
                INSERT INTO knowledge_chunks (source, content, embedding, faq_entry_id)
                VALUES ($1, $2, $3::vector, $4)
                """,
                SOURCE_LABEL,
                content,
                vec_str,
                entry_id,
            )
        return {"id": entry_id, "question": question, "answer": answer}
    finally:
        await conn.close()


async def update_faq(entry_id: int, question: str, answer: str) -> dict:
    """Sua FAQ - XOA chunk cu roi TAO LAI (khong UPDATE embedding tai cho) de
    dam bao khong bao gio co chunk "mo côi" content cu/embedding moi lech nhau."""
    content = f"{question}\n{answer}"
    vec_str = _vec_str(embed(content))

    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            result = await conn.execute(
                "UPDATE faq_entries SET question = $1, answer = $2, updated_at = now() WHERE id = $3",
                question,
                answer,
                entry_id,
            )
            if result == "UPDATE 0":
                raise LookupError(f"Khong tim thay FAQ id={entry_id}")

            await conn.execute("DELETE FROM knowledge_chunks WHERE faq_entry_id = $1", entry_id)
            await conn.execute(
                """
                INSERT INTO knowledge_chunks (source, content, embedding, faq_entry_id)
                VALUES ($1, $2, $3::vector, $4)
                """,
                SOURCE_LABEL,
                content,
                vec_str,
                entry_id,
            )
        return {"id": entry_id, "question": question, "answer": answer}
    finally:
        await conn.close()


async def delete_faq(entry_id: int) -> bool:
    """Xoa FAQ - knowledge_chunks lien quan tu xoa theo qua ON DELETE CASCADE
    (migration 008), khong can xoa tay o day."""
    conn = await asyncpg.connect(_db_url())
    try:
        result = await conn.execute("DELETE FROM faq_entries WHERE id = $1", entry_id)
        return result != "DELETE 0"
    finally:
        await conn.close()
