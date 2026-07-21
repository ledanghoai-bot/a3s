"""Embedding RIENG cho NLU layer (Bat C nang cap, 18/7) - TACH BIET HOAN TOAN
khoi app/services/embedder.py (dung cho Knowledge Base V2, M1-M6) de KHONG
anh huong toi pipeline da test ky/hoat dong tot voi model cu.

LY DO doi model: ket qua Semantic Router voi model cu
(paraphrase-multilingual-MiniLM-L12-v2, 118M tham so, 384 chieu) chi dat
38.3% dung tren 60 held-out - nghi ngo model qua nho de phan biet 30 intent
gan nhau ve ngu nghia. Thu model LON HON cung ho (paraphrase-multilingual-
mpnet-base-v2, 278M tham so, 768 chieu) - thuong cho ket qua tot hon tren
semantic similarity benchmark, cung cach dung (khong can prefix "query:"/
"passage:" nhu ho E5), giam rui ro loi cach dung khi doi model.

CHUA XAC NHAN co that su cai thien hay khong - can chay that tren may co
model (tai model moi ~2x dung luong hon model cu, lan dau se lau hon).
"""

import asyncio
from functools import lru_cache

from sentence_transformers import SentenceTransformer

NLU_EMBEDDING_MODEL = "paraphrase-multilingual-mpnet-base-v2"


@lru_cache(maxsize=1)
def _get_nlu_model() -> SentenceTransformer:
    """Load model 1 lan duy nhat, cache lai - TACH RIENG voi
    app/services/embedder.py._get_model() (Knowledge Base V2 van dung model
    cu, khong bi anh huong)."""
    return SentenceTransformer(NLU_EMBEDDING_MODEL)


def nlu_embed(text: str) -> list[float]:
    model = _get_nlu_model()
    return model.encode(text, normalize_embeddings=True).tolist()


async def nlu_embed_async(text: str) -> list[float]:
    """Ban bat dong bo - offload sang threadpool giong het ly do trong
    app/services/embedder.py (tranh chan event loop, xem Bat 1 issue #9)."""
    return await asyncio.to_thread(nlu_embed, text)
