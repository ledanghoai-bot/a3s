-- Migration 044: M4 H2-A — dual-tag transcript signing (dap lai
-- CA-Docs/PHASE1B-M4-H2-ASYMMETRIC-SIGNING-DESIGN-REVIEW-1-VI.md va
-- CA-Docs/PHASE1B-M4-H2-PO-DECISION-RECORD-AND-H2A-PREPARATION-DIRECTIVE-VI.md).
--
-- BOI CANH
-- `crypto.py:sign_capture()` ky transcript bang HMAC-SHA256 voi khoa DOI XUNG luu tai
-- `m4_stage0p_transcript_signing_keys.hmac_key`. Chinh docstring `crypto.py` da ghi: khoa do
-- KHONG co non-repudiation — DBA/nguoi giu backup/nguoi doc runtime deu gia mao duoc transcript.
--
-- PO decision record 17/8/2026 chot DUAL-TAG:
--   * HMAC cu GIU NGUYEN nhung chi con la "integrity/capability gate cua DB";
--   * THEM chu ky Ed25519 tao qua KMS — private key khong bao gio nam trong DB/image/env/file;
--     DB chi giu PUBLIC verification material; verify thuc hien NGOAI DB.
--
-- PHAT HIEN QUAN TRONG khi doc code truoc khi viet migration nay:
-- `m4_stage0p_record_sample` VERIFY transcript/signature roi VUT DI — khong luu o bat ky bang
-- nao. Nghia la hom nay, sau khi capture xong, KHONG AI re-verify duoc mot mau nao ca; chu ky
-- chi song trong dung mot loi goi ham. Vi vay H2-A khong chi la "them mot chu ky" ma con la
-- "bat dau LUU GIU bang chung" — khong luu thi yeu cau "verifier ngoai DB" cua CA khong the
-- thuc hien duoc.
--
-- PHAM VI: THUAN CONG THEM. Migration nay KHONG sua `m4_stage0p_record_sample`, KHONG doi hanh vi
-- duong ghi hien tai, KHONG bo/doi cot nao. Rollback = DROP hai bang moi (khong ai doc chung o
-- baseline). "Bat buoc phai co chu ky asym" la mot BUOC SAU, can gate rieng cua CA/PO (PO decision
-- record §5) va KHONG nam trong migration nay.
--
-- BAO MAT NOI DUNG: transcript chi chua digest + dinh danh + metadata (canonical_digest,
-- ciphertext_digest, aead_algorithm, txid, ...), KHONG chua plaintext. Luu no khong lam tang
-- be mat lo du lieu khach. Du vay hang chu ky van CASCADE theo sample de tuan thu dung chinh sach
-- luu tru/purge dang co — khong tao ra mot kho du lieu song lau hon sample.

BEGIN;

-- ===========================================================================
-- 1. Registry PUBLIC verification material.
--    KHONG co cot nao chua private material. Do la thiet ke, khong phai thieu sot: neu bang nay
--    co the chua private key thi toan bo H2 vo nghia — DBA lai gia mao duoc nhu cu.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_transcript_public_keys (
  key_id      TEXT NOT NULL,
  key_version TEXT NOT NULL,
  algorithm   TEXT NOT NULL CHECK (algorithm = 'Ed25519'),
  public_key  BYTEA NOT NULL CHECK (octet_length(public_key) = 32),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  retired_at  TIMESTAMPTZ,
  PRIMARY KEY (key_id, key_version),
  CONSTRAINT m4_h2a_pubkey_retired_after_created CHECK (retired_at IS NULL OR retired_at > created_at)
);

COMMENT ON TABLE m4_stage0p_transcript_public_keys IS
  'H2-A: PUBLIC verification material cho chu ky Ed25519 cua transcript. KHONG chua private material - do la dieu kien de H2 co y nghia. Tra cuu theo (key_id, key_version) ghi trong transcript, nen transcript ky truoc rotation van verify duoc. retired_at = thu hoi: transcript ky SAU moc do bi coi la khong hop le.';

REVOKE ALL ON m4_stage0p_transcript_public_keys FROM PUBLIC;

