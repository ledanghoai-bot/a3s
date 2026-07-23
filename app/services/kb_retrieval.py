"""Hybrid retrieval (vector + lexical) cho Knowledge Base V2 (M2).

Theo dung RAG_PIPELINE.md + ADR-0003-RAG-Strategy.md: Vector search (pgvector)
SONG SONG Lexical/BM25-like search (Postgres full-text), merge bang
Reciprocal Rank Fusion (RRF) - xem docs/KNOWLEDGE_BASE_V2_DESIGN-VI.md muc M2
cho ly do lua chon RRF thay vi model rerank ML rieng (gioi han da biet, co
the nang cap len cross-encoder that o giai doan sau).

CHUA tich hop vao orchestrator.py/bot production - day la ham doc lap, dung
scripts/kb_search_test.py de tu test truoc khi quyet dinh tich hop that (M3+,
ngoai pham vi hien tai).
"""

from app.db_pool import get_pool
from app.services.embedder import embed_async

RRF_K = 60  # hang so pho bien cho Reciprocal Rank Fusion

# Thu tu tang dan theo "Knowledge Architecture" trong depository-structure.md
# (Brand Truth -> Product -> Sales -> Conversation -> FAQ Delivery Layer) -
# CHI dung de PHAN DINH khi 2 KU co diem RRF hoan toan bang nhau tuyet doi -
# KHONG duoc phep anh huong toi thu tu xep hang thuc su.
#
# BUG THUC TE 18/7: he so boost ban dau qua lon (P1=+0.03, domain*0.001) -
# LON HON CA diem RRF toi da (~0.033 khi 1 KU dung hang 1 o CA 2 danh sach
# vector+lexical) - khien MOI noi dung gan nhan P1 (vd toan bo Brand Truth)
# thang ap dao du hoan toan khong lien quan cau hoi, trong khi KU dung nhat
# (vd FAQ-BREW-001 khop gan nguyen van cau hoi) bi lep ve. Da giam he so
# xuong ~1000 lan, chi con la "tiebreaker" that su, khong con lan at RRF.
_TIEBREAK_EPS = 1e-7
_DOMAIN_PRIORITY = {
    "brand": 6,
    "product": 5,
    "sales": 4,
    "conversation": 3,
    "faq": 2,
    "playbook": 1,
}
_PRIORITY_RANK = {"P1": 4, "P2": 3, "P3": 2, "P4": 1}


async def _get_active_index_version(conn) -> int | None:
    row = await conn.fetchrow("SELECT value FROM kb_config WHERE key = 'active_index_version'")
    return int(row["value"]) if row else None


async def search_kb(
    query: str,
    top_k: int = 5,
    allowed_domains: list[str] | None = None,
    include_draft: bool = False,
) -> list[dict]:
    """Tra ve top-k Knowledge Unit lien quan nhat kem provenance day du
    (ku_id, asset_id, source_path, domain, status, score...).

    include_draft=True CHI danh cho localhost test trong luc cho team
    Knowledge cap nhat status that (xem ISSUES-VI.md) - KHONG bat mac dinh.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        index_version = await _get_active_index_version(conn)
        if index_version is None:
            return []  # chua co lan ingest nao duoc "kich hoat" qua kb_config

        status_filter = ["approved", "locked"] + (["draft"] if include_draft else [])

        query_vec = await embed_async(query)
        vec_str = "[" + ",".join(str(x) for x in query_vec) + "]"

        domain_clause = ""
        extra = []
        if allowed_domains:
            domain_clause = "AND domain = ANY($4)"
            extra = [allowed_domains]

        vector_rows = await conn.fetch(
            f"""
            SELECT id, embedding <=> $3::vector AS dist FROM kb_units
            WHERE index_version = $1 AND status = ANY($2) {domain_clause}
            ORDER BY embedding <=> $3::vector
            LIMIT 20
            """,
            index_version, status_filter, vec_str, *extra,
        )
        # cosine distance that (0=trung khop, 2=nguoc huong) - RRF vut bo thong
        # tin nay khi xep hang, nhung caller can no de LOC lien quan that
        # (fallback knowledge hint trong nlu_hint.py, 23/7) - tra kem ket qua.
        vector_dist: dict[str, float] = {r["id"]: float(r["dist"]) for r in vector_rows}

        lexical_rows = await conn.fetch(
            f"""
            SELECT id FROM kb_units, plainto_tsquery('simple', $3) q
            WHERE index_version = $1 AND status = ANY($2) {domain_clause}
              AND search_tsv @@ q
            ORDER BY ts_rank_cd(search_tsv, q) DESC
            LIMIT 20
            """,
            index_version, status_filter, query, *extra,
        )

        # Reciprocal Rank Fusion - unit xuat hien o CA 2 danh sach se co diem
        # cao han han unit chi xuat hien o 1 danh sach.
        scores: dict[str, float] = {}
        for rank, r in enumerate(vector_rows, start=1):
            scores[r["id"]] = scores.get(r["id"], 0.0) + 1 / (RRF_K + rank)
        for rank, r in enumerate(lexical_rows, start=1):
            scores[r["id"]] = scores.get(r["id"], 0.0) + 1 / (RRF_K + rank)

        if not scores:
            return []

        ids = list(scores.keys())
        detail_rows = await conn.fetch(
            """
            SELECT u.id, u.heading, u.content, u.content_hash, u.domain, u.status,
                   u.priority, a.id AS asset_id, a.source_path, a.title AS asset_title
            FROM kb_units u
            JOIN kb_assets a ON a.id = u.asset_id
            WHERE u.id = ANY($1)
            """,
            ids,
        )

        results = []
        for row in detail_rows:
            score = scores[row["id"]]
            tiebreak = (
                _DOMAIN_PRIORITY.get(row["domain"], 0) + _PRIORITY_RANK.get(row["priority"], 0)
            ) * _TIEBREAK_EPS
            score += tiebreak
            results.append({
                "ku_id": row["id"],
                "asset_id": row["asset_id"],
                "asset_title": row["asset_title"],
                "source_path": row["source_path"],
                "heading": row["heading"],
                "content": row["content"],
                "content_hash": row["content_hash"],
                "domain": row["domain"],
                "status": row["status"],
                "priority": row["priority"],
                "score": round(score, 8),
                # None neu unit chi den tu nhanh lexical (khong co trong top-20
                # vector) - caller muon loc theo do gan ngu nghia phai tu xu ly
                # truong hop nay.
                "vector_distance": round(vector_dist[row["id"]], 4) if row["id"] in vector_dist else None,
            })

        # Dedup theo content_hash - giu ban diem cao nhat neu trung
        best_by_hash: dict[str, dict] = {}
        for r in results:
            h = r["content_hash"]
            if h not in best_by_hash or r["score"] > best_by_hash[h]["score"]:
                best_by_hash[h] = r

        final = sorted(best_by_hash.values(), key=lambda r: r["score"], reverse=True)
        return final[:top_k]
