-- Migration 039: M4 Stage 0P schema — Trusted PII Path production-shadow governance
-- (A3S-PHASE1B-M4-SPEC-001 v1.1.0 §6/§7; A3S-PHASE1B-M4-STAGE-0P-DESIGN-ACCEPTANCE-VI accepted
-- head d2a63c5, package v4.0.0). Theo dung 5 finding CLOSED AT DESIGN LEVEL (F-M4-0P-01..05).
--
-- REV 2 (Technical Correction #1, sau CA Technical Review #1
-- PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-1-VI, reviewed_head e10af661): sua 6 finding P1
-- T1-01..T1-06. File nay CHINH SUA TRUC TIEP (khong tao migration 040) vi 039 chua tung apply
-- vao baseline da accept/chia se — dung tinh than xu ly migration pre-acceptance cua du an nay.
--
-- ⚠️ EXPAND-ONLY, dev/test scope theo CA Design Acceptance §4: duoc phep tao migration/role/
-- function tren branch M4 voi du lieu synthetic/test. KHONG duoc doc/copy production data,
-- KHONG cap role/credential production, KHONG dat control row ON, KHONG bat capture that.
--
-- 3 bang: m4_shadow_review_samples (sample zone, tach hoan toan pii_slots), m4_selection_batches
-- (khoa lua chon — chan collector tu do doc conversation_id; REV2 them cot captured_count/
-- labels_sealed_*/evaluation_completed_* — xem finding T1-02/T1-03/T1-06), m4_stage0p_control
-- (kill switch DONG, doc tuoi moi lan — F-M4-0P-01B, KHONG dung settings static; REV2: chi doi
-- duoc qua ham m4_stage0p_set_capture, khong con UPDATE truc tiep — T1-05).
--
-- 7 role least-privilege (REV2 them alpha3s_m4_pending_checker da co tu truoc, khong doi so
-- luong): alpha3s_m4_sample_collector (INSERT-only + EXECUTE ham fetch phan trang),
-- alpha3s_m4_sample_reviewer_api (SELECT+UPDATE nhan TRUOC seal, EXECUTE seal_labels),
-- alpha3s_m4_sample_evaluator (SELECT cot nhan/du doan + EXECUTE complete_evaluation),
-- alpha3s_m4_prediction_writer (REV2: KHONG con UPDATE truc tiep — chi EXECUTE
-- write_predictions), alpha3s_m4_sample_purge (DELETE + SELECT cot can),
-- alpha3s_m4_control_plane (REV2: KHONG con UPDATE truc tiep — chi EXECUTE set_capture),
-- alpha3s_m4_pending_checker (SELECT customers.psid, dung boi is_pending_deletion()).
--
-- Ham SECURITY DEFINER: owner LA ROLE RIENG non-superuser alpha3s_m4_definer (KHONG dung role
-- migration-owner cua ket noi hien tai — da xac nhan qua kiem tra thuc te alpha3s la superuser
-- trong docker dev image). REV2 them 4 ham SECURITY DEFINER moi cung owner:
--   m4_stage0p_set_capture       — T1-01/T1-05: doi kill switch, fence bang pg_advisory_xact_lock
--   m4_stage0p_fetch_next_message — T1-01/T1-02: phan trang 1-row, cap ap NGAY trong ham, cung
--                                    fence bang pg_advisory_xact_lock (CUNG 1 lock key voi
--                                    set_capture — dam bao khong co sample commit sau OFF commit)
--   m4_stage0p_seal_labels        — T1-03: khoa ground truth truoc khi cho phep predict
--   m4_stage0p_write_predictions  — T1-03: ghi prediction CHI qua ham nay, kiem tra sealed atomic
--   m4_stage0p_complete_evaluation — T1-06: trang thai "eval xong" tach biet "prediction da ghi"
--
-- Advisory lock key 4013003 (STAGE0P CONTROL FENCE — rieng, khac 4013001 cua scripts/migrate.py
-- va 4013002 cua run_collector's single-writer lock cu): dung thay vi SELECT...FOR UPDATE/SHARE
-- tren m4_stage0p_control vi advisory lock KHONG doi hoi cap UPDATE/DELETE cho collector role
-- (giu dung isolation "collector khong the tu doi control"). pg_advisory_xact_lock TU DONG nha
-- khi transaction goi no COMMIT/ROLLBACK — nen 1 don vi doc+ghi (1 message) PHAI nam trong DUY
-- NHAT 1 transaction de lock giu xuyen suot toan bo don vi, tao ranh gioi that: khong co sample
-- commit nao xay ra SAU khi 1 lenh set_capture(OFF) da commit (vi set_capture cung phai doi lock
-- nay truoc khi doi duoc control — bat ke ai giu lock truoc se hoan tat/rollback truoc).
--
-- transactional: true

-- ===========================================================================
-- 1. Role dinh nghia rieng cho SECURITY DEFINER function (non-superuser, xac nhan o postcondition)
-- ===========================================================================
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_definer') THEN
    CREATE ROLE alpha3s_m4_definer NOLOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB;
  END IF;
END $$;

-- ===========================================================================
-- 2. Bang m4_stage0p_control — kill switch DONG (F-M4-0P-01B). Singleton row.
--    REV2 (T1-05): doi duoc CHI qua ham m4_stage0p_set_capture (§5b) — khong con UPDATE
--    truc tiep tu bat ky role nao, kho ca truong hop caller quen mo transaction (T1-05
--    goc: "caller dung autocommit co the commit control change truoc, sau do audit loi").
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_control (
  id               SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  capture_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- KHONG dung cot nay lam nguon tham quyen — la dieu nay chi de tham khao nguoi van hanh xem
  -- nhanh; tham quyen THAT nam o audit_log (actor_staff_id + approval_ref), ghi ATOMIC cung
  -- luc voi UPDATE trong ham m4_stage0p_set_capture (§5b) — REV2, khong con phu thuoc caller.
  updated_by_note  TEXT
);
INSERT INTO m4_stage0p_control (id, capture_enabled) VALUES (1, FALSE)
  ON CONFLICT (id) DO NOTHING;

COMMENT ON TABLE m4_stage0p_control IS
  'M4 Stage 0P kill switch DONG (F-M4-0P-01B) — doc tuoi bang SELECT truoc MOI don vi ghi, KHONG dung app-level settings static. REV2 (T1-05): doi CHI qua ham m4_stage0p_set_capture (fence bang advisory lock 4013003) — khong role nao con UPDATE truc tiep. Nguon tham quyen ON/OFF that: audit_log qua ham nay.';

REVOKE ALL ON m4_stage0p_control FROM PUBLIC;
-- QUAN TRONG: migration 024 co ALTER DEFAULT PRIVILEGES tu dong cap CRUD day du cho alpha3s_app
-- (runtime) tren MOI bang MOI trong schema public. Phai REVOKE tuong minh o day roi grant lai
-- hep — neu khong alpha3s_app se co SELECT/INSERT/UPDATE/DELETE ngam dinh tren bang nay, pha vo
-- thiet ke least-privilege (F-M4-0P-02B).
REVOKE ALL ON m4_stage0p_control FROM alpha3s_app;

-- ===========================================================================
-- 3. Bang m4_selection_batches — khoa lua chon (F-M4-0P-02A/02B). Chan collector tu do
--    truy van conversation_id: sau khi khoa, collector CHI biet batch_id.
--    REV2: them captured_count (T1-02 — dem tich luy BEN VUNG o DB, khong chi dua vao counter
--    trong 1 process/advisory lock), labels_sealed_at/by/hash (T1-03 — seal ground truth truoc
--    predict), evaluation_completed_at/by/report_hash (T1-06 — tach "eval xong" khoi
--    "prediction da ghi").
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
  -- T1-02: dem tong so sample da capture cho batch nay, tang ATOMIC trong cung transaction voi
  -- INSERT sample (xem m4_stage0p_fetch_next_message) — ben vung qua process restart, khong nhu
  -- counter Python thuan tuy. Chan tren = selected_count * 20 (Cap B moi hoi thoai).
  captured_count          INT NOT NULL DEFAULT 0 CHECK (captured_count >= 0),
  -- T1-03: seal ground truth — bat bien tu day, moi sua phai tao batch/revision moi.
  labels_sealed_at        TIMESTAMPTZ,
  labels_sealed_by        BIGINT REFERENCES staff_users(id),
  labels_sealed_hash      TEXT,
  -- T1-06: "eval xong" TACH BIET "prediction da ghi" — purge_expired() phai doi cot nay,
  -- khong duoc suy tu label_status/predicted_slots cap-row (xem §5e, app/services/pii/
  -- stage0p_sampling.py purge_expired()).
  evaluation_completed_at   TIMESTAMPTZ,
  evaluation_completed_by   BIGINT REFERENCES staff_users(id),
  evaluation_report_hash    TEXT,
  CONSTRAINT m4_batch_window_valid CHECK (window_end > window_start),
  CONSTRAINT m4_batch_count_valid CHECK (selected_count <= eligible_count AND selected_count <= 260),
  CONSTRAINT m4_batch_eval_needs_seal CHECK (evaluation_completed_at IS NULL OR labels_sealed_at IS NOT NULL)
);

