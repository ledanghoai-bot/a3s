-- Migration 046: M4-9 — Dashboard-triggered Production Signing Run (control/approval surface).
--
-- Authority: CA-Docs/PHASE1B-M4-9-DASHBOARD-TRIGGER-IMPLEMENTATION-PACKAGE-60-VI.md +
--            docs/M4-9-DASHBOARD-TRIGGER-DESIGN-VI.md (baseline freeze).
--
-- PHAM VI: THUAN CONG THEM. Migration nay tao ha tang GHI SO (ledger) cho mot "signing run"
-- do dashboard khoi tao. No KHONG dung toi bat ky bang/ham stage0p nao (039/043/044), KHONG cap
-- quyen ky, KHONG start signer. Execution that su van di qua CLI runner + tang RBAC Postgres cua
-- stage0p (pinned actor). Bang o day chi la:
--   * state machine cua request (dashboard control surface),
--   * attempt ledger BAT BIEN (dem theo so row — khong co duong reset),
--   * event/audit log BAT BIEN cho moi human action + transition.
-- Rollback = DROP 3 bang + xoa 5 permission (khong ai doc chung o baseline).
--
-- BAO MAT: bang o day KHONG duoc chua secret/PIN/private key/raw token/customer data. Cot
-- `public_metadata`/`scope`/`data_boundary` chi luu JSON KHONG nhay cam (fingerprint, hash, ten
-- scope) — enforce o tang service, va them CHECK chan cac key nhay cam hien nhien o duoi.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Catalog permission moi (he RBAC "business" — role_permissions / require_permission)
-- ---------------------------------------------------------------------------
INSERT INTO permissions (key, description) VALUES
  ('m4.signing.run.view',    'Xem signing run va trang thai (read-only)'),
  ('m4.signing.run.start',   'Tao va confirm signing run request'),
  ('m4.signing.run.operate', 'Thuc hien ceremony checkpoint va bounded execution'),
  ('m4.signing.run.approve', 'Duyet canary (SoD: khac operator)'),
  ('m4.signing.run.abort',   'Abort / break-glass mot signing run')
ON CONFLICT (key) DO NOTHING;

-- admin duoc quyen view mac dinh; cac quyen thao tac PO phai gan tuong minh (khong seed).
INSERT INTO role_permissions (role_key, permission_key)
SELECT 'admin', k FROM (VALUES ('m4.signing.run.view')) AS v(k)
WHERE EXISTS (SELECT 1 FROM roles WHERE key = 'admin')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. Bang state machine cua run
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS m4_signing_run (
  run_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  -- State machine (xem docs/M4-9-DASHBOARD-TRIGGER-DESIGN-VI.md §3)
  state            TEXT NOT NULL DEFAULT 'CREATED'
                   CHECK (state IN ('CREATED','CONFIRMED','PREFLIGHT_PASSED','CEREMONY_RECORDED',
                                    'CANARY_PENDING','CANARY_APPROVED','EXECUTING',
                                    'CLOSED','ABORTED','FAILED')),
  -- Phan loai: synthetic rehearsal (M4-9) hay production (gate rieng sau).
  run_kind         TEXT NOT NULL DEFAULT 'synthetic_rehearsal'
                   CHECK (run_kind IN ('synthetic_rehearsal','production')),
  -- Change ticket + scope/window/quota/data-boundary (JSON KHONG nhay cam).
  change_ticket    TEXT,
  scope            JSONB NOT NULL DEFAULT '{}'::jsonb,
  window_start     TIMESTAMPTZ,
  window_end       TIMESTAMPTZ,
  quota_sts        INTEGER NOT NULL DEFAULT 3 CHECK (quota_sts   BETWEEN 1 AND 100),
  quota_sign       INTEGER NOT NULL DEFAULT 3 CHECK (quota_sign  BETWEEN 1 AND 1000),
  data_boundary    JSONB NOT NULL DEFAULT '{}'::jsonb,
  -- Public metadata ceremony (fingerprint/serial/hash — KHONG PIN/khoa).
  public_metadata  JSONB NOT NULL DEFAULT '{}'::jsonb,
  -- SoD: staff khoi tao/operate vs approve.
  created_by       BIGINT REFERENCES staff_users(id),
  operator_staff_id BIGINT REFERENCES staff_users(id),
  approver_staff_id BIGINT REFERENCES staff_users(id),
  -- Ket qua
  terminal_reason  TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- SoD hard constraint: approver khac operator (khi ca hai da set).
  CONSTRAINT m4_signing_run_sod
    CHECK (approver_staff_id IS NULL OR operator_staff_id IS NULL
           OR approver_staff_id <> operator_staff_id),
  -- Chan secret hien nhien lot vao cac cot JSON (defense-in-depth; service cung kiem).
  CONSTRAINT m4_signing_run_no_secret_scope
    CHECK (NOT (scope::text ~* '(pin_secret|private_key|"token"|password|-----BEGIN)')),
  CONSTRAINT m4_signing_run_no_secret_meta
    CHECK (NOT (public_metadata::text ~* '(pin_secret|private_key|"token"|password|-----BEGIN)'))
);

