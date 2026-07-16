-- Migration 003: rang buoc trang thai don hang cho dashboard (issue #8)
-- Chay THU CONG tren DB da ton tai, giong 002:
--   docker compose exec db psql -U alpha3s -d alpha3s -f /docker-entrypoint-initdb.d/003_orders_status_check.sql

ALTER TABLE orders
  ADD CONSTRAINT orders_status_check
  CHECK (status IN ('new', 'confirmed', 'shipped', 'done', 'cancelled'));
