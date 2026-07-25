-- rbac_seed_proposed.sql — ĐỀ XUẤT mapping role -> permission (least-privilege, Phụ lục A).
-- =====================================================================================
-- TRANG THAI: PROPOSED — CHO PO TICK/DUYET. CHUA phai migration (KHONG nam trong migrations/).
-- CA-REVIEW-IMPL-M0 §11.3: role_permissions mapping chi seed qua migration DA PO APPROVE.
-- Sau khi PO duyet -> copy noi dung nay thanh migration (vd 018_rbac_seed.sql) roi chay qua runner.
--
-- Chi seed cac o ✅ (direct grant) cua Phu luc A. Cac o ⚠️ (cần duyệt) / ✎ (propose-change) /
-- 👁️ (view masked) KHONG phai binary permission -> xu ly o approval framework / PII masking /
-- propose-change layer (milestone sau), KHONG grant thang o day.
-- =====================================================================================

-- admin: TAT CA permission
INSERT INTO role_permissions (role_key, permission_key)
SELECT 'admin', key FROM permissions
ON CONFLICT DO NOTHING;

-- sales
INSERT INTO role_permissions (role_key, permission_key) VALUES
  ('sales', 'customer.view'),
  ('sales', 'customer.edit'),
  ('sales', 'address.view'),
  ('sales', 'order.create_edit'),
  ('sales', 'order.cancel_before_ship'),
  ('sales', 'order.status_change')
ON CONFLICT DO NOTHING;

-- warehouse
INSERT INTO role_permissions (role_key, permission_key) VALUES
  ('warehouse', 'customer.view'),
  ('warehouse', 'fulfillment.status_change'),
  ('warehouse', 'inventory.receive_transfer')
ON CONFLICT DO NOTHING;

-- delivery
INSERT INTO role_permissions (role_key, permission_key) VALUES
  ('delivery', 'fulfillment.status_change'),
  ('delivery', 'payment.cod_record')
ON CONFLICT DO NOTHING;

-- support (edit khach = propose-change, khong grant direct edit — CA §6.2)
INSERT INTO role_permissions (role_key, permission_key) VALUES
  ('support', 'customer.view'),
  ('support', 'payment.cod_record')
ON CONFLICT DO NOTHING;

-- viewer (customer.view voi PII masked o API — CA §6.3)
INSERT INTO role_permissions (role_key, permission_key) VALUES
  ('viewer', 'customer.view')
ON CONFLICT DO NOTHING;