-- Chi mot run ACTIVE (chua terminal) tai mot thoi diem — enforce bang partial unique index.
CREATE UNIQUE INDEX IF NOT EXISTS m4_signing_run_single_active
  ON m4_signing_run ((run_kind))
  WHERE state NOT IN ('CLOSED','ABORTED','FAILED');

-- ---------------------------------------------------------------------------
-- 3. Attempt ledger BAT BIEN — dem theo so row, khong co duong reset/update/delete
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS m4_signing_run_attempt (
  attempt_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id       UUID NOT NULL REFERENCES m4_signing_run(run_id) ON DELETE RESTRICT,
  attempt_kind TEXT NOT NULL CHECK (attempt_kind IN ('sts','sign','preflight','canary')),
  outcome      TEXT NOT NULL CHECK (outcome IN ('started','ok','transient_failed','failed')),
  detail       JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT m4_signing_run_attempt_no_secret
    CHECK (NOT (detail::text ~* '(pin_secret|private_key|"token"|password|-----BEGIN|ya29\.)'))
);
CREATE INDEX IF NOT EXISTS m4_signing_run_attempt_by_run
  ON m4_signing_run_attempt (run_id, attempt_kind);

-- ---------------------------------------------------------------------------
-- 4. Event / audit log BAT BIEN cho moi transition + human action
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS m4_signing_run_event (
  event_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id       UUID NOT NULL REFERENCES m4_signing_run(run_id) ON DELETE RESTRICT,
  event_type   TEXT NOT NULL,          -- vd 'created','confirmed','preflight_pass','abort',...
  from_state   TEXT,
  to_state     TEXT,
  actor_staff_id BIGINT REFERENCES staff_users(id),
  reason       TEXT,
  detail       JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT m4_signing_run_event_no_secret
    CHECK (NOT (detail::text ~* '(pin_secret|private_key|"token"|password|-----BEGIN|ya29\.)'))
);
CREATE INDEX IF NOT EXISTS m4_signing_run_event_by_run
  ON m4_signing_run_event (run_id, created_at);

-- ---------------------------------------------------------------------------
-- 5. Immutability: attempt & event khong duoc UPDATE/DELETE (append-only ledger)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION m4_signing_run_forbid_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'm4-9 ledger la append-only: khong duoc % tren %',
    TG_OP, TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS m4_signing_run_attempt_immutable ON m4_signing_run_attempt;
CREATE TRIGGER m4_signing_run_attempt_immutable
  BEFORE UPDATE OR DELETE ON m4_signing_run_attempt
  FOR EACH ROW EXECUTE FUNCTION m4_signing_run_forbid_mutation();

DROP TRIGGER IF EXISTS m4_signing_run_event_immutable ON m4_signing_run_event;
CREATE TRIGGER m4_signing_run_event_immutable
  BEFORE UPDATE OR DELETE ON m4_signing_run_event
  FOR EACH ROW EXECUTE FUNCTION m4_signing_run_forbid_mutation();

-- Run row: cho UPDATE (doi state) nhung KHONG cho DELETE (giu ho so).
CREATE OR REPLACE FUNCTION m4_signing_run_forbid_delete()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'm4-9 signing run la ho so: khong duoc DELETE';
END;
$$;
DROP TRIGGER IF EXISTS m4_signing_run_no_delete ON m4_signing_run;
CREATE TRIGGER m4_signing_run_no_delete
  BEFORE DELETE ON m4_signing_run
  FOR EACH ROW EXECUTE FUNCTION m4_signing_run_forbid_delete();

COMMIT;
