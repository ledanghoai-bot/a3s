-- Migration 021: Inventory core (I-B M2 — Order and Inventory Correctness). Spec §9.1–9.4, §6.
-- inventory_locations / inventory_balances / inventory_reservations / inventory_movements.
-- Invariants DB-enforced: on_hand>=0, reserved>=0, reserved<=on_hand; movement delta-consistency;
-- ledger append-only (trigger chặn UPDATE/DELETE). Expand-only, forward, self-validating postcondition.
-- transactional: true

-- ===========================================================================
-- 9.1 inventory_locations — chỉ MỘT default active (partial unique index)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS inventory_locations (
  id            BIGSERIAL PRIMARY KEY,
  code          TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  location_type TEXT NOT NULL CHECK (location_type IN ('fulfillment','store','warehouse')),
  is_default    BOOLEAN NOT NULL DEFAULT FALSE,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS inventory_locations_one_default_idx
  ON inventory_locations ((is_default)) WHERE is_default AND is_active;

-- ===========================================================================
-- 9.2 inventory_balances — operational state; available = on_hand - reserved (expression, không lưu)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS inventory_balances (
  location_id BIGINT NOT NULL REFERENCES inventory_locations(id),
  product_id  BIGINT NOT NULL REFERENCES products(id),
  on_hand     INTEGER NOT NULL DEFAULT 0 CHECK (on_hand >= 0),
  reserved    INTEGER NOT NULL DEFAULT 0 CHECK (reserved >= 0),
  version     BIGINT  NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (location_id, product_id),
  CONSTRAINT inventory_balances_reserved_le_onhand CHECK (reserved <= on_hand)
);

-- ===========================================================================
-- 9.3 inventory_reservations — active reservation duy nhất cho (order_item, location)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS inventory_reservations (
  id                  UUID PRIMARY KEY,
  order_id            BIGINT NOT NULL REFERENCES orders(id),
  order_item_id       BIGINT NOT NULL REFERENCES order_items(id),
  location_id         BIGINT NOT NULL REFERENCES inventory_locations(id),
  product_id          BIGINT NOT NULL REFERENCES products(id),
  quantity_initial    INTEGER NOT NULL CHECK (quantity_initial > 0),
  quantity_remaining  INTEGER NOT NULL CHECK (quantity_remaining >= 0),
  status              TEXT NOT NULL CHECK (status IN ('active','fulfilled','released','expired')),
  expires_at          TIMESTAMPTZ NULL,
  idempotency_key     TEXT NOT NULL UNIQUE,
  created_command_id  UUID NULL REFERENCES command_executions(id),
  terminal_command_id UUID NULL REFERENCES command_executions(id),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  terminal_at         TIMESTAMPTZ NULL,
  CONSTRAINT inventory_reservations_remaining_le_initial CHECK (quantity_remaining <= quantity_initial)
);
CREATE UNIQUE INDEX IF NOT EXISTS inventory_reservations_one_active_idx
  ON inventory_reservations (order_item_id, location_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS inventory_reservations_expiry_idx
  ON inventory_reservations (expires_at) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS inventory_reservations_order_idx ON inventory_reservations (order_id);
CREATE INDEX IF NOT EXISTS inventory_reservations_balance_idx ON inventory_reservations (location_id, product_id);

-- ===========================================================================
-- 9.4 inventory_movements — immutable ledger (append-only), delta-consistent
-- ===========================================================================
CREATE TABLE IF NOT EXISTS inventory_movements (
  id                UUID PRIMARY KEY,
  location_id       BIGINT NOT NULL REFERENCES inventory_locations(id),
  product_id        BIGINT NOT NULL REFERENCES products(id),
  reservation_id    UUID NULL REFERENCES inventory_reservations(id),
  order_id          BIGINT NULL REFERENCES orders(id),
  order_item_id     BIGINT NULL REFERENCES order_items(id),
  movement_type     TEXT NOT NULL CHECK (movement_type IN (
                       'opening_balance','reserve','reservation_release','reservation_expire',
                       'fulfillment_consume','return_to_available','return_damaged',
                       'adjustment_increase','adjustment_decrease')),
  on_hand_delta     INTEGER NOT NULL,
  reserved_delta    INTEGER NOT NULL,
  before_on_hand    INTEGER NOT NULL,
  after_on_hand     INTEGER NOT NULL,
  before_reserved   INTEGER NOT NULL,
  after_reserved    INTEGER NOT NULL,
  reference_type    TEXT NOT NULL,
  reference_id      TEXT NOT NULL,
  idempotency_key   TEXT NOT NULL UNIQUE,
  actor_type        TEXT NOT NULL,
  actor_id          TEXT NOT NULL,
  reason            TEXT NULL,
  correlation_id    UUID NOT NULL,
  command_id        UUID NULL REFERENCES command_executions(id),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT inventory_movements_onhand_delta_chk CHECK (after_on_hand = before_on_hand + on_hand_delta),
  CONSTRAINT inventory_movements_reserved_delta_chk CHECK (after_reserved = before_reserved + reserved_delta)
);
CREATE INDEX IF NOT EXISTS inventory_movements_balance_idx ON inventory_movements (location_id, product_id, created_at);
CREATE INDEX IF NOT EXISTS inventory_movements_reservation_idx ON inventory_movements (reservation_id);
CREATE INDEX IF NOT EXISTS inventory_movements_order_idx ON inventory_movements (order_id);
CREATE INDEX IF NOT EXISTS inventory_movements_ref_idx ON inventory_movements (reference_type, reference_id);

-- ===========================================================================
-- Append-only enforcement (§9.8): runtime KHÔNG UPDATE/DELETE movement.
-- ===========================================================================
CREATE OR REPLACE FUNCTION inventory_movements_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'inventory_movements la append-only (khong UPDATE/DELETE); correction phai tao movement moi';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS inventory_movements_no_update ON inventory_movements;
CREATE TRIGGER inventory_movements_no_update
  BEFORE UPDATE OR DELETE ON inventory_movements
  FOR EACH ROW EXECUTE FUNCTION inventory_movements_append_only();

-- bump updated_at cho balances (locations/reservations giữ ở service layer)
CREATE OR REPLACE FUNCTION m2_set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS inventory_balances_before_update ON inventory_balances;
CREATE TRIGGER inventory_balances_before_update
  BEFORE UPDATE ON inventory_balances FOR EACH ROW EXECUTE FUNCTION m2_set_updated_at();
DROP TRIGGER IF EXISTS inventory_reservations_before_update ON inventory_reservations;
CREATE TRIGGER inventory_reservations_before_update
  BEFORE UPDATE ON inventory_reservations FOR EACH ROW EXECUTE FUNCTION m2_set_updated_at();

-- ===========================================================================
-- Postcondition fail-closed
-- ===========================================================================
DO $$
DECLARE missing TEXT := '';
BEGIN
  IF to_regclass('public.inventory_locations')    IS NULL THEN missing := missing || ' inventory_locations'; END IF;
  IF to_regclass('public.inventory_balances')     IS NULL THEN missing := missing || ' inventory_balances'; END IF;
  IF to_regclass('public.inventory_reservations') IS NULL THEN missing := missing || ' inventory_reservations'; END IF;
  IF to_regclass('public.inventory_movements')    IS NULL THEN missing := missing || ' inventory_movements'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='inventory_balances_reserved_le_onhand')
    THEN missing := missing || ' reserved_le_onhand'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='inventory_movements_onhand_delta_chk')
    THEN missing := missing || ' onhand_delta_chk'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='inventory_reservations_one_active_idx')
    THEN missing := missing || ' one_active_idx'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='inventory_movements_no_update')
    THEN missing := missing || ' movements_append_only_trigger'; END IF;
  IF missing <> '' THEN RAISE EXCEPTION '021 postcondition FAIL — thieu:%', missing; END IF;
END $$;
