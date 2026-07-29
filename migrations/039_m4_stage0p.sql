-- Migration 039: M4 Stage 0P schema — Trusted PII Path production-shadow governance
-- (A3S-PHASE1B-M4-SPEC-001 v1.1.0 §6/§7; A3S-PHASE1B-M4-STAGE-0P-DESIGN-ACCEPTANCE-VI accepted
-- head d2a63c5, package v4.0.0). Theo dung 5 finding CLOSED AT DESIGN LEVEL (F-M4-0P-01..05).
--
-- ⚠️ EXPAND-ONLY, dev/test scope theo CA Design Acceptance §4: duoc phep tao migration/role/
-- function tren branch M4 voi du lieu synthetic/test. KHONG duoc doc/copy production data,
-- KHONG cap role/credential production, KHONG dat control row ON, KHONG bat capture that.
--
-- 3 bang: m4_shadow_review_samples (sample zone, tach hoan toan pii_slots), m4_selection_batches
-- (khoa lua chon — chan collector tu do doc conversation_id), m4_stage0p_control (kill switch
-- DONG, doc tuoi moi lan — F-M4-0P-01B, KHONG dung settings static).
--
-- 6 role least-privilege: alpha3s_m4_sample_collector (INSERT-only + EXECUTE ham dinh nghia
-- duoi), alpha3s_m4_sample_reviewer_api (SELECT+UPDATE nhan, dung boi tien trinh API noi bo —
-- CHUA co con nguoi cam credential nay), alpha3s_m4_sample_evaluator (SELECT cot nhan/du doan,
-- KHONG doc noi dung), alpha3s_m4_prediction_writer (UPDATE cot du doan), alpha3s_m4_sample_purge
-- (DELETE + SELECT cot can), alpha3s_m4_control_plane (UPDATE control row, F-M4-0P-01B —
-- TACH khoi moi role khac, actor/approval_ref bat buoc qua audit rieng, KHONG dung updated_by
-- caller tu khai lam nguon tham quyen — CA yeu cau ro trong acceptance criteria muc 4).
--
-- Ham SECURITY DEFINER m4_stage0p_fetch_batch_content: owner LA ROLE RIENG non-superuser
-- alpha3s_m4_definer (KHONG dung role migration-owner cua ket noi hien tai — da xac nhan qua
-- kiem tra thuc te alpha3s la superuser trong docker dev image, sai voi gia dinh truoc do trong
-- governance package; role dinh nghia rieng la thiet ke DUNG bat ke migration-owner co superuser
-- hay khong, gioi han blast radius dung tinh than least-privilege).
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
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_control (
  id               SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  capture_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- KHONG dung cot nay lam nguon tham quyen — la dieu nay chi de tham khao nguoi van hanh xem
  -- nhanh; tham quyen THAT nam o audit_log (actor_staff_id + approval_ref) do
  -- app/services/pii/stage0p_control.py ghi qua alpha3s_m4_control_plane. Xem postcondition.
  updated_by_note  TEXT
);
INSERT INTO m4_stage0p_control (id, capture_enabled) VALUES (1, FALSE)
  ON CONFLICT (id) DO NOTHING;

COMMENT ON TABLE m4_stage0p_control IS
  'M4 Stage 0P kill switch DONG (F-M4-0P-01B) — doc tuoi bang SELECT truoc MOI don vi ghi, KHONG dung app-level settings static. Nguon tham quyen ON/OFF that: audit_log qua alpha3s_m4_control_plane, KHONG phai cot updated_by_note.';

REVOKE ALL ON m4_stage0p_control FROM PUBLIC;
-- QUAN TRONG: migration 024 co ALTER DEFAULT PRIVILEGES tu dong cap CRUD day du cho alpha3s_app
-- (runtime) tren MOI bang MOI trong schema public. Phai REVOKE tuong minh o day roi grant lai
-- hep — neu khong alpha3s_app se co SELECT/INSERT/UPDATE/DELETE ngam dinh tren bang nay, pha vo
-- thiet ke least-privilege (F-M4-0P-02B).
REVOKE ALL ON m4_stage0p_control FROM alpha3s_app;

-- ===========================================================================
-- 3. Bang m4_selection_batches — khoa lua chon (F-M4-0P-02A/02B). Chan collector tu do
--    truy van conversation_id: sau khi khoa, collector CHI biet batch_id.
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
  CONSTRAINT m4_batch_window_valid CHECK (window_end > window_start),
  CONSTRAINT m4_batch_count_valid CHECK (selected_count <= eligible_count AND selected_count <= 260)
);

COMMENT ON TABLE m4_selection_batches IS
  'M4 Stage 0P — khoa tap conversation_id da chon (F-M4-0P-02A). locked_conversation_ids CHI ham SECURITY DEFINER noi bo doc; collector KHONG co SELECT truc tiep tren cot nay.';

