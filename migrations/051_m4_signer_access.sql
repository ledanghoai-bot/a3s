-- Migration 051: M4 — Signer Access Request (Directive 91): UI request hop nhat signer-role tam thoi
-- + activation window. Backend tach 2 event: (1) provision temp signer role; (2) issue activation window.
--
-- Authority: CA Directive 91 + PO Decision Addendum 90 (SoD: Signer(request+execute) != PO/Approver) +
--            Design 71/72. CHUA cap production signing; capability activate.production van dormant.
--            Role signer chi cap TAM THOI co valid_from/until, auto-revoke. Rehearsal grants KHONG cap
--            quyen that. PHAM VI thuan cong them. CHUA apply/merge/deploy.

BEGIN;

-- 1. Perms cho workflow signer-access (tach hanh dong, allowlist). Execute dung m4.signing.run.* (cap
--    qua temp role). approve tach rieng (SoD).
INSERT INTO permissions (key, description) VALUES
  ('m4.signer_access.view',    'Xem signer access request'),
  ('m4.signer_access.request', 'Signer gui request signer-role tam + activation window'),
  ('m4.signer_access.approve', 'PO/approver duyet request + cap window (SoD, khac requester)')
ON CONFLICT (key) DO NOTHING;

-- 2. Bang workflow signer-access request (state machine)
CREATE TABLE IF NOT EXISTS m4_signer_access_request (
  request_id      TEXT PRIMARY KEY,                 -- idempotency key
  state           TEXT NOT NULL DEFAULT 'SUBMITTED'
                  CHECK (state IN ('SUBMITTED','PREFLIGHT_PASSED','APPROVED','ACTIVE',
                                   'CLOSED','EXPIRED','REVOKED')),
  scope           JSONB NOT NULL DEFAULT '{}'::jsonb,
  artifact_digest TEXT NOT NULL,                    -- khoa luc submit; bat bien sau (trigger)
  ticket          TEXT,
  reason          TEXT,
  rollback_owner  TEXT,
  requester_staff_id BIGINT REFERENCES staff_users(id),
  approver_staff_id  BIGINT REFERENCES staff_users(id),
  window_minutes  INTEGER CHECK (window_minutes IS NULL OR window_minutes BETWEEN 1 AND 240),
  window_start    TIMESTAMPTZ,
  window_end      TIMESTAMPTZ,
  activation_id   UUID REFERENCES m4_signing_activation(activation_id),  -- window da issue
  is_rehearsal    BOOLEAN NOT NULL DEFAULT false,
  preflight_at    TIMESTAMPTZ,
  approved_at     TIMESTAMPTZ,
  activated_at    TIMESTAMPTZ,
  terminal_at     TIMESTAMPTZ,
  terminal_reason TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- SoD: approver KHAC requester (Addendum 90). activator=requester duoc phep (khong ep o day).
  CONSTRAINT sar_sod_approver
    CHECK (approver_staff_id IS NULL OR requester_staff_id IS NULL
           OR approver_staff_id <> requester_staff_id),
  CONSTRAINT sar_no_secret_scope
    CHECK (NOT (scope::text ~* '(pin_secret|private_key|"token"|password|-----BEGIN)'))
);

CREATE INDEX IF NOT EXISTS sar_state ON m4_signer_access_request (state, window_end);

-- anti-substitution: artifact_digest bat bien sau SUBMITTED
CREATE OR REPLACE FUNCTION m4_sar_guard_digest()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.state <> 'SUBMITTED' AND NEW.artifact_digest IS DISTINCT FROM OLD.artifact_digest THEN
    RAISE EXCEPTION 'artifact_digest bat bien sau SUBMITTED (anti-substitution)';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS m4_sar_digest_lock ON m4_signer_access_request;
CREATE TRIGGER m4_sar_digest_lock BEFORE UPDATE ON m4_signer_access_request
  FOR EACH ROW EXECUTE FUNCTION m4_sar_guard_digest();

-- ho so — khong DELETE
CREATE OR REPLACE FUNCTION m4_sar_forbid_delete()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'm4_signer_access_request la ho so — khong duoc DELETE';
END;
$$;
DROP TRIGGER IF EXISTS m4_sar_no_delete ON m4_signer_access_request;
CREATE TRIGGER m4_sar_no_delete BEFORE DELETE ON m4_signer_access_request
  FOR EACH ROW EXECUTE FUNCTION m4_sar_forbid_delete();

-- 3. Bang temp signer-role grant (time-boxed, auto-revoke). Allowlist role = m4_signing_operator.
CREATE TABLE IF NOT EXISTS m4_temp_signer_role_grant (
  grant_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id   TEXT NOT NULL REFERENCES m4_signer_access_request(request_id),
  staff_id     BIGINT NOT NULL REFERENCES staff_users(id),
  role_key     TEXT NOT NULL DEFAULT 'm4_signing_operator'
               CHECK (role_key = 'm4_signing_operator'),   -- allowlist (Addendum 70A)
  granted_by   BIGINT REFERENCES staff_users(id),
  valid_from   TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until  TIMESTAMPTZ NOT NULL,
  revoked_at   TIMESTAMPTZ,
  revoke_reason TEXT,
  is_rehearsal BOOLEAN NOT NULL DEFAULT false,          -- rehearsal grant KHONG cap quyen that
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- lookup grant dang hieu luc (permission resolution)
CREATE INDEX IF NOT EXISTS tsrg_active
  ON m4_temp_signer_role_grant (staff_id) WHERE revoked_at IS NULL;

CREATE OR REPLACE FUNCTION m4_tsrg_forbid_delete()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'm4_temp_signer_role_grant la audit — khong duoc DELETE';
END;
$$;
DROP TRIGGER IF EXISTS m4_tsrg_no_delete ON m4_temp_signer_role_grant;
CREATE TRIGGER m4_tsrg_no_delete BEFORE DELETE ON m4_temp_signer_role_grant
  FOR EACH ROW EXECUTE FUNCTION m4_tsrg_forbid_delete();

COMMIT;

-- ROLLBACK:
--   DROP TRIGGER IF EXISTS m4_tsrg_no_delete ON m4_temp_signer_role_grant;
--   DROP TABLE IF EXISTS m4_temp_signer_role_grant;
--   DROP FUNCTION IF EXISTS m4_tsrg_forbid_delete();
--   DROP TRIGGER IF EXISTS m4_sar_no_delete ON m4_signer_access_request;
--   DROP TRIGGER IF EXISTS m4_sar_digest_lock ON m4_signer_access_request;
--   DROP TABLE IF EXISTS m4_signer_access_request;
--   DROP FUNCTION IF EXISTS m4_sar_forbid_delete(); DROP FUNCTION IF EXISTS m4_sar_guard_digest();
--   DELETE FROM permissions WHERE key IN ('m4.signer_access.view','m4.signer_access.request','m4.signer_access.approve');
