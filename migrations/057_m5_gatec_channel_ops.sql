-- Migration 057: M5 Gate C — Customer channel & staff operations.
-- (1) Seed permission `address.review` (routes m5_address_workflow enforce require_permission('address.review')
--     nhung chua migration nao seed -> review endpoint 403 trong RBAC strict; 057 va lo hong nay).
-- (2) Confirmation delivery OUTBOX (durable LOCAL/test transport): enqueue-after-commit + dedupe + bounded retry +
--     terminal/dead-letter. KHONG gui provider that (transport la callable local/fake o service layer).
-- PHAM VI: thuan cong them (1 perm + 1 bang + trigger guard). KHONG dung bang khac. Idempotent.
-- transactional: true

BEGIN;

-- 1. address.review permission (catalog). Khong grant role o day (provisioning rieng).
INSERT INTO permissions (key, description) VALUES
  ('address.review', 'M5 staff review-queue action (assign/resolve/expire) tren address_review_queue')
ON CONFLICT (key) DO NOTHING;

-- 2. Confirmation delivery outbox — durable local transport.
CREATE TABLE IF NOT EXISTS address_confirmation_outbox (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id      UUID NOT NULL REFERENCES address_confirmation_request(id),
  channel         TEXT NOT NULL,
  payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
  dedupe_key      TEXT NOT NULL UNIQUE,                       -- dedupe: 1 lan gui/logical event
  state           TEXT NOT NULL DEFAULT 'pending'
                  CHECK (state IN ('pending','sent','failed','dead_letter')),
  attempts        INT NOT NULL DEFAULT 0,
  max_attempts    INT NOT NULL DEFAULT 5,
  next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_error      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at         TIMESTAMPTZ,
  -- KHONG chua secret trong payload (giong acr_no_secret cua 054).
  CONSTRAINT aco_no_secret CHECK (payload::text !~* '(password|secret|token|api[_-]?key|authorization)')
);
CREATE INDEX IF NOT EXISTS idx_aco_due ON address_confirmation_outbox (next_attempt_at)
  WHERE state IN ('pending','failed');

-- 3. Guard: KHONG DELETE (durable); request_id/payload/dedupe_key BAT BIEN (chi doi state/attempts/timestamps).
CREATE OR REPLACE FUNCTION m5_guard_outbox() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'address_confirmation_outbox la ho so durable — khong duoc DELETE';
  END IF;
  IF NEW.request_id <> OLD.request_id OR NEW.payload::text <> OLD.payload::text
     OR NEW.dedupe_key <> OLD.dedupe_key OR NEW.created_at <> OLD.created_at THEN
    RAISE EXCEPTION 'address_confirmation_outbox: request_id/payload/dedupe_key/created_at bat bien';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS aco_guard ON address_confirmation_outbox;
CREATE TRIGGER aco_guard BEFORE UPDATE OR DELETE ON address_confirmation_outbox
  FOR EACH ROW EXECUTE FUNCTION m5_guard_outbox();

COMMIT;