REVOKE ALL ON m4_selection_batches FROM PUBLIC;
REVOKE ALL ON m4_selection_batches FROM alpha3s_app;  -- xem ghi chu default-privileges o tren

-- ===========================================================================
-- 4. Bang m4_shadow_review_samples — sample zone (tach hoan toan pii_slots)
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
  -- F-M4-0P-03B: byte cap THAT enforce lai o DB boundary — 8000 (MAX_BYTES) + 29 (version 1 +
  -- nonce 12 + tag 16) = 8045. Khong phu thuoc 100% logic cat o tang Python.
  CONSTRAINT m4_sample_ciphertext_cap CHECK (octet_length(encrypted_message) <= 8045)
);

CREATE INDEX IF NOT EXISTS m4_sample_customer_idx ON m4_shadow_review_samples (customer_ref);
CREATE INDEX IF NOT EXISTS m4_sample_expires_idx ON m4_shadow_review_samples (expires_at);
CREATE INDEX IF NOT EXISTS m4_sample_batch_idx ON m4_shadow_review_samples (selection_batch);
CREATE INDEX IF NOT EXISTS m4_sample_label_status_idx ON m4_shadow_review_samples (label_status);

COMMENT ON TABLE m4_shadow_review_samples IS
  'M4 Stage 0P sample zone (P12_PII_DETECTOR_EVAL) — encrypted_message AES-256-GCM domain rieng (a3s-m4-shadow-sample-aad-v1, khac pii_slots). Retention: eval completed OR 45 ngay tu captured_at, tuy dieu kien nao truoc (RET-11). DSR: xoa truc tiep theo customer_ref, khong join conversations/messages (khong orphan) — xem app/services/data_deletion.py.';
COMMENT ON COLUMN m4_shadow_review_samples.encrypted_message IS
  'AES-256-GCM blob v2: version(1) || nonce(12) || ct+tag. AAD domain-tag a3s-m4-shadow-sample-aad-v1, fields=(customer_ref, conversation_ref, sample_id) — sample_id lam MOI row AAD DUY NHAT.';

REVOKE ALL ON m4_shadow_review_samples FROM PUBLIC;
REVOKE ALL ON m4_shadow_review_samples FROM alpha3s_app;  -- xem ghi chu default-privileges o tren; grant hep lai o §6g

-- ===========================================================================
-- 5. Ham SECURITY DEFINER — duong doc noi dung `messages` DUY NHAT (F-M4-0P-02B hardening)
-- ===========================================================================
-- Cap ap dung: Cap B (20 tin/hoi thoai) tu tham so; MAX_CHARS/MAX_BYTES ap o tang Python truoc
-- khi ma hoa (ham nay chi tra plaintext content cho collector trong tien trinh, KHONG luu).
-- Chi tra role='customer' (loai bot/agent). Validate status/window/purpose TRUOC khi tra row nao.
-- Audit trong CUNG statement (CTE) — audit that bai thi toan bo statement rollback, khong tra gi.
CREATE OR REPLACE FUNCTION m4_stage0p_fetch_batch_content(p_batch_id UUID)
RETURNS TABLE(conversation_id BIGINT, message_id BIGINT, content TEXT, created_at TIMESTAMPTZ)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_batch RECORD;
  v_audit_id BIGINT;
BEGIN
  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_batch_content: batch_id khong ton tai';
  END IF;
  IF v_batch.status <> 'locked' THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_batch_content: batch status khong hop le (%)', v_batch.status;
  END IF;
  IF v_batch.purpose_code <> 'P12_PII_DETECTOR_EVAL' THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_batch_content: purpose_code khong khop';
  END IF;
  -- chan replay batch ngoai cua so hop le (them 7 ngay dem cho lech gio job/lag)
  IF now() < v_batch.window_start OR now() > v_batch.window_end + interval '7 days' THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_batch_content: batch ngoai cua so hop le';
  END IF;

  -- Audit TRUOC (cung statement/transaction — audit that bai se lam statement fail, khong content
  -- nao duoc tra). INSERT ... RETURNING trong CTE dam bao thu tu.
  INSERT INTO public.audit_log (actor_type, actor_ref, action, entity_type, entity_id, after)
  VALUES ('system', 'm4_stage0p_collector', 'm4_batch_fetch', 'm4_selection_batch',
          p_batch_id::text, jsonb_build_object('row_count_pending', true))
  RETURNING id INTO v_audit_id;

  -- Cap B (F-M4-0P-03B): toi da 20 tin khach/hoi thoai, 20 tin DAU TIEN theo
  -- created_at ASC, id ASC (deterministic) — ap NGAY TRONG HAM, cang som cang
  -- it be mat rui ro giu noi dung du thua du chi tam thoi trong bo nho caller.
  RETURN QUERY
    SELECT ranked.conversation_id, ranked.id, ranked.content, ranked.created_at
    FROM (
      SELECT m.conversation_id, m.id, m.content, m.created_at,
             ROW_NUMBER() OVER (PARTITION BY m.conversation_id
                                ORDER BY m.created_at ASC, m.id ASC) AS rn
      FROM public.messages m
      WHERE m.role = 'customer'
        AND m.conversation_id = ANY (v_batch.locked_conversation_ids)
    ) ranked
    WHERE ranked.rn <= 20;

  -- cap nhat dem thuc te sau khi tra (dung cong thuc CAP B, van trong cung transaction)
  UPDATE public.audit_log SET after = jsonb_build_object('row_count', (
    SELECT count(*) FROM (
      SELECT ROW_NUMBER() OVER (PARTITION BY m.conversation_id
                                ORDER BY m.created_at ASC, m.id ASC) AS rn
      FROM public.messages m
      WHERE m.role = 'customer' AND m.conversation_id = ANY (v_batch.locked_conversation_ids)
    ) ranked WHERE ranked.rn <= 20))
    WHERE id = v_audit_id;
