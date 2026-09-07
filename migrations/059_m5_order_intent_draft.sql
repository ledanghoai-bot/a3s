-- 059 M5 deterministic confirm-to-commit: durable ORDER DRAFT tren order_intents (CA Directive 232 §3).
-- Server so huu draft de RECONSTRUCT + COMMIT don MA KHONG can conversational memory hay model goi
-- create_order lai. Cot draft additive, nullable (khong backfill; intent cu van hop le). Migration 058
-- KHONG bi sua. Additive + reversible (rollback cuoi file).

-- Field don da normalize/validate (server luu tu proposal model — model KHONG cap intent/state). draft_address
-- la PROTECTED BUSINESS DATA (giong orders.shipping_address); evidence/log PHAI redacted (khong in raw).
ALTER TABLE order_intents
  ADD COLUMN IF NOT EXISTS draft_sku            TEXT,
  ADD COLUMN IF NOT EXISTS draft_quantity       INTEGER,
  ADD COLUMN IF NOT EXISTS draft_customer_name  TEXT,
  ADD COLUMN IF NOT EXISTS draft_phone          TEXT,
  ADD COLUMN IF NOT EXISTS draft_address        TEXT,
  -- §6 confirmation contract: server ghi lai state_version + order_fingerprint TAI THOI DIEM present
  -- deterministic summary (READY). Confirmation CHI hop le khi intent VAN o dung version/fingerprint do
  -- (correction sau do doi fingerprint/version -> summary cu VO HIEU -> khong commit draft da sua).
  ADD COLUMN IF NOT EXISTS summary_version      INTEGER,
  ADD COLUMN IF NOT EXISTS summary_fingerprint  TEXT,
  ADD COLUMN IF NOT EXISTS summary_presented_at TIMESTAMPTZ;

-- ROLLBACK (runbook):
--   ALTER TABLE order_intents
--     DROP COLUMN IF EXISTS draft_sku, DROP COLUMN IF EXISTS draft_quantity,
--     DROP COLUMN IF EXISTS draft_customer_name, DROP COLUMN IF EXISTS draft_phone,
--     DROP COLUMN IF EXISTS draft_address, DROP COLUMN IF EXISTS summary_version,
--     DROP COLUMN IF EXISTS summary_fingerprint, DROP COLUMN IF EXISTS summary_presented_at;
