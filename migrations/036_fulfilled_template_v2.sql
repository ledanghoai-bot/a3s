-- Migration 036: template order_status_fulfilled v2 (I-B M3 release-prep).
-- Can cu: PHASE1B-M3-PO-DECISION-RECORD-VI.md muc 4 (PO approved 2026-07-28).
-- CA F-M3-GATE-R1-02: ON CONFLICT DO NOTHING co the nuot existing row sai noi dung — POSTCONDITION
-- xac minh EXACT TUPLE (template_key, version, purpose_code, body, status); existing DB co v2 drift
-- (sai body/purpose) -> RAISE FAIL-CLOSED, KHONG phat hanh noi dung khac text PO duyet duoi version 2.
-- v1 GIU NGUYEN (immutable 034). Version map: transition_service._TEMPLATE_VERSIONS.
-- Runtime estimate: <1s. Forward-fix: dieu tra drift row (034 chan update approved -> drift chi co
-- the la row insert ngoai luong); xu ly bang version moi, khong ep sua.
-- transactional: true

INSERT INTO outbound_templates (template_key, version, purpose_code, body, status) VALUES
  ('order_status_fulfilled', 2, 'P03_TRANSACTIONAL',
   'Đơn #{id} của bạn đã được bàn giao cho đơn vị vận chuyển.', 'approved')
ON CONFLICT (template_key, version) DO NOTHING;

-- Postcondition: EXACT TUPLE (khong chi ton tai + approved)
DO $$
BEGIN
  IF (SELECT count(*) FROM outbound_templates
      WHERE template_key='order_status_fulfilled' AND version=2
        AND purpose_code='P03_TRANSACTIONAL'
        AND body='Đơn #{id} của bạn đã được bàn giao cho đơn vị vận chuyển.'
        AND status='approved') <> 1 THEN
    RAISE EXCEPTION '036 postcondition FAIL: order_status_fulfilled v2 khong khop EXACT tuple PO duyet (nghi drift row co san) — fail closed';
  END IF;
  -- v1 phai con nguyen (immutable — khong bi thay the)
  IF NOT EXISTS (SELECT 1 FROM outbound_templates
                 WHERE template_key='order_status_fulfilled' AND version=1
                   AND body='Đơn #{id} của bạn đã được giao.' AND status='approved') THEN
    RAISE EXCEPTION '036 postcondition FAIL: v1 khong con nguyen ven'; END IF;
END $$;