END;
$$;

ALTER FUNCTION m4_stage0p_fetch_batch_content(UUID) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_fetch_batch_content(UUID) FROM PUBLIC;

-- Quyen NOI BO can cho ham hoat dong (chay boi alpha3s_m4_definer, khong phai caller)
GRANT SELECT ON public.messages TO alpha3s_m4_definer;
GRANT SELECT ON public.m4_selection_batches TO alpha3s_m4_definer;
-- SELECT(id) can them vi ham dung "INSERT ... RETURNING id" — Postgres yeu cau SELECT tren
-- cot RETURNING, khong chi INSERT (de nham lan, xac nhan bang smoke test truoc do).
GRANT INSERT, UPDATE, SELECT (id) ON public.audit_log TO alpha3s_m4_definer;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_definer;

-- ===========================================================================
-- 6. 6 role least-privilege
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

-- 6a. collector: INSERT-only tren sample; SELECT metadata (KHONG messages); EXECUTE ham fetch.
GRANT INSERT ON m4_shadow_review_samples TO alpha3s_m4_sample_collector;
GRANT SELECT (id, customer_id, created_at) ON orders TO alpha3s_m4_sample_collector;
GRANT SELECT (id, customer_id, created_at) ON conversations TO alpha3s_m4_sample_collector;
GRANT EXECUTE ON FUNCTION m4_stage0p_fetch_batch_content(UUID) TO alpha3s_m4_sample_collector;
GRANT SELECT (batch_id) ON m4_selection_batches TO alpha3s_m4_sample_collector;
GRANT INSERT ON m4_selection_batches TO alpha3s_m4_sample_collector;
GRANT SELECT (capture_enabled) ON m4_stage0p_control TO alpha3s_m4_sample_collector;
-- doc customers.psid CHI qua ham is_pending_deletion (chua dinh nghia — S1 buoc sau); tam thoi
-- KHONG grant SELECT psid truc tiep cho collector (F-M4-0P-02B: khong trao PSID cho collector).

-- 6b. reviewer-api: SELECT/UPDATE nhan — dung boi tien trinh API noi bo, KHONG con nguoi cam.
GRANT SELECT (sample_id, encrypted_message, canonical_text_len, normalization_version,
              customer_ref, conversation_ref, captured_at, label_status, selection_batch)
  ON m4_shadow_review_samples TO alpha3s_m4_sample_reviewer_api;
GRANT UPDATE (labeled_slots, label_status) ON m4_shadow_review_samples TO alpha3s_m4_sample_reviewer_api;
GRANT INSERT ON audit_log TO alpha3s_m4_sample_reviewer_api;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_sample_reviewer_api;

-- 6c. evaluator: SELECT chi cot nhan/du doan + metadata can validate, KHONG noi dung/dinh danh.
GRANT SELECT (sample_id, label_status, labeled_slots, predicted_slots, canonical_text_len,
              normalization_version, detector_version, evaluation_batch, selection_batch, truncated)
  ON m4_shadow_review_samples TO alpha3s_m4_sample_evaluator;

-- 6d. prediction_writer: UPDATE chi cot du doan; SELECT encrypted_message de chay detector noi
-- bo. CAN customer_ref/conversation_ref de tinh lai AAD giai ma (decrypt_sample_value bat buoc
-- ca 3 field) — da co encrypted_message (= biet duoc plaintext sau giai ma) nen 2 cot dinh danh
-- indexed nay khong tang them muc lo lot dang ke, va la yeu cau ky thuat de hoat dong duoc.
GRANT SELECT (sample_id, encrypted_message, customer_ref, conversation_ref, canonical_text_len,
              normalization_version, label_status, selection_batch, predicted_slots)
  ON m4_shadow_review_samples TO alpha3s_m4_prediction_writer;
