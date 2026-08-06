-- Migration 042: M4 Stage 0P PIN bootstrap token <-> bind approval lifecycle link (I-B M4
-- Rehearsal, dap lai PHASE1B-M4-REHEARSAL-PIN-TOOL-REVIEW-3-VI.md F-M4-PIN-R3-01).
--
-- Van de CA chi ro: `bind-token` (migration 041) chi kiem approval TAI THOI DIEM tao token row
-- -- row `m4_stage0p_pin_bootstrap_tokens` KHONG luu `approval_id`, nen `provision-pin` (buoc
-- consume) chi con kiem duoc token_hash/consumed_at/expires_at cua CHINH token, khong join lai
-- duoc approval. He qua: approval bi revoke HOAC het han SAU khi bind van khong ngan duoc token
-- da bind provision PIN thanh cong -- vong doi cua 2 bang khong con lien ket sau buoc bind.
--
-- Sua: them cot `approval_id` (NOT NULL, FK toi `m4_stage0p_pin_bind_approvals`) vao chinh bang
-- token -- gio moi token BUOC PHAI tham chieu ro rang toi approval da cho phep no ton tai, xuyen
-- suot vong doi (khong chi luc bind). `provision-pin` (code, khong phai migration nay) se JOIN +
-- FOR UPDATE ca 2 bang tai thoi diem consume, yeu cau approval van chua revoke VA con trong
-- validity window NGAY TAI THOI DIEM DO -- khong chi tai thoi diem bind.
--
-- transactional: true

ALTER TABLE m4_stage0p_pin_bootstrap_tokens
  ADD COLUMN approval_id BIGINT REFERENCES m4_stage0p_pin_bind_approvals(id);

ALTER TABLE m4_stage0p_pin_bootstrap_tokens
  ALTER COLUMN approval_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS m4_pin_bootstrap_approval_idx
  ON m4_stage0p_pin_bootstrap_tokens (approval_id);

COMMENT ON COLUMN m4_stage0p_pin_bootstrap_tokens.approval_id IS
  'F-M4-PIN-R3-01: token PHAI tham chieu approval da cho phep bind no -- provision-pin JOIN+FOR UPDATE lai bang nay TAI THOI DIEM CONSUME (khong chi luc bind) de dam bao revoke/het han approval SAU bind van chan duoc token, va race giua revoke va consume duoc giai quyet bang row-level locking cua Postgres (ai lay lock truoc thang do).';

-- ===========================================================================
-- Postcondition fail-closed
-- ===========================================================================
DO $$
DECLARE problems TEXT := '';
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='m4_stage0p_pin_bootstrap_tokens'
                 AND column_name='approval_id' AND is_nullable='NO') THEN
    problems := problems || ' approval_id_missing_or_nullable'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public'
                 AND indexname='m4_pin_bootstrap_approval_idx') THEN
    problems := problems || ' approval_idx_missing'; END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_app') THEN
    IF has_table_privilege('alpha3s_app','public.m4_stage0p_pin_bootstrap_tokens','SELECT') THEN
      problems := problems || ' app_can_select'; END IF;
  END IF;
  IF problems <> '' THEN
    RAISE EXCEPTION '042 postcondition FAIL —%', problems; END IF;
END $$;
