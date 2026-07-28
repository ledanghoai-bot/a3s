-- Migration 038: Trusted Slot Store `pii_slots` (I-B M4-S1 — A3S-PHASE1B-M4-SPEC-001 §8).
-- Lich su so: provisional 040 trong development (M3 chua merge, dang giu 029+);
--   RENUMBER 040 -> 038 tai integration re-baseline (Directive §11) sau khi M2+M3 merge
--   main @ dc839ca (head thuc te = 037_retention_policy_immutability). Evidence migration/
--   regression duoc CHAY LAI toan bo voi so moi — xem docs/PHASE1B-M4-REBASELINE-VI.md.
-- Thiet ke:
--   - EXPAND-only: bang moi, khong dung/sua/xoa object nao co san (§12 spec).
--   - encrypted_value: AES-256-GCM MA HOA O TANG APP (app/services/pii/crypto.py) voi AAD =
--     customer_ref|conversation_ref|slot_type -> row bi doi context (tamper/replay-bind) se
--     KHONG THE giai ma (fail closed tai tang crypto, khong chi tang query).
--   - normalized_fingerprint: HMAC-SHA256 co khoa (keyed) cua gia tri da chuan hoa — de dedupe
--     replay TRONG CUNG context; KHONG phai public identifier (§8 spec), khong the suy nguoc.
--   - Khong luu plaintext PII o bat ky cot nao. source_message_ref chi la ma tham chieu.
--   - Retention ngan: expires_at BAT BUOC (TTL cau hinh m4_slot_ttl_hours, default 24h);
--     purge boi app (DELETE), khong UPDATE — bang append-then-expire.
--   - Least privilege: alpha3s_app (runtime) INSERT/SELECT/DELETE, KHONG UPDATE (bat bien);
--     role alpha3s_vendor_path (NOLOGIN, dai dien moi thanh phan vendor-path co credential
--     trong tuong lai) KHONG co bat ky quyen nao tren bang nay. External model (DeepSeek) van
--     KHONG co credential DB — role nay la chot chan them, postcondition chung minh DENY.
-- Precondition: pgcrypto KHONG can (gen_random_uuid() built-in PG13+; image pg16).
-- Runtime estimate: <1s (CREATE TABLE + index rong).
-- Forward-fix: neu can sua, tao migration moi (forward-only theo runner drift-stop).
-- transactional: true

-- ===========================================================================
-- 1. Bang pii_slots (schema 13.5 spec §8 — du 13 truong)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS pii_slots (
  slot_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_ref           TEXT NOT NULL,
  conversation_ref       TEXT NOT NULL,
  slot_type              TEXT NOT NULL
    CHECK (slot_type IN ('phone','name','address','national_id','bank_account')),
  encrypted_value        BYTEA NOT NULL,
  normalized_fingerprint TEXT NOT NULL CHECK (normalized_fingerprint ~ '^[0-9a-f]{32}$'),
  source_message_ref     TEXT,
  detector_version       TEXT NOT NULL,
  confidence             TEXT NOT NULL CHECK (confidence IN ('high','medium','low')),
  captured_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at             TIMESTAMPTZ NOT NULL,
  data_class             TEXT NOT NULL CHECK (data_class IN ('D1','D2')),
  -- canonical identifier theo docs/PROCESSING-PURPOSE-REGISTRY.md (M3): P02_COMMERCE...
  purpose_code           TEXT NOT NULL CHECK (purpose_code ~ '^P[0-9]{2}_[A-Z][A-Z_]{1,40}$'),
  CONSTRAINT pii_slots_expiry_after_capture CHECK (expires_at > captured_at)
);

COMMENT ON TABLE pii_slots IS
  'M4 Trusted Slot Store — data_class: D1/D2 theo row; purpose_code: canonical registry id (vd P02_COMMERCE); PII chi o encrypted_value (AES-GCM v2 length-prefix AAD binding context); retention: expires_at + purge app-layer';
COMMENT ON COLUMN pii_slots.encrypted_value IS
  'AES-256-GCM: v1||nonce(12)||ct+tag. AAD=customer_ref|conversation_ref|slot_type -> doi context la KHONG giai ma duoc';
COMMENT ON COLUMN pii_slots.normalized_fingerprint IS
  'HMAC-SHA256 keyed (32 hex) cua gia tri chuan hoa — dedupe replay trong CUNG context; KHONG phai public identifier';

-- ===========================================================================
-- 2. Indexes
-- ===========================================================================
-- Effective-once cho retry/replay TRONG CUNG context (khac context -> row khac,
-- khong bao gio "bind sang context khac" — §8 spec).
CREATE UNIQUE INDEX IF NOT EXISTS pii_slots_context_fp_uq
  ON pii_slots (customer_ref, conversation_ref, slot_type, normalized_fingerprint);

-- Duong resolve: moi nhat truoc, loc theo binding day du.
CREATE INDEX IF NOT EXISTS pii_slots_resolve_idx
  ON pii_slots (customer_ref, conversation_ref, slot_type, captured_at DESC);

-- Duong purge theo retention.
CREATE INDEX IF NOT EXISTS pii_slots_expires_idx ON pii_slots (expires_at);

-- ===========================================================================
-- 3. Least-privilege roles
-- ===========================================================================
REVOKE ALL ON pii_slots FROM PUBLIC;

-- Role dai dien vendor-path (chua co thanh phan nao dung — chot chan + postcondition).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_vendor_path') THEN
    CREATE ROLE alpha3s_vendor_path NOLOGIN;
  END IF;
END $$;
REVOKE ALL ON pii_slots FROM alpha3s_vendor_path;

-- Runtime app: 024 default-privileges da cap CRUD cho bang moi -> thu hep lai:
-- KHONG UPDATE (row bat bien; vong doi = INSERT -> het han -> DELETE purge).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_app') THEN
    REVOKE UPDATE ON pii_slots FROM alpha3s_app;
  END IF;
END $$;

-- ===========================================================================
-- 4. Postcondition fail-closed
-- ===========================================================================
DO $$
DECLARE problems TEXT := '';
BEGIN
  IF to_regclass('public.pii_slots') IS NULL THEN
    problems := problems || ' table_missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public'
                 AND indexname='pii_slots_context_fp_uq') THEN
    problems := problems || ' uq_index_missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_vendor_path') THEN
    problems := problems || ' vendor_role_missing'; END IF;
  -- vendor-path role: DENY toan bo
  IF has_table_privilege('alpha3s_vendor_path','public.pii_slots','SELECT') THEN
    problems := problems || ' vendor_can_select'; END IF;
  IF has_table_privilege('alpha3s_vendor_path','public.pii_slots','INSERT') THEN
    problems := problems || ' vendor_can_insert'; END IF;
  -- runtime app: co INSERT/SELECT/DELETE, KHONG UPDATE
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_app') THEN
    IF NOT has_table_privilege('alpha3s_app','public.pii_slots','INSERT') THEN
      problems := problems || ' app_no_insert'; END IF;
    IF NOT has_table_privilege('alpha3s_app','public.pii_slots','SELECT') THEN
      problems := problems || ' app_no_select'; END IF;
    IF NOT has_table_privilege('alpha3s_app','public.pii_slots','DELETE') THEN
      problems := problems || ' app_no_delete'; END IF;
    IF has_table_privilege('alpha3s_app','public.pii_slots','UPDATE') THEN
      problems := problems || ' app_has_update'; END IF;
  END IF;
  IF problems <> '' THEN
    RAISE EXCEPTION '040 postcondition FAIL —%', problems; END IF;
END $$;
