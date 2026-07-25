-- Migration 018: seed role_permissions mapping (I-B M0.4, CA-REVIEW-M0-DEV-003 §5).
-- VERSIONED seed — thay cho chay scripts/rbac_seed_proposed.sql truc tiep bang psql (CA cam).
-- NOI DUNG = ma tran role->permission PO DA DUYET. Hien tai = de xuat least-privilege (Phu luc A);
-- PO phai duyet/sua truoc khi chay tren production (worksheet PHASE1B-RBAC-STAFF-WORKSHEET).
-- Idempotent (ON CONFLICT DO NOTHING) -> chay lai an toan. transactional: true
-- KHONG chay tren production truoc khi: PO duyet ma tran + CA release approval (xem runbook §3A).

-- admin: TAT CA permission
INSERT INTO role_permissions (role_key, permission_key)
SELECT 'admin', key FROM permissions ON CONFLICT DO NOTHING;

-- sales
INSERT INTO role_permissions (role_key, permission_key) VALUES
  ('sales', 'customer.view'), ('sales', 'customer.edit'), ('sales', 'address.view'),
  ('sales', 'order.create_edit'), ('sales', 'order.cancel_before_ship'), ('sales', 'order.status_change')
ON CONFLICT DO NOTHING;

-- warehouse
INSERT INTO role_permissions (role_key, permission_key) VALUES
  ('warehouse', 'customer.view'), ('warehouse', 'fulfillment.status_change'),
  ('warehouse', 'inventory.receive_transfer')
ON CONFLICT DO NOTHING;

-- delivery  (payment.cod_record = quyen ghi nhan tai chinh — PO xac nhan, CA §7)
INSERT INTO role_permissions (role_key, permission_key) VALUES
  ('delivery', 'fulfillment.status_change'), ('delivery', 'payment.cod_record')
ON CONFLICT DO NOTHING;

-- support  (edit khach = propose-change; payment.cod_record = PO xac nhan)
INSERT INTO role_permissions (role_key, permission_key) VALUES
  ('support', 'customer.view'), ('support', 'payment.cod_record')
ON CONFLICT DO NOTHING;

-- viewer (customer.view voi PII masked o API)
INSERT INTO role_permissions (role_key, permission_key) VALUES
  ('viewer', 'customer.view')
ON CONFLICT DO NOTHING;
