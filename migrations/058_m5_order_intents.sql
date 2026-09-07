-- 058 M5 order-intent durable state machine (CA Directive 223 + Amendment 224).
-- Server-owned order intent: which messages/actions belong to ONE prospective order (order_intent_id)
-- + what operation is permitted now (state). Stable fingerprints (khong dung resolution-UUID lam semantic
-- identity). At-most-one committed order/intent o tang DB. Additive + reversible (rollback cuoi file).

CREATE TABLE IF NOT EXISTS order_intents (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  -- Ownership server-derived (KHONG lay tu LLM/body). Cross-customer reuse bi cam (index ben duoi).
  customer_id                 BIGINT      NOT NULL REFERENCES customers(id),
  conversation_id             BIGINT      REFERENCES conversations(id),
  channel                     TEXT        NOT NULL CHECK (channel IN ('telegram_customer','messenger','dashboard')),
  -- State machine (Amendment 224 §2).
  state                       TEXT        NOT NULL DEFAULT 'COLLECTING'
                              CHECK (state IN ('COLLECTING','ADDRESS_CHECK','NEEDS_CLARIFICATION',
                                               'READY_TO_COMMIT','COMMITTING','COMMITTED','RETRYING',
                                               'REJECTED','CANCELLED','ESCALATED','EXPIRED')),
  -- Optimistic concurrency: moi transition BAT BUOC compare-and-set theo state_version.
  state_version               INTEGER     NOT NULL DEFAULT 0,
  -- Canonical fingerprints (Amendment 224 §5). order_fingerprint = hash(SKU+qty+contact-fields+
  -- verified_address_fingerprint). verified_address_fingerprint = hash(dataset_version+province_code+
  -- ward_code+one-way delivery-detail). KHONG chua PII raw. Nullable khi chua du/ chua verify.
  order_fingerprint           TEXT,
  verified_address_fingerprint TEXT,
  -- verified_resolution_id giu cho AUDIT + exact binding; KHONG dung UUID nay lam semantic hash identity.
  verified_resolution_id      UUID        REFERENCES address_resolution(id),
  -- Ket qua commit (chi set khi COMMITTED). At-most-one committed order/intent (unique ben duoi).
  committed_order_id          BIGINT      REFERENCES orders(id),
  -- Terminal reason/error (REJECTED/CANCELLED/ESCALATED/EXPIRED).
  terminal_reason             TEXT,
  error_code                  TEXT,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- expires_at chi de GC/recovery abandoned state — KHONG dinh nghia semantic 2 don co giong nhau khong.
  expires_at                  TIMESTAMPTZ
);

-- At-most-one committed order per intent (mot committed order thuoc dung 1 intent).
CREATE UNIQUE INDEX IF NOT EXISTS oi_one_committed_order
  ON order_intents(committed_order_id) WHERE committed_order_id IS NOT NULL;

-- 1 open intent moi (customer, conversation) = "prospective order HIEN TAI" cua hoi thoai (CA 225-01).
-- Correction (doi dia chi/so luong) CAP NHAT CHINH intent nay (re-enter ADDRESS_CHECK, tang version) —
-- KHONG tao intent song song. Don moi that su SAU commit -> intent moi (cai cu da COMMITTED, khong con open).
-- Ngan 2 open intent song song cho cung hoi thoai (control plane don nhat).
CREATE UNIQUE INDEX IF NOT EXISTS oi_one_open_per_conversation
  ON order_intents(customer_id, conversation_id)
  WHERE state IN ('COLLECTING','ADDRESS_CHECK','NEEDS_CLARIFICATION','READY_TO_COMMIT','COMMITTING','RETRYING');

-- Lookup theo owner + state (routing, GC expired).
CREATE INDEX IF NOT EXISTS oi_owner_state ON order_intents(customer_id, channel, state);
CREATE INDEX IF NOT EXISTS oi_expiry ON order_intents(expires_at) WHERE expires_at IS NOT NULL;

-- updated_at tu dong.
CREATE OR REPLACE FUNCTION oi_touch_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS oi_set_updated_at ON order_intents;
CREATE TRIGGER oi_set_updated_at BEFORE UPDATE ON order_intents
  FOR EACH ROW EXECUTE FUNCTION oi_touch_updated_at();

-- ROLLBACK (runbook):
--   DROP TABLE IF EXISTS order_intents CASCADE;
--   DROP FUNCTION IF EXISTS oi_touch_updated_at();
