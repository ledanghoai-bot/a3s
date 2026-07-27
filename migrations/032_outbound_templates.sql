-- Migration 032: outbound template registry (I-B M3 Slice 5). Spec §7.6 (approved template version).
-- Template IMMUTABLE theo (template_key, version): sua noi dung = version moi; KHONG UPDATE body
-- (enforce: app khong co code update + trigger chan UPDATE body/status->khac-approved khong can thiet
--  o muc M3 — quy uoc + review; ghi trong runbook).
-- Seed v1 = DUNG BANG text _CUSTOMER_NOTIFY hien hanh (M2 + delivered M3-S1) -> flag ON khong doi
-- noi dung gui khach (AC-M3-06).
-- Runtime estimate: <1s. Forward-fix: chay lai file (idempotent). transactional: true

CREATE TABLE IF NOT EXISTS outbound_templates (
  template_key text NOT NULL,
  version      integer NOT NULL CHECK (version >= 1),
  purpose_code text NOT NULL CHECK (purpose_code IN (
    'P03_TRANSACTIONAL','P04_SUPPORT','P05_LIFECYCLE','P06_MARKETING')),
  body         text NOT NULL,
  status       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','retired')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (template_key, version)
);

COMMENT ON TABLE outbound_templates IS
  'Template registry cho Outbound Dispatcher (M3-S5). Immutable theo (key,version). '
  'data_class=D0_PUBLIC (body khong PII — placeholder {id}...); owner_system=alpha3s';

INSERT INTO outbound_templates (template_key, version, purpose_code, body, status) VALUES
  ('order_status_confirmed', 1, 'P03_TRANSACTIONAL', 'Đơn #{id} của bạn đã được xác nhận.', 'approved'),
  ('order_status_fulfilled', 1, 'P03_TRANSACTIONAL', 'Đơn #{id} của bạn đã được giao.', 'approved'),
  ('order_status_delivered', 1, 'P03_TRANSACTIONAL', 'Đơn #{id} của bạn đã giao thành công. Cảm ơn bạn!', 'approved'),
  ('order_status_cancelled', 1, 'P03_TRANSACTIONAL', 'Đơn #{id} của bạn đã được huỷ.', 'approved'),
  ('order_status_cancelled_by_exception', 1, 'P03_TRANSACTIONAL', 'Đơn #{id} của bạn đã được huỷ.', 'approved'),
  ('order_status_completed', 1, 'P03_TRANSACTIONAL', 'Đơn #{id} của bạn đã hoàn tất. Cảm ơn bạn!', 'approved')
ON CONFLICT (template_key, version) DO NOTHING;

DO $$
BEGIN
  IF (SELECT count(*) FROM outbound_templates WHERE status='approved') < 6 THEN
    RAISE EXCEPTION '032 postcondition FAIL: thieu seed template approved'; END IF;
END $$;
