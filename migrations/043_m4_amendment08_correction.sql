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
-- A08-COR-04 (REV1, dap F-A08-R1-05): chan duplicate bind approval CUNG approval_ref +
-- target_staff_id cho DU BAT KY trang thai nao (ke ca hang lich su DA revoke) - REV0 (partial
-- unique index WHERE revoked_at IS NULL) chi chan hang CON hieu luc, van cho tao lai CUNG cap
-- (ref, target) sau khi revoke - CA yeu cau chan tuyet doi hon: 1 cap (ref, target) chi duoc
-- dung DUNG 1 lan trong toan bo lich su, muon ceremony lai PHAI dung approval_ref MOI (vd
-- amendment khac).
--
-- KHONG dung UNIQUE INDEX thuong: production DA CO 2 hang lich su trung nhau that su (approval id
-- 4 va 7, Amendment 08, ca hai DA revoke) - 1 UNIQUE INDEX thuong se FAIL NGAY luc tao migration
-- vi du lieu cu vi pham no, va yeu cau nay CAM xoa/sua du lieu lich su do. Dung TRIGGER + advisory
-- lock: chi ap dung cho INSERT MOI (khong retroactive kiem tra hang cu), rieng du lieu cu van giu
-- nguyen 100%. `pg_advisory_xact_lock(hashtext(ref), hashtext(target::text))` khoa theo CAP
-- (ref, target) trong PHAM VI transaction hien tai - dong bo hoa 2 INSERT dong thoi cho CUNG cap
-- (transaction thu 2 phai doi transaction thu nhat COMMIT/ROLLBACK truoc khi duoc tiep tuc, luc
-- do EXISTS check cua no se THAY hang vua duoc INSERT boi transaction thu nhat va tu choi dung) -
-- dong hoan toan khoang ho TOCTOU giua luc kiem tra va luc ghi that su xay ra o Amendment 08.
-- ===========================================================================
DROP INDEX IF EXISTS m4_pin_bind_approval_active_unique;

CREATE OR REPLACE FUNCTION m4_pin_bind_approval_prevent_duplicate() RETURNS TRIGGER AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext(NEW.approval_ref), hashtext(NEW.target_staff_id::text));
  IF EXISTS (
    SELECT 1 FROM m4_stage0p_pin_bind_approvals
    WHERE approval_ref = NEW.approval_ref AND target_staff_id = NEW.target_staff_id
  ) THEN
    RAISE EXCEPTION 'm4_stage0p_pin_bind_approvals: da co it nhat 1 hang (bat ky trang thai, ke '
      'ca da revoke) cho approval_ref=% target_staff_id=% - khong tao duplicate '
      '(F-A08-EXEC-04/A08-COR-04). Dung approval_ref MOI de tao ceremony moi cho staff nay.',
      NEW.approval_ref, NEW.target_staff_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS m4_pin_bind_approval_dedup_trigger ON m4_stage0p_pin_bind_approvals;
CREATE TRIGGER m4_pin_bind_approval_dedup_trigger
  BEFORE INSERT ON m4_stage0p_pin_bind_approvals
  FOR EACH ROW EXECUTE FUNCTION m4_pin_bind_approval_prevent_duplicate();

COMMENT ON TRIGGER m4_pin_bind_approval_dedup_trigger ON m4_stage0p_pin_bind_approvals IS
  'F-A08-EXEC-04/A08-COR-04 (REV1): chan MOI INSERT trung (approval_ref, target_staff_id) voi BAT
   KY hang nao da ton tai (ke ca da revoke) - khong retroactive, khong xoa/sua du lieu lich su
   (vd approval id 4/7 tren production). Advisory lock (2 tham so, khoa theo cap ref+target) dong
   khoang ho TOCTOU giua 2 INSERT dong thoi cho cung 1 cap.';

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
  IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public'
             AND indexname = 'm4_pin_bind_approval_active_unique') THEN
    problems := problems || ' stale_partial_unique_index_still_present'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'm4_pin_bind_approval_prevent_duplicate') THEN
    problems := problems || ' dedup_trigger_function_missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'm4_pin_bind_approval_dedup_trigger'
                 AND NOT tgisinternal) THEN
    problems := problems || ' dedup_trigger_missing'; END IF;
  IF problems <> '' THEN
    RAISE EXCEPTION '043 postcondition FAIL —%', problems; END IF;
END $$;