-- Bat bien: public key da cong bo thi KHONG duoc sua. Neu sua duoc, moi chu ky qua khu deu co the
-- bi "verify lai thanh hop le" bang mot khoa khac - dung thu H2 phai chan.
CREATE OR REPLACE FUNCTION m4_h2a_public_keys_immutable() RETURNS TRIGGER AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'm4_stage0p_transcript_public_keys: khong duoc XOA public key (dung retired_at de thu hoi)';
  END IF;
  IF NEW.key_id <> OLD.key_id OR NEW.key_version <> OLD.key_version
     OR NEW.algorithm <> OLD.algorithm OR NEW.public_key <> OLD.public_key
     OR NEW.created_at <> OLD.created_at THEN
    RAISE EXCEPTION 'm4_stage0p_transcript_public_keys: chi duoc sua retired_at, moi cot khac bat bien';
  END IF;
  IF OLD.retired_at IS NOT NULL AND NEW.retired_at IS DISTINCT FROM OLD.retired_at THEN
    RAISE EXCEPTION 'm4_stage0p_transcript_public_keys: retired_at chi duoc dat MOT lan';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_m4_h2a_public_keys_immutable ON m4_stage0p_transcript_public_keys;
CREATE TRIGGER trg_m4_h2a_public_keys_immutable
  BEFORE UPDATE OR DELETE ON m4_stage0p_transcript_public_keys
  FOR EACH ROW EXECUTE FUNCTION m4_h2a_public_keys_immutable();

-- ===========================================================================
-- 2. Chu ky asym da luu, gan voi sample.
--    CASCADE theo sample: purge sample thi chu ky di theo, khong de lai kho du lieu song lau hon.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_transcript_signatures (
  sample_id   UUID PRIMARY KEY REFERENCES m4_shadow_review_samples(sample_id) ON DELETE CASCADE,
  -- Canonical signed bytes: DUNG chuoi byte ma ca HMAC lan Ed25519 cung ky. Luu nguyen van de
  -- verifier ngoai DB khong phai dung lai transcript (dung lai = co co hoi dung sai).
  transcript  BYTEA NOT NULL CHECK (octet_length(transcript) BETWEEN 1 AND 8192),
  sig_alg     TEXT NOT NULL CHECK (sig_alg = 'Ed25519'),
  sig_key_id  TEXT NOT NULL,
  sig_key_ver TEXT NOT NULL,
  signature   BYTEA NOT NULL CHECK (octet_length(signature) = 64),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT m4_h2a_sig_key_fk FOREIGN KEY (sig_key_id, sig_key_ver)
    REFERENCES m4_stage0p_transcript_public_keys(key_id, key_version)
);

COMMENT ON TABLE m4_stage0p_transcript_signatures IS
  'H2-A: chu ky Ed25519 + canonical signed bytes cua transcript, LUU LAI de verify duoc NGOAI DB bang public key. Truoc H2-A, transcript/signature bi vut sau khi verify nen khong the re-verify mot capture nao. DB KHONG verify chu ky nay (pgcrypto khong lam duoc Ed25519) - DB chi rang buoc cau truc; verify la viec cua verifier doc lap.';

REVOKE ALL ON m4_stage0p_transcript_signatures FROM PUBLIC;

CREATE INDEX IF NOT EXISTS idx_m4_h2a_sig_key ON m4_stage0p_transcript_signatures (sig_key_id, sig_key_ver);

-- Bat bien tuyet doi: chu ky da ghi thi khong sua duoc. Sua duoc = khong con la bang chung.
CREATE OR REPLACE FUNCTION m4_h2a_signatures_immutable() RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'm4_stage0p_transcript_signatures: bat bien - khong duoc UPDATE (xoa chi qua CASCADE khi purge sample)';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_m4_h2a_signatures_immutable ON m4_stage0p_transcript_signatures;
CREATE TRIGGER trg_m4_h2a_signatures_immutable
  BEFORE UPDATE ON m4_stage0p_transcript_signatures
  FOR EACH ROW EXECUTE FUNCTION m4_h2a_signatures_immutable();

