"""Truy van knowledge base (PostgreSQL + pgvector)."""

import asyncpg

from app.config import settings
from app.services.embedder import embed


async def search_knowledge(query: str, top_k: int = 4) -> list[str]:
    """Tra ve top-k doan kien thuc lien quan nhat voi cau hoi cua khach."""
    query_vec = embed(query)
    vec_str = "[" + ",".join(str(x) for x in query_vec) + "]"

    conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
    try:
        rows = await conn.fetch(
            """
            SELECT content
            FROM knowledge_chunks
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            vec_str,
            top_k,
        )
        return [r["content"] for r in rows]
    finally:
        await conn.close()
