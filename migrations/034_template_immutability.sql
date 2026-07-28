-- Migration 034: enforce immutability cho outbound_templates tai DATABASE boundary (I-B M3, CA F-M3-R1-03).
-- 032 dua tren quy uoc app-side — KHONG du (SQL van hanh/migration/code tuong lai co the sua body
-- cua approved version tai cho). 034 them trigger:
--   Lifecycle hop le:  draft -> approved -> retired (mot chieu).
--   draft:    duoc sua body/purpose_code (chua publish), duoc DELETE.
--   approved: body/purpose_code/template_key/version BAT BIEN; status chi duoc -> retired; cam DELETE.
--   retired:  bat bien hoan toan (khong un-retire); cam DELETE (audit trail).
-- Sua noi dung = tao version MOI (INSERT), khong bao gio update-in-place approved.
-- Seed drift: 032 dung ON CONFLICT DO NOTHING nen re-apply khong phat hien drift -> 034 postcondition
-- kiem checksum seed v1 (RAISE neu lech).
-- Runtime estimate: <1s. Forward-fix: chay lai file (idempotent). transactional: true

CREATE OR REPLACE FUNCTION outbound_templates_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status IN ('approved', 'retired') THEN
      RAISE EXCEPTION 'immutable_template: cam DELETE template % v% (status=%)',
        OLD.template_key, OLD.version, OLD.status;
    END IF;
    RETURN OLD;  -- draft duoc xoa
  END IF;
  -- UPDATE
  IF OLD.status = 'retired' THEN
    RAISE EXCEPTION 'immutable_template: retired bat bien (% v%)', OLD.template_key, OLD.version;
  END IF;
  IF OLD.template_key IS DISTINCT FROM NEW.template_key
     OR OLD.version IS DISTINCT FROM NEW.version THEN
    RAISE EXCEPTION 'immutable_template: cam doi khoa (key,version) (% v%)', OLD.template_key, OLD.version;
  END IF;
  IF OLD.status = 'approved' THEN
    IF OLD.body IS DISTINCT FROM NEW.body
       OR OLD.purpose_code IS DISTINCT FROM NEW.purpose_code
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
      RAISE EXCEPTION 'immutable_template: approved body/purpose bat bien — tao version moi (% v%)',
        OLD.template_key, OLD.version;
    END IF;
    IF NEW.status NOT IN ('approved', 'retired') THEN
      RAISE EXCEPTION 'immutable_template: approved chi duoc chuyen retired (% v% -> %)',
        OLD.template_key, OLD.version, NEW.status;
    END IF;
  ELSE  -- OLD.status = 'draft': duoc sua noi dung; status chi draft|approved (khong nhay thang retired)
    IF NEW.status NOT IN ('draft', 'approved') THEN
      RAISE EXCEPTION 'immutable_template: draft chi duoc giu draft hoac approve (% v% -> %)',
        OLD.template_key, OLD.version, NEW.status;
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS outbound_templates_guard_trg ON outbound_templates;
CREATE TRIGGER outbound_templates_guard_trg
  BEFORE UPDATE OR DELETE ON outbound_templates
  FOR EACH ROW EXECUTE FUNCTION outbound_templates_guard();

-- Postcondition 1: trigger ton tai
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='outbound_templates_guard_trg') THEN
    RAISE EXCEPTION '034 postcondition FAIL: thieu trigger outbound_templates_guard_trg'; END IF;
END $$;

-- Postcondition 2 (seed drift check — CA F-M3-R1-03): checksum 6 seed v1 cua 032 phai dung ky vong.
-- Re-apply/existing-apply se RAISE neu ai do da sua seed (thay vi im lang nhu ON CONFLICT DO NOTHING).
DO $$
DECLARE
  ck text;
BEGIN
  SELECT md5(string_agg(template_key || '|' || version || '|' || purpose_code || '|' || status
                        || '|' || body, E'\n' ORDER BY template_key))
    INTO ck
    FROM outbound_templates
   WHERE version = 1
     AND template_key IN ('order_status_confirmed','order_status_fulfilled','order_status_delivered',
                          'order_status_cancelled','order_status_cancelled_by_exception',
                          'order_status_completed');
  IF ck IS DISTINCT FROM '538cf5f754455679ae4bd3beb6eab009' THEN
    RAISE EXCEPTION '034 postcondition FAIL: seed template v1 drift (md5=%)', ck;
  END IF;
END $$;
