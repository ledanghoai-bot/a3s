-- Migration 020: M1 command/outbox RBAC permissions + role mappings (I-B M1 Slice 8).
-- Governing: A3S-PHASE1B-M1-SPEC-001 §11.1. Catalog permission (ky thuat) + mapping role->permission
-- (policy least-privilege). Admin full; support (CSKH/operator) view+retry+cancel; sales/viewer view;
-- replay CHI admin (permission cao hon retry, §9.3). Forward-only, idempotent (ON CONFLICT DO NOTHING).
-- transactional: true
INSERT INTO permissions (key, description) VALUES
  ('commands.view', 'Xem command executions + receipt (M1)'),
  ('outbox.view',   'Xem outbox events + delivery attempts (M1)'),
  ('outbox.retry',  'Retry mot dead-letter outbox event (M1)'),
  ('outbox.replay', 'Replay: tao outbox event moi (admin, M1)'),
  ('outbox.cancel', 'Cancel outbox event chua delivered (M1)')
ON CONFLICT (key) DO NOTHING;

INSERT INTO role_permissions (role_key, permission_key) VALUES
  ('admin','commands.view'), ('admin','outbox.view'), ('admin','outbox.retry'),
  ('admin','outbox.replay'), ('admin','outbox.cancel'),
  ('support','commands.view'), ('support','outbox.view'), ('support','outbox.retry'), ('support','outbox.cancel'),
  ('sales','commands.view'), ('sales','outbox.view'),
  ('viewer','commands.view'), ('viewer','outbox.view')
ON CONFLICT (role_key, permission_key) DO NOTHING;

-- Postcondition fail-closed: 5 permission M1 phai ton tai + admin phai co replay.
DO $$
BEGIN
  IF (SELECT count(*) FROM permissions WHERE key IN
        ('commands.view','outbox.view','outbox.retry','outbox.replay','outbox.cancel')) <> 5 THEN
    RAISE EXCEPTION '020 postcondition FAIL: thieu M1 permission catalog';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM role_permissions WHERE role_key='admin' AND permission_key='outbox.replay') THEN
    RAISE EXCEPTION '020 postcondition FAIL: admin thieu outbox.replay';
  END IF;
END $$;
