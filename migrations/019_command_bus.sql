-- Migration 019: Command bus persistence foundation (I-B M1 — Reliable Command and Receipt).
-- Governing: A3S-PHASE1B-M1-SPEC-001 v1.0.0 §7 (persistence model).
-- Ba bang durable: command_executions (§7.1), outbox_events (§7.2), delivery_attempts (§7.3).
-- Nguyen tac M1: effective-once business mutation + atomic mutation/outbox + at-least-once delivery
-- + deterministic receipt tu committed data. KHONG luu raw secret/token/phone/address/provider payload
-- (§6.1, §7.4 — application layer redact truoc khi ghi; DDL chi cung cap noi luu da-redact).
-- Forward-only, self-validating: postcondition DO block RAISE -> rollback ca migration (fail-closed).
-- transactional: true

-- ===========================================================================
-- 7.1  command_executions — durable command record + deterministic result
-- ===========================================================================
CREATE TABLE IF NOT EXISTS command_executions (
  id                    UUID PRIMARY KEY,
  command_type          TEXT     NOT NULL,
  command_version       SMALLINT NOT NULL CHECK (command_version > 0),
  idempotency_scope     TEXT     NOT NULL,
  idempotency_key       TEXT     NOT NULL,
  request_hash          CHAR(64) NOT NULL,
  status                TEXT     NOT NULL
                          CHECK (status IN ('accepted','processing','succeeded','failed_terminal')),
  actor_type            TEXT     NOT NULL CHECK (actor_type IN ('customer','staff','system')),
  actor_id              TEXT     NOT NULL,
  channel               TEXT     NOT NULL
                          CHECK (channel IN ('messenger','telegram_customer','dashboard')),
  customer_id           BIGINT REFERENCES customers(id),
  conversation_id       BIGINT REFERENCES conversations(id),
  location_id           BIGINT,                         -- §4.2 reserved (1 brand nhieu dia diem); M1 khong dung
  correlation_id        UUID     NOT NULL,
  causation_id          TEXT,                           -- provider message/update id (khong phai full payload)
  request_payload       JSONB    NOT NULL,              -- da redact/allowlist (masked phone, khong address neu khong can)
  result_payload        JSONB,
  resource_type         TEXT,
  resource_id           TEXT,
  error_code            TEXT,
  error_detail_redacted JSONB,
  lease_owner           TEXT,
  lease_expires_at      TIMESTAMPTZ,
  accepted_at           TIMESTAMPTZ,
  started_at            TIMESTAMPTZ,
  completed_at          TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- §6.2 scope unique: mot idempotency key chi tao mot command trong scope cua no
  CONSTRAINT command_executions_idem_key
    UNIQUE (command_type, command_version, idempotency_scope, idempotency_key),
  -- §7.1 succeeded phai co result/resource/completed
  CONSTRAINT command_executions_succeeded_chk CHECK (
    status <> 'succeeded'
    OR (result_payload IS NOT NULL AND resource_type IS NOT NULL
        AND resource_id IS NOT NULL AND completed_at IS NOT NULL)
  ),
  -- §7.1 terminal failure phai co error_code + completed
  CONSTRAINT command_executions_failed_chk CHECK (
    status <> 'failed_terminal'
    OR (error_code IS NOT NULL AND completed_at IS NOT NULL)
  )
);

-- §7.1 indexes
CREATE INDEX IF NOT EXISTS command_executions_status_lease_idx
  ON command_executions (status, lease_expires_at);
CREATE INDEX IF NOT EXISTS command_executions_correlation_idx
  ON command_executions (correlation_id);
CREATE INDEX IF NOT EXISTS command_executions_causation_idx
  ON command_executions (causation_id);
CREATE INDEX IF NOT EXISTS command_executions_resource_idx
  ON command_executions (resource_type, resource_id);

-- ===========================================================================
-- 7.2  outbox_events — at-least-once delivery, unique destination/dedupe
-- ===========================================================================
CREATE TABLE IF NOT EXISTS outbox_events (
  id                  UUID PRIMARY KEY,
  command_id          UUID     NOT NULL REFERENCES command_executions(id),
  event_type          TEXT     NOT NULL,
  event_version       SMALLINT NOT NULL CHECK (event_version > 0),
  destination         TEXT     NOT NULL,
  dedupe_key          TEXT     NOT NULL,
  payload             JSONB    NOT NULL,                -- da redact (no token/header/full provider payload)
  status              TEXT     NOT NULL
                        CHECK (status IN ('pending','delivering','delivered',
                                          'retry_scheduled','dead_lettered','cancelled')),
  available_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  attempt_count       INTEGER  NOT NULL DEFAULT 0,
  max_attempts        INTEGER  NOT NULL CHECK (max_attempts > 0),
  lease_owner         TEXT,
  lease_expires_at    TIMESTAMPTZ,
  provider_message_id TEXT,
  delivered_at        TIMESTAMPTZ,
  dead_lettered_at    TIMESTAMPTZ,
  cancelled_at        TIMESTAMPTZ,
  last_error_code     TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- §6.3 / §8.3 consumer noi bo bat buoc unique destination/dedupe key
  CONSTRAINT outbox_events_dedupe UNIQUE (destination, dedupe_key)
);

