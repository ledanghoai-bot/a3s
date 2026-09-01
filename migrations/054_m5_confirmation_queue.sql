-- Migration 054: M5 Phase 3 — Customer confirmation workflow + durable staff review queue.
--
-- Authority: CA Directive 112 (M5 Phase 3). PHAM VI: confirmation request + review queue cho resolution
-- ket qua needs_customer_confirmation / needs_staff_review. CHUA order/quote/snapshot wiring, khong active
-- dataset production, khong gui thong bao that. Additive/idempotent/non-destroy. Phase 1/2 + M4 giu nguyen.
--
-- Ghi chu: mo rong status address_resolution them 'customer_confirmed'/'staff_confirmed' (ket qua sau khi
-- khach xac nhan / staff quyet). Ket qua confirm = INSERT ban ghi resolution MOI (address_resolution append-
-- only tu Phase 2) — khong UPDATE ban cu.

BEGIN;

-- 0. Mo rong tap status resolution (additive; ket qua confirm). Idempotent: drop-if-exists + add.
ALTER TABLE address_resolution DROP CONSTRAINT IF EXISTS address_resolution_status_check;
ALTER TABLE address_resolution ADD CONSTRAINT address_resolution_status_check
  CHECK (status IN ('auto_verified','needs_customer_confirmation','needs_staff_review','failed',
                    'unverified','customer_confirmed','staff_confirmed'));

-- 1. Permission phat hanh/huy confirmation request (staff/system). Staff decision dung address.review;
--    override dung address.override (da seed 016).
INSERT INTO permissions (key, description) VALUES
  ('address.confirm', 'Phat hanh/huy customer confirmation request (khong gui thong bao that o dormant)')
ON CONFLICT (key) DO NOTHING;

-- 2. Customer confirmation request. candidate_snapshot + resolution_id BAT BIEN sau phat hanh (anti-substitution).
CREATE TABLE IF NOT EXISTS address_confirmation_request (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  resolution_id      UUID NOT NULL REFERENCES address_resolution(id),
  subject_type       TEXT NOT NULL CHECK (subject_type IN ('customer','order','adhoc')),
  subject_id         TEXT,
  candidate_snapshot JSONB NOT NULL,                 -- dong bang tu resolution luc phat hanh
  channel            TEXT NOT NULL,                  -- messenger/telegram/web/staff (chi la field)
  bound_ref          TEXT NOT NULL,                  -- session/channel binding: ai duoc phep phan hoi
  state              TEXT NOT NULL DEFAULT 'issued'
                     CHECK (state IN ('issued','confirmed','rejected','expired','cancelled')),
  expiry             TIMESTAMPTZ NOT NULL,
  chosen_code        TEXT,                           -- ma khach chon (phai nam trong snapshot)
  result_resolution_id UUID REFERENCES address_resolution(id),  -- resolution moi sinh ra khi confirmed
  idempotency_key    TEXT UNIQUE,
  issued_by          TEXT NOT NULL,
  responded_by       TEXT,
  responded_at       TIMESTAMPTZ,
  reason             TEXT, ticket TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT acr_no_secret
    CHECK (NOT (candidate_snapshot::text ~* '(pin_secret|private_key|"token"|password|-----BEGIN)'))
);
CREATE INDEX IF NOT EXISTS acr_state ON address_confirmation_request (state, expiry);
CREATE INDEX IF NOT EXISTS acr_resolution ON address_confirmation_request (resolution_id);

-- 3. Durable staff review queue.
CREATE TABLE IF NOT EXISTS address_review_queue (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  resolution_id      UUID NOT NULL REFERENCES address_resolution(id),
  subject_type       TEXT NOT NULL CHECK (subject_type IN ('customer','order','adhoc')),
  subject_id         TEXT,
  candidate_snapshot JSONB NOT NULL,
  state              TEXT NOT NULL DEFAULT 'open'
                     CHECK (state IN ('open','assigned','resolved','rejected','expired')),
  assignee           TEXT,
  reason             TEXT,
  chosen_code        TEXT,
  is_override        BOOLEAN NOT NULL DEFAULT false,
  approver           TEXT,                            -- approver doc lap khi override anh huong fulfillment
  result_resolution_id UUID REFERENCES address_resolution(id),
  ticket             TEXT,
  idempotency_key    TEXT UNIQUE,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  assigned_at        TIMESTAMPTZ,
  resolved_at        TIMESTAMPTZ,
  resolved_by        TEXT
);
CREATE INDEX IF NOT EXISTS arq_state ON address_review_queue (state);
CREATE INDEX IF NOT EXISTS arq_resolution ON address_review_queue (resolution_id);

-- 4. Anti-substitution: candidate_snapshot + resolution_id BAT BIEN sau insert; khong DELETE (ca hai bang).
CREATE OR REPLACE FUNCTION m5_guard_snapshot_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION '% la ho so — khong duoc DELETE', TG_TABLE_NAME;
  END IF;
  IF NEW.candidate_snapshot IS DISTINCT FROM OLD.candidate_snapshot
  OR NEW.resolution_id IS DISTINCT FROM OLD.resolution_id THEN
    RAISE EXCEPTION 'candidate_snapshot/resolution_id bat bien sau phat hanh (anti-substitution)';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS acr_guard ON address_confirmation_request;
CREATE TRIGGER acr_guard BEFORE UPDATE OR DELETE ON address_confirmation_request
  FOR EACH ROW EXECUTE FUNCTION m5_guard_snapshot_immutable();
DROP TRIGGER IF EXISTS arq_guard ON address_review_queue;
CREATE TRIGGER arq_guard BEFORE UPDATE OR DELETE ON address_review_queue
  FOR EACH ROW EXECUTE FUNCTION m5_guard_snapshot_immutable();

COMMIT;

-- ROLLBACK:
--   DROP TRIGGER IF EXISTS arq_guard ON address_review_queue;
--   DROP TRIGGER IF EXISTS acr_guard ON address_confirmation_request;
--   DROP FUNCTION IF EXISTS m5_guard_snapshot_immutable();
--   DROP TABLE IF EXISTS address_review_queue; DROP TABLE IF EXISTS address_confirmation_request;
--   DELETE FROM permissions WHERE key='address.confirm';
--   ALTER TABLE address_resolution DROP CONSTRAINT IF EXISTS address_resolution_status_check;
--   ALTER TABLE address_resolution ADD CONSTRAINT address_resolution_status_check
--     CHECK (status IN ('auto_verified','needs_customer_confirmation','needs_staff_review','failed','unverified'));
