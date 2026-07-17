-- Migration 008: FAQ CRUD qua dashboard, tu dong re-ingest RAG khi sua/xoa
-- (issue #8 - Bat 2). Khac voi data/knowledge/*.md (file tinh, nap 1 lan qua
-- scripts/ingest.py), FAQ tao qua dashboard luu truc tiep trong DB, moi entry
-- gan dung 1 dong trong knowledge_chunks qua faq_entry_id - sua/xoa entry se
-- tu dong xoa/tao lai chunk + embedding tuong ung, khong can chay lai ingest.py.
--
-- Chay THU CONG tren DB da ton tai, giong cac migration truoc:
--   docker compose exec db psql -U alpha3s -d alpha3s -f /docker-entrypoint-initdb.d/008_faq_entries.sql

CREATE TABLE IF NOT EXISTS faq_entries (
  id BIGSERIAL PRIMARY KEY,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE knowledge_chunks
  ADD COLUMN IF NOT EXISTS faq_entry_id BIGINT REFERENCES faq_entries(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS knowledge_chunks_faq_entry_id_idx ON knowledge_chunks(faq_entry_id);
