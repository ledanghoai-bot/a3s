-- Migration 011: Knowledge Base V2 (M1 Ingestion + M2 Retrieval) - thu nghiem
-- song song voi he thong RAG production hien tai (knowledge_chunks), KHONG
-- thay the. Xem docs/KNOWLEDGE_BASE_V2_DESIGN-VI.md cho thiet ke day du.
--
-- Chay THU CONG tren DB da ton tai, giong cac migration truoc:
--   docker compose exec db psql -U alpha3s -d alpha3s -f /docker-entrypoint-initdb.d/011_knowledge_base_v2.sql

-- Nguon that cho tung file Skill/Playbook da ingest
CREATE TABLE IF NOT EXISTS kb_assets (
  id TEXT PRIMARY KEY,               -- vd 'SKL-FAQ-003' (lay tu front matter, khong tu sinh)
  title TEXT,
  domain TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  status TEXT NOT NULL,              -- draft/review/approved/locked/superseded/archived
  version TEXT,
  priority TEXT,                     -- P1-P4
  source_path TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT 'vi',
  raw_frontmatter JSONB,
  content_hash TEXT NOT NULL,
  ingested_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Knowledge Unit - don vi chunk theo heading
CREATE TABLE IF NOT EXISTS kb_units (
  id TEXT PRIMARY KEY,               -- vd 'KU-FAQ-003-005', on dinh qua cac lan ingest lai
  asset_id TEXT NOT NULL REFERENCES kb_assets(id) ON DELETE CASCADE,
  heading TEXT,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  domain TEXT NOT NULL,
  status TEXT NOT NULL,
  priority TEXT,
  language TEXT NOT NULL DEFAULT 'vi',
  embedding vector(384),
  search_tsv TSVECTOR,
  index_version INTEGER NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS kb_units_embedding_idx ON kb_units USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS kb_units_tsv_idx ON kb_units USING GIN (search_tsv);
CREATE INDEX IF NOT EXISTS kb_units_asset_id_idx ON kb_units(asset_id);
CREATE INDEX IF NOT EXISTS kb_units_index_version_idx ON kb_units(index_version);

-- 1 dong / lan chay ingest - bao cao + can cu quyet dinh atomic switch
CREATE TABLE IF NOT EXISTS kb_ingestion_reports (
  id BIGSERIAL PRIMARY KEY,
  index_version INTEGER NOT NULL,
  run_at TIMESTAMPTZ DEFAULT now(),
  include_draft BOOLEAN NOT NULL,
  accepted_count INTEGER NOT NULL,
  rejected_count INTEGER NOT NULL,
  rejected_files JSONB NOT NULL
);

-- Config nho, dung cho atomic switch (vd active_index_version)
CREATE TABLE IF NOT EXISTS kb_config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
