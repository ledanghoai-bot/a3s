-- Migration 036: template order_status_fulfilled v2 (I-B M3 release-prep).
-- Can cu: PHASE1B-M3-PO-DECISION-RECORD-VI.md muc 4 (PO approved 2026-07-28). fulfilled = hang roi
-- kho (co delivered rieng tu 029) -> text v1 "da duoc giao" gay hieu nham. v2 = ban giao van chuyen.
-- Dung co che immutable 034: v1 GIU NGUYEN (khong update-in-place), INSERT version moi approved.
-- Dispatcher chon version qua map tuong minh trong transition_service (v2 cho fulfilled) — chi hieu
-- luc khi flag m3_outbound_dispatcher ON; duong legacy (flag OFF) van text cu -> khong doi behavior.
-- Runtime estimate: <1s. Forward-fix: chay lai file (idempotent). transactional: true

INSERT INTO outbound_templates (template_key, version, purpose_code, body, status) VALUES
  ('order_status_fulfilled', 2, 'P03_TRANSACTIONAL',
   'Đơn #{id} của bạn đã được bàn giao cho đơn vị vận chuyển.', 'approved')
ON CONFLICT (template_key, version) DO NOTHING;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM outbound_templates
                 WHERE template_key='order_status_fulfilled' AND version=2 AND status='approved') THEN
    RAISE EXCEPTION '036 postcondition FAIL: thieu order_status_fulfilled v2 approved'; END IF;
  -- v1 phai con nguyen (immutable — khong bi thay the)
  IF NOT EXISTS (SELECT 1 FROM outbound_templates
                 WHERE template_key='order_status_fulfilled' AND version=1 AND status='approved') THEN
    RAISE EXCEPTION '036 postcondition FAIL: v1 khong con nguyen'; END IF;
END $$;
