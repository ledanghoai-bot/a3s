-- 061 M5 confirm-to-commit V02-final-r1 (CA Review 235-02): durable INBOUND provider-event claim/dedupe
-- scoped by (channel, provider_message_id) — replay cua CUNG su kien KHONG duoc chay lai extraction/mutation
-- (version bump / summary row / intent moi). Additive, khong backfill. Migration 059/060 KHONG bi sua.
-- Additive + reversible (rollback cuoi file).

CREATE TABLE IF NOT EXISTS inbound_event_log (
  channel             TEXT        NOT NULL,
  provider_message_id TEXT        NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (channel, provider_message_id)
);

-- ROLLBACK (runbook):
--   DROP TABLE IF EXISTS inbound_event_log;
