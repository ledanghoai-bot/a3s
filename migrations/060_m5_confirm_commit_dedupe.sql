-- 060 M5 confirm-to-commit V02-final (CA Review 234 §234-03/234-04): stable dedupe identity cho staff-
-- history + summary-response content hash. Additive, nullable, KHONG backfill; migration 059 KHONG bi sua.
-- Additive + reversible (rollback cuoi file).

-- 234-04: staff-visible receipt/summary row phai dedup theo STABLE ORDER/EVENT IDENTITY (khong content
-- matching). dedupe_key NULL cho tin nhan thuong; khi co, UNIQUE toan cuc -> INSERT ON CONFLICT DO NOTHING
-- => exactly-once row cho cung (order/summary) qua replay/concurrent.
ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS dedupe_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS messages_dedupe_key_uidx
  ON messages(dedupe_key) WHERE dedupe_key IS NOT NULL;

-- 234-03: content hash cua server-rendered summary DA PERSIST, bound theo intent version/fingerprint.
-- Confirmation chi hop le khi persisted response ton tai + khop; neu render/persist doi -> hash doi.
ALTER TABLE order_intents
  ADD COLUMN IF NOT EXISTS summary_content_hash TEXT;

-- ROLLBACK (runbook):
--   DROP INDEX IF EXISTS messages_dedupe_key_uidx;
--   ALTER TABLE messages DROP COLUMN IF EXISTS dedupe_key;
--   ALTER TABLE order_intents DROP COLUMN IF EXISTS summary_content_hash;
