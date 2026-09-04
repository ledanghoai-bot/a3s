-- Migration 056: M5 Gate A — Dataset SoD role provisioning (version-controlled, fail-closed, anti-escalation).
--
-- Authority: chuan bi cho Production Gate A (Directive 148 abort vi 3 principal chua co role/grant path).
--            Nhan pattern migration 048 (m4_9_rbac_provisioning) + siet fail-closed theo CA Review 149.
--
-- BOI CANH: 052 seed catalog permissions address.dataset.view/ingest/review/manage NHUNG co y KHONG seed
-- role_permissions (dormant). role_permissions chi seed qua migration; khong co duong runtime INSERT.
-- => 3 account Gate A khong co role mang quyen dataset => require_permission tu choi. Migration nay va mảnh do.
--
-- SoD: 3 role TACH BIET, moi role DUNG 1 quyen mutation:
--   m5_dataset_custodian -> address.dataset.ingest
--   m5_dataset_reviewer  -> address.dataset.review
--   m5_dataset_owner     -> address.dataset.manage
--
-- FAIL-CLOSED (Review 149):
--  * G-A-149-03: hard-stop neu thieu bat ky permission catalog key nao (khong dua vao WHERE EXISTS im lang).
--  * G-A-149-04: hard-stop neu role key da ton tai voi is_system=true (khong coerce role la).
--  * G-A-149-02: hard-stop neu 3 role da co grant NGOAI allowlist tu truoc (trigger chi soi INSERT sau khi tao).
--  * Postcondition trong transaction: khang dinh dung 3 role (is_system=false,is_active=true) + dung 3 tuple
--    role-permission, khong thua/thieu.
--  * Trigger anti-escalation cho INSERT/UPDATE ve sau.
--
-- PHAM VI: THUAN CONG THEM (3 role + 3 grant + 1 guard trigger). KHONG dung bang khac. KHONG gan role cho staff
-- => sau migration: role ton tai nhung chua account nao giu => VAN DORMANT. Idempotent (ap lai = no-op).
-- LUU Y: CHUA apply/merge/deploy — nop de CA review; merge/deploy + gan role + window Gate A can directive rieng.
-- transactional: true

BEGIN;

-- 0. PRE-CONDITIONS (fail-closed truoc moi mutation).
--    Chinh sach (Review 150 G-A-150-01): moi target role key phai HOAC absent hoan toan, HOAC dang o dung
--    exact migration-managed state (name dung, is_system=false, is_active=true, khong grant ngoai exact tuple).
--    Moi trang thai khac -> RAISE. KHONG coerce (khong DO UPDATE ten/activation cua role khong exact).
DO $pre$
DECLARE
  missing TEXT;
  rec RECORD;
  r RECORD;
  badgrant TEXT;
BEGIN
  -- (149-03) ca ba permission key phai ton tai.
  SELECT string_agg(v.p, ', ') INTO missing
  FROM (VALUES ('address.dataset.ingest'),('address.dataset.review'),('address.dataset.manage')) AS v(p)
  WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE key = v.p);
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION '056 pre-condition FAIL: thieu permission catalog key(s): %', missing;
  END IF;

  -- (149-04 + 150-01) exact-state-or-absent cho tung role.
  FOR rec IN SELECT * FROM (VALUES
      ('m5_dataset_custodian', 'M5 Dataset Custodian (nap draft)',      'address.dataset.ingest'),
      ('m5_dataset_reviewer',  'M5 Dataset Reviewer (acceptance gate)', 'address.dataset.review'),
      ('m5_dataset_owner',     'M5 Dataset Owner (accept/activate)',    'address.dataset.manage')
    ) AS v(k, expname, expperm)
  LOOP
    SELECT key, name, is_system, is_active INTO r FROM roles WHERE key = rec.k;
    IF FOUND THEN
      IF r.is_system <> false OR r.is_active <> true OR r.name <> rec.expname THEN
        RAISE EXCEPTION '056 pre-condition FAIL: role % ton tai voi state KHONG khop managed '
          '(name=%, is_system=%, is_active=%; expected name=%, is_system=false, is_active=true) — tu choi coerce',
          rec.k, r.name, r.is_system, r.is_active, rec.expname;
      END IF;
      -- khong grant NGOAI exact tuple (exact tuple hoac rong deu chap nhan).
      SELECT string_agg(permission_key, ', ') INTO badgrant
      FROM role_permissions WHERE role_key = rec.k AND permission_key <> rec.expperm;
      IF badgrant IS NOT NULL THEN
        RAISE EXCEPTION '056 pre-condition FAIL: role % co grant ngoai allowlist: %', rec.k, badgrant;
      END IF;
    END IF;
  END LOOP;
END $pre$;

