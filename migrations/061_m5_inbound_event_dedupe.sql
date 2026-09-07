-- 061 M5 confirm-to-commit V02-final-r2 (CA Review 235-02 + 236-01): INBOX state machine cho provider
-- event (channel, provider_message_id) — EFFECTIVE-ONCE (khong phai at-most-once). Luu status + lease +
-- attempt de: replay cua event DA succeeded -> no-op on dinh; claim transient-failed/abandoned (lease het)
-- -> retry an toan; 2 delivery dong thoi -> 1 xu ly. Additive; migration 059/060 KHONG bi sua. Reversible.

CREATE TABLE IF NOT EXISTS inbound_event_log (
  channel             TEXT        NOT NULL,
  provider_message_id TEXT        NOT NULL,
  -- processing = dang xu ly (giu lease); succeeded = da xu ly xong (durable outcome / stable no-op);
  -- retryable_failed = loi transient truoc khi co mutation ben vung -> redelivery duoc retry.
  status              TEXT        NOT NULL DEFAULT 'processing'
                        CHECK (status IN ('processing', 'succeeded', 'retryable_failed')),
  attempt_count       INTEGER     NOT NULL DEFAULT 0,
  lease_expires_at    TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (channel, provider_message_id)
);

-- ROLLBACK (runbook):
--   DROP TABLE IF EXISTS inbound_event_log;
