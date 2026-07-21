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


def nlu_embed_batch(texts: list[str]) -> list[list[float]]:
    """Tinh embedding cho NHIEU cau CUNG LUC (dung sentence-transformers batch
    encode noi bo, nhanh hon RAT NHIEU so voi goi tung cau rieng le trong 1
    vong lap) - dung cho build_semantic_index() khoi tao Intent Index (300+
    utterance).

    BUG HIEU NANG THUC TE PHAT HIEN (18/7): ban dau build_semantic_index() goi
    nlu_embed_async() TUNG CAU MOT trong vong lap (380 lan goi threadpool
    rieng le) - voi model lon (mpnet-base-v2, 278M tham so) chay tren CPU, viec
    nay co the mat rat lau (hang chuc giay den vai phut) o lan dau tien sau
    khi container khoi dong lai - khien bot co ve "khong phan hoi" trong luc
    do (that ra dang xu ly, khong bi treo/crash). Fix: gom TOAN BO text can
    embed thanh 1 list, goi encode() DUY NHAT 1 LAN - sentence-transformers tu
    batch hieu qua ben trong.
    """
    model = _get_nlu_model()
    return model.encode(texts, normalize_embeddings=True).tolist()


async def nlu_embed_async(text: str) -> list[float]:
    """Ban bat dong bo - offload sang threadpool giong het ly do trong
    app/services/embedder.py (tranh chan event loop, xem Bat 1 issue #9)."""
    return await asyncio.to_thread(nlu_embed, text)


async def nlu_embed_batch_async(texts: list[str]) -> list[list[float]]:
    """Ban bat dong bo cua nlu_embed_batch() - CHI 1 lan goi asyncio.to_thread
    duy nhat cho toan bo danh sach, thay vi 1 lan cho MOI text rieng le."""
    return await asyncio.to_thread(nlu_embed_batch, texts)
