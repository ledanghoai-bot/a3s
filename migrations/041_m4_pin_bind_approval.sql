-- Migration 041: M4 Stage 0P PIN bind-approval ceremony + token TTL hard cap (I-B M4 Rehearsal,
-- dap lai PHASE1B-M4-REHEARSAL-PIN-TOOL-REVIEW-2-VI.md F-M4-PIN-R2-01/02/03).
--
-- REV2 (migration 040) van con 2 lo hong CA chi ra:
--
-- (R2-01) `issue-token` TU SINH raw token va IN NO RA CHO Dev/admin chuyen tiep -- token la
-- bearer credential dung 1 lan, ai NHIN THAY no truoc deu co the tu dat PIN cho staff_id da
-- bind TRUOC nguoi that su duoc cap. Sua o REV3 (`provision_pin.py`): principal TU SINH token
-- tren chinh session cua ho (subcommand `generate-token`, KHONG can DB), chi dua HASH (sha256)
-- cho Dev/admin -- Dev/admin tu do KHONG BAO GIO nhin thay/sinh ra raw token duoi bat ky hinh
-- thuc nao, chi lam viec voi hash (khong phai secret nghiep vu).
--
-- (R2-02) `--issued-by` la 1 CLI flag caller tu go, khong co gi rang buoc no voi nguoi THAT SU
-- dang chay lenh -- CA yeu cau: neu chua co authenticated execution identity (dung, moi truong
-- CLI nay khong co session/SSO cho thao tac van hanh, va day CHINH LA cong cu bootstrap PIN dau
-- tien nen khong the dung pin_actor() de xac thuc - chicken-and-egg), phai dung 1 "approval-
-- bound request record" PO ky nhan va CA kiem duoc. Bang MOI o day (`m4_stage0p_pin_bind_
-- approvals`) chinh la ghi nhan do -- 1 su kien RIENG, co timestamp/approval_ref/validity
-- window/kha nang thu hoi, TACH BIET khoi buoc bind-token. `bind-token` (REV3) khong con nhan
-- `--issued-by` nua -- `issued_by` duoc SERVER-SIDE resolve tu chinh approval record da duoc
-- tham chieu ro rang bang `--approval-id`. Gioi han trung thuc (khong the vuot qua neu khong co
-- ha tang auth thuc su): ai THAT SU go lenh `record-bind-approval` van dua tren ky luat quy
-- trinh (PO/nguoi PO uy quyen TU chay tren SSH session cua ho, dung mo hinh da chap nhan cho
-- `record-approval`/`m4_stage0p_capture_approvals` va PO Decision Record) -- code KHONG tu xung
-- day la 1 khang dinh danh tinh duoc ma hoa, chi la 1 audit trail co the thu hoi.
--
-- (R2-03) `ttl-minutes` cua bootstrap token truoc day khong co tran tren (CHECK cu chi doi hoi
-- expires_at > issued_at). Them CHECK moi gioi han cung 1-30 phut.
--
-- transactional: true

-- ===========================================================================
-- 1. Bang m4_stage0p_pin_bind_approvals (approval-bound ceremony cho bind-token)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_pin_bind_approvals (
  id              BIGSERIAL PRIMARY KEY,
  approval_ref    TEXT NOT NULL,
  target_staff_id BIGINT NOT NULL REFERENCES staff_users(id),
  recorded_by     BIGINT NOT NULL REFERENCES staff_users(id),
  valid_from      TIMESTAMPTZ NOT NULL,
  valid_until     TIMESTAMPTZ NOT NULL,
  revoked_at      TIMESTAMPTZ,
  revoke_reason   TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT m4_pin_bind_approval_window_valid CHECK (valid_until > valid_from)
);

COMMENT ON TABLE m4_stage0p_pin_bind_approvals IS
  'F-M4-PIN-R2-02: ghi nhan RIENG BIET, co timestamp/approval_ref/validity-window/thu-hoi-duoc, truoc khi bind-token duoc phep chay cho 1 target_staff_id -- bind-token resolve issued_by TU day (khong con nhan qua CLI flag tu do). Khong GRANT role m4 nao -- ngoai luong qua superuser, cung mo hinh voi m4_stage0p_pin_bootstrap_tokens.';

CREATE INDEX IF NOT EXISTS m4_pin_bind_approval_target_idx
  ON m4_stage0p_pin_bind_approvals (target_staff_id);

REVOKE ALL ON m4_stage0p_pin_bind_approvals FROM PUBLIC;
REVOKE ALL ON m4_stage0p_pin_bind_approvals FROM alpha3s_app;
REVOKE ALL ON m4_stage0p_pin_bind_approvals_id_seq FROM PUBLIC;
REVOKE ALL ON m4_stage0p_pin_bind_approvals_id_seq FROM alpha3s_app;

-- ===========================================================================
-- 2. F-M4-PIN-R2-03: tran cung 1-30 phut cho TTL cua bootstrap token
-- ===========================================================================
ALTER TABLE m4_stage0p_pin_bootstrap_tokens
  ADD CONSTRAINT m4_pin_bootstrap_ttl_bounded CHECK (
    expires_at <= issued_at + interval '30 minutes'
    AND expires_at >= issued_at + interval '1 minute'
  );

-- ===========================================================================
-- 3. Postcondition fail-closed
-- ===========================================================================
DO $$
DECLARE problems TEXT := '';
BEGIN
  IF to_regclass('public.m4_stage0p_pin_bind_approvals') IS NULL THEN
    problems := problems || ' approvals_table_missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public'
                 AND indexname='m4_pin_bind_approval_target_idx') THEN
    problems := problems || ' approval_target_idx_missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='m4_pin_bootstrap_ttl_bounded') THEN
    problems := problems || ' ttl_bound_check_missing'; END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_app') THEN
    IF has_table_privilege('alpha3s_app','public.m4_stage0p_pin_bind_approvals','SELECT') THEN
      problems := problems || ' app_can_select_approvals'; END IF;
    IF has_table_privilege('alpha3s_app','public.m4_stage0p_pin_bind_approvals','INSERT') THEN
      problems := problems || ' app_can_insert_approvals'; END IF;
  END IF;
  IF problems <> '' THEN
    RAISE EXCEPTION '041 postcondition FAIL —%', problems; END IF;
END $$;
