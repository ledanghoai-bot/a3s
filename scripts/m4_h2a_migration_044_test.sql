-- H2-A sandbox: kiem hanh vi THAT cua migration 044.
--
-- SUA SAU LAN CHAY DAU (quan trong, giu lai de khong lap lai):
--   Lan dau, `t_phai_loi` chi kiem "co nem loi khong" — nen 4 ca NEGATIVE da "PASS" vi
--   'permission denied' chu KHONG phai vi phep kiem cua migration. Mot phep thu bao PASS vi sai
--   ly do con te hon mot phep thu bao FAIL. Ban nay bat buoc khop DUNG LY DO (`mong_doi`).
--   Fixture cung phai DUNG NGAY neu khong dung duoc, thay vi in 'OK' roi chay tiep tren nen rong.
\set ON_ERROR_STOP off
\pset pager off

-- Nem loi DUNG LY DO moi tinh la PASS.
CREATE OR REPLACE FUNCTION t_phai_loi(sql TEXT, ten TEXT, mong_doi TEXT) RETURNS TEXT AS $$
BEGIN
  EXECUTE sql;
  RETURN '  FAIL  ' || ten || '  <- lenh chay LOT, dang le phai bi tu choi';
EXCEPTION WHEN others THEN
  IF SQLERRM ~* mong_doi THEN
    RETURN '  PASS  ' || ten;
  END IF;
  RETURN '  FAIL  ' || ten || '  <- loi SAI LY DO, cho ' || quote_literal(mong_doi)
         || ' nhung nhan: ' || left(SQLERRM, 70);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION t_phai_chay(sql TEXT, ten TEXT) RETURNS TEXT AS $$
BEGIN
  EXECUTE sql;
  RETURN '  PASS  ' || ten;
EXCEPTION WHEN others THEN
  RETURN '  FAIL  ' || ten || '  <- ' || left(SQLERRM, 80);
END;
$$ LANGUAGE plpgsql;

\echo '=== [B] FIXTURE (chay TRUOC; hong la DUNG HAN) ==='
\set ON_ERROR_STOP on
INSERT INTO m4_selection_batches(batch_id, window_start, window_end, eligible_count, selected_count,
  algorithm_seed, locked_conversation_ids, purpose_code, normalization_version)
VALUES ('11111111-1111-1111-1111-111111111111', now()-interval '1 day', now(), 10, 1,
  'seed', ARRAY[1]::bigint[], 'P12_PII_DETECTOR_EVAL', (SELECT version FROM m4_stage0p_normalization_registry WHERE is_current));
INSERT INTO m4_shadow_review_samples(sample_id, customer_ref, conversation_ref, encrypted_message,
  canonical_text_len, expires_at, purpose_code, normalization_version, selection_batch)
VALUES ('22222222-2222-2222-2222-222222222222', 'c1', 'v1', '\x00'::bytea, 5,
  now()+interval '30 day', 'P12_PII_DETECTOR_EVAL', (SELECT version FROM m4_stage0p_normalization_registry WHERE is_current), '11111111-1111-1111-1111-111111111111');
SELECT '  fixture THAT SU dung duoc: ' || count(*)::text || ' sample'
FROM m4_shadow_review_samples WHERE sample_id='22222222-2222-2222-2222-222222222222';
\set ON_ERROR_STOP off

\echo ''
\echo '=== [A] REGISTRY PUBLIC KEY ==='
SELECT t_phai_chay($$INSERT INTO m4_stage0p_transcript_public_keys(key_id,key_version,algorithm,public_key)
  VALUES ('m4-transcript-ed25519','v1','Ed25519', decode(repeat('aa',32),'hex'))$$,
  'A1 them public key hop le');
SELECT t_phai_loi($$INSERT INTO m4_stage0p_transcript_public_keys(key_id,key_version,algorithm,public_key)
  VALUES ('k','v9','Ed25519', decode(repeat('aa',31),'hex'))$$,
  'A2 public key 31 byte bi tu choi', 'check constraint');
