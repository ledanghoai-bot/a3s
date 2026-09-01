-- Migration 053: M5 Phase 2 — Address resolution (current verify + legacy->current mapping + ambiguity).
--
-- Authority: CA Directive 108 (M5 Phase 2). PHAM VI: address_resolution records (immutable) + permission
-- address.resolve. CHUA customer confirmation/staff queue (054), CHUA order/quote wiring, CHUA order FK/snapshot.
-- Additive + idempotent + non-destroy. Giu nguyen free-text address (customers.address, orders.shipping_address)
-- + M4 signing controls. Khong secret. Resolution la HO SO BAT BIEN (append-only): khong UPDATE/DELETE.

BEGIN;

-- 1. Permission thuc hien resolution (server-side enforce; doc dung address.view da seed o 016).
INSERT INTO permissions (key, description) VALUES
  ('address.resolve', 'Thuc hien verify/mapping dia chi (tao resolution record)')
ON CONFLICT (key) DO NOTHING;

-- 2. Ban ghi resolution (bat bien). subject_id la tham chieu TEXT (KHONG FK order/customer o Phase 2).
CREATE TABLE IF NOT EXISTS address_resolution (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_type    TEXT NOT NULL CHECK (subject_type IN ('customer','order','adhoc')),
  subject_id      TEXT,                              -- tham chieu mem (khong FK Phase 2)
  raw_province    TEXT, raw_district TEXT, raw_ward TEXT, street_text TEXT,
  province_code   TEXT, district_code TEXT, ward_code TEXT,
  dataset_version TEXT REFERENCES admin_unit_dataset(version),
  as_of           DATE,
  status          TEXT NOT NULL
                  CHECK (status IN ('auto_verified','needs_customer_confirmation','needs_staff_review',
                                    'failed','unverified')),
  method          TEXT CHECK (method IN ('current','legacy_mapping','manual',NULL)),
  confidence      NUMERIC(4,3) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  candidates      JSONB NOT NULL DEFAULT '[]'::jsonb,
  rules_applied   JSONB NOT NULL DEFAULT '[]'::jsonb,
  idempotency_key TEXT UNIQUE,
  resolved_by     TEXT,                              -- actor tu session (khong tin body)
  reason          TEXT,
  ticket          TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ar_no_secret
    CHECK (NOT ((candidates::text || rules_applied::text) ~* '(pin_secret|private_key|"token"|password|-----BEGIN)'))
);
CREATE INDEX IF NOT EXISTS ar_subject ON address_resolution (subject_type, subject_id);
CREATE INDEX IF NOT EXISTS ar_status  ON address_resolution (status);

-- 3. Ho so BAT BIEN: khong UPDATE, khong DELETE (re-resolution -> ban ghi MOI).
CREATE OR REPLACE FUNCTION ar_forbid_mutate()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'address_resolution la ho so bat bien — khong duoc %; tao ban ghi moi', TG_OP;
END;
$$;
DROP TRIGGER IF EXISTS ar_no_update ON address_resolution;
CREATE TRIGGER ar_no_update BEFORE UPDATE ON address_resolution
  FOR EACH ROW EXECUTE FUNCTION ar_forbid_mutate();
DROP TRIGGER IF EXISTS ar_no_delete ON address_resolution;
CREATE TRIGGER ar_no_delete BEFORE DELETE ON address_resolution
  FOR EACH ROW EXECUTE FUNCTION ar_forbid_mutate();

COMMIT;

-- ROLLBACK:
--   DROP TRIGGER IF EXISTS ar_no_update ON address_resolution;
--   DROP TRIGGER IF EXISTS ar_no_delete ON address_resolution;
--   DROP FUNCTION IF EXISTS ar_forbid_mutate();
--   DROP TABLE IF EXISTS address_resolution;
--   DELETE FROM permissions WHERE key='address.resolve';