COMMENT ON TABLE m4_selection_batches IS
  'M4 Stage 0P — khoa tap conversation_id da chon (F-M4-0P-02A). locked_conversation_ids CHI ham SECURITY DEFINER noi bo doc; collector KHONG co SELECT truc tiep tren cot nay. REV2: captured_count/labels_sealed_*/evaluation_completed_* la trang thai DB-enforced cho T1-02/T1-03/T1-06 — xem §5.';

REVOKE ALL ON m4_selection_batches FROM PUBLIC;
REVOKE ALL ON m4_selection_batches FROM alpha3s_app;  -- xem ghi chu default-privileges o tren

-- ===========================================================================
-- 4. Bang m4_shadow_review_samples — sample zone (tach hoan toan pii_slots)
--    REV2 (T1-02): sua CHECK ciphertext boundary — _SAMPLE_VERSION = b"v1" la 2 BYTE (ASCII
--    "v" + "1"), khong phai 1 nhu gia dinh sai truoc do. Overhead dung = 2 (version) + 12
--    (nonce) + 16 (tag GCM) = 30. Cap plaintext MAX_BYTES=8000 => ciphertext toi da 8030,
--    KHONG phai 8045. Khoa bang unit test exact-boundary (tests/test_m4_stage0p_crypto.py).
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_shadow_review_samples (
  sample_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_ref          TEXT NOT NULL,   -- = customers.id::text (bat bien, KHONG psid — xem crypto.py)
  conversation_ref       TEXT NOT NULL,   -- = conversations.id::text
  encrypted_message     BYTEA NOT NULL,
  canonical_text_len    INT NOT NULL CHECK (canonical_text_len >= 0),
  truncated             BOOLEAN NOT NULL DEFAULT FALSE,
  captured_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at            TIMESTAMPTZ NOT NULL,
  purpose_code          TEXT NOT NULL CHECK (purpose_code = 'P12_PII_DETECTOR_EVAL'),
  label_status          TEXT NOT NULL DEFAULT 'unlabeled'
                           CHECK (label_status IN ('unlabeled', 'labeled')),
  normalization_version TEXT NOT NULL,
  labeled_slots         JSONB,   -- [{slot_type,start,end,confidence,reason}] — F-M4-0P-05A
  predicted_slots       JSONB,   -- CUNG format; NULL toi khi ca batch labeled xong (§5.4)
  detector_version      TEXT,
  evaluation_batch      TEXT,
  selection_batch       UUID NOT NULL REFERENCES m4_selection_batches(batch_id),
  CONSTRAINT m4_sample_expiry_after_capture CHECK (expires_at > captured_at),
  -- F-M4-0P-03B / REV2 T1-02: byte cap THAT enforce lai o DB boundary — 8000 (MAX_BYTES) + 30
  -- (version 2 + nonce 12 + tag 16) = 8030. Khong phu thuoc 100% logic cat o tang Python.
  CONSTRAINT m4_sample_ciphertext_cap CHECK (octet_length(encrypted_message) <= 8030)
);

