-- Migration 026: inventory_backorders (I-B M2 PO-change: never-drop-order on out-of-stock).
-- PO-directed behavior change (deviates CA spec §10.1 "insufficient -> no order"), gated flag
-- M2_BACKORDER_ESCALATION mac dinh TAT. Khi thieu hang: giu don o inventory_status='unreserved' +
-- ghi backorder row -> escalate inventory topup; topup (adjustment_increase) auto-reserve FIFO.
-- Append-only-ish: mot active backorder duy nhat cho moi order_item. Expand-only, forward.
-- transactional: true

CREATE TABLE IF NOT EXISTS inventory_backorders (
  id                   UUID PRIMARY KEY,
  order_id             BIGINT NOT NULL REFERENCES orders(id),
  order_item_id        BIGINT NOT NULL REFERENCES order_items(id),
  location_id          BIGINT NOT NULL REFERENCES inventory_locations(id),
  product_id           BIGINT NOT NULL REFERENCES products(id),
  quantity             INTEGER NOT NULL CHECK (quantity > 0),
  status               TEXT NOT NULL CHECK (status IN ('active','reserved','cancelled')),
  idempotency_key      TEXT NOT NULL UNIQUE,
  created_command_id   UUID NULL REFERENCES command_executions(id),
  reserved_command_id  UUID NULL REFERENCES command_executions(id),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at          TIMESTAMPTZ NULL
);
-- mot active backorder duy nhat cho moi order_item
CREATE UNIQUE INDEX IF NOT EXISTS inventory_backorders_one_active_idx
  ON inventory_backorders (order_item_id) WHERE status = 'active';
-- FIFO drain theo (location, product, created_at)
CREATE INDEX IF NOT EXISTS inventory_backorders_fifo_idx
  ON inventory_backorders (location_id, product_id, created_at) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS inventory_backorders_order_idx ON inventory_backorders (order_id);

DO $$
BEGIN
  IF to_regclass('public.inventory_backorders') IS NULL THEN
    RAISE EXCEPTION '026 postcondition FAIL: thieu inventory_backorders'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='inventory_backorders_one_active_idx') THEN
    RAISE EXCEPTION '026 postcondition FAIL: thieu one_active_idx'; END IF;
END $$;
