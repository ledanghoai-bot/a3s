-- Migration 048: M4-9 — Ratify + version-control role m4_signing_operator (post-closure hardening).
--
-- Authority: CA-Docs/PHASE1B-M4-9-POST-CLOSURE-RBAC-RATIFICATION-DIRECTIVE-70-VI.md
--            + Addendum 70-A (SIGNER ROLE PROVISIONING CONTROL).
--
-- BOI CANH: sau khi M4-9 handover CLOSED (Review 68), PO da chay provision_m4_signing_operator.py
-- THU CONG tren DB production, tao role `m4_signing_operator` (5 quyen m4.signing.run.*) + staff
-- `signer1`. Do la RBAC mutation NGOAI gate (Review 69). PO chon PA1 (giu operator) — Directive 70
-- yeu cau version-control hoa dinh nghia role/grants thay vi de script tay tao.
--
-- MIGRATION NAY: dinh nghia role + 5 grants BANG CODE (idempotent — ap tren prod da co la no-op).
-- Day la ranh gioi chong-escalation: role->permissions duoc CHOT o migration (reviewed), script
-- provisioning CHI GAN role co dinh nay cho staff (khong tao/grant quyen), nen khong the cap quyen
-- ngoai allowlist.
--
-- PHAM VI: THUAN CONG THEM (seed role + 5 grants). Khong dung bang khac. Khong start signer, khong
-- credential. Rollback: xoa 5 grants + role (khi khong con staff nao giu role — xem cuoi).
-- LUU Y: migration nay CHUA duoc apply/merge/deploy — nop trong RBAC Ratification & Hardening
-- Package de CA review; merge/deploy can Apply/Merge-Dormant directive rieng.

BEGIN;

-- 1. Role chuyen biet (idempotent). name cap nhat neu da ton tai (tu manual provision).
INSERT INTO roles (key, name, is_system, is_active)
VALUES ('m4_signing_operator', 'Van hanh ky transcript (Tier A)', false, true)
ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, is_active = true;

-- 2. Grant DUNG 5 quyen m4.signing.run.* cho role (allowlist chot o migration). Idempotent.
INSERT INTO role_permissions (role_key, permission_key)
SELECT 'm4_signing_operator', k FROM (VALUES
  ('m4.signing.run.view'), ('m4.signing.run.start'), ('m4.signing.run.operate'),
  ('m4.signing.run.approve'), ('m4.signing.run.abort')
) AS v(k)
WHERE EXISTS (SELECT 1 FROM permissions WHERE key = v.k)
ON CONFLICT DO NOTHING;

-- 3. Chan escalation: role m4_signing_operator KHONG duoc co bat ky quyen nao NGOAI 5 quyen tren.
--    Trigger nay chi soi rieng role do — neu ai co INSERT quyen khac cho no thi bi tu choi.
CREATE OR REPLACE FUNCTION m4_9_guard_operator_grants()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.role_key = 'm4_signing_operator'
     AND NEW.permission_key NOT IN (
       'm4.signing.run.view','m4.signing.run.start','m4.signing.run.operate',
       'm4.signing.run.approve','m4.signing.run.abort') THEN
    RAISE EXCEPTION 'role m4_signing_operator chi duoc cap 5 quyen m4.signing.run.* (allowlist); '
                    'tu choi cap %', NEW.permission_key;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS m4_9_operator_grants_allowlist ON role_permissions;
CREATE TRIGGER m4_9_operator_grants_allowlist
  BEFORE INSERT OR UPDATE ON role_permissions
  FOR EACH ROW EXECUTE FUNCTION m4_9_guard_operator_grants();

COMMIT;

-- ROLLBACK (tay, khi KHONG con staff nao giu role — de dua ve dormant baseline):
--   BEGIN;
--   UPDATE staff_users SET role_key = NULL WHERE role_key = 'm4_signing_operator';  -- neu can
--   DROP TRIGGER IF EXISTS m4_9_operator_grants_allowlist ON role_permissions;
--   DROP FUNCTION IF EXISTS m4_9_guard_operator_grants();
--   DELETE FROM role_permissions WHERE role_key = 'm4_signing_operator';
--   DELETE FROM roles WHERE key = 'm4_signing_operator';
--   COMMIT;
