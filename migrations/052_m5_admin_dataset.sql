-- Migration 052: M5 Phase 1 — Admin dataset versioned + provenance/license + checksum + registry.
--
-- Authority: CA Directive 104 (M5 Phase 1). PO Address Policy Record 6aec2a8f + Final Confirmation 9ca23f.
-- PHAM VI: CHI dataset hanh chinh versioned + acceptance-gate + active-version registry. CHUA verify/mapping
-- (053), CHUA customer confirmation/staff queue (054), CHUA wiring order/quote. Additive + idempotent, khong
-- DROP/pha du lieu cu. Giu nguyen free-text address (customers.address, orders.shipping_address) + M4 signing.
-- Khong auto-activate dataset moi. Chi mot version ACTIVE; version cu RETIRED, khong xoa.

BEGIN;

-- 1. Permissions (SoD dataset): custodian ingest != reviewer != PO owner manage. Enforce o control layer.
INSERT INTO permissions (key, description) VALUES
  ('address.dataset.view',    'Xem dataset hanh chinh + trang thai/registry'),
  ('address.dataset.ingest',  'Custodian (Dev/Ops) nap goi dataset staging (draft) — khong tu accept'),
  ('address.dataset.review',  'Reviewer doc lap chay acceptance gate + validation'),
  ('address.dataset.manage',  'PO Data Owner accept/activate/rollback dataset')
ON CONFLICT (key) DO NOTHING;

-- 2. Dataset (mot version = mot ban immutable). Version format VN-ADMIN-YYYY-MM-vN.
CREATE TABLE IF NOT EXISTS admin_unit_dataset (
  version         TEXT PRIMARY KEY
                  CHECK (version ~ '^VN-ADMIN-[0-9]{4}-[0-9]{2}-v[0-9]+$'),
  status          TEXT NOT NULL DEFAULT 'draft'
                  CHECK (status IN ('draft','review','accepted','active','retired','rolled_back')),
  source_url      TEXT NOT NULL,
  source_kind     TEXT NOT NULL CHECK (source_kind IN ('authoritative','cross_reference')),
  release_tag     TEXT,
  commit_ref      TEXT,
  downloaded_at   TIMESTAMPTZ,
  sha256          TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  license         TEXT NOT NULL,
  provenance      JSONB NOT NULL DEFAULT '{}'::jsonb,
  acceptance_report JSONB,
  ingested_by     TEXT,                       -- actor custodian (dinh danh khong bi mat)
  reviewed_by     TEXT,                       -- actor reviewer doc lap
  approved_by     TEXT,                       -- actor PO owner (accept)
  ticket          TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  accepted_at     TIMESTAMPTZ,
  activated_at    TIMESTAMPTZ,
  terminal_at     TIMESTAMPTZ,
  -- khong chua secret trong provenance
  CONSTRAINT aud_no_secret_provenance
    CHECK (NOT (provenance::text ~* '(pin_secret|private_key|"token"|password|-----BEGIN)'))
);
CREATE INDEX IF NOT EXISTS aud_status ON admin_unit_dataset (status);

-- Anti-substitution: sau khi ROI 'draft', cac cot nguon/checksum/license/provenance bat bien
-- (chi status + cot moc thoi gian + reviewed_by/approved_by/acceptance_report duoc doi qua control).
CREATE OR REPLACE FUNCTION aud_guard_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'draft' THEN
    IF NEW.sha256      IS DISTINCT FROM OLD.sha256
    OR NEW.source_url  IS DISTINCT FROM OLD.source_url
    OR NEW.source_kind IS DISTINCT FROM OLD.source_kind
    OR NEW.release_tag IS DISTINCT FROM OLD.release_tag
    OR NEW.commit_ref  IS DISTINCT FROM OLD.commit_ref
    OR NEW.license     IS DISTINCT FROM OLD.license
    OR NEW.provenance  IS DISTINCT FROM OLD.provenance THEN
      RAISE EXCEPTION 'admin_unit_dataset: nguon/checksum/license/provenance bat bien sau draft (anti-substitution)';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS aud_immutable ON admin_unit_dataset;
CREATE TRIGGER aud_immutable BEFORE UPDATE ON admin_unit_dataset
  FOR EACH ROW EXECUTE FUNCTION aud_guard_immutable();

