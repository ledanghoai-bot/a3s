"""Truy van knowledge base (PostgreSQL + pgvector).

Nguon du lieu: data/knowledge/*.md -> chunk -> embedding -> bang knowledge_chunks.
Script ingest se duoc bo sung o issue [Tuan 3-4] RAG pipeline.
"""


async def search_knowledge(query: str, top_k: int = 4) -> list[str]:
    """Tra ve top-k doan kien thuc lien quan toi cau hoi cua khach.

    TODO(Tuan 3-4):
    1. Tao embedding cho `query` (settings.embedding_model).
    2. SELECT content FROM knowledge_chunks
       ORDER BY embedding <=> :query_embedding LIMIT :top_k
    """
    return []