-- ===========================================================================
-- 3. Ham ghi chu ky - SECURITY DEFINER, rang buoc CAU TRUC (khong verify mat ma).
--
--    DB KHONG THE verify Ed25519 (pgcrypto chi co digest/hmac/pgp_*). Day khong phai diem yeu:
--    verify bang public key la viec BAT KY AI cung lam duoc, va viec no KHONG con nam trong DB
--    chinh la dieu lam non-repudiation tro thanh that - hom nay chi DB verify duoc, ma DB cung la
--    ben gia mao duoc.
--
--    Nhung DB VAN phai chan cac sai lech co the kiem duoc bang cau truc:
--      * sample phai ton tai (FK)
--      * (key_id, key_version) phai ton tai va CHUA thu hoi
--      * truong sample_id BEN TRONG transcript phai khop tham so - chan gan chu ky cua mau nay
--        sang mau khac
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_record_transcript_signature(
  p_sample_id   UUID,
  p_transcript  BYTEA,
  p_signature   BYTEA,
  p_sig_alg     TEXT,
  p_sig_key_id  TEXT,
  p_sig_key_ver TEXT
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_key   RECORD;
  v_json  JSONB;
BEGIN
  IF p_sig_alg <> 'Ed25519' THEN
    RAISE EXCEPTION 'm4_stage0p_record_transcript_signature: sig_alg phai la Ed25519, nhan %', p_sig_alg;
  END IF;

  SELECT * INTO v_key FROM m4_stage0p_transcript_public_keys
    WHERE key_id = p_sig_key_id AND key_version = p_sig_key_ver;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_record_transcript_signature: khong co public key (%, %) trong registry',
      p_sig_key_id, p_sig_key_ver;
  END IF;
  IF v_key.retired_at IS NOT NULL AND v_key.retired_at <= now() THEN
    RAISE EXCEPTION 'm4_stage0p_record_transcript_signature: key (%, %) da thu hoi luc %',
      p_sig_key_id, p_sig_key_ver, v_key.retired_at;
  END IF;

  BEGIN
    v_json := convert_from(p_transcript, 'UTF8')::jsonb;
  EXCEPTION WHEN others THEN
    RAISE EXCEPTION 'm4_stage0p_record_transcript_signature: transcript khong phai JSON UTF-8 hop le';
  END;

  IF (v_json ->> 'sample_id') IS DISTINCT FROM p_sample_id::text THEN
    RAISE EXCEPTION 'm4_stage0p_record_transcript_signature: sample_id trong transcript khong khop tham so (chan gan chu ky sang mau khac)';
  END IF;

  INSERT INTO m4_stage0p_transcript_signatures
    (sample_id, transcript, sig_alg, sig_key_id, sig_key_ver, signature)
  VALUES (p_sample_id, p_transcript, p_sig_alg, p_sig_key_id, p_sig_key_ver, p_signature);
END;
$$;

ALTER FUNCTION m4_stage0p_record_transcript_signature(UUID, BYTEA, BYTEA, TEXT, TEXT, TEXT)
  OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_record_transcript_signature(UUID, BYTEA, BYTEA, TEXT, TEXT, TEXT) FROM PUBLIC;

-- Quyen toi thieu cho role chay ben trong ham SECURITY DEFINER.
-- Bo sung sau khi sandbox phat hien loi that: thieu hai GRANT nay thi ham KHONG doc noi chinh
-- registry cua no va tra ve 'permission denied' — nguy hiem hon la no lam cac test negative
-- "PASS" vi LY DO SAI (bi chan boi quyen, khong phai boi phep kiem). Xem
-- evidence-h2a-sandbox/migration_044_behaviour.log lan chay dau.
-- Theo dung quy uoc 039 dong 2485 (GRANT SELECT ... TO alpha3s_m4_definer), KHONG cap cho
-- alpha3s_app: registry va chu ky khong nam trong duong doc cua ung dung thuong.
GRANT SELECT ON public.m4_stage0p_transcript_public_keys TO alpha3s_m4_definer;
GRANT SELECT, INSERT ON public.m4_stage0p_transcript_signatures TO alpha3s_m4_definer;

COMMIT;

-- ===========================================================================
-- ROLLBACK (thu cong, khong mat du lieu cua baseline):
--   DROP FUNCTION IF EXISTS m4_stage0p_record_transcript_signature(UUID, BYTEA, BYTEA, TEXT, TEXT, TEXT);
--   DROP TABLE IF EXISTS m4_stage0p_transcript_signatures;
--   DROP TABLE IF EXISTS m4_stage0p_transcript_public_keys;
--   DROP FUNCTION IF EXISTS m4_h2a_signatures_immutable();
--   DROP FUNCTION IF EXISTS m4_h2a_public_keys_immutable();
-- Khong hang nao cua baseline bi dung toi, nen rollback khong lam mat du lieu da co.
-- ===========================================================================
