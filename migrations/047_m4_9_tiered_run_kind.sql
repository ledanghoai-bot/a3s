-- Migration 047: M4-9 — Tiered operating model (evidence_batch + conditional SoD).
--
-- Authority: CA-Docs/PHASE1B-M4-9-TIERED-MODEL-POLICY-REVIEW-64-VI.md
--            + Dev/PHASE1B-M4-9-TIERED-MODEL-POLICY-ANALYSIS-VI.md (PO endorsed §5).
--
-- MUC TIEU: cho phep Tier A "routine internal evidence batch" (run_kind='evidence_batch') chay
-- SINGLE-OPERATOR (khong SoD/ceremony), trong khi Tier B (run_kind='production') GIU nguyen SoD +
-- ceremony + Ed25519-KMS. Tier A blast-radius thap (digest-only, purge, khong non-repudiation).
--
-- HIEU CHINH SO VOI CHECK CA de xuat (Review 64): CA de xuat
--   run_kind <> 'production' OR (operator IS NOT NULL AND approver IS NOT NULL AND operator<>approver)
-- Nhung production run luc CREATED CHUA co operator/approver (set o ceremony/canary SAU), nen CHECK
-- nguyen van se TU CHOI tao production run hop le. Migration nay giu DUNG y dinh bao mat cua CA
-- (production khong duoc EXECUTE khi thieu SoD) bang CHECK STATE-AWARE: SoD day du bat buoc khi
-- production DA toi EXECUTING/CLOSED. Service layer (run_store) enforce them o transition execute_start.
--
-- PHAM VI: THUAN CONG THEM + sua 2 CHECK. KHONG doi state machine, khong doi ledger. Tier B khong
-- ne. Rollback (§cuoi): revert run_kind CHECK ve 2 gia tri + khoi phuc SoD vo dieu kien + drop 2 cot.
--
-- LUU Y: migration nay CHUA duoc apply len production (theo Review 64: viet nhung chua apply/merge/
-- deploy). Nop trong integrated correction package de CA review kem test/rollback.

BEGIN;

-- 1. run_kind: them 'evidence_batch' (Tier A)
ALTER TABLE m4_signing_run DROP CONSTRAINT m4_signing_run_run_kind_check;
ALTER TABLE m4_signing_run ADD CONSTRAINT m4_signing_run_run_kind_check
  CHECK (run_kind IN ('synthetic_rehearsal','production','evidence_batch'));

-- 2. purpose + escalation_flags (co so auto-escalate Tier B, §4 policy)
ALTER TABLE m4_signing_run ADD COLUMN IF NOT EXISTS purpose TEXT;
ALTER TABLE m4_signing_run ADD COLUMN IF NOT EXISTS escalation_flags JSONB NOT NULL DEFAULT '[]'::jsonb;
-- escalation_flags khong duoc chua secret (defense-in-depth, dong bo cac cot JSON khac)
ALTER TABLE m4_signing_run ADD CONSTRAINT m4_signing_run_no_secret_escal
  CHECK (NOT (escalation_flags::text ~* '(pin_secret|private_key|"token"|password|-----BEGIN)'));

-- 3. SoD conditional STATE-AWARE (thay CHECK vo dieu kien cu)
-- SoD CHI ap cho production (Tier B). Tier A (evidence_batch/synthetic) la SINGLE-OPERATOR:
-- operator DUOC tu approve canary (approver = operator hoac NULL) — day chinh la muc tieu don gian
-- hoa (Review 64: routine single-operator). Voi production:
--   (a) neu ca hai da set thi phai KHAC (chong same-person);
--   (b) khi da toi EXECUTING/CLOSED thi ca hai BAT BUOC non-NULL + khac (SoD day du).
--   State dau cho phep NULL vi operator/approver set dan theo state machine.
ALTER TABLE m4_signing_run DROP CONSTRAINT m4_signing_run_sod;
ALTER TABLE m4_signing_run ADD CONSTRAINT m4_signing_run_sod CHECK (
  run_kind <> 'production'
  OR (
    (operator_staff_id IS NULL OR approver_staff_id IS NULL
     OR operator_staff_id <> approver_staff_id)
    AND
    (state NOT IN ('EXECUTING','CLOSED')
     OR (operator_staff_id IS NOT NULL AND approver_staff_id IS NOT NULL
         AND operator_staff_id <> approver_staff_id))
  )
);

COMMIT;

-- ROLLBACK (tay, khi chua co run evidence_batch nao):
--   BEGIN;
--   ALTER TABLE m4_signing_run DROP CONSTRAINT m4_signing_run_run_kind_check;
--   ALTER TABLE m4_signing_run ADD CONSTRAINT m4_signing_run_run_kind_check
--     CHECK (run_kind IN ('synthetic_rehearsal','production'));
--   ALTER TABLE m4_signing_run DROP CONSTRAINT m4_signing_run_sod;
--   ALTER TABLE m4_signing_run ADD CONSTRAINT m4_signing_run_sod
--     CHECK (approver_staff_id IS NULL OR operator_staff_id IS NULL
--            OR approver_staff_id <> operator_staff_id);
--   ALTER TABLE m4_signing_run DROP CONSTRAINT m4_signing_run_no_secret_escal;
--   ALTER TABLE m4_signing_run DROP COLUMN escalation_flags;
--   ALTER TABLE m4_signing_run DROP COLUMN purpose;
--   COMMIT;
