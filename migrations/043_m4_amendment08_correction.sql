-- Migration 043: M4 Amendment 08 execution-attempt correction (I-B M4 Rehearsal, dap lai
-- PHASE1B-M4-AMENDMENT-08-EXECUTION-ATTEMPT-1-REVIEW-VI.md F-A08-EXEC-02/04 va
-- PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-DIRECTIVE-VI.md A08-COR-02/A08-COR-04).
--
-- Boi canh: lan execute that dau tien (Amendment 08, 11/8) that bai o buoc collector vi signing
-- service chua duoc cau hinh chay tren production. Runner tu cleanup phan lon (capture OFF, key
-- retired, synthetic rows purge) nhung BO SOT hang `m4_selection_batches` vua tao — batch nay
-- khong nam trong danh sach bang nao `_purge_synthetic()`/`_verify_cleanup_postconditions()` biet
-- toi, nen postcondition verifier KHONG phat hien duoc residual, khong bao CLEANUP_FAILED du batch
-- van o trang thai 'locked'. Dev phai xoa tay batch nay qua 1 cleanup directive rieng cua CA.
--
-- Cung round nay, ceremony tao du 1 bind approval (approval_ref='...amendment-08-bind-3',
-- target_staff_id=3) vi 1 lenh bi go/paste lap 2 lan — khong co gi ngan CSDL tu choi truoc, chi
-- phat hien duoc qua doc lai thu cong.
--
-- transactional: true

-- ===========================================================================
-- A08-COR-02: them trang thai terminal 'aborted' cho m4_selection_batches, de cleanup co the
-- TERMINALIZE (khong xoa) batch cua 1 lifecycle that bai — giu lai lam audit trail (batch_id/
-- status/count/timestamp, KHONG chua noi dung tin nhan) thay vi mat dau vet hoan toan, cung
-- triet ly voi cach approval/token lich su duoc giu lai (khong xoa) xuyen suot du an. Batch DA
-- toi 'evaluation_completed' (thanh cong that su) khong bao gio bi doi sang 'aborted' - chi ap
-- dung cho batch chua hoan tat truoc khi lifecycle that bai.
-- ===========================================================================
DO $$
DECLARE
  v_conname TEXT;
BEGIN
  SELECT con.conname INTO v_conname
  FROM pg_constraint con
  JOIN pg_class rel ON rel.oid = con.conrelid
  WHERE rel.relname = 'm4_selection_batches'
    AND con.contype = 'c'
    AND pg_get_constraintdef(con.oid) LIKE '%status%locked%collecting%';
  IF v_conname IS NULL THEN
    RAISE EXCEPTION '043: khong tim thay CHECK constraint hien tai cua cot status tren m4_selection_batches - schema da thay doi ngoai du kien, dung migration de tranh ghi de sai';
  END IF;
  EXECUTE format('ALTER TABLE m4_selection_batches DROP CONSTRAINT %I', v_conname);
END $$;

ALTER TABLE m4_selection_batches
  ADD CONSTRAINT m4_selection_batches_status_check CHECK (
    status IN ('locked', 'collecting', 'collection_closed', 'labels_sealed',
               'predictions_written', 'evaluation_completed', 'aborted'));

ALTER TABLE m4_selection_batches
  ADD COLUMN IF NOT EXISTS aborted_at TIMESTAMPTZ;

ALTER TABLE m4_selection_batches
  ADD CONSTRAINT m4_batch_aborted_at_consistent CHECK (
    (status = 'aborted') = (aborted_at IS NOT NULL));

COMMENT ON COLUMN m4_selection_batches.aborted_at IS
  'F-A08-EXEC-02: dat khi runner cleanup terminalize 1 batch cua lifecycle THAT BAI (khong bao gio
   dung cho batch da toi evaluation_completed) - giu batch lam audit trail thay vi xoa.';

-- ===========================================================================
-- A08-COR-04: chan duplicate bind approval CUNG approval_ref + target_staff_id o trang thai CON
-- HIEU LUC (chua revoke) bang DB-enforced partial unique index - khong con chi dua vao CLI
-- precheck (de rang buoc bang race, dung xay ra dung nhu vay o Amendment 08). Partial (WHERE
-- revoked_at IS NULL) de: (a) row lich su da revoke KHONG bi tinh, khong can xoa gi de dat duoc
-- uniqueness; (b) van tao duoc approval MOI cho amendment/approval_ref KHAC bat cu luc nao.
-- ===========================================================================
CREATE UNIQUE INDEX IF NOT EXISTS m4_pin_bind_approval_active_unique
  ON m4_stage0p_pin_bind_approvals (approval_ref, target_staff_id)
  WHERE revoked_at IS NULL;

COMMENT ON INDEX m4_pin_bind_approval_active_unique IS
  'F-A08-EXEC-04/A08-COR-04: toi da 1 bind approval CON HIEU LUC (chua revoke) cho 1 cap
   (approval_ref, target_staff_id) - chan duplicate ceremony do lap lenh/race, khong anh huong
   row lich su da revoke.';

-- ===========================================================================
-- Postcondition fail-closed
-- ===========================================================================
DO $$
DECLARE problems TEXT := '';
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'm4_selection_batches_status_check') THEN
    problems := problems || ' status_check_missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'm4_batch_aborted_at_consistent') THEN
    problems := problems || ' aborted_at_consistency_check_missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'm4_selection_batches' AND column_name = 'aborted_at') THEN
    problems := problems || ' aborted_at_column_missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public'
                 AND indexname = 'm4_pin_bind_approval_active_unique') THEN
    problems := problems || ' bind_approval_active_unique_index_missing'; END IF;
  IF problems <> '' THEN
    RAISE EXCEPTION '043 postcondition FAIL —%', problems; END IF;
END $$;
