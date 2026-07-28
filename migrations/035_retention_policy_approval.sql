-- Migration 035: PO approval cho retention policy (I-B M3 release-prep).
-- Can cu: PHASE1B-M3-PO-DECISION-RECORD-VI.md muc 1 (PO approved 2026-07-28): RET-04 raw_chat
-- 730 ngay, RET-09 deletion_requests 730 ngay -> nang draft (seed 033) len 'approved'.
-- Executor van KHONG chay that: flag m3_retention_executor default OFF; dieu kien PO = dry-run
-- production + PO xem report truoc khi bat flag (2 lop chan doc lap).
-- Runtime estimate: <1s. Forward-fix: chay lai file (idempotent). transactional: true

UPDATE retention_policies SET status='approved'
 WHERE (rule_id, version) IN (('RET-04', 1), ('RET-09', 1)) AND status='draft';

DO $$
BEGIN
  IF (SELECT count(*) FROM retention_policies
      WHERE (rule_id, version) IN (('RET-04',1),('RET-09',1)) AND status='approved') <> 2 THEN
    RAISE EXCEPTION '035 postcondition FAIL: RET-04/RET-09 v1 chua approved'; END IF;
END $$;
