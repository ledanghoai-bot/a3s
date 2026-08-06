-- Migration 040: M4 Stage 0P PIN bootstrap tokens (I-B M4 Rehearsal, dap lai
-- PHASE1B-M4-REHEARSAL-READINESS-SNAPSHOT-REVIEW-1-VI.md finding F-M4-PIN-R1-01).
--
-- Van de CA chi ro: `scripts/m4_stage0p_provision_pin.py` (PR #7 draft) nhan `--staff-id` TUY
-- Y tu caller, ket noi DB bang DATABASE_URL co quyen ghi — KHONG co gi rang buoc nguoi go PIN
-- CHINH LA chu so huu staff_id do. Bat ky ai chay duoc `docker exec` deu co the chon staff_id
-- 3/4/5 va dat lai PIN cua principal KHAC.
--
-- Sua: single-use bootstrap token (CA de xuat huong 2, khop mo hinh "capability token dung 1
-- lan" da dung xuyen suot Stage 0P — vd m4_stage0p_fetch_capability T4-01). Dev (hoac nguoi
-- issue token) TAO token TRUOC, BUOC CUNG voi 1 staff_id CU THE — nguoi dam nhan vai tro do
-- CHI can trinh dung token (khong con tu chon staff_id) de dat PIN cho DUNG staff_id da bind.
-- Token KHONG PHAI PIN — no la ve xac thuc quyen "duoc phep dat PIN cho staff_id nay", tieu
-- thu 1 lan, het han ngan — Dev BIET token (khong sao, no khong phai secret nghiep vu), nhung
-- VAN KHONG BIET PIN thuc te nguoi do go vao (van qua getpass, rieng biet hoan toan).
--
-- Provisioning/consumption NGOAI LUONG qua superuser (DATABASE_URL admin) - CUNG mo hinh voi
-- m4_stage0p_actor_credentials/m4_stage0p_transcript_signing_keys/m4_stage0p_signing_auth_keys
-- da co (khong GRANT cho bat ky role m4 nao, khong qua ham SECURITY DEFINER rieng - ban than
-- viec issue/consume token la 1 buoc van hanh ngoai luong, khong phai 1 nghiep vu Stage 0P).
--
-- Chi luu HASH cua token (sha256 hex) - KHONG BAO GIO luu token goc trong DB.
-- transactional: true

-- ===========================================================================
-- 1. Bang m4_stage0p_pin_bootstrap_tokens
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_pin_bootstrap_tokens (
  token_hash   TEXT PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),  -- sha256 hex
  staff_id     BIGINT NOT NULL REFERENCES staff_users(id),
  issued_by    BIGINT NOT NULL REFERENCES staff_users(id),
  issued_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ NOT NULL,
  consumed_at  TIMESTAMPTZ,
  CONSTRAINT m4_pin_bootstrap_expiry_valid CHECK (expires_at > issued_at)
);

COMMENT ON TABLE m4_stage0p_pin_bootstrap_tokens IS
  'F-M4-PIN-R1-01: token dung 1 lan BUOC TRUOC voi 1 staff_id cu the - nguoi dat PIN M4 khong con tu chon staff_id, chi trinh dung token da duoc phat cho ho. Chi luu sha256(token), khong bao gio luu token goc. Provisioning/consumption ngoai luong qua superuser, khong GRANT role m4 nao.';

CREATE INDEX IF NOT EXISTS m4_pin_bootstrap_staff_idx
  ON m4_stage0p_pin_bootstrap_tokens (staff_id);

REVOKE ALL ON m4_stage0p_pin_bootstrap_tokens FROM PUBLIC;
REVOKE ALL ON m4_stage0p_pin_bootstrap_tokens FROM alpha3s_app;

-- ===========================================================================
-- 2. Postcondition fail-closed
-- ===========================================================================
DO $$
DECLARE problems TEXT := '';
BEGIN
  IF to_regclass('public.m4_stage0p_pin_bootstrap_tokens') IS NULL THEN
    problems := problems || ' table_missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public'
                 AND indexname='m4_pin_bootstrap_staff_idx') THEN
    problems := problems || ' staff_idx_missing'; END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_app') THEN
    IF has_table_privilege('alpha3s_app','public.m4_stage0p_pin_bootstrap_tokens','SELECT') THEN
      problems := problems || ' app_can_select'; END IF;
    IF has_table_privilege('alpha3s_app','public.m4_stage0p_pin_bootstrap_tokens','INSERT') THEN
      problems := problems || ' app_can_insert'; END IF;
  END IF;
  IF problems <> '' THEN
    RAISE EXCEPTION '040 postcondition FAIL —%', problems; END IF;
END $$;
