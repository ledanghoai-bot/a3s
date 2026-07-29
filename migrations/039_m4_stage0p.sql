-- Migration 039: M4 Stage 0P schema — Trusted PII Path production-shadow governance
-- (A3S-PHASE1B-M4-SPEC-001 v1.1.0 §6/§7; A3S-PHASE1B-M4-STAGE-0P-DESIGN-ACCEPTANCE-VI accepted
-- head d2a63c5, package v4.0.0). Theo dung 5 finding CLOSED AT DESIGN LEVEL (F-M4-0P-01..05).
--
-- REV 2 (Technical Correction #1, CA Technical Review #1 e10af661): sua 6 finding T1-01..T1-06.
-- REV 3 (Technical Correction #2, CA Technical Review #2 470d985, doc
-- PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-2-VI): sua 6 finding P1 T2-01..T2-06 — CA ket luan REV2
-- moi "PARTIALLY CLOSED"/"CLOSED AT CODE-DESIGN LEVEL", chua nghiem thu. File nay CHINH SUA TRUC
-- TIEP (khong tao migration 040) vi 039 chua tung apply vao baseline da accept/chia se.
--
-- ⚠️ EXPAND-ONLY, dev/test scope theo CA Design Acceptance §4: duoc phep tao migration/role/
-- function tren branch M4 voi du lieu synthetic/test. KHONG duoc doc/copy production data,
-- KHONG cap role/credential production, KHONG dat control row ON, KHONG bat capture that.
--
-- REV3 tom tat 6 sua doi (T2-01..06):
--   T2-01: fenced work unit co the bi giu vo thoi han (pending-check/Redis/INSERT khong timeout
--          trong luc giu lock 4013003). Sua: tach `m4_stage0p_peek_next_candidate` (KHONG lock,
--          KHONG PII, an toan goi truoc) khoi `m4_stage0p_fetch_message_content` (fenced, nhan
--          dung (conversation_id,message_id) da biet — khong con cursor mo trong ham); pending-
--          check chuyen ra NGOAI fence truoc, recheck ngan BEN TRONG fence voi timeout rieng;
--          Python bao boc toan bo don vi fenced bang asyncio.wait_for deadline.
--   T2-02: prediction path SELECT+decrypt toan bo truoc khi biet batch sealed. Sua: ham moi
--          `m4_stage0p_fetch_sealed_message` — kiem tra labels_sealed_at TRUOC khi tra BAT KY
--          content nao, phan trang 1-row, audit tung lan doc; REVOKE SELECT truc tiep tren cot
--          noi dung cua alpha3s_m4_prediction_writer.
--   T2-03: `write_predictions` nhan JSONB tuy y, khong validate. Sua: validate schema/enum/
--          bounds/non-overlap/unique-sample/thuoc-dung-batch/PHU DUNG toan bo corpus (predictions
--          + exclusions co ly do); them `predictions_written_at` — bat bien mot lan ghi, rerun
--          phai tao batch/revision moi.
--   T2-04: hash do Python tinh, DB chi kiem "khong rong". Sua: BAT pgcrypto, DB TU TINH
--          `labels_sealed_hash` (seal_labels) va `result_hash` (write_predictions, bind
--          labels_sealed_hash+detector_version+predictions) va `evaluation_report_hash`
--          (complete_evaluation, bind result_hash+metrics) — caller CHI truyen "expected" hash de
--          DB doi chieu tu choi neu sai/cu/gia.
--   T2-05: `approval_ref` chi can non-empty string. Sua: bang moi `m4_stage0p_capture_approvals`
--          + role rieng `alpha3s_m4_approval_recorder` (tach khoi control_plane — chong tu duyet);
--          bat ON doi hoi approval row APPROVED, dung purpose/window, chua het han/thu hoi; tat
--          OFF khong doi hoi approval (chi can actor hop le).
--   T2-06: `captured_count` tang cung luc fetch (truoc ca pending-check) nen row bi skip van tinh
--          vao cap. Sua: bo tang counter trong content-fetch; ham moi `m4_stage0p_record_sample`
--          gop INSERT sample + tang captured_count ATOMIC — counter CHI tang khi sample THAT SU
--          duoc luu.
--
-- 3 bang chinh (khong doi ten): m4_shadow_review_samples (REV3 them cot
-- prediction_excluded_reason), m4_selection_batches (REV3 them predictions_written_at/
-- result_hash), m4_stage0p_control. REV3 them bang moi m4_stage0p_capture_approvals (T2-05).
--
-- 8 role least-privilege (REV3 them alpha3s_m4_approval_recorder): alpha3s_m4_sample_collector
-- (REV3: KHONG con INSERT truc tiep tren sample — chi EXECUTE 3 ham peek/fetch/record),
-- alpha3s_m4_sample_reviewer_api, alpha3s_m4_sample_evaluator, alpha3s_m4_prediction_writer
-- (REV3: KHONG con SELECT truc tiep tren cot noi dung — chi EXECUTE fetch_sealed_message +
-- write_predictions), alpha3s_m4_sample_purge, alpha3s_m4_control_plane, alpha3s_m4_pending_checker,
-- alpha3s_m4_approval_recorder (MOI — INSERT/SELECT approval record, tach biet control_plane).
--
-- Ham SECURITY DEFINER (owner alpha3s_m4_definer, non-superuser — xac nhan postcondition), REV3:
--   m4_stage0p_peek_next_candidate  — KHONG lock/PII, an toan goi truoc fence (T2-01)
--   m4_stage0p_fetch_message_content — fenced, nhan dung 1 (conversation_id,message_id) (T2-01)
--   m4_stage0p_record_sample         — INSERT + captured_count ATOMIC (T2-06)
--   m4_stage0p_set_capture           — them xac thuc approval record cho ON (T2-05)
--   m4_stage0p_seal_labels           — DB TU TINH labels_sealed_hash qua pgcrypto (T2-04)
--   m4_stage0p_fetch_sealed_message  — sealed-only paginated content cho prediction (T2-02)
--   m4_stage0p_write_predictions     — validate JSONB day du + bind labels_sealed_hash + tinh
--                                       result_hash + bat bien 1-lan-ghi (T2-03/T2-04)
--   m4_stage0p_complete_evaluation   — bind result_hash + tinh report_hash (T2-04)
--   m4_stage0p_block_label_after_seal — trigger bat bien label (REV2, khong doi)
--
-- Advisory lock key 4013003 (STAGE0P CONTROL FENCE) dung CHUNG giua fetch_message_content va
-- set_capture (xem ghi chu REV2 truoc). REV3: fence GIU NGAN HON — chi fetch_message_content +
-- record_sample (khong con giu qua ca cursor-scan cua peek, vi peek khong lock).
--
-- transactional: true

-- ===========================================================================
-- 1. Role dinh nghia rieng cho SECURITY DEFINER function + pgcrypto (T2-04, chuan, ship san
--    trong postgres:16 image)
-- ===========================================================================
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_definer') THEN
    CREATE ROLE alpha3s_m4_definer NOLOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB;
  END IF;
END $$;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ===========================================================================
-- 2. Bang m4_stage0p_control — kill switch DONG (F-M4-0P-01B). Singleton row.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_control (
  id               SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  capture_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by_note  TEXT
);
INSERT INTO m4_stage0p_control (id, capture_enabled) VALUES (1, FALSE)
  ON CONFLICT (id) DO NOTHING;

COMMENT ON TABLE m4_stage0p_control IS
  'M4 Stage 0P kill switch DONG (F-M4-0P-01B) — doc tuoi bang SELECT truoc MOI don vi ghi. Doi CHI qua ham m4_stage0p_set_capture (fence advisory lock 4013003, REV3 T2-05: ON doi hoi approval record xac thuc). Nguon tham quyen ON/OFF that: audit_log qua ham nay.';

REVOKE ALL ON m4_stage0p_control FROM PUBLIC;
REVOKE ALL ON m4_stage0p_control FROM alpha3s_app;

-- ===========================================================================
-- 2b. Bang m4_stage0p_capture_approvals — approval record cho phep bat capture (REV3 T2-05).
--     Role rieng alpha3s_m4_approval_recorder ghi bang nay — TACH BIET alpha3s_m4_control_plane
--     (role doi cong tac) de khong role nao tu duyet cho chinh minh.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_capture_approvals (
  approval_ref      TEXT PRIMARY KEY,
  purpose_code      TEXT NOT NULL CHECK (purpose_code = 'P12_PII_DETECTOR_EVAL'),
  requested_enabled BOOLEAN NOT NULL,  -- CHI dung xac thuc khi bat ON — TAT khong doi hoi approval
  status            TEXT NOT NULL CHECK (status IN ('approved', 'revoked')),
  valid_from        TIMESTAMPTZ NOT NULL,
  valid_until       TIMESTAMPTZ NOT NULL,
  recorded_by       BIGINT REFERENCES staff_users(id),
  recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  note              TEXT,
  CONSTRAINT m4_approval_window_valid CHECK (valid_until > valid_from)
);

COMMENT ON TABLE m4_stage0p_capture_approvals IS
  'REV3 T2-05: approval/decision record ma m4_stage0p_set_capture(ON) BAT BUOC doi chieu — khong con chi kiem approval_ref la chuoi khong rong. Ghi boi alpha3s_m4_approval_recorder (tach biet control_plane, chong tu duyet). OFF khong doi hoi row nao o day.';

REVOKE ALL ON m4_stage0p_capture_approvals FROM PUBLIC;
REVOKE ALL ON m4_stage0p_capture_approvals FROM alpha3s_app;

-- ===========================================================================
-- 3. Bang m4_selection_batches — khoa lua chon. REV3 them predictions_written_at/result_hash
--    (T2-03/T2-04).
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_selection_batches (
  batch_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  window_start            TIMESTAMPTZ NOT NULL,
  window_end              TIMESTAMPTZ NOT NULL,
  eligible_count          INT NOT NULL,
  selected_count          INT NOT NULL,
  algorithm_seed          TEXT NOT NULL,
  locked_conversation_ids BIGINT[] NOT NULL,
  purpose_code            TEXT NOT NULL CHECK (purpose_code = 'P12_PII_DETECTOR_EVAL'),
  locked_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  status                  TEXT NOT NULL DEFAULT 'locked'
                             CHECK (status IN ('locked', 'collecting', 'closed')),
  captured_count          INT NOT NULL DEFAULT 0 CHECK (captured_count >= 0),
  labels_sealed_at        TIMESTAMPTZ,
  labels_sealed_by        BIGINT REFERENCES staff_users(id),
  labels_sealed_hash      TEXT,
  -- REV3 T2-03/T2-04: "prediction da ghi" (mot lan, bat bien) TACH BIET "eval xong". result_hash
  -- do DB tu tinh trong m4_stage0p_write_predictions (bind labels_sealed_hash+detector_version+
  -- predictions), KHONG phai Python truyen vao.
  predictions_written_at  TIMESTAMPTZ,
  result_hash             TEXT,
  evaluation_completed_at   TIMESTAMPTZ,
  evaluation_completed_by   BIGINT REFERENCES staff_users(id),
  evaluation_report_hash    TEXT,
  CONSTRAINT m4_batch_window_valid CHECK (window_end > window_start),
  CONSTRAINT m4_batch_count_valid CHECK (selected_count <= eligible_count AND selected_count <= 260),
  CONSTRAINT m4_batch_predictions_need_seal CHECK (predictions_written_at IS NULL OR labels_sealed_at IS NOT NULL),
  CONSTRAINT m4_batch_eval_needs_predictions CHECK (evaluation_completed_at IS NULL OR predictions_written_at IS NOT NULL)
);

COMMENT ON TABLE m4_selection_batches IS
  'M4 Stage 0P — khoa tap conversation_id da chon. REV3: predictions_written_at/result_hash la trang thai DB-enforced moi cho T2-03/T2-04 (xem §5).';

REVOKE ALL ON m4_selection_batches FROM PUBLIC;
REVOKE ALL ON m4_selection_batches FROM alpha3s_app;

-- ===========================================================================
-- 4. Bang m4_shadow_review_samples — sample zone. REV3 them prediction_excluded_reason (T2-03:
--    danh dau sample bi loai khoi cham diem CO LY DO ro rang, thay vi de predicted_slots NULL
--    vo thoi han khong phan biet duoc "chua xu ly" voi "co chu dinh loai").
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_shadow_review_samples (
  sample_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_ref          TEXT NOT NULL,
  conversation_ref       TEXT NOT NULL,
  encrypted_message     BYTEA NOT NULL,
  canonical_text_len    INT NOT NULL CHECK (canonical_text_len >= 0),
  truncated             BOOLEAN NOT NULL DEFAULT FALSE,
  captured_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at            TIMESTAMPTZ NOT NULL,
  purpose_code          TEXT NOT NULL CHECK (purpose_code = 'P12_PII_DETECTOR_EVAL'),
  label_status          TEXT NOT NULL DEFAULT 'unlabeled'
                           CHECK (label_status IN ('unlabeled', 'labeled')),
  normalization_version TEXT NOT NULL,
  labeled_slots         JSONB,
  predicted_slots       JSONB,
  prediction_excluded_reason TEXT,
  detector_version      TEXT,
  evaluation_batch      TEXT,
  selection_batch       UUID NOT NULL REFERENCES m4_selection_batches(batch_id),
  CONSTRAINT m4_sample_expiry_after_capture CHECK (expires_at > captured_at),
  CONSTRAINT m4_sample_ciphertext_cap CHECK (octet_length(encrypted_message) <= 8030),
  CONSTRAINT m4_sample_not_predicted_and_excluded CHECK (NOT (predicted_slots IS NOT NULL AND prediction_excluded_reason IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS m4_sample_customer_idx ON m4_shadow_review_samples (customer_ref);
CREATE INDEX IF NOT EXISTS m4_sample_expires_idx ON m4_shadow_review_samples (expires_at);
CREATE INDEX IF NOT EXISTS m4_sample_batch_idx ON m4_shadow_review_samples (selection_batch);
CREATE INDEX IF NOT EXISTS m4_sample_label_status_idx ON m4_shadow_review_samples (label_status);

COMMENT ON TABLE m4_shadow_review_samples IS
  'M4 Stage 0P sample zone (P12_PII_DETECTOR_EVAL). Retention: eval completed OR 45 ngay, tuy dieu kien nao truoc (RET-11b). DSR: xoa truc tiep theo customer_ref, khong join (khong orphan).';
COMMENT ON COLUMN m4_shadow_review_samples.encrypted_message IS
  'AES-256-GCM blob v2: version(2 byte ASCII "v1") || nonce(12) || ct+tag. AAD domain-tag a3s-m4-shadow-sample-aad-v1, fields=(customer_ref, conversation_ref, sample_id).';

REVOKE ALL ON m4_shadow_review_samples FROM PUBLIC;
REVOKE ALL ON m4_shadow_review_samples FROM alpha3s_app;

-- Trigger bat bien ground truth sau seal — PHAI SECURITY DEFINER (xem ghi chu REV2: neu khong,
-- trigger chay bang quyen invoker, reviewer_api khong co SELECT tren m4_selection_batches nen
-- MOI UPDATE se fail, khong chi UPDATE sau-seal — bug tu phat hien qua evidence thuc te).
CREATE OR REPLACE FUNCTION m4_stage0p_block_label_after_seal()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE v_sealed TIMESTAMPTZ;
BEGIN
  SELECT labels_sealed_at INTO v_sealed FROM public.m4_selection_batches
    WHERE batch_id = OLD.selection_batch;
  IF v_sealed IS NOT NULL
     AND (NEW.labeled_slots IS DISTINCT FROM OLD.labeled_slots
          OR NEW.label_status IS DISTINCT FROM OLD.label_status) THEN
    RAISE EXCEPTION 'm4_shadow_review_samples: labeled_slots/label_status bat bien sau khi batch % da sealed luc %',
      OLD.selection_batch, v_sealed;
  END IF;
  RETURN NEW;
END;
$$;

ALTER FUNCTION m4_stage0p_block_label_after_seal() OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_block_label_after_seal() FROM PUBLIC;

DROP TRIGGER IF EXISTS m4_stage0p_label_immutable_after_seal ON m4_shadow_review_samples;
CREATE TRIGGER m4_stage0p_label_immutable_after_seal
  BEFORE UPDATE ON m4_shadow_review_samples
  FOR EACH ROW EXECUTE FUNCTION m4_stage0p_block_label_after_seal();

-- Xoa toan bo ham REV2 se thay the (chu ky doi hoac logic doi hoan toan) — tranh CREATE OR
-- REPLACE nham lan giua cac chu ky khac nhau.
DROP FUNCTION IF EXISTS m4_stage0p_fetch_batch_content(UUID);
DROP FUNCTION IF EXISTS m4_stage0p_fetch_next_message(UUID, BIGINT, BIGINT);
DROP FUNCTION IF EXISTS m4_stage0p_seal_labels(UUID, BIGINT, TEXT);
DROP FUNCTION IF EXISTS m4_stage0p_write_predictions(UUID, JSONB, TEXT, TEXT);
DROP FUNCTION IF EXISTS m4_stage0p_complete_evaluation(UUID, BIGINT, TEXT);

-- ===========================================================================
-- 5a. m4_stage0p_peek_next_candidate — REV3 T2-01: KHONG lock, KHONG kiem tra control, KHONG
--     tra plaintext (chi conversation_id/message_id/customer_id) — an toan goi TRUOC khi giu
--     fence, dung de biet customer_id ma kiem tra pending-deletion TRUOC (chu khong phai BEN
--     TRONG luc dang giu advisory lock 4013003).
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_peek_next_candidate(
  p_batch_id UUID,
  p_after_conversation_id BIGINT DEFAULT -1,
  p_after_message_id BIGINT DEFAULT -1
)
RETURNS TABLE(status TEXT, conversation_id BIGINT, message_id BIGINT, customer_id BIGINT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_batch RECORD;
  v_row RECORD;
BEGIN
  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_peek_next_candidate: batch_id khong ton tai';
  END IF;
  IF v_batch.status = 'closed' THEN
    RAISE EXCEPTION 'm4_stage0p_peek_next_candidate: batch da closed';
  END IF;
  IF v_batch.purpose_code <> 'P12_PII_DETECTOR_EVAL' THEN
    RAISE EXCEPTION 'm4_stage0p_peek_next_candidate: purpose_code khong khop';
  END IF;
  IF now() < v_batch.window_start OR now() > v_batch.window_end + interval '7 days' THEN
    RAISE EXCEPTION 'm4_stage0p_peek_next_candidate: batch ngoai cua so hop le';
  END IF;

  SELECT ranked.conversation_id, ranked.id AS message_id, c.customer_id
    INTO v_row
    FROM (
      SELECT m.conversation_id, m.id,
             ROW_NUMBER() OVER (PARTITION BY m.conversation_id ORDER BY m.id ASC) AS rn
      FROM public.messages m
      WHERE m.role = 'customer'
        AND m.conversation_id = ANY (v_batch.locked_conversation_ids)
    ) ranked
    JOIN public.conversations c ON c.id = ranked.conversation_id
    WHERE ranked.rn <= 20
      AND (ranked.conversation_id, ranked.id) > (p_after_conversation_id, p_after_message_id)
    ORDER BY ranked.conversation_id, ranked.id
    LIMIT 1;

  IF NOT FOUND THEN
    RETURN QUERY SELECT 'exhausted'::TEXT, NULL::BIGINT, NULL::BIGINT, NULL::BIGINT;
    RETURN;
  END IF;

  RETURN QUERY SELECT 'ok'::TEXT, v_row.conversation_id, v_row.message_id, v_row.customer_id;
END;
$$;

ALTER FUNCTION m4_stage0p_peek_next_candidate(UUID, BIGINT, BIGINT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_peek_next_candidate(UUID, BIGINT, BIGINT) FROM PUBLIC;

-- ===========================================================================
-- 5b. m4_stage0p_fetch_message_content — REV3 T2-01/T2-02 pattern: fenced, nhan DUNG 1
--     (conversation_id, message_id) da biet (khong con tu quet cursor ben trong — giam thoi
--     gian giu lock). Validate lai (khong tin caller) rang cap doi thuoc dung batch + rn<=20.
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_fetch_message_content(
  p_batch_id UUID,
  p_conversation_id BIGINT,
  p_message_id BIGINT
)
RETURNS TABLE(status TEXT, content TEXT, char_truncated BOOLEAN, created_at TIMESTAMPTZ)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_batch RECORD;
  v_enabled BOOLEAN;
  v_row RECORD;
  v_audit_id BIGINT;
  v_cap INT;
BEGIN
  PERFORM pg_advisory_xact_lock(4013003);

  SELECT capture_enabled INTO v_enabled FROM public.m4_stage0p_control WHERE id = 1;
  IF v_enabled IS NOT TRUE THEN
    RETURN QUERY SELECT 'control_off'::TEXT, NULL::TEXT, NULL::BOOLEAN, NULL::TIMESTAMPTZ;
    RETURN;
  END IF;

  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_message_content: batch_id khong ton tai';
  END IF;
  IF v_batch.status = 'closed' THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_message_content: batch da closed';
  END IF;
  IF v_batch.purpose_code <> 'P12_PII_DETECTOR_EVAL' THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_message_content: purpose_code khong khop';
  END IF;
  IF now() < v_batch.window_start OR now() > v_batch.window_end + interval '7 days' THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_message_content: batch ngoai cua so hop le';
  END IF;

  v_cap := v_batch.selected_count * 20;
  IF v_batch.captured_count >= v_cap THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_message_content: batch % da dat tran captured_count (%/%)',
      p_batch_id, v_batch.captured_count, v_cap;
  END IF;

  -- KHONG tin (conversation_id, message_id) caller dua vao — re-derive dung tu ranked subquery
  -- (thuoc locked_conversation_ids VA rn<=20).
  SELECT ranked.content, ranked.created_at INTO v_row
    FROM (
      SELECT m.conversation_id, m.id, m.content, m.created_at,
             ROW_NUMBER() OVER (PARTITION BY m.conversation_id ORDER BY m.id ASC) AS rn
      FROM public.messages m
      WHERE m.role = 'customer'
        AND m.conversation_id = ANY (v_batch.locked_conversation_ids)
    ) ranked
    WHERE ranked.rn <= 20
      AND ranked.conversation_id = p_conversation_id
      AND ranked.id = p_message_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_message_content: message (%,%) khong hop le trong batch %',
      p_conversation_id, p_message_id, p_batch_id;
  END IF;

  INSERT INTO public.audit_log (actor_type, actor_ref, action, entity_type, entity_id, after)
  VALUES ('system', 'm4_stage0p_collector', 'm4_message_fetch', 'm4_selection_batch',
          p_batch_id::text, jsonb_build_object('conversation_id', p_conversation_id, 'message_id', p_message_id))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT 'ok'::TEXT, left(v_row.content, 2000), (char_length(v_row.content) > 2000),
                      v_row.created_at;
END;
$$;

ALTER FUNCTION m4_stage0p_fetch_message_content(UUID, BIGINT, BIGINT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_fetch_message_content(UUID, BIGINT, BIGINT) FROM PUBLIC;

-- ===========================================================================
-- 5c. m4_stage0p_record_sample — REV3 T2-06: INSERT + captured_count ATOMIC. Counter CHI tang
--     khi sample THAT SU duoc luu (khong con tang o buoc fetch, truoc ca pending-check).
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_record_sample(
  p_batch_id UUID,
  p_sample_id UUID,
  p_customer_ref TEXT,
  p_conversation_ref TEXT,
  p_encrypted_message BYTEA,
  p_canonical_text_len INT,
  p_truncated BOOLEAN,
  p_retention_days INT,
  p_normalization_version TEXT
)
RETURNS TABLE(captured_count INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_batch RECORD;
  v_cap INT;
  v_new_count INT;
  v_audit_id BIGINT;
BEGIN
  -- Lock nay thuong DA duoc giu tu fetch_message_content trong CUNG transaction (advisory
  -- xact-lock cho phep tai giu boi chinh transaction dang giu, khong deadlock voi chinh minh) —
  -- van goi de dam bao dung fenced ke ca khi ham nay duoc goi doc lap trong tuong lai.
  PERFORM pg_advisory_xact_lock(4013003);

  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: batch_id khong ton tai';
  END IF;
  IF v_batch.status = 'closed' THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: batch da closed';
  END IF;

  v_cap := v_batch.selected_count * 20;
  IF v_batch.captured_count >= v_cap THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: batch % da dat tran captured_count (%/%)',
      p_batch_id, v_batch.captured_count, v_cap;
  END IF;

  INSERT INTO public.m4_shadow_review_samples
    (sample_id, customer_ref, conversation_ref, encrypted_message, canonical_text_len,
     truncated, expires_at, purpose_code, normalization_version, selection_batch)
  VALUES (p_sample_id, p_customer_ref, p_conversation_ref, p_encrypted_message, p_canonical_text_len,
          p_truncated, now() + make_interval(days => p_retention_days), 'P12_PII_DETECTOR_EVAL',
          p_normalization_version, p_batch_id);

  UPDATE public.m4_selection_batches AS b
    SET captured_count = b.captured_count + 1,
        status = CASE WHEN b.status = 'locked' THEN 'collecting' ELSE b.status END
    WHERE b.batch_id = p_batch_id
    RETURNING b.captured_count INTO v_new_count;

  INSERT INTO public.audit_log (actor_type, actor_ref, action, entity_type, entity_id, after)
  VALUES ('system', 'm4_stage0p_collector', 'm4_sample_recorded', 'm4_selection_batch',
          p_batch_id::text, jsonb_build_object('sample_id', p_sample_id, 'captured_count', v_new_count))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_new_count;
END;
$$;

ALTER FUNCTION m4_stage0p_record_sample(UUID, UUID, TEXT, TEXT, BYTEA, INT, BOOLEAN, INT, TEXT)
  OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_record_sample(UUID, UUID, TEXT, TEXT, BYTEA, INT, BOOLEAN, INT, TEXT)
  FROM PUBLIC;

-- ===========================================================================
-- 5d. m4_stage0p_set_capture — REV3 T2-05: ON doi hoi approval record xac thuc (bang
--     m4_stage0p_capture_approvals) — KHONG con chi kiem approval_ref la chuoi khong rong. OFF
--     KHONG doi hoi approval (chi actor hop le) — CA yeu cau ro OFF khong duoc bi chan vi
--     approval het han/thu hoi.
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_set_capture(
  p_enabled BOOLEAN,
  p_actor_staff_id BIGINT,
  p_approval_ref TEXT
)
RETURNS TABLE(before_enabled BOOLEAN, after_enabled BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_before BOOLEAN;
  v_audit_id BIGINT;
BEGIN
  PERFORM pg_advisory_xact_lock(4013003);

  IF NOT EXISTS (SELECT 1 FROM public.staff_users WHERE id = p_actor_staff_id AND is_active = TRUE) THEN
    RAISE EXCEPTION 'm4_stage0p_set_capture: actor_staff_id khong ton tai hoac khong active';
  END IF;

  IF p_enabled THEN
    IF p_approval_ref IS NULL OR length(btrim(p_approval_ref)) = 0 THEN
      RAISE EXCEPTION 'm4_stage0p_set_capture: approval_ref bat buoc khi bat ON';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM public.m4_stage0p_capture_approvals
      WHERE approval_ref = p_approval_ref
        AND purpose_code = 'P12_PII_DETECTOR_EVAL'
        AND requested_enabled = TRUE
        AND status = 'approved'
        AND now() BETWEEN valid_from AND valid_until
    ) THEN
      RAISE EXCEPTION 'm4_stage0p_set_capture: approval_ref % khong hop le cho ON (khong ton tai/het han/bi thu hoi/sai purpose/sai trang thai yeu cau)',
        p_approval_ref;
    END IF;
  END IF;
  -- OFF: khong kiem approval — actor hop le la du (T2-05: khong duoc chan OFF vi approval het han).

  SELECT capture_enabled INTO v_before FROM public.m4_stage0p_control WHERE id = 1;

  UPDATE public.m4_stage0p_control
    SET capture_enabled = p_enabled,
        updated_at = now(),
        updated_by_note = 'actor_staff_id=' || p_actor_staff_id
                           || ' approval_ref=' || coalesce(p_approval_ref, '(none-off)')
    WHERE id = 1;

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id,
                                before, after, reason)
  VALUES ('staff', p_actor_staff_id, 'm4_stage0p_set_capture', 'm4_stage0p_control', '1',
          jsonb_build_object('capture_enabled', v_before),
          jsonb_build_object('capture_enabled', p_enabled), p_approval_ref)
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_before, p_enabled;
END;
$$;

ALTER FUNCTION m4_stage0p_set_capture(BOOLEAN, BIGINT, TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_set_capture(BOOLEAN, BIGINT, TEXT) FROM PUBLIC;

-- ===========================================================================
-- 5e. m4_stage0p_seal_labels — REV3 T2-04: DB TU TINH labels_sealed_hash qua pgcrypto digest()
--     — KHONG con nhan hash do Python truyen vao (truoc day chi kiem "khong rong", khong xac
--     minh khop labels that).
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_seal_labels(
  p_batch_id UUID,
  p_actor_staff_id BIGINT
)
RETURNS TABLE(sealed_hash TEXT, sample_count INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_unlabeled INT;
  v_count INT;
  v_hash TEXT;
  v_audit_id BIGINT;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.staff_users WHERE id = p_actor_staff_id AND is_active = TRUE) THEN
    RAISE EXCEPTION 'm4_stage0p_seal_labels: actor_staff_id khong ton tai hoac khong active';
  END IF;

  PERFORM 1 FROM public.m4_selection_batches WHERE batch_id = p_batch_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_seal_labels: batch_id khong ton tai';
  END IF;
  IF EXISTS (SELECT 1 FROM public.m4_selection_batches
             WHERE batch_id = p_batch_id AND labels_sealed_at IS NOT NULL) THEN
    RAISE EXCEPTION 'm4_stage0p_seal_labels: batch % da sealed', p_batch_id;
  END IF;

  SELECT count(*) FILTER (WHERE label_status <> 'labeled'), count(*)
    INTO v_unlabeled, v_count
    FROM public.m4_shadow_review_samples WHERE selection_batch = p_batch_id;

  IF v_count = 0 THEN
    RAISE EXCEPTION 'm4_stage0p_seal_labels: batch % khong co sample nao', p_batch_id;
  END IF;
  IF v_unlabeled > 0 THEN
    RAISE EXCEPTION 'm4_stage0p_seal_labels: batch % con % sample unlabeled', p_batch_id, v_unlabeled;
  END IF;

  -- T2-04: hash TU DB tinh tren chinh du lieu that trong bang (sample_id + labeled_slots, sap
  -- xep theo sample_id de doc lap thu tu tra ve) — khong phu thuoc/tin gia tri Python tuyen bo.
  SELECT encode(
    digest('m4-stage0p-label-hash-v1|' ||
           string_agg(sample_id::text || ':' || coalesce(labeled_slots::text, 'null'), '|' ORDER BY sample_id),
           'sha256'), 'hex')
    INTO v_hash
    FROM public.m4_shadow_review_samples WHERE selection_batch = p_batch_id;

  UPDATE public.m4_selection_batches
    SET labels_sealed_at = now(), labels_sealed_by = p_actor_staff_id, labels_sealed_hash = v_hash
    WHERE batch_id = p_batch_id;

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id, after)
  VALUES ('staff', p_actor_staff_id, 'm4_stage0p_seal_labels', 'm4_selection_batch',
          p_batch_id::text, jsonb_build_object('labels_sealed_hash', v_hash, 'sample_count', v_count))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_hash, v_count;
END;
$$;

ALTER FUNCTION m4_stage0p_seal_labels(UUID, BIGINT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_seal_labels(UUID, BIGINT) FROM PUBLIC;

-- ===========================================================================
-- 5f. m4_stage0p_fetch_sealed_message — REV3 T2-02: duong doc DUY NHAT cho prediction writer.
--     Kiem tra labels_sealed_at TRUOC khi tra BAT KY encrypted_message nao — batch chua sealed
--     thi KHONG mot row nao roi khoi ham (0 raw fetch, khong chi 0 write). Phan trang 1-row,
--     audit tung lan doc.
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_fetch_sealed_message(
  p_batch_id UUID,
  p_after_sample_id UUID DEFAULT NULL
)
RETURNS TABLE(status TEXT, sample_id UUID, encrypted_message BYTEA, customer_ref TEXT,
              conversation_ref TEXT, canonical_text_len INT, normalization_version TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_sealed TIMESTAMPTZ;
  v_row RECORD;
  v_audit_id BIGINT;
BEGIN
  SELECT labels_sealed_at INTO v_sealed FROM public.m4_selection_batches WHERE batch_id = p_batch_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_sealed_message: batch_id khong ton tai';
  END IF;
  IF v_sealed IS NULL THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_sealed_message: batch % chua sealed — KHONG duoc doc raw content', p_batch_id;
  END IF;

  SELECT s.sample_id, s.encrypted_message, s.customer_ref, s.conversation_ref, s.canonical_text_len,
         s.normalization_version
    INTO v_row
    FROM public.m4_shadow_review_samples s
    WHERE s.selection_batch = p_batch_id
      AND (p_after_sample_id IS NULL OR s.sample_id > p_after_sample_id)
    ORDER BY s.sample_id
    LIMIT 1;

  IF NOT FOUND THEN
    RETURN QUERY SELECT 'exhausted'::TEXT, NULL::UUID, NULL::BYTEA, NULL::TEXT, NULL::TEXT,
                        NULL::INT, NULL::TEXT;
    RETURN;
  END IF;

  INSERT INTO public.audit_log (actor_type, actor_ref, action, entity_type, entity_id, after)
  VALUES ('system', 'm4_stage0p_prediction_writer', 'm4_sealed_sample_fetch', 'm4_selection_batch',
          p_batch_id::text, jsonb_build_object('sample_id', v_row.sample_id))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT 'ok'::TEXT, v_row.sample_id, v_row.encrypted_message, v_row.customer_ref,
                      v_row.conversation_ref, v_row.canonical_text_len, v_row.normalization_version;
END;
$$;

ALTER FUNCTION m4_stage0p_fetch_sealed_message(UUID, UUID) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_fetch_sealed_message(UUID, UUID) FROM PUBLIC;

-- ===========================================================================
-- 5g. m4_stage0p_write_predictions — REV3 T2-03/T2-04: validate schema/enum/bounds/non-overlap/
--     sample-uniqueness/batch-membership, PHU DUNG toan bo corpus (predictions+exclusions),
--     bind labels_sealed_hash (tu choi stale/forged), tinh result_hash, BAT BIEN mot lan ghi.
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_write_predictions(
  p_batch_id UUID,
  p_expected_labels_sealed_hash TEXT,
  p_predictions JSONB,     -- [{"sample_id":"...", "predicted_slots":[{slot_type,start,end,confidence,reason}]}]
  p_exclusions JSONB,      -- [{"sample_id":"...", "reason":"..."}]
  p_detector_version TEXT,
  p_evaluation_batch TEXT
)
RETURNS TABLE(updated_count INT, excluded_count INT, result_hash TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_batch RECORD;
  v_item JSONB;
  v_span JSONB;
  v_sample_id UUID;
  v_canon_len INT;
  v_keys TEXT[];
  v_pred_ids UUID[] := ARRAY[]::UUID[];
  v_excl_ids UUID[] := ARRAY[]::UUID[];
  v_all_ids UUID[];
  v_updated INT := 0;
  v_excluded INT := 0;
  v_result_hash TEXT;
  v_audit_id BIGINT;
  v_prev_end INT;
  v_start INT;
  v_end INT;
BEGIN
  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: batch_id khong ton tai';
  END IF;
  IF v_batch.labels_sealed_at IS NULL THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: batch % chua sealed', p_batch_id;
  END IF;
  IF v_batch.labels_sealed_hash IS DISTINCT FROM p_expected_labels_sealed_hash THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: labels_sealed_hash khong khop (stale/forged corpus reference)';
  END IF;
  IF v_batch.predictions_written_at IS NOT NULL THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: batch % da ghi prediction luc % — bat bien, rerun phai tao batch moi',
      p_batch_id, v_batch.predictions_written_at;
  END IF;

  IF jsonb_typeof(p_predictions) <> 'array' THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: predictions phai la JSON array';
  END IF;
  IF p_exclusions IS NULL THEN
    p_exclusions := '[]'::jsonb;
  END IF;
  IF jsonb_typeof(p_exclusions) <> 'array' THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: exclusions phai la JSON array';
  END IF;

  FOR v_item IN SELECT elem FROM jsonb_array_elements(p_predictions) AS elem
  LOOP
    IF jsonb_typeof(v_item) <> 'object' THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: moi prediction phai la object';
    END IF;
    SELECT array_agg(k ORDER BY k) INTO v_keys FROM jsonb_object_keys(v_item) k;
    IF v_keys IS DISTINCT FROM ARRAY['predicted_slots', 'sample_id'] THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: prediction co key sai (thuc te %)', v_keys;
    END IF;
    BEGIN
      v_sample_id := (v_item ->> 'sample_id')::UUID;
    EXCEPTION WHEN OTHERS THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: sample_id khong phai UUID hop le: %', v_item ->> 'sample_id';
    END;
    IF v_sample_id = ANY (v_pred_ids) THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: sample_id % lap trong predictions', v_sample_id;
    END IF;
    SELECT canonical_text_len INTO v_canon_len FROM public.m4_shadow_review_samples
      WHERE sample_id = v_sample_id AND selection_batch = p_batch_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: sample_id % khong thuoc batch %', v_sample_id, p_batch_id;
    END IF;
    IF jsonb_typeof(v_item -> 'predicted_slots') <> 'array' THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: predicted_slots (sample %) phai la JSON array', v_sample_id;
    END IF;

    v_prev_end := NULL;
    FOR v_span IN
      SELECT elem FROM jsonb_array_elements(v_item -> 'predicted_slots') AS elem
      ORDER BY (elem ->> 'start')::int
    LOOP
      IF jsonb_typeof(v_span) <> 'object' THEN
        RAISE EXCEPTION 'm4_stage0p_write_predictions: span (sample %) phai la object', v_sample_id;
      END IF;
      SELECT array_agg(k ORDER BY k) INTO v_keys FROM jsonb_object_keys(v_span) k;
      IF v_keys IS DISTINCT FROM ARRAY['confidence', 'end', 'reason', 'slot_type', 'start'] THEN
        RAISE EXCEPTION 'm4_stage0p_write_predictions: span (sample %) co key sai (thuc te %)', v_sample_id, v_keys;
      END IF;
      IF NOT (v_span ->> 'slot_type' = ANY (ARRAY['phone', 'name', 'address', 'national_id', 'bank_account'])) THEN
        RAISE EXCEPTION 'm4_stage0p_write_predictions: slot_type khong hop le (sample %): %', v_sample_id, v_span ->> 'slot_type';
      END IF;
      IF NOT (v_span ->> 'confidence' = ANY (ARRAY['high', 'medium', 'low'])) THEN
        RAISE EXCEPTION 'm4_stage0p_write_predictions: confidence khong hop le (sample %): %', v_sample_id, v_span ->> 'confidence';
      END IF;
      IF jsonb_typeof(v_span -> 'start') <> 'number' OR jsonb_typeof(v_span -> 'end') <> 'number' THEN
        RAISE EXCEPTION 'm4_stage0p_write_predictions: start/end phai la so (sample %)', v_sample_id;
      END IF;
      v_start := (v_span ->> 'start')::int;
      v_end := (v_span ->> 'end')::int;
      IF NOT (v_start >= 0 AND v_start < v_end AND v_end <= v_canon_len) THEN
        RAISE EXCEPTION 'm4_stage0p_write_predictions: offset ngoai bounds (sample %): %-%/%',
          v_sample_id, v_start, v_end, v_canon_len;
      END IF;
      IF v_prev_end IS NOT NULL AND v_start < v_prev_end THEN
        RAISE EXCEPTION 'm4_stage0p_write_predictions: span chong lan (sample %)', v_sample_id;
      END IF;
      v_prev_end := v_end;
      IF v_span ->> 'reason' IS NULL OR length(btrim(v_span ->> 'reason')) = 0 THEN
        RAISE EXCEPTION 'm4_stage0p_write_predictions: reason khong duoc rong (sample %)', v_sample_id;
      END IF;
    END LOOP;

    v_pred_ids := v_pred_ids || v_sample_id;
  END LOOP;

  FOR v_item IN SELECT elem FROM jsonb_array_elements(p_exclusions) AS elem
  LOOP
    IF jsonb_typeof(v_item) <> 'object' THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: moi exclusion phai la object';
    END IF;
    SELECT array_agg(k ORDER BY k) INTO v_keys FROM jsonb_object_keys(v_item) k;
    IF v_keys IS DISTINCT FROM ARRAY['reason', 'sample_id'] THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: exclusion co key sai (thuc te %)', v_keys;
    END IF;
    BEGIN
      v_sample_id := (v_item ->> 'sample_id')::UUID;
    EXCEPTION WHEN OTHERS THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: exclusion sample_id khong phai UUID hop le: %', v_item ->> 'sample_id';
    END;
    IF v_sample_id = ANY (v_excl_ids) THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: sample_id % lap trong exclusions', v_sample_id;
    END IF;
    IF v_sample_id = ANY (v_pred_ids) THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: sample_id % vua co prediction vua bi exclude', v_sample_id;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.m4_shadow_review_samples
                   WHERE sample_id = v_sample_id AND selection_batch = p_batch_id) THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: exclusion sample_id % khong thuoc batch %', v_sample_id, p_batch_id;
    END IF;
    IF v_item ->> 'reason' IS NULL OR length(btrim(v_item ->> 'reason')) = 0 THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: exclusion reason khong duoc rong (sample %)', v_sample_id;
    END IF;
    v_excl_ids := v_excl_ids || v_sample_id;
  END LOOP;

  SELECT array_agg(sample_id ORDER BY sample_id) INTO v_all_ids
    FROM public.m4_shadow_review_samples WHERE selection_batch = p_batch_id;
  IF v_all_ids IS NULL THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: batch % khong co sample nao', p_batch_id;
  END IF;
  IF (SELECT array_agg(x ORDER BY x) FROM unnest(v_pred_ids || v_excl_ids) x) IS DISTINCT FROM v_all_ids THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: predictions+exclusions KHONG phu dung toan bo % sample cua batch (thieu/thua/sai)',
      array_length(v_all_ids, 1);
  END IF;

  FOR v_item IN SELECT elem FROM jsonb_array_elements(p_predictions) AS elem
  LOOP
    UPDATE public.m4_shadow_review_samples
      SET predicted_slots = v_item -> 'predicted_slots',
          detector_version = p_detector_version,
          evaluation_batch = p_evaluation_batch
      WHERE sample_id = (v_item ->> 'sample_id')::UUID AND selection_batch = p_batch_id;
    v_updated := v_updated + 1;
  END LOOP;

  FOR v_item IN SELECT elem FROM jsonb_array_elements(p_exclusions) AS elem
  LOOP
    UPDATE public.m4_shadow_review_samples
      SET prediction_excluded_reason = v_item ->> 'reason',
          detector_version = p_detector_version,
          evaluation_batch = p_evaluation_batch
      WHERE sample_id = (v_item ->> 'sample_id')::UUID AND selection_batch = p_batch_id;
    v_excluded := v_excluded + 1;
  END LOOP;

  -- T2-04: result_hash bind labels_sealed_hash (chinh gia tri vua doi chieu) + detector_version +
  -- toan bo predicted_slots/exclusion THAT SU vua ghi (doc lai tu bang, khong phai tu payload dau
  -- vao — dam bao hash phan anh dung trang thai DB sau ghi).
  SELECT encode(digest(
    'm4-stage0p-result-hash-v1|' || p_expected_labels_sealed_hash || '|' || p_detector_version || '|' ||
    string_agg(
      sample_id::text || ':' || coalesce(predicted_slots::text, 'excluded:' || coalesce(prediction_excluded_reason, '')),
      '|' ORDER BY sample_id),
    'sha256'), 'hex')
    INTO v_result_hash
    FROM public.m4_shadow_review_samples WHERE selection_batch = p_batch_id;

  UPDATE public.m4_selection_batches
    SET predictions_written_at = now(), result_hash = v_result_hash
    WHERE batch_id = p_batch_id;

  INSERT INTO public.audit_log (actor_type, actor_ref, action, entity_type, entity_id, after)
  VALUES ('system', 'm4_stage0p_prediction_writer', 'm4_stage0p_write_predictions',
          'm4_selection_batch', p_batch_id::text,
          jsonb_build_object('updated_count', v_updated, 'excluded_count', v_excluded,
                              'result_hash', v_result_hash, 'detector_version', p_detector_version,
                              'evaluation_batch', p_evaluation_batch))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_updated, v_excluded, v_result_hash;
END;
$$;

ALTER FUNCTION m4_stage0p_write_predictions(UUID, TEXT, JSONB, JSONB, TEXT, TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_write_predictions(UUID, TEXT, JSONB, JSONB, TEXT, TEXT) FROM PUBLIC;

-- ===========================================================================
-- 5h. m4_stage0p_complete_evaluation — REV3 T2-04/T2-06: bind result_hash (tu choi stale/
--     forged), tinh report_hash tu chinh chuoi da xac thuc (matching/aggregation version +
--     result_hash + metrics).
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_complete_evaluation(
  p_batch_id UUID,
  p_actor_staff_id BIGINT,
  p_expected_result_hash TEXT,
  p_metrics JSONB
)
RETURNS TABLE(completed_at TIMESTAMPTZ, report_hash TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_batch RECORD;
  v_uncovered INT;
  v_report_hash TEXT;
  v_audit_id BIGINT;
  v_now TIMESTAMPTZ := now();
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.staff_users WHERE id = p_actor_staff_id AND is_active = TRUE) THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: actor_staff_id khong ton tai hoac khong active';
  END IF;
  IF jsonb_typeof(p_metrics) <> 'object' THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: metrics phai la JSON object';
  END IF;

  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: batch_id khong ton tai';
  END IF;
  IF v_batch.labels_sealed_at IS NULL THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: batch % chua sealed', p_batch_id;
  END IF;
  IF v_batch.predictions_written_at IS NULL THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: batch % chua ghi prediction', p_batch_id;
  END IF;
  IF v_batch.result_hash IS DISTINCT FROM p_expected_result_hash THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: result_hash khong khop (stale/forged)';
  END IF;
  IF v_batch.evaluation_completed_at IS NOT NULL THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: batch % da eval-completed luc %',
      p_batch_id, v_batch.evaluation_completed_at;
  END IF;

  SELECT count(*) INTO v_uncovered FROM public.m4_shadow_review_samples
    WHERE selection_batch = p_batch_id AND predicted_slots IS NULL AND prediction_excluded_reason IS NULL;
  IF v_uncovered > 0 THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: batch % con % sample chua co prediction/exclusion',
      p_batch_id, v_uncovered;
  END IF;

  v_report_hash := encode(
    digest('m4-stage0p-report-hash-v1|exact-span-v1|micro-v1|' || v_batch.result_hash || '|' || p_metrics::text,
           'sha256'), 'hex');

  UPDATE public.m4_selection_batches
    SET evaluation_completed_at = v_now, evaluation_completed_by = p_actor_staff_id,
        evaluation_report_hash = v_report_hash, status = 'closed'
    WHERE batch_id = p_batch_id;

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id, after)
  VALUES ('staff', p_actor_staff_id, 'm4_stage0p_complete_evaluation', 'm4_selection_batch',
          p_batch_id::text, jsonb_build_object('evaluation_report_hash', v_report_hash))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_now, v_report_hash;
END;
$$;

ALTER FUNCTION m4_stage0p_complete_evaluation(UUID, BIGINT, TEXT, JSONB) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_complete_evaluation(UUID, BIGINT, TEXT, JSONB) FROM PUBLIC;

-- Quyen NOI BO can cho 8 ham hoat dong (chay boi alpha3s_m4_definer, khong phai caller)
GRANT SELECT ON public.messages TO alpha3s_m4_definer;
GRANT SELECT (id, customer_id) ON public.conversations TO alpha3s_m4_definer;
GRANT SELECT, UPDATE ON public.m4_selection_batches TO alpha3s_m4_definer;
GRANT SELECT, INSERT, UPDATE ON public.m4_shadow_review_samples TO alpha3s_m4_definer;
GRANT SELECT, UPDATE (capture_enabled, updated_at, updated_by_note) ON public.m4_stage0p_control
  TO alpha3s_m4_definer;
GRANT SELECT ON public.m4_stage0p_capture_approvals TO alpha3s_m4_definer;
GRANT SELECT (id, is_active) ON public.staff_users TO alpha3s_m4_definer;
GRANT INSERT, UPDATE, SELECT (id) ON public.audit_log TO alpha3s_m4_definer;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_definer;

-- ===========================================================================
-- 6. 8 role least-privilege (REV3 them alpha3s_m4_approval_recorder)
-- ===========================================================================
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_sample_collector') THEN
    CREATE ROLE alpha3s_m4_sample_collector NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_sample_reviewer_api') THEN
    CREATE ROLE alpha3s_m4_sample_reviewer_api NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_sample_evaluator') THEN
    CREATE ROLE alpha3s_m4_sample_evaluator NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_prediction_writer') THEN
    CREATE ROLE alpha3s_m4_prediction_writer NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_sample_purge') THEN
    CREATE ROLE alpha3s_m4_sample_purge NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_control_plane') THEN
    CREATE ROLE alpha3s_m4_control_plane NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_pending_checker') THEN
    CREATE ROLE alpha3s_m4_pending_checker NOLOGIN;
  END IF;
  -- REV3 T2-05: role RIENG ghi approval record — tach biet control_plane (chong tu duyet).
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_approval_recorder') THEN
    CREATE ROLE alpha3s_m4_approval_recorder NOLOGIN;
  END IF;
END $$;

-- 6a. collector: REV3 — KHONG con INSERT truc tiep tren sample (T2-06: INSERT+counter gop atomic
-- trong record_sample). CHI EXECUTE 3 ham: peek (khong lock)/fetch_message_content (fenced)/
-- record_sample. Van giu SELECT metadata cho Phase 1 (select_eligible_conversations/lock_batch —
-- khong doi, khong lien quan T2).
GRANT SELECT (id, customer_id, created_at) ON orders TO alpha3s_m4_sample_collector;
GRANT SELECT (id, customer_id, created_at) ON conversations TO alpha3s_m4_sample_collector;
GRANT SELECT (batch_id) ON m4_selection_batches TO alpha3s_m4_sample_collector;
GRANT INSERT ON m4_selection_batches TO alpha3s_m4_sample_collector;
GRANT EXECUTE ON FUNCTION m4_stage0p_peek_next_candidate(UUID, BIGINT, BIGINT) TO alpha3s_m4_sample_collector;
GRANT EXECUTE ON FUNCTION m4_stage0p_fetch_message_content(UUID, BIGINT, BIGINT) TO alpha3s_m4_sample_collector;
GRANT EXECUTE ON FUNCTION m4_stage0p_record_sample(UUID, UUID, TEXT, TEXT, BYTEA, INT, BOOLEAN, INT, TEXT)
  TO alpha3s_m4_sample_collector;

-- 6b. reviewer-api: SELECT/UPDATE nhan TRUOC seal; EXECUTE seal_labels (REV3: chu ky 2 tham so,
-- khong con nhan hash tu Python).
GRANT SELECT (sample_id, encrypted_message, canonical_text_len, normalization_version,
              customer_ref, conversation_ref, captured_at, label_status, selection_batch,
              labeled_slots)
  ON m4_shadow_review_samples TO alpha3s_m4_sample_reviewer_api;
GRANT UPDATE (labeled_slots, label_status) ON m4_shadow_review_samples TO alpha3s_m4_sample_reviewer_api;
GRANT EXECUTE ON FUNCTION m4_stage0p_seal_labels(UUID, BIGINT) TO alpha3s_m4_sample_reviewer_api;
GRANT INSERT ON audit_log TO alpha3s_m4_sample_reviewer_api;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_sample_reviewer_api;

-- 6c. evaluator: SELECT chi cot nhan/du doan + metadata, KHONG noi dung/dinh danh. EXECUTE
-- complete_evaluation (REV3: chu ky 4 tham so, them p_metrics).
GRANT SELECT (sample_id, label_status, labeled_slots, predicted_slots, prediction_excluded_reason,
              canonical_text_len, normalization_version, detector_version, evaluation_batch,
              selection_batch, truncated)
  ON m4_shadow_review_samples TO alpha3s_m4_sample_evaluator;
GRANT SELECT (batch_id, labels_sealed_at, labels_sealed_hash, predictions_written_at, result_hash,
              evaluation_completed_at)
  ON m4_selection_batches TO alpha3s_m4_sample_evaluator;
GRANT EXECUTE ON FUNCTION m4_stage0p_complete_evaluation(UUID, BIGINT, TEXT, JSONB) TO alpha3s_m4_sample_evaluator;
GRANT INSERT ON audit_log TO alpha3s_m4_sample_evaluator;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_sample_evaluator;

-- 6d. prediction_writer: REV3 T2-02 — KHONG con SELECT truc tiep tren cot noi dung; CHI EXECUTE
-- fetch_sealed_message (sealed-only, phan trang, audited) + write_predictions.
GRANT SELECT (batch_id, labels_sealed_hash) ON m4_selection_batches TO alpha3s_m4_prediction_writer;
GRANT EXECUTE ON FUNCTION m4_stage0p_fetch_sealed_message(UUID, UUID) TO alpha3s_m4_prediction_writer;
GRANT EXECUTE ON FUNCTION m4_stage0p_write_predictions(UUID, TEXT, JSONB, JSONB, TEXT, TEXT)
  TO alpha3s_m4_prediction_writer;

-- 6e. purge: DELETE + SELECT chi cot can cho WHERE.
GRANT SELECT (customer_ref, expires_at, sample_id, selection_batch) ON m4_shadow_review_samples
  TO alpha3s_m4_sample_purge;
GRANT DELETE ON m4_shadow_review_samples TO alpha3s_m4_sample_purge;
GRANT SELECT (batch_id, evaluation_completed_at) ON m4_selection_batches TO alpha3s_m4_sample_purge;

-- 6f. control_plane: KHONG UPDATE truc tiep tren control; CHI EXECUTE set_capture (kiem approval
-- record BEN TRONG ham — control_plane KHONG duoc doc/ghi bang approvals truc tiep, T2-05).
GRANT SELECT (capture_enabled, updated_at) ON m4_stage0p_control TO alpha3s_m4_control_plane;
GRANT EXECUTE ON FUNCTION m4_stage0p_set_capture(BOOLEAN, BIGINT, TEXT) TO alpha3s_m4_control_plane;

-- 6g. pending_checker: CHI role duoc doc customers.psid trong pham vi M4.
GRANT SELECT (id, psid) ON customers TO alpha3s_m4_pending_checker;
GRANT INSERT ON audit_log TO alpha3s_m4_pending_checker;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_pending_checker;

-- 6h. approval_recorder (MOI, T2-05): CHI role ghi/doc approval record — KHONG lien quan gi den
-- control_plane (khong the tu duyet cho chinh minh boi vi day la 2 role tach biet hoan toan,
-- khong role nao la member cua role kia).
GRANT INSERT, SELECT ON m4_stage0p_capture_approvals TO alpha3s_m4_approval_recorder;

-- 6i. DSR: process_deletion() qua runtime alpha3s_app.
GRANT DELETE ON m4_shadow_review_samples TO alpha3s_app;
GRANT SELECT (customer_ref) ON m4_shadow_review_samples TO alpha3s_app;

-- runtime app + vendor-path: KHONG quyen nao khac ngoai DSR delete o tren.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_vendor_path') THEN
    REVOKE ALL ON m4_shadow_review_samples, m4_selection_batches, m4_stage0p_control,
      m4_stage0p_capture_approvals FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_peek_next_candidate(UUID, BIGINT, BIGINT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_fetch_message_content(UUID, BIGINT, BIGINT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_record_sample(UUID, UUID, TEXT, TEXT, BYTEA, INT, BOOLEAN, INT, TEXT)
      FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_set_capture(BOOLEAN, BIGINT, TEXT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_seal_labels(UUID, BIGINT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_fetch_sealed_message(UUID, UUID) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_write_predictions(UUID, TEXT, JSONB, JSONB, TEXT, TEXT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_complete_evaluation(UUID, BIGINT, TEXT, JSONB) FROM alpha3s_vendor_path;
  END IF;
END $$;

-- ===========================================================================
-- 7. Postcondition fail-closed — REV3: chung minh T2-01..06 thiet ke (cong voi toan bo bat bien
--    REV2 truoc do)
-- ===========================================================================
DO $$
DECLARE problems TEXT := '';
BEGIN
  IF to_regclass('public.m4_shadow_review_samples') IS NULL THEN
    problems := problems || ' sample_table_missing'; END IF;
  IF to_regclass('public.m4_selection_batches') IS NULL THEN
    problems := problems || ' batch_table_missing'; END IF;
  IF to_regclass('public.m4_stage0p_control') IS NULL THEN
    problems := problems || ' control_table_missing'; END IF;
  IF to_regclass('public.m4_stage0p_capture_approvals') IS NULL THEN
    problems := problems || ' approvals_table_missing'; END IF;
  IF (SELECT count(*) FROM m4_stage0p_control) <> 1 THEN
    problems := problems || ' control_not_singleton'; END IF;
  IF (SELECT capture_enabled FROM m4_stage0p_control WHERE id=1) IS DISTINCT FROM FALSE THEN
    problems := problems || ' control_not_default_off'; END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_m4_definer'
                 AND NOT rolsuper AND NOT rolcreaterole AND NOT rolcreatedb) THEN
    problems := problems || ' definer_role_privileged'; END IF;

  -- REV3: 9 ham SECURITY DEFINER (8 nghiep vu + 1 trigger) phai cung owner/search_path/khong PUBLIC
  IF EXISTS (
    SELECT 1 FROM pg_proc WHERE proname IN (
      'm4_stage0p_peek_next_candidate','m4_stage0p_fetch_message_content','m4_stage0p_record_sample',
      'm4_stage0p_set_capture','m4_stage0p_seal_labels','m4_stage0p_fetch_sealed_message',
      'm4_stage0p_write_predictions','m4_stage0p_complete_evaluation','m4_stage0p_block_label_after_seal')
      AND (proowner::regrole::text <> 'alpha3s_m4_definer' OR prosecdef IS NOT TRUE
           OR proconfig IS NULL
           OR NOT EXISTS (SELECT 1 FROM unnest(proconfig) c WHERE c LIKE 'search_path=%'))
  ) THEN
    problems := problems || ' definer_function_hardening_incomplete'; END IF;

  IF has_function_privilege('public', 'm4_stage0p_peek_next_candidate(uuid,bigint,bigint)', 'EXECUTE') THEN
    problems := problems || ' peek_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_fetch_message_content(uuid,bigint,bigint)', 'EXECUTE') THEN
    problems := problems || ' fetch_content_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_record_sample(uuid,uuid,text,text,bytea,int,boolean,int,text)', 'EXECUTE') THEN
    problems := problems || ' record_sample_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_set_capture(boolean,bigint,text)', 'EXECUTE') THEN
    problems := problems || ' set_capture_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_seal_labels(uuid,bigint)', 'EXECUTE') THEN
    problems := problems || ' seal_labels_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_fetch_sealed_message(uuid,uuid)', 'EXECUTE') THEN
    problems := problems || ' fetch_sealed_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_write_predictions(uuid,text,jsonb,jsonb,text,text)', 'EXECUTE') THEN
    problems := problems || ' write_predictions_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_complete_evaluation(uuid,bigint,text,jsonb)', 'EXECUTE') THEN
    problems := problems || ' complete_evaluation_execute_public'; END IF;

  IF NOT has_function_privilege('alpha3s_m4_sample_collector',
       'm4_stage0p_peek_next_candidate(uuid,bigint,bigint)', 'EXECUTE') THEN
    problems := problems || ' collector_no_execute_peek'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_collector',
       'm4_stage0p_fetch_message_content(uuid,bigint,bigint)', 'EXECUTE') THEN
    problems := problems || ' collector_no_execute_fetch_content'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_collector',
       'm4_stage0p_record_sample(uuid,uuid,text,text,bytea,int,boolean,int,text)', 'EXECUTE') THEN
    problems := problems || ' collector_no_execute_record_sample'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_control_plane',
       'm4_stage0p_set_capture(boolean,bigint,text)', 'EXECUTE') THEN
    problems := problems || ' control_plane_no_execute_set_capture'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_reviewer_api',
       'm4_stage0p_seal_labels(uuid,bigint)', 'EXECUTE') THEN
    problems := problems || ' reviewer_no_execute_seal'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_prediction_writer',
       'm4_stage0p_fetch_sealed_message(uuid,uuid)', 'EXECUTE') THEN
    problems := problems || ' prediction_writer_no_execute_fetch_sealed'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_prediction_writer',
       'm4_stage0p_write_predictions(uuid,text,jsonb,jsonb,text,text)', 'EXECUTE') THEN
    problems := problems || ' prediction_writer_no_execute_write'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_evaluator',
       'm4_stage0p_complete_evaluation(uuid,bigint,text,jsonb)', 'EXECUTE') THEN
    problems := problems || ' evaluator_no_execute_complete'; END IF;

  -- REV3 T2-06: collector KHONG con INSERT truc tiep tren sample (chi qua record_sample)
  IF has_table_privilege('alpha3s_m4_sample_collector','m4_shadow_review_samples','INSERT') THEN
    problems := problems || ' collector_has_direct_insert'; END IF;
  IF has_table_privilege('alpha3s_m4_sample_collector','m4_shadow_review_samples','SELECT') THEN
    problems := problems || ' collector_can_select_sample'; END IF;
  IF has_table_privilege('alpha3s_m4_sample_collector','public.messages','SELECT') THEN
    problems := problems || ' collector_can_select_messages_directly'; END IF;
  IF has_column_privilege('alpha3s_m4_sample_collector','public.customers','psid','SELECT') THEN
    problems := problems || ' collector_can_read_psid'; END IF;
  IF has_column_privilege('alpha3s_m4_sample_collector','m4_stage0p_control','capture_enabled','SELECT') THEN
    problems := problems || ' collector_can_read_control_directly'; END IF;
  IF NOT has_column_privilege('alpha3s_m4_pending_checker','public.customers','psid','SELECT') THEN
    problems := problems || ' pending_checker_no_psid'; END IF;

  IF has_column_privilege('alpha3s_m4_sample_reviewer_api','m4_shadow_review_samples',
                          'predicted_slots','SELECT') THEN
    problems := problems || ' reviewer_can_see_prediction'; END IF;

  IF has_column_privilege('alpha3s_m4_sample_evaluator','m4_shadow_review_samples',
                          'encrypted_message','SELECT') THEN
    problems := problems || ' evaluator_can_read_content'; END IF;
  IF has_column_privilege('alpha3s_m4_sample_evaluator','m4_shadow_review_samples',
                          'customer_ref','SELECT') THEN
    problems := problems || ' evaluator_can_read_customer_ref'; END IF;

  -- REV3 T2-02: prediction_writer KHONG con SELECT truc tiep tren cot noi dung
  IF has_column_privilege('alpha3s_m4_prediction_writer','m4_shadow_review_samples',
                          'encrypted_message','SELECT') THEN
    problems := problems || ' prediction_writer_can_select_content_directly'; END IF;
  IF has_column_privilege('alpha3s_m4_prediction_writer','m4_shadow_review_samples',
                          'customer_ref','SELECT') THEN
    problems := problems || ' prediction_writer_can_select_customer_ref_directly'; END IF;

  IF NOT has_table_privilege('alpha3s_m4_sample_purge','m4_shadow_review_samples','DELETE') THEN
    problems := problems || ' purge_no_delete'; END IF;
  IF has_table_privilege('alpha3s_m4_sample_purge','m4_shadow_review_samples','UPDATE') THEN
    problems := problems || ' purge_has_update'; END IF;
  IF has_column_privilege('alpha3s_m4_sample_purge','m4_shadow_review_samples',
                          'encrypted_message','SELECT') THEN
    problems := problems || ' purge_can_read_content'; END IF;

  IF has_column_privilege('alpha3s_m4_control_plane','m4_stage0p_control',
                          'capture_enabled','UPDATE') THEN
    problems := problems || ' control_plane_has_direct_update'; END IF;
  IF has_column_privilege('alpha3s_m4_sample_collector','m4_stage0p_control',
                          'capture_enabled','UPDATE') THEN
    problems := problems || ' collector_can_update_control'; END IF;
  IF has_column_privilege('alpha3s_m4_prediction_writer','m4_shadow_review_samples',
                          'predicted_slots','UPDATE') THEN
    problems := problems || ' prediction_writer_has_direct_update'; END IF;

  -- REV3 T2-05: chi approval_recorder duoc ghi bang approvals; control_plane KHONG duoc doc/ghi
  -- truc tiep (phai qua ham set_capture).
  IF NOT has_table_privilege('alpha3s_m4_approval_recorder','m4_stage0p_capture_approvals','INSERT') THEN
    problems := problems || ' approval_recorder_no_insert'; END IF;
  IF has_table_privilege('alpha3s_m4_control_plane','m4_stage0p_capture_approvals','INSERT') THEN
    problems := problems || ' control_plane_can_insert_approval'; END IF;
  IF has_table_privilege('alpha3s_m4_control_plane','m4_stage0p_capture_approvals','SELECT') THEN
    problems := problems || ' control_plane_can_select_approval'; END IF;
  IF has_table_privilege('alpha3s_m4_sample_collector','m4_stage0p_capture_approvals','INSERT') THEN
    problems := problems || ' collector_can_insert_approval'; END IF;

  IF has_table_privilege('alpha3s_app','m4_shadow_review_samples','INSERT') THEN
    problems := problems || ' app_can_insert_sample'; END IF;
  IF has_column_privilege('alpha3s_app','m4_shadow_review_samples','encrypted_message','SELECT') THEN
    problems := problems || ' app_can_read_content'; END IF;
  IF NOT has_table_privilege('alpha3s_app','m4_shadow_review_samples','DELETE') THEN
    problems := problems || ' app_no_dsr_delete'; END IF;

  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_vendor_path') THEN
    IF has_table_privilege('alpha3s_vendor_path','m4_shadow_review_samples','SELECT') THEN
      problems := problems || ' vendor_can_select_sample'; END IF;
    IF has_function_privilege('alpha3s_vendor_path',
                              'm4_stage0p_fetch_message_content(uuid,bigint,bigint)','EXECUTE') THEN
      problems := problems || ' vendor_can_execute_fetch'; END IF;
  END IF;

  IF has_table_privilege('public','m4_shadow_review_samples','SELECT') THEN
    problems := problems || ' public_can_select_sample'; END IF;
  IF has_table_privilege('public','m4_selection_batches','SELECT') THEN
    problems := problems || ' public_can_select_batches'; END IF;
  IF has_table_privilege('public','m4_stage0p_control','SELECT') THEN
    problems := problems || ' public_can_select_control'; END IF;
  IF has_table_privilege('public','m4_stage0p_capture_approvals','SELECT') THEN
    problems := problems || ' public_can_select_approvals'; END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'm4_stage0p_label_immutable_after_seal'
      AND tgrelid = 'public.m4_shadow_review_samples'::regclass AND tgenabled <> 'D'
  ) THEN
    problems := problems || ' label_immutable_trigger_missing_or_disabled'; END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'm4_sample_ciphertext_cap'
      AND pg_get_constraintdef(oid) LIKE '%<= 8030%'
  ) THEN
    problems := problems || ' ciphertext_cap_wrong_value'; END IF;

  IF problems <> '' THEN
    RAISE EXCEPTION '039 postcondition FAIL —%', problems; END IF;
END $$;
