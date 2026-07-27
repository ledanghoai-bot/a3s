-- Migration 022: order_events (append-only) + orders inventory columns (I-B M2). Spec §9.5, §9.7, §7.4.
-- Two-axis: giữ orders.status (business) + thêm inventory_status/location/status_updated_at.
-- order_events append-only (runtime chỉ INSERT). Expand-only, forward, self-validating.
-- transactional: true

-- ===========================================================================
-- 9.5 order_events — append-only timeline; một transition = một event idempotent
-- ===========================================================================
CREATE TABLE IF NOT EXISTS order_events (
  id                        UUID PRIMARY KEY,
  order_id                  BIGINT NOT NULL REFERENCES orders(id),
  event_type                TEXT NOT NULL,
  event_version             SMALLINT NOT NULL CHECK (event_version > 0),
  from_status               TEXT NULL,
  to_status                 TEXT NOT NULL,
  inventory_status_before   TEXT NULL,
  inventory_status_after    TEXT NULL,
  actor_type                TEXT NOT NULL,
  actor_id                  TEXT NOT NULL,
  reason                    TEXT NULL,
  command_id                UUID NULL REFERENCES command_executions(id),
  correlation_id            UUID NOT NULL,
  causation_id              TEXT NULL,
  idempotency_key           TEXT NOT NULL UNIQUE,
  metadata_redacted         JSONB NOT NULL DEFAULT '{}',
  occurred_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS order_events_order_idx ON order_events (order_id, occurred_at);
CREATE INDEX IF NOT EXISTS order_events_correlation_idx ON order_events (correlation_id);

CREATE OR REPLACE FUNCTION order_events_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'order_events la append-only (khong UPDATE/DELETE)';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS order_events_no_update ON order_events;
CREATE TRIGGER order_events_no_update
  BEFORE UPDATE OR DELETE ON order_events
  FOR EACH ROW EXECUTE FUNCTION order_events_append_only();

-- ===========================================================================
-- 9.7 orders inventory columns — KHÔNG đổi tên cột status cũ (giảm migration risk)
-- ===========================================================================
ALTER TABLE orders ADD COLUMN IF NOT EXISTS inventory_status TEXT NOT NULL DEFAULT 'unreserved';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS inventory_location_id BIGINT NULL REFERENCES inventory_locations(id);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- CHECK inventory_status hợp lệ (§7.4). Thêm riêng để idempotent (drop-if-exists trước).
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_inventory_status_check;
ALTER TABLE orders ADD CONSTRAINT orders_inventory_status_check
  CHECK (inventory_status IN ('unreserved','reserved','partially_reserved','fulfilled','released','return_inspection'));

-- ===========================================================================
-- Postcondition
-- ===========================================================================
DO $$
DECLARE missing TEXT := '';
BEGIN
  IF to_regclass('public.order_events') IS NULL THEN missing := missing || ' order_events'; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='orders' AND column_name='inventory_status')
    THEN missing := missing || ' orders.inventory_status'; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='orders' AND column_name='inventory_location_id')
    THEN missing := missing || ' orders.inventory_location_id'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='order_events_no_update')
    THEN missing := missing || ' order_events_append_only'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='orders_inventory_status_check')
    THEN missing := missing || ' orders_inventory_status_check'; END IF;
  IF missing <> '' THEN RAISE EXCEPTION '022 postcondition FAIL — thieu:%', missing; END IF;
END $$;
