-- Migration 055: M5 Phase 4 — Address snapshot cho order + quote_shipping wiring (dormant/shadow).
--
-- Authority: CA Directive 116 (M5 Phase 4). Additive/nullable/backward-compat. CHUA backfill hoac mutate
-- customer/order production; CHUA bat quote/fulfillment enforcement (feature flag shadow OFF). Giu nguyen
-- free-text (customers.address, orders.shipping_address) + M4 signing. Snapshot BAT BIEN sau commit.

BEGIN;

-- 1. Permission bind verified address vao order.
INSERT INTO permissions (key, description) VALUES
  ('address.bind', 'Bind verified address (resolution) vao order + tao snapshot bat bien')
ON CONFLICT (key) DO NOTHING;

-- 2. Order: them nullable verified_address_id + dataset_version (KHONG bo shipping_address free-text).
ALTER TABLE orders ADD COLUMN IF NOT EXISTS verified_address_id UUID REFERENCES address_resolution(id);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS address_dataset_version TEXT REFERENCES admin_unit_dataset(version);

-- 3. Customer: con tro resolution hien hanh (additive nullable; KHONG thay/xoa customers.address free-text).
ALTER TABLE customers ADD COLUMN IF NOT EXISTS current_address_resolution_id UUID REFERENCES address_resolution(id);

-- 4. Snapshot bat bien tai thoi diem order commit (dong bang, doc lap thay doi resolution/dataset sau do).
CREATE TABLE IF NOT EXISTS order_address_snapshot (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id            BIGINT NOT NULL REFERENCES orders(id),
  resolution_id       UUID NOT NULL REFERENCES address_resolution(id),
  province_code       TEXT, district_code TEXT, ward_code TEXT,
  province_name       TEXT, district_name TEXT, ward_name TEXT,
  street_text         TEXT,
  dataset_version     TEXT NOT NULL,
  verified_at         TIMESTAMPTZ,
  verification_method TEXT,
  provenance_ref      JSONB NOT NULL DEFAULT '{}'::jsonb,
  bound_by            TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT oas_one_per_order UNIQUE (order_id),   -- 1 snapshot / order (idempotent binding)
  CONSTRAINT oas_no_secret
    CHECK (NOT (provenance_ref::text ~* '(pin_secret|private_key|"token"|password|-----BEGIN)'))
);
CREATE INDEX IF NOT EXISTS oas_resolution ON order_address_snapshot (resolution_id);

-- 5. Append-only log thay doi dia chi customer (old/new/actor/reason/ticket/timestamp).
CREATE TABLE IF NOT EXISTS address_change_log (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_ref  TEXT,
  old_value     TEXT, new_value TEXT,
  actor         TEXT NOT NULL, reason TEXT, ticket TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS acl_customer ON address_change_log (customer_ref);

-- 6. Immutability: snapshot + change_log khong UPDATE/DELETE (ho so bat bien).
CREATE OR REPLACE FUNCTION m5_forbid_mutate_p4()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% la ho so bat bien — khong duoc %', TG_TABLE_NAME, TG_OP;
END;
$$;
DROP TRIGGER IF EXISTS oas_no_mutate ON order_address_snapshot;
CREATE TRIGGER oas_no_mutate BEFORE UPDATE OR DELETE ON order_address_snapshot
  FOR EACH ROW EXECUTE FUNCTION m5_forbid_mutate_p4();
DROP TRIGGER IF EXISTS acl_no_mutate ON address_change_log;
CREATE TRIGGER acl_no_mutate BEFORE UPDATE OR DELETE ON address_change_log
  FOR EACH ROW EXECUTE FUNCTION m5_forbid_mutate_p4();

COMMIT;

-- ROLLBACK:
--   DROP TRIGGER IF EXISTS acl_no_mutate ON address_change_log;
--   DROP TRIGGER IF EXISTS oas_no_mutate ON order_address_snapshot;
--   DROP FUNCTION IF EXISTS m5_forbid_mutate_p4();
--   DROP TABLE IF EXISTS address_change_log; DROP TABLE IF EXISTS order_address_snapshot;
--   ALTER TABLE customers DROP COLUMN IF EXISTS current_address_resolution_id;
--   ALTER TABLE orders DROP COLUMN IF EXISTS address_dataset_version;
--   ALTER TABLE orders DROP COLUMN IF EXISTS verified_address_id;
--   DELETE FROM permissions WHERE key='address.bind';
