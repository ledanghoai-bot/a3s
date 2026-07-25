-- Migration 016: RBAC schema + seed ROLES + seed PERMISSIONS catalog (I-B M0.4).
-- CA-REVIEW-IMPL-M0 §11: roles table canonical (khong text tu do). role_permissions MAPPING
-- (policy) KHONG seed o day — chi seed qua migration da PO approve (CA §11.3). Xem
-- scripts/rbac_seed_proposed.sql (de xuat least-privilege theo Phu luc A, cho PO tick).
-- staff_users.role_key nullable truoc (CA §11.2: audit -> PO gan -> backfill -> sau moi NOT NULL).
-- transactional: true
CREATE TABLE IF NOT EXISTS roles (
  key       TEXT PRIMARY KEY,
  name      TEXT NOT NULL,
  is_system BOOLEAN NOT NULL DEFAULT false,
  is_active BOOLEAN NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS permissions (
  key         TEXT PRIMARY KEY,
  description TEXT
);
CREATE TABLE IF NOT EXISTS role_permissions (
  role_key       TEXT NOT NULL REFERENCES roles(key) ON DELETE CASCADE,
  permission_key TEXT NOT NULL REFERENCES permissions(key) ON DELETE CASCADE,
  PRIMARY KEY (role_key, permission_key)
);
ALTER TABLE staff_users ADD COLUMN IF NOT EXISTS role_key TEXT REFERENCES roles(key);

-- Seed roles (canonical, low-controversy)
INSERT INTO roles (key, name, is_system) VALUES
  ('admin',     'Quản trị viên', true),
  ('sales',     'Kinh doanh',    true),
  ('warehouse', 'Kho vận',       true),
  ('delivery',  'Giao vận',      true),
  ('support',   'CSKH',          true),
  ('viewer',    'Chỉ xem',       true)
ON CONFLICT (key) DO NOTHING;

-- Seed permissions catalog (danh muc key ky thuat; MAPPING role->permission la policy PO)
INSERT INTO permissions (key, description) VALUES
  ('customer.view',                    'Xem khách hàng (PII mask theo quyền)'),
  ('customer.edit',                    'Sửa tên/SĐT khách'),
  ('customer.export',                  'Export dữ liệu khách'),
  ('address.view',                     'Xem địa chỉ giao'),
  ('address.override',                 'Override địa chỉ (ép xác minh)'),
  ('order.create_edit',                'Tạo/sửa đơn trước fulfillment'),
  ('order.cancel_before_ship',         'Hủy đơn trước khi shipped'),
  ('order.cancel_after_fulfillment',   'Sửa/hủy đơn sau fulfillment boundary'),
  ('order.status_change',              'Đổi order_status'),
  ('fulfillment.status_change',        'Đổi fulfillment_status (pick/pack/ship/deliver)'),
  ('payment.cod_record',               'Ghi nhận COD thu hộ (evidence/số tiền)'),
  ('payment.reconcile',                'Xác nhận payment reconciliation'),
  ('inventory.adjust',                 'Điều chỉnh tồn kho thủ công'),
  ('inventory.receive_transfer',       'Nhận hàng / chuyển kho'),
  ('price.manage',                     'Quản lý giá/khuyến mãi'),
  ('member.points_adjust',             'Điều chỉnh điểm thành viên'),
  ('affiliate.commission_approve',     'Duyệt hoa hồng affiliate'),
  ('refund.approve',                   'Duyệt refund/hoàn tiền'),
  ('approval.decide',                  'Approval inbox — người duyệt'),
  ('staff.manage',                     'Quản lý staff & session'),
  ('audit.view',                       'Xem audit log')
ON CONFLICT (key) DO NOTHING;
