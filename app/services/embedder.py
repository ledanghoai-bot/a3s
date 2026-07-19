"""Embedding local dung sentence-transformers.

Model: paraphrase-multilingual-MiniLM-L12-v2
- Ho tro tieng Viet tot
- Nhe (~120MB), chay duoc tren CPU
- Dimension: 384
"""

import asyncio
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.config import settings


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Load model 1 lan duy nhat, cache lai."""
    return SentenceTransformer(settings.embedding_model)


def embed(text: str) -> list[float]:
    model = _get_model()
    return model.encode(text, normalize_embeddings=True).tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    return model.encode(texts, normalize_embeddings=True).tolist()


async def embed_async(text: str) -> list[float]:
    """Ban bat dong bo cua embed() (issue #9, Bat 1) - `encode()` la CPU-bound
    dong bo, neu goi truc tiep trong 1 ham async se CHAN toan bo event loop
    (worker/api) trong luc tinh toan - anh huong toi MOI request khac dang
    cho xu ly cung luc, khong chi rieng request goi embedding. Chay trong
    threadpool rieng qua `asyncio.to_thread` de tra event loop chinh ve rang.
    Dung ham nay (KHONG dung `embed()` truc tiep) trong moi code async moi
    tu day tro di (vd products.py, knowledge_entries.py)."""
    return await asyncio.to_thread(embed, text)
