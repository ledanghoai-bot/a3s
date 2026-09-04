-- Migration 056: M5 Gate A — Dataset SoD role provisioning (version-controlled, anti-escalation).
--
-- Authority: chuan bi cho Production Gate A (Directive 148 aborted vi 3 principal chua co role/grant path).
--            Nhan pattern migration 048 (m4_9_rbac_provisioning): dinh nghia role->permission BANG CODE
--            (reviewed), khong grant tay/ad-hoc.
--
-- BOI CANH: migration 052 seed permissions catalog `address.dataset.view/ingest/review/manage` NHUNG CO Y
-- KHONG seed role_permissions (dormant). role_permissions chi seed qua migration (018/020/023/026/046/048...);
-- KHONG co duong runtime INSERT role_permissions. => 3 account (custodian/staff-1/po-hoai) khong co role
-- mang quyen dataset => require_permission tu choi => Gate A khong chay duoc. Migration nay vá dung mảnh do.
--
-- SoD: 3 role TACH BIET, moi role DUNG 1 quyen mutation (khong chong lan) — bao toan
-- accepter != reviewer != ingester o TANG RBAC (control layer van ep SoD actor-distinct doc lap):
--   m5_dataset_custodian -> address.dataset.ingest   (Custodian nap draft)
--   m5_dataset_reviewer  -> address.dataset.review   (Reviewer chay acceptance gate)
--   m5_dataset_owner     -> address.dataset.manage   (PO Data Owner accept/activate/deactivate/rollback)
--
-- PHAM VI: THUAN CONG THEM (3 role + 3 grant + 1 guard trigger). Khong dung bang khac. KHONG gan role cho
-- staff nao (viec gan role = thao tac van hanh trong window Gate A qua duong quan tri co audit, revoke sau).
-- => sau migration nay: role ton tai nhung CHUA account nao giu => VAN DORMANT (khong ai ingest/gate/accept
-- /activate duoc cho toi khi PO gan role trong window). Idempotent (ap lai = no-op).
--
-- LUU Y: migration nay CHUA duoc apply/merge/deploy — nop trong Gate A RBAC Provisioning Package de CA review;
-- merge/deploy + gan role + window Gate A can directive rieng (PO-approved). Rollback: xem cuoi.
-- transactional: true

BEGIN;

-- 1. Ba role SoD chuyen biet (idempotent).
INSERT INTO roles (key, name, is_system, is_active) VALUES
  ('m5_dataset_custodian', 'M5 Dataset Custodian (nap draft)',        false, true),
  ('m5_dataset_reviewer',  'M5 Dataset Reviewer (acceptance gate)',   false, true),
  ('m5_dataset_owner',     'M5 Dataset Owner (accept/activate)',      false, true)
ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, is_active = true;

-- 2. Grant DUNG 1 quyen dataset cho moi role (allowlist chot o migration). Chi grant khi permission ton tai.
INSERT INTO role_permissions (role_key, permission_key)
SELECT r, p FROM (VALUES
  ('m5_dataset_custodian', 'address.dataset.ingest'),
  ('m5_dataset_reviewer',  'address.dataset.review'),
  ('m5_dataset_owner',     'address.dataset.manage')
) AS v(r, p)
WHERE EXISTS (SELECT 1 FROM permissions WHERE key = v.p)
ON CONFLICT DO NOTHING;

-- 3. Chan escalation: 3 role tren CHI duoc giu dung 1 quyen dataset cua no, khong quyen nao khac.
--    Trigger chi soi 3 role nay; role khac khong bi anh huong. (Song song, khong dung, voi trigger 048.)
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