CREATE INDEX IF NOT EXISTS m4_sample_customer_idx ON m4_shadow_review_samples (customer_ref);
CREATE INDEX IF NOT EXISTS m4_sample_expires_idx ON m4_shadow_review_samples (expires_at);
CREATE INDEX IF NOT EXISTS m4_sample_batch_idx ON m4_shadow_review_samples (selection_batch);
CREATE INDEX IF NOT EXISTS m4_sample_label_status_idx ON m4_shadow_review_samples (label_status);

COMMENT ON TABLE m4_shadow_review_samples IS
  'M4 Stage 0P sample zone (P12_PII_DETECTOR_EVAL) — encrypted_message AES-256-GCM domain rieng (a3s-m4-shadow-sample-aad-v1, khac pii_slots). Retention: eval completed (m4_selection_batches.evaluation_completed_at) OR 45 ngay tu captured_at, tuy dieu kien nao truoc (RET-11b, REV2 T1-06). DSR: xoa truc tiep theo customer_ref, khong join conversations/messages (khong orphan) — xem app/services/data_deletion.py.';
COMMENT ON COLUMN m4_shadow_review_samples.encrypted_message IS
  'AES-256-GCM blob v2: version(2 byte ASCII "v1") || nonce(12) || ct+tag. AAD domain-tag a3s-m4-shadow-sample-aad-v1, fields=(customer_ref, conversation_ref, sample_id) — sample_id lam MOI row AAD DUY NHAT.';

REVOKE ALL ON m4_shadow_review_samples FROM PUBLIC;
REVOKE ALL ON m4_shadow_review_samples FROM alpha3s_app;  -- xem ghi chu default-privileges o tren; grant hep lai o §6g

-- REV2 (T1-03): bat bien ground truth sau seal — trigger chay bat ke role nao thuc hien UPDATE
-- (kho reviewer_api sua labeled_slots/label_status SAU KHI batch da sealed, dung DB-level, khong
-- phai app convention). PHAI la SECURITY DEFINER: trigger chay BANG QUYEN CUA ROLE DANG UPDATE
-- (invoker) neu khong khai bao SECURITY DEFINER — role do (vd reviewer_api) KHONG co SELECT tren
-- m4_selection_batches (khong can cho cong viec binh thuong cua no), nen ban khong-SECURITY-
-- DEFINER se lam TAT CA UPDATE that bai vi ban than trigger khong doc duoc batch de kiem tra
-- sealed_at — phat hien qua evidence thuc te (permissions_test.py), khong phai chi ly thuyet.
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
-- Trigger EXECUTE ham nay tu dong, KHONG can GRANT EXECUTE tuong minh cho tung role — Postgres
-- luon cho phep trigger tu goi ham cua no bat ke quyen EXECUTE cua caller UPDATE.

DROP TRIGGER IF EXISTS m4_stage0p_label_immutable_after_seal ON m4_shadow_review_samples;
CREATE TRIGGER m4_stage0p_label_immutable_after_seal
  BEFORE UPDATE ON m4_shadow_review_samples
  FOR EACH ROW EXECUTE FUNCTION m4_stage0p_block_label_after_seal();

