-- Migration 009: dong bo RAG tu dong theo tung san pham (issue #8 - "Lop 2"
-- theo de xuat 17/7: thay vi bom toan bo chi tiet san pham vao system prompt
-- moi luot chat (khong scale khi nhieu SKU), moi san pham co 1 knowledge_chunk
-- rieng, CRUD qua dashboard tu dong tao/sua/xoa chunk nay - giong het pattern
-- da lam cho FAQ (faq_entries + knowledge_chunks.faq_entry_id, migration 008).
--
-- Chay THU CONG tren DB da ton tai, giong cac migration truoc:
--   docker compose exec db psql -U alpha3s -d alpha3s -f /docker-entrypoint-initdb.d/009_product_knowledge.sql

ALTER TABLE knowledge_chunks
  ADD COLUMN IF NOT EXISTS product_id BIGINT REFERENCES products(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS knowledge_chunks_product_id_idx ON knowledge_chunks(product_id);