SELECT t_phai_loi($$INSERT INTO m4_stage0p_transcript_public_keys(key_id,key_version,algorithm,public_key)
  VALUES ('k','v9','RSA', decode(repeat('aa',32),'hex'))$$,
  'A3 thuat toan khac Ed25519 bi tu choi', 'check constraint');
SELECT t_phai_loi($$UPDATE m4_stage0p_transcript_public_keys SET public_key=decode(repeat('bb',32),'hex')
  WHERE key_id='m4-transcript-ed25519'$$,
  'A4 SUA public key bi tu choi (bat bien)', 'chi duoc sua retired_at');
SELECT t_phai_loi($$DELETE FROM m4_stage0p_transcript_public_keys WHERE key_id='m4-transcript-ed25519'$$,
  'A5 XOA public key bi tu choi', 'khong duoc XOA public key');
SELECT t_phai_chay($$UPDATE m4_stage0p_transcript_public_keys SET retired_at=now()+interval '1 day'
  WHERE key_id='m4-transcript-ed25519' AND key_version='v1'$$,
  'A6 dat retired_at lan dau: duoc');
SELECT t_phai_loi($$UPDATE m4_stage0p_transcript_public_keys SET retired_at=now()+interval '2 day'
  WHERE key_id='m4-transcript-ed25519' AND key_version='v1'$$,
  'A7 doi retired_at lan hai bi tu choi', 'retired_at chi duoc dat MOT lan');

INSERT INTO m4_stage0p_transcript_public_keys(key_id,key_version,algorithm,public_key)
  VALUES ('m4-transcript-ed25519','v2','Ed25519', decode(repeat('cc',32),'hex'));
-- v0: tao binh thuong roi MOI thu hoi. Khong the chen thang retired_at trong qua khu vi CHECK
-- `retired_at > created_at` — do la co y: khong ai duoc lui ngay thu hoi de vo hieu hoa chu ky
-- da ky truoc do.
INSERT INTO m4_stage0p_transcript_public_keys(key_id,key_version,algorithm,public_key)
  VALUES ('m4-transcript-ed25519','v0','Ed25519', decode(repeat('dd',32),'hex'));
UPDATE m4_stage0p_transcript_public_keys SET retired_at=now() WHERE key_id='m4-transcript-ed25519' AND key_version='v0';

\echo ''
\echo '=== [C] HAM GHI CHU KY (chay DUOI VAI alpha3s_m4_definer, dung nhu luc that) ==='
SET ROLE alpha3s_m4_definer;
SELECT t_phai_chay($$SELECT m4_stage0p_record_transcript_signature(
  '22222222-2222-2222-2222-222222222222'::uuid,
  convert_to('{"sample_id":"22222222-2222-2222-2222-222222222222","v":1}','UTF8'),
  decode(repeat('11',64),'hex'), 'Ed25519', 'm4-transcript-ed25519', 'v2')$$,
  'C1 ghi chu ky hop le');
SELECT t_phai_loi($$SELECT m4_stage0p_record_transcript_signature(
  '22222222-2222-2222-2222-222222222222'::uuid,
  convert_to('{"sample_id":"22222222-2222-2222-2222-222222222222","v":1}','UTF8'),
  decode(repeat('11',64),'hex'), 'HMAC-SHA256', 'm4-transcript-ed25519', 'v2')$$,
  'C2 sig_alg khong phai Ed25519', 'sig_alg phai la Ed25519');
SELECT t_phai_loi($$SELECT m4_stage0p_record_transcript_signature(
  '22222222-2222-2222-2222-222222222222'::uuid,
  convert_to('{"sample_id":"22222222-2222-2222-2222-222222222222","v":1}','UTF8'),
  decode(repeat('11',64),'hex'), 'Ed25519', 'm4-transcript-ed25519', 'khong-ton-tai')$$,
  'C3 key_version khong co trong registry', 'khong co public key');
