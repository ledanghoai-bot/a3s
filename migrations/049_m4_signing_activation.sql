-- Migration 049: M4 — Production Signing Activation (Tier B) capability + lifecycle table.
--
-- Authority: CA-Docs/PHASE1B-M4-9-PRODUCTION-SIGNING-ACTIVATION-ELIGIBILITY-DESIGN-71-VI.md
--            + …-REQUESTER-APPROVAL-ADDENDUM-72-VI.md. Xem docs/M4-SIGNING-ACTIVATION-DESIGN-VI.md.
--
-- CHUA cap production signing. Migration nay chi tao ha tang (capability + bang lifecycle). KHONG
-- grant capability cho role nao (dormant — PO cap tuong minh khi co Activation Gate). PHAM VI thuan
-- cong them. CHUA apply/merge/deploy.

BEGIN;

-- 1. Capability RIENG (khong suy tu role signer). KHONG grant mac dinh.
INSERT INTO permissions (key, description) VALUES
  ('m4.signing.activate.production', 'Kich hoat production signing (Tier B) — capability rieng, TTL')
ON CONFLICT (key) DO NOTHING;

-- 2. Bang lifecycle activation
CREATE TABLE IF NOT EXISTS m4_signing_activation (
  activation_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id      TEXT NOT NULL,                 -- idempotency key
  state           TEXT NOT NULL DEFAULT 'REQUESTED'
                  CHECK (state IN ('REQUESTED','PREFLIGHT_PASSED','APPROVED','ACTIVE',
                                   'EXPIRED','REVOKED','CLOSED')),
  scope           JSONB NOT NULL DEFAULT '{}'::jsonb,   -- data scope / tenant-customer boundary (KHONG PII)
  artifact_digest TEXT NOT NULL,                 -- KHOA luc request; bat bien sau approve (trigger)
  manifest_ref    TEXT,
  max_sign_count  INTEGER NOT NULL DEFAULT 1 CHECK (max_sign_count BETWEEN 1 AND 100000),
  reason          TEXT,
  ticket          TEXT,
  requester_staff_id BIGINT REFERENCES staff_users(id),
  approver_staff_id  BIGINT REFERENCES staff_users(id),
  activator_staff_id BIGINT REFERENCES staff_users(id),
  delegated_by    TEXT,
  rollback_owner  TEXT,
  window_start    TIMESTAMPTZ,
  window_end      TIMESTAMPTZ,                   -- TTL
  preflight_at    TIMESTAMPTZ,
  approved_at     TIMESTAMPTZ,
  activated_at    TIMESTAMPTZ,
  terminal_at     TIMESTAMPTZ,
  terminal_reason TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- SoD: approver KHAC requester; activator KHAC approver (khi da set).
  CONSTRAINT m4_act_sod_approver
    CHECK (approver_staff_id IS NULL OR requester_staff_id IS NULL
           OR approver_staff_id <> requester_staff_id),
  CONSTRAINT m4_act_sod_activator
    CHECK (activator_staff_id IS NULL OR approver_staff_id IS NULL
           OR activator_staff_id <> approver_staff_id),
  -- no-secret o cot JSON/text (defense-in-depth)
  CONSTRAINT m4_act_no_secret_scope
    CHECK (NOT (scope::text ~* '(pin_secret|private_key|"token"|password|-----BEGIN)'))
);

-- Chi mot activation ACTIVE/dang mo cho mot request_id (idempotency, khong "standing approval" trung).
CREATE UNIQUE INDEX IF NOT EXISTS m4_act_request_active
  ON m4_signing_activation (request_id)
  WHERE state NOT IN ('EXPIRED','REVOKED','CLOSED');

CREATE INDEX IF NOT EXISTS m4_act_state ON m4_signing_activation (state, window_end);

-- 3. Anti-substitution: artifact_digest BAT BIEN sau khi roi REQUESTED (khoa digest sau approve/preflight).
CREATE OR REPLACE FUNCTION m4_act_guard_digest()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.state <> 'REQUESTED' AND NEW.artifact_digest IS DISTINCT FROM OLD.artifact_digest THEN
    RAISE EXCEPTION 'artifact_digest bat bien sau REQUESTED (anti-substitution) — tu choi doi digest';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS m4_act_digest_lock ON m4_signing_activation;
CREATE TRIGGER m4_act_digest_lock
  BEFORE UPDATE ON m4_signing_activation
  FOR EACH ROW EXECUTE FUNCTION m4_act_guard_digest();

-- 4. Ho so activation khong duoc DELETE (giu audit trail).
CREATE OR REPLACE FUNCTION m4_act_forbid_delete()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'm4_signing_activation la ho so — khong duoc DELETE';
END;
$$;
DROP TRIGGER IF EXISTS m4_act_no_delete ON m4_signing_activation;
CREATE TRIGGER m4_act_no_delete
  BEFORE DELETE ON m4_signing_activation
  FOR EACH ROW EXECUTE FUNCTION m4_act_forbid_delete();

COMMIT;

-- ROLLBACK (khi chua co activation nao):
--   DROP TRIGGER IF EXISTS m4_act_no_delete ON m4_signing_activation;
--   DROP TRIGGER IF EXISTS m4_act_digest_lock ON m4_signing_activation;
--   DROP FUNCTION IF EXISTS m4_act_forbid_delete();
--   DROP FUNCTION IF EXISTS m4_act_guard_digest();
--   DROP TABLE IF EXISTS m4_signing_activation;
--   DELETE FROM permissions WHERE key='m4.signing.activate.production';
