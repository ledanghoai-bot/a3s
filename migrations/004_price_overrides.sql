-- Migration 004: staff duyet gia/so luong dac biet cho don hang lon (issue #8)
-- Chay THU CONG tren DB da ton tai, giong 002/003:
--   docker compose exec db psql -U alpha3s -d alpha3s -f /docker-entrypoint-initdb.d/004_price_overrides.sql

CREATE TABLE IF NOT EXISTS price_overrides (
  id BIGSERIAL PRIMARY KEY,
  customer_id BIGINT REFERENCES customers(id),
  quantity INTEGER NOT NULL,
  unit_price_vnd INTEGER NOT NULL,
  note TEXT,
  used BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS price_overrides_customer_id_idx ON price_overrides(customer_id);