SELECT t_phai_loi($$SELECT m4_stage0p_record_transcript_signature(
  '22222222-2222-2222-2222-222222222222'::uuid,
  convert_to('{"sample_id":"33333333-3333-3333-3333-333333333333","v":1}','UTF8'),
  decode(repeat('11',64),'hex'), 'Ed25519', 'm4-transcript-ed25519', 'v2')$$,
  'C4 sample_id trong transcript LECH tham so', 'khong khop tham so');
SELECT t_phai_loi($$SELECT m4_stage0p_record_transcript_signature(
  '22222222-2222-2222-2222-222222222222'::uuid,
  convert_to('khong phai json','UTF8'),
  decode(repeat('11',64),'hex'), 'Ed25519', 'm4-transcript-ed25519', 'v2')$$,
  'C5 transcript khong phai JSON', 'khong phai JSON UTF-8');
SELECT t_phai_loi($$SELECT m4_stage0p_record_transcript_signature(
  '44444444-4444-4444-4444-444444444444'::uuid,
  convert_to('{"sample_id":"44444444-4444-4444-4444-444444444444"}','UTF8'),
  decode(repeat('11',64),'hex'), 'Ed25519', 'm4-transcript-ed25519', 'v2')$$,
  'C6 sample khong ton tai (FK chan)', 'foreign key|violates');
SELECT t_phai_loi($$SELECT m4_stage0p_record_transcript_signature(
  '22222222-2222-2222-2222-222222222222'::uuid,
  convert_to('{"sample_id":"22222222-2222-2222-2222-222222222222"}','UTF8'),
  decode(repeat('11',64),'hex'), 'Ed25519', 'm4-transcript-ed25519', 'v0')$$,
  'C7 key DA THU HOI bi tu choi', 'da thu hoi');
RESET ROLE;
SELECT t_phai_loi($$INSERT INTO m4_stage0p_transcript_signatures(sample_id,transcript,sig_alg,sig_key_id,sig_key_ver,signature)
  VALUES ('22222222-2222-2222-2222-222222222222','\x01'::bytea,'Ed25519','m4-transcript-ed25519','v2',decode(repeat('11',63),'hex'))$$,
  'C8 chu ky 63 byte bi tu choi', 'check constraint');

\echo ''
\echo '=== [D] BAT BIEN + CASCADE (chi co nghia khi THAT SU co hang) ==='
SELECT '  so hang chu ky hien co: ' || count(*)::text || '   <- PHAI >0 thi hai phep duoi moi co nghia'
FROM m4_stage0p_transcript_signatures;
SELECT t_phai_loi($$UPDATE m4_stage0p_transcript_signatures SET signature=decode(repeat('22',64),'hex')
  WHERE sample_id='22222222-2222-2222-2222-222222222222'$$,
  'D1 SUA chu ky da ghi bi tu choi (bat bien tuyet doi)', 'bat bien');
DELETE FROM m4_shadow_review_samples WHERE sample_id='22222222-2222-2222-2222-222222222222';
SELECT '  sau khi xoa sample: ' || count(*)::text || ' hang chu ky (ky vong 0 - CASCADE)'
FROM m4_stage0p_transcript_signatures;

\echo ''
\echo '=== [E] KHONG CO COT NAO CHUA PRIVATE MATERIAL ==='
SELECT '  cot registry: ' || string_agg(column_name, ', ' ORDER BY ordinal_position)
FROM information_schema.columns WHERE table_name='m4_stage0p_transcript_public_keys';
SELECT '  so cot ten kieu private/secret/hmac: ' || count(*)::text || '  (ky vong 0)'
FROM information_schema.columns
WHERE table_name IN ('m4_stage0p_transcript_public_keys','m4_stage0p_transcript_signatures')
  AND column_name ~* 'private|secret|hmac';
