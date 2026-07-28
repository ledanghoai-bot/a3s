-- Migration 035: PO approval cho retention policy (I-B M3 release-prep).
-- Can cu: PHASE1B-M3-PO-DECISION-RECORD-VI.md muc 1 (PO approved 2026-07-28).
-- CA F-M3-GATE-R1-01: KHONG approve mu theo (rule_id, version) — PRECONDITION xac minh EXACT TUPLE
-- ma PO da duyet (data_category, action, retention_period_days=730, respect_legal_hold=true);
-- existing DB co draft bi drift (sai period/action/category) -> RAISE, KHONG approve.
-- Executor van KHONG chay that: flag m3_retention_executor default OFF (dieu kien PO: dry-run
-- production + PO xem report truoc khi bat). Immutability sau approve: trigger migration 037.
-- Runtime estimate: <1s. Forward-fix: dieu tra drift, sua bang version moi (khong ep approve).
-- transactional: true

-- Precondition: exact tuple khop quyet dinh PO (status draft hoac approved - idempotent re-run)
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM retention_policies
   WHERE rule_id='RET-04' AND version=1 AND data_category='raw_chat' AND action='delete'
     AND retention_period_days=730 AND respect_legal_hold=true AND status IN ('draft','approved');
  IF n <> 1 THEN
    RAISE EXCEPTION '035 precondition FAIL: RET-04 v1 khong khop exact tuple PO duyet (raw_chat/delete/730/hold=true) — nghi drift, KHONG approve';
  END IF;
  SELECT count(*) INTO n FROM retention_policies
   WHERE rule_id='RET-09' AND version=1 AND data_category='deletion_requests' AND action='delete'
     AND retention_period_days=730 AND respect_legal_hold=true AND status IN ('draft','approved');
  IF n <> 1 THEN
    RAISE EXCEPTION '035 precondition FAIL: RET-09 v1 khong khop exact tuple PO duyet (deletion_requests/delete/730/hold=true) — nghi drift, KHONG approve';
  END IF;
END $$;

UPDATE retention_policies SET status='approved'
 WHERE (rule_id, version) IN (('RET-04', 1), ('RET-09', 1)) AND status='draft';

-- Postcondition: approved VA van dung exact tuple
DO $$
BEGIN
  IF (SELECT count(*) FROM retention_policies
      WHERE rule_id='RET-04' AND version=1 AND data_category='raw_chat' AND action='delete'
        AND retention_period_days=730 AND respect_legal_hold=true AND status='approved') <> 1
     OR (SELECT count(*) FROM retention_policies
      WHERE rule_id='RET-09' AND version=1 AND data_category='deletion_requests' AND action='delete'
        AND retention_period_days=730 AND respect_legal_hold=true AND status='approved') <> 1 THEN
    RAISE EXCEPTION '035 postcondition FAIL: RET-04/RET-09 v1 chua approved dung exact tuple'; END IF;
END $$;