-- §7.2 indexes — partial claim index chi cho hang cho gui
CREATE INDEX IF NOT EXISTS outbox_events_claim_idx
  ON outbox_events (available_at, created_at)
  WHERE status IN ('pending','retry_scheduled');
CREATE INDEX IF NOT EXISTS outbox_events_status_updated_idx
  ON outbox_events (status, updated_at);
CREATE INDEX IF NOT EXISTS outbox_events_command_idx
  ON outbox_events (command_id);

-- ===========================================================================
-- 7.3  delivery_attempts — append-only attempt history
-- ===========================================================================
CREATE TABLE IF NOT EXISTS delivery_attempts (
  id                    BIGSERIAL PRIMARY KEY,
  outbox_event_id       UUID    NOT NULL REFERENCES outbox_events(id),
  attempt_no            INTEGER NOT NULL CHECK (attempt_no > 0),
  worker_id             TEXT    NOT NULL,
  started_at            TIMESTAMPTZ,
  finished_at           TIMESTAMPTZ,
  outcome               TEXT    NOT NULL
                          CHECK (outcome IN ('delivered','retryable_error','terminal_error','unknown')),
  http_status           INTEGER,
  provider_message_id   TEXT,
  error_class           TEXT,
  error_detail_redacted JSONB,
  duration_ms           INTEGER,
  correlation_id        UUID    NOT NULL,
  -- §7.3 mot attempt_no duy nhat cho moi outbox event (append-only)
  CONSTRAINT delivery_attempts_unique UNIQUE (outbox_event_id, attempt_no)
);

-- §7.3 indexes
CREATE INDEX IF NOT EXISTS delivery_attempts_event_idx
  ON delivery_attempts (outbox_event_id, started_at);
CREATE INDEX IF NOT EXISTS delivery_attempts_outcome_idx
  ON delivery_attempts (outcome, started_at);

-- ===========================================================================
-- Triggers: auto updated_at + guard terminal -> non-terminal (§6.3 / §7.1)
-- ===========================================================================
-- Bump updated_at moi UPDATE (dung chung).
CREATE OR REPLACE FUNCTION m1_set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- §6.3: accepted/processing -> succeeded|failed_terminal, nhung terminal KHONG duoc mo lai.
CREATE OR REPLACE FUNCTION command_executions_guard_terminal() RETURNS trigger AS $$
BEGIN
  IF OLD.status IN ('succeeded','failed_terminal')
     AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'command_executions % da o terminal (%); khong duoc chuyen sang %',
      OLD.id, OLD.status, NEW.status
      USING ERRCODE = 'check_violation';
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS command_executions_before_update ON command_executions;
CREATE TRIGGER command_executions_before_update
  BEFORE UPDATE ON command_executions
  FOR EACH ROW EXECUTE FUNCTION command_executions_guard_terminal();

DROP TRIGGER IF EXISTS outbox_events_before_update ON outbox_events;
CREATE TRIGGER outbox_events_before_update
  BEFORE UPDATE ON outbox_events
  FOR EACH ROW EXECUTE FUNCTION m1_set_updated_at();

-- ===========================================================================
-- Postcondition (fail-closed): xac nhan schema da tao dung truoc khi commit.
-- Bat ky assert fail -> RAISE -> rollback ca migration (runner up: exit != 0).
-- ===========================================================================
DO $$
DECLARE
  missing TEXT := '';
BEGIN
  -- tables
  IF to_regclass('public.command_executions') IS NULL THEN missing := missing || ' command_executions'; END IF;
  IF to_regclass('public.outbox_events')      IS NULL THEN missing := missing || ' outbox_events'; END IF;
  IF to_regclass('public.delivery_attempts')  IS NULL THEN missing := missing || ' delivery_attempts'; END IF;
  -- key constraints
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'command_executions_idem_key')
    THEN missing := missing || ' command_executions_idem_key'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'command_executions_succeeded_chk')
    THEN missing := missing || ' command_executions_succeeded_chk'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'command_executions_failed_chk')
    THEN missing := missing || ' command_executions_failed_chk'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'outbox_events_dedupe')
    THEN missing := missing || ' outbox_events_dedupe'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'delivery_attempts_unique')
    THEN missing := missing || ' delivery_attempts_unique'; END IF;
  -- claim index (partial) + terminal guard trigger
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='outbox_events_claim_idx')
    THEN missing := missing || ' outbox_events_claim_idx'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='command_executions_before_update')
    THEN missing := missing || ' command_executions_before_update'; END IF;
  IF missing <> '' THEN
    RAISE EXCEPTION '019 postcondition FAIL — thieu:%', missing;
  END IF;
END $$;