CREATE OR REPLACE FUNCTION aud_forbid_delete()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'admin_unit_dataset la ho so — khong duoc DELETE (RETIRED thay vi xoa)';
END;
$$;
DROP TRIGGER IF EXISTS aud_no_delete ON admin_unit_dataset;
CREATE TRIGGER aud_no_delete BEFORE DELETE ON admin_unit_dataset
  FOR EACH ROW EXECUTE FUNCTION aud_forbid_delete();

-- 3. Don vi hanh chinh (noi dung dataset). Phan cap province/district/ward + hieu luc thoi gian.
CREATE TABLE IF NOT EXISTS admin_unit (
  dataset_version TEXT NOT NULL REFERENCES admin_unit_dataset(version),
  level           TEXT NOT NULL CHECK (level IN ('province','district','ward')),
  code            TEXT NOT NULL,
  name            TEXT NOT NULL,
  name_normalized TEXT NOT NULL,
  parent_code     TEXT,
  effective_from  DATE,
  effective_to    DATE,
  PRIMARY KEY (dataset_version, code)
);
CREATE INDEX IF NOT EXISTS au_parent ON admin_unit (dataset_version, parent_code);
CREATE INDEX IF NOT EXISTS au_norm   ON admin_unit (dataset_version, name_normalized);

-- 4. Alias (ten cu/khong dau/viet tat) phuc vu mapping. Alias KHONG override canonical (kiem o gate).
CREATE TABLE IF NOT EXISTS admin_unit_alias (
  dataset_version  TEXT NOT NULL REFERENCES admin_unit_dataset(version),
  unit_code        TEXT NOT NULL,
  alias_name       TEXT NOT NULL,
  alias_normalized TEXT NOT NULL,
  alias_kind       TEXT NOT NULL CHECK (alias_kind IN ('legacy','accentless','abbrev','other')),
  source           TEXT,
  confidence       NUMERIC(4,3) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  PRIMARY KEY (dataset_version, unit_code, alias_normalized)
);

-- 5. Noi dung dataset bat bien khi dataset da ACTIVE/RETIRED/ROLLED_BACK (chi sua khi con draft/review).
CREATE OR REPLACE FUNCTION au_guard_content_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_status TEXT; v_ver TEXT;
BEGIN
  v_ver := COALESCE(NEW.dataset_version, OLD.dataset_version);
  SELECT status INTO v_status FROM admin_unit_dataset WHERE version = v_ver;
  IF v_status IN ('active','retired','rolled_back') THEN
    RAISE EXCEPTION 'noi dung dataset % bat bien khi trang thai % (chi sua khi draft/review)', v_ver, v_status;
  END IF;
  RETURN COALESCE(NEW, OLD);
END;
$$;
DROP TRIGGER IF EXISTS au_content_lock ON admin_unit;
CREATE TRIGGER au_content_lock BEFORE INSERT OR UPDATE OR DELETE ON admin_unit
  FOR EACH ROW EXECUTE FUNCTION au_guard_content_immutable();
DROP TRIGGER IF EXISTS aua_content_lock ON admin_unit_alias;
CREATE TRIGGER aua_content_lock BEFORE INSERT OR UPDATE OR DELETE ON admin_unit_alias
  FOR EACH ROW EXECUTE FUNCTION au_guard_content_immutable();

-- 6. Registry con tro active-version (chuyen ACTIVE nguyen tu, nhu kb_config.active_index_version).
CREATE TABLE IF NOT EXISTS address_dataset_config (
  key        TEXT PRIMARY KEY,
  value      TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO address_dataset_config (key, value) VALUES ('active_version', NULL)
ON CONFLICT (key) DO NOTHING;

COMMIT;

-- ROLLBACK:
--   DROP TRIGGER IF EXISTS aua_content_lock ON admin_unit_alias;
--   DROP TRIGGER IF EXISTS au_content_lock ON admin_unit;
--   DROP FUNCTION IF EXISTS au_guard_content_immutable();
--   DROP TABLE IF EXISTS admin_unit_alias; DROP TABLE IF EXISTS admin_unit;
--   DROP TRIGGER IF EXISTS aud_no_delete ON admin_unit_dataset;
--   DROP TRIGGER IF EXISTS aud_immutable ON admin_unit_dataset;
--   DROP FUNCTION IF EXISTS aud_forbid_delete(); DROP FUNCTION IF EXISTS aud_guard_immutable();
--   DROP TABLE IF EXISTS admin_unit_dataset; DROP TABLE IF EXISTS address_dataset_config;
--   DELETE FROM permissions WHERE key IN ('address.dataset.view','address.dataset.ingest',
--     'address.dataset.review','address.dataset.manage');
