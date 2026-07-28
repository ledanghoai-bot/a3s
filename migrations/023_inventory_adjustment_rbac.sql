-- Migration 023: adjustment requests + unit/location mapping + M2 RBAC (I-B M2). Spec §9.6, §12, §14.
-- Separation of duties: requester != approver; large adjustment cần Unit Head của location approve.
-- Unit Head = role 'unit_head' (capability) + mapping inventory_unit_members (scope location).
-- transactional: true

-- ===========================================================================
-- 9.6 inventory_adjustment_requests
-- ===========================================================================
CREATE TABLE IF NOT EXISTS inventory_adjustment_requests (
  id                    UUID PRIMARY KEY,
  location_id           BIGINT NOT NULL REFERENCES inventory_locations(id),
  product_id            BIGINT NOT NULL REFERENCES products(id),
  quantity_delta        INTEGER NOT NULL CHECK (quantity_delta <> 0),
  threshold_at_request  INTEGER NOT NULL,
  is_large              BOOLEAN NOT NULL,
  reason                TEXT NOT NULL,
  evidence_ref          TEXT NULL,
  status                TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','expired','applied')),
  requested_by_staff_id BIGINT NOT NULL REFERENCES staff_users(id),
  approved_by_staff_id  BIGINT NULL REFERENCES staff_users(id),
  requested_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at            TIMESTAMPTZ NULL,
  applied_at            TIMESTAMPTZ NULL,
  request_command_id    UUID NULL REFERENCES command_executions(id),
  decision_command_id   UUID NULL REFERENCES command_executions(id),
  -- SoD: người duyệt != người yêu cầu (§12.3)
  CONSTRAINT inventory_adjustment_requester_ne_approver
    CHECK (approved_by_staff_id IS NULL OR approved_by_staff_id <> requested_by_staff_id),
  -- large đã applied phải có approver (§9.6)
  CONSTRAINT inventory_adjustment_large_needs_approver
    CHECK (NOT (is_large AND status = 'applied' AND approved_by_staff_id IS NULL))
);
CREATE INDEX IF NOT EXISTS inventory_adjustment_status_idx ON inventory_adjustment_requests (status, requested_at);
CREATE INDEX IF NOT EXISTS inventory_adjustment_location_idx ON inventory_adjustment_requests (location_id, product_id);

-- ===========================================================================
-- Unit/location mapping (§12.4): ai là Unit Head của location nào
-- ===========================================================================
CREATE TABLE IF NOT EXISTS inventory_unit_members (
  staff_id    BIGINT NOT NULL REFERENCES staff_users(id) ON DELETE CASCADE,
  location_id BIGINT NOT NULL REFERENCES inventory_locations(id) ON DELETE CASCADE,
  unit_role   TEXT NOT NULL CHECK (unit_role IN ('unit_head','member')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (staff_id, location_id)
);
CREATE INDEX IF NOT EXISTS inventory_unit_members_location_idx ON inventory_unit_members (location_id, unit_role);

-- ===========================================================================
-- RBAC: role 'unit_head' + M2 permissions + role_permissions maps (§14)
-- ===========================================================================
INSERT INTO roles (key, name, is_system) VALUES ('unit_head', 'Trưởng đơn vị (kho)', true)
ON CONFLICT (key) DO NOTHING;

INSERT INTO permissions (key, description) VALUES
  ('order.transition.view',       'Xem trạng thái/timeline đơn (M2)'),
  ('order.confirm',               'Xác nhận đơn new->confirmed'),
  ('order.process',               'confirmed->processing'),
  ('order.fulfillment.prepare',   'processing->ready_for_fulfillment'),
  ('order.fulfill',               'ready->fulfilled (consume reservation/on_hand)'),
  ('order.cancel',                'Huỷ đơn trước fulfillment'),
  ('order.cancel.exception',      'Huỷ ngoại lệ (processing->cancelled_by_exception)'),
  ('inventory.view',              'Xem balance on_hand/reserved/available'),
  ('inventory.movement.view',     'Xem ledger movement'),
  ('inventory.reservation.extend','Gia hạn reservation'),
  ('inventory.adjust',            'Yêu cầu/áp điều chỉnh tồn nhỏ'),
  ('inventory.adjust.approve',    'Duyệt điều chỉnh tồn lớn (Unit Head)'),
  ('inventory.reconcile',         'Xem/đối soát reconciliation')
ON CONFLICT (key) DO NOTHING;

INSERT INTO role_permissions (role_key, permission_key) VALUES
  -- admin: full
  ('admin','order.transition.view'),('admin','order.confirm'),('admin','order.process'),
  ('admin','order.fulfillment.prepare'),('admin','order.fulfill'),('admin','order.cancel'),
  ('admin','order.cancel.exception'),('admin','inventory.view'),('admin','inventory.movement.view'),
  ('admin','inventory.reservation.extend'),('admin','inventory.adjust'),('admin','inventory.adjust.approve'),
  ('admin','inventory.reconcile'),
  -- unit_head: quản lý kho + duyệt adjustment lớn (scope theo mapping)
  ('unit_head','order.transition.view'),('unit_head','inventory.view'),('unit_head','inventory.movement.view'),
  ('unit_head','inventory.reservation.extend'),('unit_head','inventory.adjust'),
  ('unit_head','inventory.adjust.approve'),('unit_head','inventory.reconcile'),
  -- warehouse (tài khoản 'inventory'): thao tác tồn, KHÔNG approve
  ('warehouse','order.transition.view'),('warehouse','order.fulfillment.prepare'),('warehouse','order.fulfill'),
  ('warehouse','inventory.view'),('warehouse','inventory.movement.view'),
  ('warehouse','inventory.reservation.extend'),('warehouse','inventory.adjust'),
  -- sales: quản lý đơn
  ('sales','order.transition.view'),('sales','order.confirm'),('sales','order.process'),
  ('sales','order.fulfillment.prepare'),('sales','order.cancel'),('sales','inventory.view'),
  -- support: xem + huỷ/xác nhận, KHÔNG adjust/fulfill
  ('support','order.transition.view'),('support','order.confirm'),('support','order.cancel'),('support','inventory.view'),
  -- delivery: xem, KHÔNG inventory adjustment
  ('delivery','order.transition.view'),('delivery','inventory.view'),
  -- viewer: read-only
  ('viewer','order.transition.view'),('viewer','inventory.view'),('viewer','inventory.movement.view')
ON CONFLICT (role_key, permission_key) DO NOTHING;

-- ===========================================================================
-- Postcondition
-- ===========================================================================
DO $$
BEGIN
  IF to_regclass('public.inventory_adjustment_requests') IS NULL THEN
    RAISE EXCEPTION '023 postcondition FAIL: thieu inventory_adjustment_requests'; END IF;
  IF to_regclass('public.inventory_unit_members') IS NULL THEN
    RAISE EXCEPTION '023 postcondition FAIL: thieu inventory_unit_members'; END IF;
  IF NOT EXISTS (SELECT 1 FROM roles WHERE key='unit_head') THEN
    RAISE EXCEPTION '023 postcondition FAIL: thieu role unit_head'; END IF;
  IF NOT EXISTS (SELECT 1 FROM role_permissions WHERE role_key='unit_head' AND permission_key='inventory.adjust.approve') THEN
    RAISE EXCEPTION '023 postcondition FAIL: unit_head thieu inventory.adjust.approve'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='inventory_adjustment_requester_ne_approver') THEN
    RAISE EXCEPTION '023 postcondition FAIL: thieu SoD constraint'; END IF;
END $$;