-- ===========================================================================
-- 5a. Ham SECURITY DEFINER — duong doc noi dung `messages` DUY NHAT, phan trang 1-row
--     (REV2 T1-01/T1-02, thay the m4_stage0p_fetch_batch_content cu — HAM CU DA XOA, KHONG
--     con o migration nay: no fetch NGUYEN CA BATCH truoc khi kiem tra control, vi pham
--     "kiem tra control TRUOC khi doc plaintext" va "khong materialize toan batch").
-- ===========================================================================
-- Fence: pg_advisory_xact_lock(4013003) — CUNG lock key voi m4_stage0p_set_capture (§5b).
-- Ham nay PHAI duoc goi trong 1 transaction Python giu nguyen tu fetch->encrypt->insert (xem
-- app/services/pii/stage0p_sampling.py run_collector) de lock giu xuyen suot toan bo don vi.
-- Tra ve DUNG 1 row voi cot `status`:
--   'control_off'  — kill switch dang OFF, KHONG doc bat ky content nao (T1-01: kiem tra
--                    control TRUOC khi duoc phep doc plaintext).
--   'exhausted'    — het message hop le trong batch (cursor da toi cuoi).
--   'ok'           — co 1 message, da audit VA da tang captured_count (cung transaction).
CREATE OR REPLACE FUNCTION m4_stage0p_fetch_next_message(
  p_batch_id UUID,
  p_after_conversation_id BIGINT DEFAULT -1,
  p_after_message_id BIGINT DEFAULT -1
)
RETURNS TABLE(status TEXT, conversation_id BIGINT, message_id BIGINT, content TEXT,
              char_truncated BOOLEAN, created_at TIMESTAMPTZ)
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

  -- T1-01: doc control SAU KHI da giu lock — bat ke ai giu lock truoc phai hoan tat/rollback
  -- truoc, nen gia tri doc duoc o day LUON la gia tri MOI NHAT da commit. Khong doc content
  -- nao neu OFF.
  SELECT capture_enabled INTO v_enabled FROM public.m4_stage0p_control WHERE id = 1;
  IF v_enabled IS NOT TRUE THEN
    RETURN QUERY SELECT 'control_off'::TEXT, NULL::BIGINT, NULL::BIGINT, NULL::TEXT,
                        NULL::BOOLEAN, NULL::TIMESTAMPTZ;
    RETURN;
  END IF;

  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_next_message: batch_id khong ton tai';
  END IF;
  IF v_batch.status = 'closed' THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_next_message: batch da closed';
  END IF;
  IF v_batch.purpose_code <> 'P12_PII_DETECTOR_EVAL' THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_next_message: purpose_code khong khop';
  END IF;
  IF now() < v_batch.window_start OR now() > v_batch.window_end + interval '7 days' THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_next_message: batch ngoai cua so hop le';
  END IF;

  -- T1-02: total-batch enforcement BEN VUNG tai DB (khong chi counter Python) — chan tren
  -- selected_count * 20 (Cap B moi hoi thoai).
  v_cap := v_batch.selected_count * 20;
  IF v_batch.captured_count >= v_cap THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_next_message: batch % da dat tran captured_count (%/%)',
      p_batch_id, v_batch.captured_count, v_cap;
  END IF;

  -- Cap B (F-M4-0P-03B): toi da 20 tin khach/hoi thoai. Cursor (conversation_id, id) — id la
  -- BIGSERIAL tang don dieu theo thu tu chen, nen tuong duong thu tu thoi gian trong pham vi
  -- 1 hoi thoai (khong co du lieu backdate trong schema nay).
  SELECT ranked.conversation_id, ranked.id AS message_id, ranked.content, ranked.created_at
    INTO v_row
    FROM (
      SELECT m.conversation_id, m.id, m.content, m.created_at,
             ROW_NUMBER() OVER (PARTITION BY m.conversation_id ORDER BY m.id ASC) AS rn
      FROM public.messages m
      WHERE m.role = 'customer'
        AND m.conversation_id = ANY (v_batch.locked_conversation_ids)
    ) ranked
    WHERE ranked.rn <= 20
      AND (ranked.conversation_id, ranked.id) > (p_after_conversation_id, p_after_message_id)
    ORDER BY ranked.conversation_id, ranked.id
    LIMIT 1;

  IF NOT FOUND THEN
    RETURN QUERY SELECT 'exhausted'::TEXT, NULL::BIGINT, NULL::BIGINT, NULL::TEXT,
                        NULL::BOOLEAN, NULL::TIMESTAMPTZ;
    RETURN;
  END IF;

  -- Audit TRUOC khi tra content (audit that bai -> toan bo statement/goi ham rollback, khong
  -- content nao roi khoi ham).
  INSERT INTO public.audit_log (actor_type, actor_ref, action, entity_type, entity_id, after)
  VALUES ('system', 'm4_stage0p_collector', 'm4_message_fetch', 'm4_selection_batch',
          p_batch_id::text,
          jsonb_build_object('conversation_id', v_row.conversation_id, 'message_id', v_row.message_id))
  RETURNING id INTO v_audit_id;

  -- "status" la ten trung voi cot OUT cua ham (RETURNS TABLE(status TEXT,...) tu dong tao 1
  -- bien PL/pgSQL ten "status") -> PHAI qualify bang alias b.status de tranh AmbiguousColumnError
  -- (loi thuc te bat duoc qua evidence script, khong phai chi ly thuyet).
  UPDATE public.m4_selection_batches AS b
    SET captured_count = b.captured_count + 1,
        status = CASE WHEN b.status = 'locked' THEN 'collecting' ELSE b.status END
    WHERE b.batch_id = p_batch_id;

  -- Cap ky tu NGAY TRONG SQL (T1-02: cap phai ap tai purpose-bound interface, truoc khi
  -- plaintext roi DB) — MAX_CHARS=2000. Cap byte UTF-8-safe van o tang Python (crypto.py) vi
  -- can lam viec voi bytes da encode truoc khi ma hoa.
  RETURN QUERY SELECT 'ok'::TEXT, v_row.conversation_id, v_row.message_id,
                      left(v_row.content, 2000), (char_length(v_row.content) > 2000),
                      v_row.created_at;
END;
$$;

DROP FUNCTION IF EXISTS m4_stage0p_fetch_batch_content(UUID);

ALTER FUNCTION m4_stage0p_fetch_next_message(UUID, BIGINT, BIGINT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_fetch_next_message(UUID, BIGINT, BIGINT) FROM PUBLIC;

-- ===========================================================================
-- 5b. Ham SECURITY DEFINER — doi kill switch, atomic voi validation + audit (REV2 T1-01/T1-05)
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
  -- CUNG lock key voi m4_stage0p_fetch_next_message — dam bao khong the co 1 sample commit
  -- SAU KHI 1 lenh set_capture(OFF) da commit (T1-01: "OFF commit tao ranh gioi").
  PERFORM pg_advisory_xact_lock(4013003);

  IF p_approval_ref IS NULL OR length(btrim(p_approval_ref)) = 0 THEN
    RAISE EXCEPTION 'm4_stage0p_set_capture: approval_ref khong duoc rong';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.staff_users WHERE id = p_actor_staff_id AND is_active = TRUE) THEN
    RAISE EXCEPTION 'm4_stage0p_set_capture: actor_staff_id khong ton tai hoac khong active';
  END IF;

  SELECT capture_enabled INTO v_before FROM public.m4_stage0p_control WHERE id = 1;

  UPDATE public.m4_stage0p_control
    SET capture_enabled = p_enabled,
        updated_at = now(),
        updated_by_note = 'actor_staff_id=' || p_actor_staff_id || ' approval_ref=' || p_approval_ref
    WHERE id = 1;

  -- Audit CUNG transaction voi UPDATE — that bai INSERT nay se rollback ca UPDATE (T1-05:
  -- khong con phu thuoc caller tu quan ly transaction/autocommit). reason = approval_ref, dung
  -- cung convention voi audit_log hien co (xem migration 015).
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
-- 5c. Ham SECURITY DEFINER — seal ground truth truoc khi cho phep predict (REV2 T1-03)
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_seal_labels(
  p_batch_id UUID,
  p_actor_staff_id BIGINT,
  p_labels_hash TEXT
)
RETURNS TABLE(sealed_hash TEXT, sample_count INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_unlabeled INT;
  v_count INT;
  v_audit_id BIGINT;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.staff_users WHERE id = p_actor_staff_id AND is_active = TRUE) THEN
    RAISE EXCEPTION 'm4_stage0p_seal_labels: actor_staff_id khong ton tai hoac khong active';
  END IF;
  IF p_labels_hash IS NULL OR length(btrim(p_labels_hash)) = 0 THEN
    RAISE EXCEPTION 'm4_stage0p_seal_labels: labels_hash khong duoc rong';
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

  UPDATE public.m4_selection_batches
    SET labels_sealed_at = now(), labels_sealed_by = p_actor_staff_id, labels_sealed_hash = p_labels_hash
    WHERE batch_id = p_batch_id;

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id, after)
  VALUES ('staff', p_actor_staff_id, 'm4_stage0p_seal_labels', 'm4_selection_batch',
          p_batch_id::text, jsonb_build_object('labels_sealed_hash', p_labels_hash, 'sample_count', v_count))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT p_labels_hash, v_count;
