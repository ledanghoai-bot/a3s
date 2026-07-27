-- Migration 026: quyền MUTATION riêng cho lifecycle (I-B M2 — CA M2-S1-F03 fix).
-- Trước đó complete/mark_delivery_failed/request_return map nhầm vào quyền CHỈ-ĐỌC
-- 'order.transition.view' (viewer cũng có) -> tài khoản read-only mutate được. Sửa: quyền write riêng,
-- KHÔNG cấp cho viewer. Expand-only, forward, self-validating.
-- transactional: true

INSERT INTO permissions (key, description) VALUES
  ('order.complete',        'Hoàn tất đơn (fulfilled/return_inspection -> completed)'),
  ('order.delivery.manage', 'Đánh dấu giao thất bại (fulfilled -> delivery_failed)'),
  ('order.return.manage',   'Xử lý trả hàng (request_return / return_inspect)')
ON CONFLICT (key) DO NOTHING;

INSERT INTO role_permissions (role_key, permission_key) VALUES
  ('admin','order.complete'),('admin','order.delivery.manage'),('admin','order.return.manage'),
  ('sales','order.complete'),('sales','order.delivery.manage'),('sales','order.return.manage'),
  ('support','order.complete'),('support','order.return.manage'),
  ('delivery','order.delivery.manage'),
  ('warehouse','order.return.manage')
ON CONFLICT (role_key, permission_key) DO NOTHING;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM permissions WHERE key='order.complete') THEN
    RAISE EXCEPTION '026 postcondition FAIL: thieu order.complete'; END IF;
  IF NOT EXISTS (SELECT 1 FROM permissions WHERE key='order.return.manage') THEN
    RAISE EXCEPTION '026 postcondition FAIL: thieu order.return.manage'; END IF;
  -- viewer (read-only) TUYET DOI khong duoc co quyen mutation
  IF EXISTS (SELECT 1 FROM role_permissions WHERE role_key='viewer'
             AND permission_key IN ('order.complete','order.delivery.manage','order.return.manage')) THEN
    RAISE EXCEPTION '026 postcondition FAIL: viewer khong duoc co quyen mutation lifecycle'; END IF;
END $$;