-- 1. Ba role SoD chuyen biet. DO NOTHING (khong coerce; da dam bao exact-state-or-absent o pre-condition).
INSERT INTO roles (key, name, is_system, is_active) VALUES
  ('m5_dataset_custodian', 'M5 Dataset Custodian (nap draft)',      false, true),
  ('m5_dataset_reviewer',  'M5 Dataset Reviewer (acceptance gate)', false, true),
  ('m5_dataset_owner',     'M5 Dataset Owner (accept/activate)',    false, true)
ON CONFLICT (key) DO NOTHING;

-- 2. Grant DUNG 1 quyen/role. Khong WHERE EXISTS (da assert o tren; FK role_permissions->permissions cung
--    dam bao fail-closed neu key bien mat giua chung). Idempotent.
INSERT INTO role_permissions (role_key, permission_key) VALUES
  ('m5_dataset_custodian', 'address.dataset.ingest'),
  ('m5_dataset_reviewer',  'address.dataset.review'),
  ('m5_dataset_owner',     'address.dataset.manage')
ON CONFLICT DO NOTHING;

-- 3. Trigger anti-escalation: 3 role tren CHI duoc giu dung 1 quyen cua no. Role khac khong bi anh huong.
CREATE OR REPLACE FUNCTION m5_guard_dataset_role_grants()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.role_key = 'm5_dataset_custodian' AND NEW.permission_key <> 'address.dataset.ingest' THEN
    RAISE EXCEPTION 'role m5_dataset_custodian chi duoc cap address.dataset.ingest (allowlist); tu choi %',
                    NEW.permission_key;
  ELSIF NEW.role_key = 'm5_dataset_reviewer' AND NEW.permission_key <> 'address.dataset.review' THEN
    RAISE EXCEPTION 'role m5_dataset_reviewer chi duoc cap address.dataset.review (allowlist); tu choi %',
                    NEW.permission_key;
  ELSIF NEW.role_key = 'm5_dataset_owner' AND NEW.permission_key <> 'address.dataset.manage' THEN
    RAISE EXCEPTION 'role m5_dataset_owner chi duoc cap address.dataset.manage (allowlist); tu choi %',
                    NEW.permission_key;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS m5_dataset_role_grants_allowlist ON role_permissions;
CREATE TRIGGER m5_dataset_role_grants_allowlist
  BEFORE INSERT OR UPDATE ON role_permissions
  FOR EACH ROW EXECUTE FUNCTION m5_guard_dataset_role_grants();

-- 4. POSTCONDITIONS (fail-closed trong CUNG transaction — rollback het neu sai).
DO $post$
DECLARE
  n_roles INT;
  n_grants INT;
BEGIN
  SELECT count(*) INTO n_roles FROM roles
  WHERE (key,name,is_system,is_active) IN (
      ('m5_dataset_custodian','M5 Dataset Custodian (nap draft)',      false, true),
      ('m5_dataset_reviewer', 'M5 Dataset Reviewer (acceptance gate)', false, true),
      ('m5_dataset_owner',    'M5 Dataset Owner (accept/activate)',    false, true));
  IF n_roles <> 3 THEN
    RAISE EXCEPTION '056 postcondition FAIL: expected 3 roles voi exact name/is_system=false/is_active=true, got %',
                    n_roles;
  END IF;

  SELECT count(*) INTO n_grants FROM role_permissions
  WHERE role_key IN ('m5_dataset_custodian','m5_dataset_reviewer','m5_dataset_owner');
  IF n_grants <> 3 THEN
    RAISE EXCEPTION '056 postcondition FAIL: expected exactly 3 grants for the 3 roles, got %', n_grants;
  END IF;

  IF NOT (
        EXISTS (SELECT 1 FROM role_permissions WHERE role_key='m5_dataset_custodian' AND permission_key='address.dataset.ingest')
    AND EXISTS (SELECT 1 FROM role_permissions WHERE role_key='m5_dataset_reviewer'  AND permission_key='address.dataset.review')
    AND EXISTS (SELECT 1 FROM role_permissions WHERE role_key='m5_dataset_owner'     AND permission_key='address.dataset.manage')
  ) THEN
    RAISE EXCEPTION '056 postcondition FAIL: 3 exact tuple(s) khong dung';
  END IF;
END $post$;

COMMIT;

-- ROLLBACK (tay, khi KHONG con staff nao giu 3 role — de dua ve dormant baseline):
--   BEGIN;
--   UPDATE staff_users SET role_key = NULL
--     WHERE role_key IN ('m5_dataset_custodian','m5_dataset_reviewer','m5_dataset_owner');  -- neu can
--   DROP TRIGGER IF EXISTS m5_dataset_role_grants_allowlist ON role_permissions;
--   DROP FUNCTION IF EXISTS m5_guard_dataset_role_grants();
--   DELETE FROM role_permissions
--     WHERE role_key IN ('m5_dataset_custodian','m5_dataset_reviewer','m5_dataset_owner');
--   DELETE FROM roles WHERE key IN ('m5_dataset_custodian','m5_dataset_reviewer','m5_dataset_owner');
--   COMMIT;
