-- Post-migration validation for M1 command bus (migration 019).
-- Governing: A3S-PHASE1B-M1-SPEC-001 v1.0.0 §7 / §13.2.
-- Fail-closed: RAISE EXCEPTION neu bat ky table/constraint/index/trigger cot loi bi thieu.
-- Standalone (chay tay: psql -f) HOAC nhung vao post_migration_validations cua M1 release manifest.
-- KHONG sua migration da apply — day la kiem tra doc-only tren schema hien tai.
DO $$
DECLARE
  missing TEXT := '';
BEGIN
  -- §7.1/§7.2/§7.3 tables
  IF to_regclass('public.command_executions') IS NULL THEN missing := missing || ' table:command_executions'; END IF;
  IF to_regclass('public.outbox_events')      IS NULL THEN missing := missing || ' table:outbox_events'; END IF;
  IF to_regclass('public.delivery_attempts')  IS NULL THEN missing := missing || ' table:delivery_attempts'; END IF;

  -- §6.2/§8.1 effective-once: scoped idempotency unique
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='command_executions_idem_key' AND contype='u')
    THEN missing := missing || ' uniq:command_executions_idem_key'; END IF;
  -- §8.3 outbox consumer dedupe unique
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='outbox_events_dedupe' AND contype='u')
    THEN missing := missing || ' uniq:outbox_events_dedupe'; END IF;
  -- §7.3 attempts append-only unique
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='delivery_attempts_unique' AND contype='u')
    THEN missing := missing || ' uniq:delivery_attempts_unique'; END IF;

  -- §7.1 succeeded/failed integrity CHECKs
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='command_executions_succeeded_chk' AND contype='c')
    THEN missing := missing || ' check:succeeded_chk'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='command_executions_failed_chk' AND contype='c')
    THEN missing := missing || ' check:failed_chk'; END IF;

  -- §9.1 claim path: partial index cho hang cho gui
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='outbox_events_claim_idx')
    THEN missing := missing || ' index:outbox_events_claim_idx'; END IF;
  -- §7.1 reconciler path: (status, lease_expires_at)
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='command_executions_status_lease_idx')
    THEN missing := missing || ' index:command_executions_status_lease_idx'; END IF;

  -- §6.3 terminal-reopen guard trigger
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='command_executions_before_update' AND NOT tgisinternal)
    THEN missing := missing || ' trigger:command_executions_before_update'; END IF;

  IF missing <> '' THEN
    RAISE EXCEPTION 'command_bus validation FAIL — thieu:%', missing;
  END IF;
  RAISE NOTICE 'command_bus validation OK (019 schema day du).';
END $$;
