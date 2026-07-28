-- Migration 033: retention policy + run log + legal hold (I-B M3 Slice 6). Spec §7.7.
-- Policy VERSION hoa; executor CHI apply policy status='approved' (dry-run duoc voi moi status).
-- Seed tu docs/RETENTION-SCHEDULE.md o trang thai 'draft' — [PROPOSED] CHO PO APPROVE (AC-M3-07:
-- dry-run duoc duyet truoc; apply that = release gate). Audit bang opaque reference, KHONG PII.
-- Runtime estimate: <1s. Forward-fix: chay lai file (idempotent). transactional: true

CREATE TABLE IF NOT EXISTS retention_policies (
  rule_id               text NOT NULL,            -- khop RETENTION-SCHEDULE (RET-04, RET-09...)
  version               integer NOT NULL CHECK (version >= 1),
  data_category         text NOT NULL,            -- raw_chat | deletion_requests | ...
  action                text NOT NULL CHECK (action IN ('delete','anonymize','archive')),
  retention_period_days integer NOT NULL CHECK (retention_period_days > 0),
  respect_legal_hold    boolean NOT NULL DEFAULT true,
  status                text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','retired')),
  created_at            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (rule_id, version)
);

CREATE TABLE IF NOT EXISTS legal_holds (
  hold_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id bigint NULL REFERENCES customers(id),
  order_id    bigint NULL REFERENCES orders(id),
  reason_ref  text NOT NULL,   -- opaque reference (ticket/audit id) — KHONG mo ta vu viec
  active      boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  released_at timestamptz NULL,
  CHECK (customer_id IS NOT NULL OR order_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS retention_run_log (
  run_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_id     text NOT NULL,
  version     integer NOT NULL,
  dry_run     boolean NOT NULL,
  counts      jsonb NOT NULL,   -- {"candidates":n,"deleted":n,"skipped_hold":n} — so lieu, KHONG PII
  actor       text NOT NULL,
  started_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz NULL
);

COMMENT ON TABLE retention_policies IS
  'Retention policy version hoa (M3-S6). data_class=D0; owner=PO (approve) / Dev (executor). '
  'Apply chi khi status=approved; khong retain_forever.';
COMMENT ON TABLE retention_run_log IS
  'Audit chay retention — opaque counts only, KHONG PII. data_class=D0; retention_rule_id=RET-05';

-- Seed [PROPOSED] -> draft (PO chua duyet — executor se tu choi apply, chi dry-run)
INSERT INTO retention_policies (rule_id, version, data_category, action, retention_period_days, status) VALUES
  ('RET-04', 1, 'raw_chat', 'delete', 730, 'draft'),
  ('RET-09', 1, 'deletion_requests', 'delete', 730, 'draft')
ON CONFLICT (rule_id, version) DO NOTHING;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='retention_policies') THEN
    RAISE EXCEPTION '033 postcondition FAIL: thieu retention_policies'; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='retention_run_log') THEN
    RAISE EXCEPTION '033 postcondition FAIL: thieu retention_run_log'; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='legal_holds') THEN
    RAISE EXCEPTION '033 postcondition FAIL: thieu legal_holds'; END IF;
END $$;
