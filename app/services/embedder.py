"""Embedding local dung sentence-transformers.

Model: paraphrase-multilingual-MiniLM-L12-v2
- Ho tro tieng Viet tot
- Nhe (~120MB), chay duoc tren CPU
- Dimension: 384
"""

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
