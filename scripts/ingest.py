"""Ingest knowledge base vao PostgreSQL + pgvector.

Chay:
    docker compose exec api python scripts/ingest.py

Script se:
1. Doc tat ca file .md trong data/knowledge/
2. Chunk theo doan (2 dong trong = ranh gioi chunk)
3. Tao embedding bang sentence-transformers (local, khong can API)
4. Insert vao bang knowledge_chunks (upsert theo source+content)
"""

import asyncio
import re
from pathlib import Path

import asyncpg

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.services.embedder import embed_batch

KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "data" / "knowledge"


def chunk_markdown(text: str, source: str) -> list[dict]:
    """Tach markdown thanh cac chunk nho theo doan."""
    # Tach theo 2 dong trong lien tiep
    raw_chunks = re.split(r"\n{2,}", text.strip())
    chunks = []
    for c in raw_chunks:
        c = c.strip()
        if len(c) < 20:  # bo qua chunk qua ngan
            continue
        chunks.append({"source": source, "content": c})
    return chunks


async def ingest():
    db_url = settings.database_url.replace("+asyncpg", "")
    conn = await asyncpg.connect(db_url)

    all_chunks = []
    for md_file in sorted(KNOWLEDGE_DIR.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        chunks = chunk_markdown(text, source=md_file.name)
        all_chunks.extend(chunks)
        print(f"  {md_file.name}: {len(chunks)} chunks")

    if not all_chunks:
        print("Khong tim thay file .md nao trong data/knowledge/")
        return

    print(f"\nTong cong {len(all_chunks)} chunks. Dang tao embedding...")
    texts = [c["content"] for c in all_chunks]
    embeddings = embed_batch(texts)
    print("Embedding xong. Dang insert vao DB...")

    # Xoa chunks cu cua cac source nay truoc khi insert lai
    sources = list({c["source"] for c in all_chunks})
    await conn.execute(
        "DELETE FROM knowledge_chunks WHERE source = ANY($1)", sources
    )

    records = [
        (
            chunk["source"],
            chunk["content"],
            "[" + ",".join(str(x) for x in emb) + "]",
        )
        for chunk, emb in zip(all_chunks, embeddings)
    ]

    await conn.executemany(
        """
        INSERT INTO knowledge_chunks (source, content, embedding)
        VALUES ($1, $2, $3::vector)
        """,
        records,
    )

    await conn.close()
    print(f"Done! Da insert {len(records)} chunks vao knowledge_chunks.")


if __name__ == "__main__":
    asyncio.run(ingest())