END;
$$;

ALTER FUNCTION m4_stage0p_seal_labels(UUID, BIGINT, TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_seal_labels(UUID, BIGINT, TEXT) FROM PUBLIC;

-- ===========================================================================
-- 5d. Ham SECURITY DEFINER — ghi prediction CHI qua day, kiem tra sealed atomic (REV2 T1-03)
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_write_predictions(
  p_batch_id UUID,
  p_predictions JSONB,   -- [{"sample_id": "...", "predicted_slots": [...]}]
  p_detector_version TEXT,
  p_evaluation_batch TEXT
)
RETURNS TABLE(updated_count INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_sealed TIMESTAMPTZ;
  v_updated INT := 0;
  v_audit_id BIGINT;
  v_item JSONB;
  v_sample_id UUID;
BEGIN
  SELECT labels_sealed_at INTO v_sealed FROM public.m4_selection_batches WHERE batch_id = p_batch_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: batch_id khong ton tai';
  END IF;
  IF v_sealed IS NULL THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: batch % chua sealed, khong duoc ghi prediction', p_batch_id;
  END IF;

  FOR v_item IN SELECT * FROM jsonb_array_elements(p_predictions)
  LOOP
    v_sample_id := (v_item->>'sample_id')::UUID;
    UPDATE public.m4_shadow_review_samples
      SET predicted_slots = v_item->'predicted_slots',
          detector_version = p_detector_version,
          evaluation_batch = p_evaluation_batch
      WHERE sample_id = v_sample_id AND selection_batch = p_batch_id;
    IF FOUND THEN
      v_updated := v_updated + 1;
    END IF;
  END LOOP;

  INSERT INTO public.audit_log (actor_type, actor_ref, action, entity_type, entity_id, after)
  VALUES ('system', 'm4_stage0p_prediction_writer', 'm4_stage0p_write_predictions',
          'm4_selection_batch', p_batch_id::text,
          jsonb_build_object('updated_count', v_updated, 'detector_version', p_detector_version,
                              'evaluation_batch', p_evaluation_batch))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_updated;
END;
$$;

ALTER FUNCTION m4_stage0p_write_predictions(UUID, JSONB, TEXT, TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_write_predictions(UUID, JSONB, TEXT, TEXT) FROM PUBLIC;

-- ===========================================================================
-- 5e. Ham SECURITY DEFINER — trang thai "eval xong" TACH BIET "prediction da ghi" (REV2 T1-06)
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_complete_evaluation(
  p_batch_id UUID,
  p_actor_staff_id BIGINT,
  p_report_hash TEXT
)
RETURNS TABLE(completed_at TIMESTAMPTZ)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_batch RECORD;
  v_unpredicted INT;
  v_audit_id BIGINT;
  v_now TIMESTAMPTZ := now();
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.staff_users WHERE id = p_actor_staff_id AND is_active = TRUE) THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: actor_staff_id khong ton tai hoac khong active';
  END IF;
  IF p_report_hash IS NULL OR length(btrim(p_report_hash)) = 0 THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: report_hash khong duoc rong';
  END IF;

  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: batch_id khong ton tai';
  END IF;
  IF v_batch.labels_sealed_at IS NULL THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: batch % chua sealed', p_batch_id;
  END IF;
  IF v_batch.evaluation_completed_at IS NOT NULL THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: batch % da eval-completed luc %',
      p_batch_id, v_batch.evaluation_completed_at;
  END IF;

  SELECT count(*) INTO v_unpredicted FROM public.m4_shadow_review_samples
    WHERE selection_batch = p_batch_id AND predicted_slots IS NULL;
  IF v_unpredicted > 0 THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: batch % con % sample chua co prediction',
      p_batch_id, v_unpredicted;
  END IF;

  UPDATE public.m4_selection_batches
    SET evaluation_completed_at = v_now, evaluation_completed_by = p_actor_staff_id,
        evaluation_report_hash = p_report_hash, status = 'closed'
    WHERE batch_id = p_batch_id;

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id, after)
  VALUES ('staff', p_actor_staff_id, 'm4_stage0p_complete_evaluation', 'm4_selection_batch',
          p_batch_id::text, jsonb_build_object('evaluation_report_hash', p_report_hash))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_now;
END;
$$;

ALTER FUNCTION m4_stage0p_complete_evaluation(UUID, BIGINT, TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_complete_evaluation(UUID, BIGINT, TEXT) FROM PUBLIC;

-- Quyen NOI BO can cho 5 ham hoat dong (chay boi alpha3s_m4_definer, khong phai caller)
GRANT SELECT ON public.messages TO alpha3s_m4_definer;
GRANT SELECT, UPDATE (captured_count, status) ON public.m4_selection_batches TO alpha3s_m4_definer;
GRANT UPDATE (labels_sealed_at, labels_sealed_by, labels_sealed_hash) ON public.m4_selection_batches
  TO alpha3s_m4_definer;
GRANT UPDATE (evaluation_completed_at, evaluation_completed_by, evaluation_report_hash)
  ON public.m4_selection_batches TO alpha3s_m4_definer;
GRANT SELECT, UPDATE (predicted_slots, detector_version, evaluation_batch)
  ON public.m4_shadow_review_samples TO alpha3s_m4_definer;
GRANT SELECT, UPDATE (capture_enabled, updated_at, updated_by_note) ON public.m4_stage0p_control
  TO alpha3s_m4_definer;
GRANT SELECT (id, is_active) ON public.staff_users TO alpha3s_m4_definer;
-- SELECT(id) can them vi ham dung "INSERT ... RETURNING id" — Postgres yeu cau SELECT tren
-- cot RETURNING, khong chi INSERT (de nham lan, xac nhan bang smoke test truoc do).
GRANT INSERT, UPDATE, SELECT (id) ON public.audit_log TO alpha3s_m4_definer;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_definer;

-- ===========================================================================
-- 6. 7 role least-privilege
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
  -- Role rieng cho is_pending_deletion() (F-M4-0P-02B) — CHI role nay duoc doc customers.psid
  -- trong pham vi M4; collector KHONG bao gio co quyen nay (khong trao PSID cho collector).
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_pending_checker') THEN
    CREATE ROLE alpha3s_m4_pending_checker NOLOGIN;
  END IF;
END $$;

-- 6a. collector: INSERT-only tren sample; SELECT metadata (KHONG messages, KHONG control truc
-- tiep — REV2: bo GRANT SELECT(capture_enabled) cu, control CHI doc duoc GIAN TIEP qua ham
-- fetch, khong bao gio truc tiep); EXECUTE ham fetch phan trang.
GRANT INSERT ON m4_shadow_review_samples TO alpha3s_m4_sample_collector;
GRANT SELECT (id, customer_id, created_at) ON orders TO alpha3s_m4_sample_collector;
GRANT SELECT (id, customer_id, created_at) ON conversations TO alpha3s_m4_sample_collector;
GRANT EXECUTE ON FUNCTION m4_stage0p_fetch_next_message(UUID, BIGINT, BIGINT) TO alpha3s_m4_sample_collector;
GRANT SELECT (batch_id) ON m4_selection_batches TO alpha3s_m4_sample_collector;
GRANT INSERT ON m4_selection_batches TO alpha3s_m4_sample_collector;
-- doc customers.psid CHI qua ham is_pending_deletion (chua dinh nghia — S1 buoc sau); tam thoi
-- KHONG grant SELECT psid truc tiep cho collector (F-M4-0P-02B: khong trao PSID cho collector).

-- 6b. reviewer-api: SELECT/UPDATE nhan TRUOC seal — dung boi tien trinh API noi bo, KHONG con
-- nguoi cam. REV2 (T1-03): them EXECUTE seal_labels — sau khi goi, trigger §4 chan moi sua doi
-- them tren labeled_slots/label_status (bat ke role nao, ke ca role nay).
GRANT SELECT (sample_id, encrypted_message, canonical_text_len, normalization_version,
              customer_ref, conversation_ref, captured_at, label_status, selection_batch,
              labeled_slots)
  ON m4_shadow_review_samples TO alpha3s_m4_sample_reviewer_api;
GRANT UPDATE (labeled_slots, label_status) ON m4_shadow_review_samples TO alpha3s_m4_sample_reviewer_api;
GRANT EXECUTE ON FUNCTION m4_stage0p_seal_labels(UUID, BIGINT, TEXT) TO alpha3s_m4_sample_reviewer_api;
GRANT INSERT ON audit_log TO alpha3s_m4_sample_reviewer_api;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_sample_reviewer_api;

-- 6c. evaluator: SELECT chi cot nhan/du doan + metadata can validate, KHONG noi dung/dinh danh.
-- REV2 (T1-06): them EXECUTE complete_evaluation.
GRANT SELECT (sample_id, label_status, labeled_slots, predicted_slots, canonical_text_len,
              normalization_version, detector_version, evaluation_batch, selection_batch, truncated)
  ON m4_shadow_review_samples TO alpha3s_m4_sample_evaluator;
GRANT SELECT (batch_id, labels_sealed_at, labels_sealed_hash, evaluation_completed_at)
  ON m4_selection_batches TO alpha3s_m4_sample_evaluator;
GRANT EXECUTE ON FUNCTION m4_stage0p_complete_evaluation(UUID, BIGINT, TEXT) TO alpha3s_m4_sample_evaluator;
GRANT INSERT ON audit_log TO alpha3s_m4_sample_evaluator;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_sample_evaluator;

-- 6d. prediction_writer: REV2 (T1-03) — KHONG con UPDATE truc tiep cot du doan; CHI EXECUTE
-- write_predictions (kiem tra sealed atomic ben trong ham). Van can SELECT encrypted_message +
-- customer_ref/conversation_ref de chay detector noi bo va tinh lai AAD giai ma
-- (decrypt_sample_value bat buoc ca 3 field).
GRANT SELECT (sample_id, encrypted_message, customer_ref, conversation_ref, canonical_text_len,
              normalization_version, label_status, selection_batch, predicted_slots)
  ON m4_shadow_review_samples TO alpha3s_m4_prediction_writer;
GRANT EXECUTE ON FUNCTION m4_stage0p_write_predictions(UUID, JSONB, TEXT, TEXT) TO alpha3s_m4_prediction_writer;

-- 6e. purge: DELETE + SELECT chi cot can cho WHERE (Postgres yeu cau SELECT tren cot dung trong
-- dieu kien DELETE). REV2 (T1-06): them SELECT tren m4_selection_batches.evaluation_completed_at
-- vi purge_expired() gio JOIN sang batch de xac dinh "eval xong" (xem stage0p_sampling.py).
GRANT SELECT (customer_ref, expires_at, sample_id, selection_batch) ON m4_shadow_review_samples
  TO alpha3s_m4_sample_purge;
GRANT DELETE ON m4_shadow_review_samples TO alpha3s_m4_sample_purge;
GRANT SELECT (batch_id, evaluation_completed_at) ON m4_selection_batches TO alpha3s_m4_sample_purge;

-- 6f. control_plane: REV2 (T1-01/T1-05) — KHONG con UPDATE truc tiep tren m4_stage0p_control;
-- CHI EXECUTE set_capture (fence + validate + audit atomic ben trong ham). Giu SELECT de van
-- hanh xem trang thai hien tai (read-only, khong phai nguon tham quyen).
GRANT SELECT (capture_enabled, updated_at) ON m4_stage0p_control TO alpha3s_m4_control_plane;
GRANT EXECUTE ON FUNCTION m4_stage0p_set_capture(BOOLEAN, BIGINT, TEXT) TO alpha3s_m4_control_plane;

-- 6h. pending_checker: CHI role duoc doc customers.psid trong pham vi M4 (F-M4-0P-02B) — dung
-- boi is_pending_deletion() rieng biet voi collector's own credential.
GRANT SELECT (id, psid) ON customers TO alpha3s_m4_pending_checker;
GRANT INSERT ON audit_log TO alpha3s_m4_pending_checker;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_pending_checker;

-- 6g. DSR: process_deletion() can DELETE sample theo customer_ref — dung QUA runtime alpha3s_app
-- (da co CRUD chung tu 024) nhung XOA sample KHONG can UPDATE — them DELETE tuong minh, van
-- KHONG SELECT/UPDATE noi dung (giu nguyen nguyen tac it quyen nhat cho runtime).
GRANT DELETE ON m4_shadow_review_samples TO alpha3s_app;
GRANT SELECT (customer_ref) ON m4_shadow_review_samples TO alpha3s_app;

-- runtime app + vendor-path: KHONG quyen nao khac ngoai DSR delete o tren (vendor path: khong gi ca)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_vendor_path') THEN
    REVOKE ALL ON m4_shadow_review_samples, m4_selection_batches, m4_stage0p_control
      FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_fetch_next_message(UUID, BIGINT, BIGINT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_set_capture(BOOLEAN, BIGINT, TEXT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_seal_labels(UUID, BIGINT, TEXT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_write_predictions(UUID, JSONB, TEXT, TEXT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_complete_evaluation(UUID, BIGINT, TEXT) FROM alpha3s_vendor_path;
  END IF;
END $$;

-- ===========================================================================
-- 7. Postcondition fail-closed — chung minh dung F-M4-0P-01B/02B/03B + REV2 T1-01..06 thiet ke
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
  IF (SELECT count(*) FROM m4_stage0p_control) <> 1 THEN
    problems := problems || ' control_not_singleton'; END IF;
  IF (SELECT capture_enabled FROM m4_stage0p_control WHERE id=1) IS DISTINCT FROM FALSE THEN
    problems := problems || ' control_not_default_off'; END IF;

  -- F-M4-0P-02B: definer role phai NON-SUPERUSER (bat ke migration-owner co superuser hay khong)
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_m4_definer'
                 AND NOT rolsuper AND NOT rolcreaterole AND NOT rolcreatedb) THEN
    problems := problems || ' definer_role_privileged'; END IF;

  -- REV2: ca 6 ham SECURITY DEFINER (5 ham nghiep vu + 1 trigger function) phai cung owner,
  -- cung khoa search_path, cung khong PUBLIC EXECUTE
  IF EXISTS (
    SELECT 1 FROM pg_proc WHERE proname IN (
      'm4_stage0p_fetch_next_message','m4_stage0p_set_capture','m4_stage0p_seal_labels',
      'm4_stage0p_write_predictions','m4_stage0p_complete_evaluation',
      'm4_stage0p_block_label_after_seal')
      AND (proowner::regrole::text <> 'alpha3s_m4_definer' OR prosecdef IS NOT TRUE
           OR proconfig IS NULL
           OR NOT EXISTS (SELECT 1 FROM unnest(proconfig) c WHERE c LIKE 'search_path=%'))
  ) THEN
    problems := problems || ' definer_function_hardening_incomplete'; END IF;

  IF has_function_privilege('public', 'm4_stage0p_fetch_next_message(uuid,bigint,bigint)', 'EXECUTE') THEN
    problems := problems || ' fetch_function_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_set_capture(boolean,bigint,text)', 'EXECUTE') THEN
    problems := problems || ' set_capture_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_seal_labels(uuid,bigint,text)', 'EXECUTE') THEN
    problems := problems || ' seal_labels_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_write_predictions(uuid,jsonb,text,text)', 'EXECUTE') THEN
    problems := problems || ' write_predictions_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_complete_evaluation(uuid,bigint,text)', 'EXECUTE') THEN
    problems := problems || ' complete_evaluation_execute_public'; END IF;

  IF NOT has_function_privilege('alpha3s_m4_sample_collector',
                                'm4_stage0p_fetch_next_message(uuid,bigint,bigint)', 'EXECUTE') THEN
    problems := problems || ' collector_no_execute_fetch'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_control_plane',
                                'm4_stage0p_set_capture(boolean,bigint,text)', 'EXECUTE') THEN
    problems := problems || ' control_plane_no_execute_set_capture'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_reviewer_api',
                                'm4_stage0p_seal_labels(uuid,bigint,text)', 'EXECUTE') THEN
    problems := problems || ' reviewer_no_execute_seal'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_prediction_writer',
                                'm4_stage0p_write_predictions(uuid,jsonb,text,text)', 'EXECUTE') THEN
    problems := problems || ' prediction_writer_no_execute_write'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_evaluator',
                                'm4_stage0p_complete_evaluation(uuid,bigint,text)', 'EXECUTE') THEN
    problems := problems || ' evaluator_no_execute_complete'; END IF;

  -- collector: INSERT sample OK, SELECT sample KHONG; KHONG con doc control truc tiep (REV2)
  IF NOT has_table_privilege('alpha3s_m4_sample_collector','m4_shadow_review_samples','INSERT') THEN
    problems := problems || ' collector_no_insert'; END IF;
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

  -- reviewer-api: KHONG duoc doc predicted_slots/detector_version (chong thien lech xac nhan)
  IF has_column_privilege('alpha3s_m4_sample_reviewer_api','m4_shadow_review_samples',
                          'predicted_slots','SELECT') THEN
    problems := problems || ' reviewer_can_see_prediction'; END IF;

  -- evaluator: KHONG duoc doc encrypted_message/customer_ref/conversation_ref
  IF has_column_privilege('alpha3s_m4_sample_evaluator','m4_shadow_review_samples',
                          'encrypted_message','SELECT') THEN
    problems := problems || ' evaluator_can_read_content'; END IF;
  IF has_column_privilege('alpha3s_m4_sample_evaluator','m4_shadow_review_samples',
                          'customer_ref','SELECT') THEN
    problems := problems || ' evaluator_can_read_customer_ref'; END IF;

  -- purge: DELETE OK, KHONG UPDATE, KHONG doc noi dung
  IF NOT has_table_privilege('alpha3s_m4_sample_purge','m4_shadow_review_samples','DELETE') THEN
    problems := problems || ' purge_no_delete'; END IF;
  IF has_table_privilege('alpha3s_m4_sample_purge','m4_shadow_review_samples','UPDATE') THEN
    problems := problems || ' purge_has_update'; END IF;
  IF has_column_privilege('alpha3s_m4_sample_purge','m4_shadow_review_samples',
                          'encrypted_message','SELECT') THEN
    problems := problems || ' purge_can_read_content'; END IF;

  -- REV2 T1-01/T1-05: KHONG role nao (ngoai definer) con UPDATE truc tiep tren control
  IF has_column_privilege('alpha3s_m4_control_plane','m4_stage0p_control',
                          'capture_enabled','UPDATE') THEN
    problems := problems || ' control_plane_has_direct_update'; END IF;
  IF has_column_privilege('alpha3s_m4_sample_collector','m4_stage0p_control',
                          'capture_enabled','UPDATE') THEN
    problems := problems || ' collector_can_update_control'; END IF;

  -- REV2 T1-03: KHONG role nao (ngoai definer) con UPDATE truc tiep tren prediction columns
  IF has_column_privilege('alpha3s_m4_prediction_writer','m4_shadow_review_samples',
                          'predicted_slots','UPDATE') THEN
    problems := problems || ' prediction_writer_has_direct_update'; END IF;

  -- runtime app: CHI DELETE + SELECT(customer_ref) tren sample cho DSR — khong hon
  IF has_table_privilege('alpha3s_app','m4_shadow_review_samples','INSERT') THEN
    problems := problems || ' app_can_insert_sample'; END IF;
  IF has_column_privilege('alpha3s_app','m4_shadow_review_samples','encrypted_message','SELECT') THEN
    problems := problems || ' app_can_read_content'; END IF;
  IF NOT has_table_privilege('alpha3s_app','m4_shadow_review_samples','DELETE') THEN
    problems := problems || ' app_no_dsr_delete'; END IF;

  -- vendor-path: hoan toan khong quyen (neu role ton tai)
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_vendor_path') THEN
    IF has_table_privilege('alpha3s_vendor_path','m4_shadow_review_samples','SELECT') THEN
      problems := problems || ' vendor_can_select_sample'; END IF;
    IF has_function_privilege('alpha3s_vendor_path',
                              'm4_stage0p_fetch_next_message(uuid,bigint,bigint)','EXECUTE') THEN
      problems := problems || ' vendor_can_execute_fetch'; END IF;
  END IF;

  -- PUBLIC: khong quyen nao tren ca 3 bang
  IF has_table_privilege('public','m4_shadow_review_samples','SELECT') THEN
    problems := problems || ' public_can_select_sample'; END IF;
  IF has_table_privilege('public','m4_selection_batches','SELECT') THEN
    problems := problems || ' public_can_select_batches'; END IF;
  IF has_table_privilege('public','m4_stage0p_control','SELECT') THEN
    problems := problems || ' public_can_select_control'; END IF;

  -- REV2: trigger bat bien label sau seal phai ton tai va dang enable
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'm4_stage0p_label_immutable_after_seal'
      AND tgrelid = 'public.m4_shadow_review_samples'::regclass AND tgenabled <> 'D'
  ) THEN
    problems := problems || ' label_immutable_trigger_missing_or_disabled'; END IF;

  -- REV2 T1-02: ciphertext CHECK constraint phai la 8030 (khong phai 8045 cu)
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'm4_sample_ciphertext_cap'
      AND pg_get_constraintdef(oid) LIKE '%<= 8030%'
  ) THEN
    problems := problems || ' ciphertext_cap_wrong_value'; END IF;

  IF problems <> '' THEN
    RAISE EXCEPTION '039 postcondition FAIL —%', problems; END IF;
END $$;