GRANT UPDATE (predicted_slots, detector_version, evaluation_batch)
  ON m4_shadow_review_samples TO alpha3s_m4_prediction_writer;

-- 6e. purge: DELETE + SELECT chi cot can cho WHERE (Postgres yeu cau SELECT tren cot dung trong
-- dieu kien DELETE).
GRANT SELECT (customer_ref, expires_at, sample_id) ON m4_shadow_review_samples TO alpha3s_m4_sample_purge;
GRANT DELETE ON m4_shadow_review_samples TO alpha3s_m4_sample_purge;

-- 6f. control_plane: role RIENG update control row (F-M4-0P-01B muc 4 acceptance criteria —
-- KHONG dung updated_by tu khai; tham quyen that o audit_log actor_staff_id/approval_ref).
GRANT SELECT, UPDATE (capture_enabled, updated_at, updated_by_note) ON m4_stage0p_control
  TO alpha3s_m4_control_plane;
GRANT INSERT ON audit_log TO alpha3s_m4_control_plane;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_control_plane;

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
    REVOKE EXECUTE ON FUNCTION m4_stage0p_fetch_batch_content(UUID) FROM alpha3s_vendor_path;
  END IF;
END $$;

-- ===========================================================================
-- 7. Postcondition fail-closed — chung minh dung F-M4-0P-01B/02B/03B thiet ke
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
  IF (SELECT proowner::regrole::text FROM pg_proc WHERE proname='m4_stage0p_fetch_batch_content')
     <> 'alpha3s_m4_definer' THEN
    problems := problems || ' function_owner_wrong'; END IF;
  IF (SELECT prosecdef FROM pg_proc WHERE proname='m4_stage0p_fetch_batch_content') IS NOT TRUE THEN
    problems := problems || ' function_not_security_definer'; END IF;
  -- search_path phai duoc khoa (proconfig chua entry search_path=...)
  IF NOT EXISTS (
    SELECT 1 FROM pg_proc WHERE proname='m4_stage0p_fetch_batch_content'
      AND proconfig IS NOT NULL
      AND EXISTS (SELECT 1 FROM unnest(proconfig) c WHERE c LIKE 'search_path=%')
  ) THEN
    problems := problems || ' search_path_not_locked'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_fetch_batch_content(uuid)', 'EXECUTE') THEN
    problems := problems || ' function_execute_public'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_collector',
                                'm4_stage0p_fetch_batch_content(uuid)', 'EXECUTE') THEN
    problems := problems || ' collector_no_execute'; END IF;

  -- collector: INSERT sample OK, SELECT sample KHONG (khong duoc doc lai da ghi)
  IF NOT has_table_privilege('alpha3s_m4_sample_collector','m4_shadow_review_samples','INSERT') THEN
    problems := problems || ' collector_no_insert'; END IF;
  IF has_table_privilege('alpha3s_m4_sample_collector','m4_shadow_review_samples','SELECT') THEN
    problems := problems || ' collector_can_select_sample'; END IF;
  IF has_table_privilege('alpha3s_m4_sample_collector','public.messages','SELECT') THEN
    problems := problems || ' collector_can_select_messages_directly'; END IF;
  IF has_column_privilege('alpha3s_m4_sample_collector','public.customers','psid','SELECT') THEN
    problems := problems || ' collector_can_read_psid'; END IF;
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

  -- control_plane: UPDATE capture_enabled OK; KHONG role nao khac duoc UPDATE control
  IF NOT has_column_privilege('alpha3s_m4_control_plane','m4_stage0p_control',
                              'capture_enabled','UPDATE') THEN
    problems := problems || ' control_plane_no_update'; END IF;
  IF has_column_privilege('alpha3s_m4_sample_collector','m4_stage0p_control',
                          'capture_enabled','UPDATE') THEN
    problems := problems || ' collector_can_update_control'; END IF;

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
                              'm4_stage0p_fetch_batch_content(uuid)','EXECUTE') THEN
      problems := problems || ' vendor_can_execute_fetch'; END IF;
  END IF;

  -- PUBLIC: khong quyen nao tren ca 3 bang
  IF has_table_privilege('public','m4_shadow_review_samples','SELECT') THEN
    problems := problems || ' public_can_select_sample'; END IF;
  IF has_table_privilege('public','m4_selection_batches','SELECT') THEN
    problems := problems || ' public_can_select_batches'; END IF;
  IF has_table_privilege('public','m4_stage0p_control','SELECT') THEN
    problems := problems || ' public_can_select_control'; END IF;

  IF problems <> '' THEN
    RAISE EXCEPTION '039 postcondition FAIL —%', problems; END IF;
END $$;
