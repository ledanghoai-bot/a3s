-- Migration 050: M4 — Signing control (freeze/incident flag) cho preflight thật (Roadmap Buoc 1).
--
-- Authority: CA Review 78 (ACCEPT-AS-ROADMAP) — Buoc 1 "Dev preflight that": thay stub
--            no_conflicting_incident bang check THAT co backing store. Mau theo m4_stage0p_control
--            (039) nhung cho SIGNING (khong phai capture — tach biet nghia, khong tai dien giai).
--
-- CHUA cap production signing. Bang nay chi cho preflight doc fail-closed. Mac dinh KHONG dong bang
-- (signing_frozen=false) — nhung neu bang thieu/khong doc duoc thi check phai fail-closed (defense).
-- PHAM VI thuan cong them. CHUA apply/merge/deploy.

BEGIN;

-- Singleton control row cho signing. signing_frozen=true => preflight no_conflicting_incident FAIL.
CREATE TABLE IF NOT EXISTS m4_signing_control (
  id              SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  signing_frozen  BOOLEAN NOT NULL DEFAULT false,
  incident_ref    TEXT,                         -- ma su co dang mo (neu frozen)
  reason          TEXT,
  updated_by      TEXT,                         -- actor ref (khong secret)
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed row mac dinh: KHONG dong bang. Idempotent.
INSERT INTO m4_signing_control (id, signing_frozen, reason, updated_by)
VALUES (1, false, 'seed mac dinh — signing khong bi dong bang', 'migration-050')
ON CONFLICT (id) DO NOTHING;

COMMENT ON TABLE m4_signing_control IS
  'Buoc 1 preflight that: co dong-bang-ky (signing_frozen) cho SIGNING (tach biet m4_stage0p_control cua capture). preflight no_conflicting_incident doc tuoi row id=1; frozen=true => FAIL fail-closed. Doi trang thai qua service co audit, KHONG qua caller param.';

-- Bang nay chi doc noi bo qua service; khong role app nao duoc GRANT truc tiep.
REVOKE ALL ON m4_signing_control FROM PUBLIC;

-- Khong cho DELETE row control (giu single-row invariant). Cho UPDATE (doi co) + audit o tang service.
CREATE OR REPLACE FUNCTION m4_signing_control_forbid_delete()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'm4_signing_control la singleton control — khong duoc DELETE';
END;
$$;
DROP TRIGGER IF EXISTS m4_signing_control_no_delete ON m4_signing_control;
CREATE TRIGGER m4_signing_control_no_delete
  BEFORE DELETE ON m4_signing_control
  FOR EACH ROW EXECUTE FUNCTION m4_signing_control_forbid_delete();

COMMIT;

-- ROLLBACK:
--   DROP TRIGGER IF EXISTS m4_signing_control_no_delete ON m4_signing_control;
--   DROP FUNCTION IF EXISTS m4_signing_control_forbid_delete();
--   DROP TABLE IF EXISTS m4_signing_control;
