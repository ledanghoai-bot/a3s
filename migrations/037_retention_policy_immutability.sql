-- Migration 037: enforce immutability cho retention_policies tai DATABASE boundary (CA F-M3-GATE-R1-01.3).
-- Mirror pattern 034 (outbound_templates_guard): approved policy KHONG duoc sua semantics tai cho —
-- thay doi = version moi voi lifecycle ro rang.
--   Lifecycle: draft -> approved -> retired (mot chieu).
--   draft:    duoc sua (chua hieu luc), duoc DELETE.
--   approved: data_category/action/retention_period_days/respect_legal_hold/created_at BAT BIEN;
--             status chi duoc -> retired; cam DELETE.
--   retired:  bat bien hoan toan (khong un-retire); cam DELETE (audit trail).
-- Dat SAU 035 trong chuoi (035 approve tren draft van hop le; re-run 035 idempotent: UPDATE 0 row).
-- Runtime estimate: <1s. Forward-fix: chay lai file (idempotent). transactional: true

CREATE OR REPLACE FUNCTION retention_policies_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status IN ('approved', 'retired') THEN
      RAISE EXCEPTION 'immutable_retention_policy: cam DELETE policy % v% (status=%)',
        OLD.rule_id, OLD.version, OLD.status;
    END IF;
    RETURN OLD;  -- draft duoc xoa
  END IF;
  -- UPDATE
  IF OLD.status = 'retired' THEN
    RAISE EXCEPTION 'immutable_retention_policy: retired bat bien (% v%)', OLD.rule_id, OLD.version;
  END IF;
  IF OLD.rule_id IS DISTINCT FROM NEW.rule_id OR OLD.version IS DISTINCT FROM NEW.version THEN
    RAISE EXCEPTION 'immutable_retention_policy: cam doi khoa (rule_id,version) (% v%)',
      OLD.rule_id, OLD.version;
  END IF;
  IF OLD.status = 'approved' THEN
    IF OLD.data_category IS DISTINCT FROM NEW.data_category
       OR OLD.action IS DISTINCT FROM NEW.action
       OR OLD.retention_period_days IS DISTINCT FROM NEW.retention_period_days
       OR OLD.respect_legal_hold IS DISTINCT FROM NEW.respect_legal_hold
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
      RAISE EXCEPTION 'immutable_retention_policy: approved semantics bat bien — tao version moi (% v%)',
        OLD.rule_id, OLD.version;
    END IF;
    IF NEW.status NOT IN ('approved', 'retired') THEN
      RAISE EXCEPTION 'immutable_retention_policy: approved chi duoc chuyen retired (% v% -> %)',
        OLD.rule_id, OLD.version, NEW.status;
    END IF;
  ELSE  -- draft: sua duoc; status chi draft|approved
    IF NEW.status NOT IN ('draft', 'approved') THEN
      RAISE EXCEPTION 'immutable_retention_policy: draft chi duoc giu draft hoac approve (% v% -> %)',
        OLD.rule_id, OLD.version, NEW.status;
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS retention_policies_guard_trg ON retention_policies;
CREATE TRIGGER retention_policies_guard_trg
  BEFORE UPDATE OR DELETE ON retention_policies
  FOR EACH ROW EXECUTE FUNCTION retention_policies_guard();

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='retention_policies_guard_trg') THEN
    RAISE EXCEPTION '037 postcondition FAIL: thieu trigger retention_policies_guard_trg'; END IF;
END $$;
