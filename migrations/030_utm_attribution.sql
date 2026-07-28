-- Migration 030: UTM attribution cho conversations + orders (I-B M3 Slice 2).
-- Spec A3S-PHASE1B-M3-SPEC-001 §7.3; Directive §5-S2. Expand-only, nullable, khong doi API cu.
-- utm_term: cot ton tai nhung CHI ghi khi co input that (khong suy dien/synthesize — validation app).
-- origin_channel (027) GIU nguyen nghia kenh nguon — UTM khong thay the.
-- Runtime estimate: <1s (ADD COLUMN NULL). Forward-fix: chay lai file (idempotent).
-- transactional: true

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='orders' AND column_name='origin_channel') THEN
    RAISE EXCEPTION '030 precondition FAIL: thieu orders.origin_channel (can 027)'; END IF;
END $$;

ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS utm_source   text NULL CHECK (utm_source   IS NULL OR char_length(utm_source)   <= 150),
  ADD COLUMN IF NOT EXISTS utm_medium   text NULL CHECK (utm_medium   IS NULL OR char_length(utm_medium)   <= 150),
  ADD COLUMN IF NOT EXISTS utm_campaign text NULL CHECK (utm_campaign IS NULL OR char_length(utm_campaign) <= 150),
  ADD COLUMN IF NOT EXISTS utm_content  text NULL CHECK (utm_content  IS NULL OR char_length(utm_content)  <= 150),
  ADD COLUMN IF NOT EXISTS utm_term     text NULL CHECK (utm_term     IS NULL OR char_length(utm_term)     <= 150);

ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS utm_source   text NULL CHECK (utm_source   IS NULL OR char_length(utm_source)   <= 150),
  ADD COLUMN IF NOT EXISTS utm_medium   text NULL CHECK (utm_medium   IS NULL OR char_length(utm_medium)   <= 150),
  ADD COLUMN IF NOT EXISTS utm_campaign text NULL CHECK (utm_campaign IS NULL OR char_length(utm_campaign) <= 150),
  ADD COLUMN IF NOT EXISTS utm_content  text NULL CHECK (utm_content  IS NULL OR char_length(utm_content)  <= 150),
  ADD COLUMN IF NOT EXISTS utm_term     text NULL CHECK (utm_term     IS NULL OR char_length(utm_term)     <= 150);

COMMENT ON COLUMN orders.utm_source IS
  'Attribution token (campaign metadata, CAM PII — validate app attribution.py, mapping v1). '
  'data_class=D1_PERSONAL_BASIC(gan record khach; gia tri token D0); purpose_code=P07_ANALYTICS; '
  'retention_rule_id=RET-03; owner_system=alpha3s; lineage_ref=attribution.MAPPING_VERSION';
COMMENT ON COLUMN conversations.utm_source IS
  'Nhu orders.utm_source; retention_rule_id=RET-04; ghi tuong minh tu web/channel input — KHONG suy tu prefix/text';

DO $$
BEGIN
  IF (SELECT count(*) FROM information_schema.columns WHERE table_name='orders'
      AND column_name IN ('utm_source','utm_medium','utm_campaign','utm_content','utm_term')) <> 5 THEN
    RAISE EXCEPTION '030 postcondition FAIL: orders thieu cot UTM'; END IF;
  IF (SELECT count(*) FROM information_schema.columns WHERE table_name='conversations'
      AND column_name IN ('utm_source','utm_medium','utm_campaign','utm_content','utm_term')) <> 5 THEN
    RAISE EXCEPTION '030 postcondition FAIL: conversations thieu cot UTM'; END IF;
END $$;
