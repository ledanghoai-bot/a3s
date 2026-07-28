-- Migration 031: consent/preference ledger (I-B M3 Slice 3).
-- Spec A3S-PHASE1B-M3-SPEC-001 §7.4 (schema §13.5 Scalffold V2.0 + authority fields §5).
-- Ledger APPEND-ONLY (khong UPDATE/DELETE record — thay doi = record moi voi authority_revision tang).
-- Khong dung boolean don; khong timestamp-only conflict resolution (authority_revision monotonic).
-- Runtime estimate: <1s (CREATE TABLE). Forward-fix: chay lai file (idempotent).
-- transactional: true

CREATE TABLE IF NOT EXISTS consent_records (
  consent_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id        integer NOT NULL REFERENCES customers(id),
  purpose_code       text NOT NULL CHECK (purpose_code IN (
    'P01_CONSULT','P02_COMMERCE','P03_TRANSACTIONAL','P04_SUPPORT','P05_LIFECYCLE',
    'P06_MARKETING','P07_ANALYTICS','P08_CONTENT_INSIGHT','P09_UGC_PUBLICATION',
    'P10_AI_PROCESSING','P11_LEGAL_RETENTION')),
  channel            text NOT NULL DEFAULT 'any',
  policy_version     text NOT NULL,
  notice_version     text NOT NULL,
  status             text NOT NULL CHECK (status IN ('granted','denied','withdrawn','expired')),
  captured_at        timestamptz NOT NULL DEFAULT now(),
  captured_via       text NOT NULL,  -- vd: chat_optin | chat_optout | complaint | staff_manual | migration
  evidence_ref       text NULL,      -- opaque ref (message id/audit id) — KHONG copy evidence body
  withdrawn_at       timestamptz NULL,
  jurisdiction       text NOT NULL DEFAULT 'VN',
  -- Authority contract (spec M3 §5): Gateway chua production -> alpha3s capture tam.
  authority_system   text NOT NULL DEFAULT 'alpha3s',
  authority_revision bigint NOT NULL,
  synced_at          timestamptz NULL
);

-- Monotonic per (customer, purpose, channel): revision duy nhat -> conflict = insert fail, khong ghi de.
CREATE UNIQUE INDEX IF NOT EXISTS consent_records_rev_uq
  ON consent_records (customer_id, purpose_code, channel, authority_revision);
-- Projection lookup: ban ghi moi nhat theo revision.
CREATE INDEX IF NOT EXISTS consent_records_lookup_idx
  ON consent_records (customer_id, purpose_code, channel, authority_revision DESC);

COMMENT ON TABLE consent_records IS
  'Consent/preference ledger append-only (M3-S3). data_class=D1_PERSONAL_BASIC; '
  'purpose_code=P11_LEGAL_RETENTION (chung minh tuan thu — KHONG tai dung cho marketing); '
  'retention_rule_id=RET-09; owner_system=alpha3s (authority tam thoi, Gateway la authority dai han); '
  'lineage_ref=evidence_ref(opaque)';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='consent_records') THEN
    RAISE EXCEPTION '031 postcondition FAIL: thieu consent_records'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='consent_records_rev_uq') THEN
    RAISE EXCEPTION '031 postcondition FAIL: thieu unique revision index'; END IF;
END $$;
