-- Migration 006: cot "handled" cho tung note rieng le (issue #8 - nang cap UX
-- hien thi tung note/approve rieng, thay vi gop chung 1 cot Action cho ca hoi thoai).
-- Chay THU CONG tren DB da ton tai, giong cac migration truoc:
--   docker compose exec db psql -U alpha3s -d alpha3s -f /docker-entrypoint-initdb.d/006_messages_handled.sql

ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS handled BOOLEAN NOT NULL DEFAULT FALSE;

-- Luu y: price_overrides da co san cot "used" - tai su dung lam co "da tao don"
-- cho tung approve, khong can them cot moi cho bang do.
