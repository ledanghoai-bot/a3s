"""CLI chay toan bo pipeline Ingestion cho Knowledge Base V2 (M1).

Cach dung:
    docker compose exec api python scripts/kb_ingest.py
        -> CHI ingest asset status=approved/locked (dung production rule)

    docker compose exec api python scripts/kb_ingest.py --include-draft
        -> CHO PHEP ca status=draft (localhost test trong luc cho team
           Knowledge cap nhat status that - xem ISSUES-VI.md)

Sau khi chay xong, script IN RA huong dan doi kb_config['active_index_version']
thu cong - KHONG tu dong switch (dung "atomic switch" that su, phai xac nhan
truoc khi cho retrieval dung index moi).
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import asyncpg
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.services.embedder import embed_async  # noqa: E402
from app.services.kb_ingest.loader import discover_files, parse_asset_file  # noqa: E402
from app.services.kb_ingest.unit_builder import build_units  # noqa: E402
from app.services.kb_ingest.validator import validate_asset  # noqa: E402

KB_ROOT = Path(__file__).resolve().parent.parent / "knowledge-base"
TAXONOMY_PATH = KB_ROOT / "taxonomy.yaml"


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _load_taxonomy_prefix_map() -> dict[str, tuple[str, str]]:
    """Tra ve {prefix: (asset_type, domain)} tu taxonomy.yaml - dung de suy
    ra domain/asset_type cho asset khong tu khai (vd file khong-YAML)."""
    if not TAXONOMY_PATH.is_file():
        print(f"CANH BAO: khong thay {TAXONOMY_PATH}, dung domain rong cho moi asset.")
        return {}
    data = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))
    mapping = {}
    for asset_type, info in (data.get("asset_types") or {}).items():
        prefix = info.get("prefix")
        domain = info.get("domain")
        if prefix:
            mapping[prefix] = (asset_type, domain)
    return mapping


def _classify(asset_id: str, prefix_map: dict) -> tuple[str, str]:
    """Tim prefix DAI NHAT khop truoc (vd 'SKL-BRAND' phai thang 'SKL-' neu
    ca 2 co trong map) - tranh SKL-BRAND-001 bi nham thanh loai SKL chung
    chung neu co ca 2 muc trong taxonomy."""
    best = None
    for prefix, (asset_type, domain) in prefix_map.items():
        if asset_id.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, asset_type, domain)
    if best:
        return best[1], best[2]
    return "unknown", "unknown"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Knowledge Base V2 (M1)")
    parser.add_argument(
        "--include-draft", action="store_true",
        help="Cho phep ingest ca asset status=draft (chi dung localhost test)",
    )
    args = parser.parse_args()

    if not KB_ROOT.is_dir():
        print(f"Loi: khong thay thu muc {KB_ROOT}.")
        print("Chay scripts/kb_normalize_source.py truoc de tao thu muc nay tu depository team Knowledge.")
        return

    prefix_map = _load_taxonomy_prefix_map()
    files = discover_files(KB_ROOT)
    print(f"Tim thay {len(files)} file trong {KB_ROOT}.\n")

    # Pass 1: parse toan bo (chua ghi DB) de co known_ids cho dependency check
    parsed = [parse_asset_file(f) for f in files]
    known_ids = {a.id for a in parsed}

    conn = await asyncpg.connect(_db_url())
    try:
        index_version = await conn.fetchval(
            "SELECT COALESCE(MAX(index_version), 0) + 1 FROM kb_units"
        )
        print(f"index_version moi cho lan chay nay: {index_version}\n")

        accepted, rejected = [], []
        seen_ids: set[str] = set()

        for asset in parsed:
            reasons = validate_asset(asset, seen_ids, known_ids, args.include_draft)
            if reasons:
                rejected.append({"file": asset.source_path, "id": asset.id, "reasons": reasons})
                print(f"[TU CHOI] {asset.source_path} ({asset.id}): {', '.join(reasons)}")
                continue

            seen_ids.add(asset.id)
            asset_type, taxonomy_domain = _classify(asset.id, prefix_map)
            domain = asset.domain or taxonomy_domain

            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO kb_assets
                        (id, title, domain, asset_type, status, version, priority,
                         source_path, language, raw_frontmatter, content_hash)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    ON CONFLICT (id) DO UPDATE SET
                        title=$2, domain=$3, asset_type=$4, status=$5, version=$6,
                        priority=$7, source_path=$8, language=$9, raw_frontmatter=$10,
                        content_hash=$11, updated_at=now()
                    """,
                    asset.id, asset.title, domain, asset_type, asset.status, asset.version,
                    asset.priority, asset.source_path, asset.language,
                    json.dumps(asset.raw_frontmatter, ensure_ascii=False, default=str), asset.content_hash,
                )

                units = build_units(asset)
                for u in units:
                    vec = await embed_async(u["embedding_text"])
                    vec_str = "[" + ",".join(str(x) for x in vec) + "]"
                    await conn.execute(
                        """
                        INSERT INTO kb_units
                            (id, asset_id, heading, content, content_hash, domain,
                             status, priority, language, embedding, search_tsv, index_version)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::vector,
                                to_tsvector('simple', $4), $11)
                        ON CONFLICT (id) DO UPDATE SET
                            asset_id=$2, heading=$3, content=$4, content_hash=$5,
                            domain=$6, status=$7, priority=$8, language=$9,
                            embedding=$10::vector, search_tsv=to_tsvector('simple', $4),
                            index_version=$11, created_at=now()
                        """,
                        u["id"], asset.id, u["heading"], u["content"], u["content_hash"],
                        domain, asset.status, asset.priority, asset.language, vec_str,
                        index_version,
                    )

            accepted.append(asset.id)
            print(f"[DA INGEST] {asset.id} ({asset.status}) -> {len(units)} Knowledge Unit")

        await conn.execute(
            """
            INSERT INTO kb_ingestion_reports
                (index_version, include_draft, accepted_count, rejected_count, rejected_files)
            VALUES ($1,$2,$3,$4,$5)
            """,
            index_version, args.include_draft, len(accepted), len(rejected),
            json.dumps(rejected, ensure_ascii=False, default=str),
        )

        print(f"\n=== XONG ===")
        print(f"Chap nhan: {len(accepted)} asset | Tu choi: {len(rejected)} asset")
        print(f"index_version vua ghi: {index_version}")
        print("\nDay CHUA phai index dang active cho retrieval. Kiem tra ky ket qua o tren,")
        print("roi chay lenh sau de kich hoat (atomic switch):")
        print(f"""
docker compose exec db psql -U alpha3s -d alpha3s -c \\
  "INSERT INTO kb_config (key, value) VALUES ('active_index_version', '{index_version}') \\
   ON CONFLICT (key) DO UPDATE SET value = '{index_version}';\"
""")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
