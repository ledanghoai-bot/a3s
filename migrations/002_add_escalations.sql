-- Migration 002: human handoff (issue #7)
-- Chay file nay THU CONG tren DB da ton tai (docker-entrypoint-initdb.d chi chay
-- luc tao volume moi lan dau, khong tu ap dung cho DB dang chay):
--   docker compose exec db psql -U alpha3s -d alpha3s -f /docker-entrypoint-initdb.d/002_add_escalations.sql
-- hoac don gian hon, copy-paste noi dung file nay vao:
--   docker compose exec db psql -U alpha3s -d alpha3s

CREATE TABLE IF NOT EXISTS escalations (
  id BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT REFERENCES conversations(id),
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS escalations_conversation_id_idx ON escalations(conversation_id);
