-- Migration 039: M4 Stage 0P schema - Trusted PII Path production-shadow governance
-- (A3S-PHASE1B-M4-SPEC-001 v1.1.0 Â§6/Â§7; A3S-PHASE1B-M4-STAGE-0P-DESIGN-ACCEPTANCE-VI accepted
-- head d2a63c5, package v4.0.0). Theo dung 5 finding CLOSED AT DESIGN LEVEL (F-M4-0P-01..05).
--
-- REV 2 (Technical Correction #1, CA Technical Review #1 e10af661): sua 6 finding T1-01..T1-06.
-- REV 3 (Technical Correction #2, CA Technical Review #2 470d985): sua 6 finding T2-01..T2-06.
-- REV 4 (Technical Correction #3, CA Technical Review #3 4f76d2e): sua 6 finding T3-01..T3-06.
-- REV 5 (Technical Correction #4, CA Technical Review #4 6c5f0f1, doc
-- PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-4-VI): sua 5 finding P1 T4-01..T4-05.
-- REV 6 (Technical Correction #5, CA Technical Review #5 c7fdbaf, doc
-- PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-5-VI): sua 3 finding P1 + 1 P2 T5-01..T5-04. File nay
-- CHINH SUA TRUC TIEP (khong tao migration 040) vi 039 chua tung apply vao baseline da accept/
-- chia se.
-- REV 7 (Correction #6, CA Technical Review #6 62b47b7, doc
-- PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-6-VI): sua 3 P1 + 1 P2 T6-01..T6-04 - CA khong chap nhan
-- REV6 la du, chi ro 4 khoang cach cu the con lai:
--   T6-01: actor_session REV6 chi khoa boi backend_pid DON - PID CO THE bi tai su dung sau khi
--          backend cu chet (session moi vo tinh "ke thua" pin cu); khong co expiry/TTL; pin_secret
--          luu PLAINTEXT. Sua: them cot session_nonce (UUID ngau nhien pin_actor dat DONG THOI
--          vao row VA vao 1 GUC session-scoped cua chinh connection - backend MOI luon co GUC
--          rong nen phat hien duoc PID-tai-su-dung MA KHONG can doc pg_stat_activity.backend_start,
--          cot nay bi Postgres NULL hoa cho role khong dac quyen nhu alpha3s_m4_definer - phat
--          hien qua evidence thuc te, xem bug tu phat hien); them expires_at (TTL 15 phut, khong
--          con "pin vinh vien"); pin_secret chuyen sang pin_secret_hash (pgcrypto crypt()/gen_salt('bf'),
--          KHONG CON PLAINTEXT); them rate-limit (failed_attempts/locked_until, khoa 15 phut sau 5
--          lan sai); ham moi m4_stage0p_unpin_actor() (tu xoa session, "logout" tuong minh). Gioi
--          han con lai (khai bao minh bach): Stage 0P CHUA co tang HTTP auth/identity-provider that
--          - pin_secret van la 1 bespoke shared credential, khong phai binding tu authenticated
--          application principal that su; day la quyet dinh kien truc can CA/PO xac nhan truoc
--          activation (khong phai thu Dev tu dong o tang DB).
--   T6-02: record_sample REV6 chi kiem do dai/truncation HEURISTIC - ciphertext KHAC nhung CUNG do
--          dai van qua duoc. Sua: fetch_message_content TU TINH digest SHA-256 tren dung van ban
--          canonical (NFC-normalize + truncate 2 buoc GIONG HET logic Python _truncate(nfc(...)))
--          luc fetch, luu vao fetch_capability.fetched_canonical_digest; record_sample doi hoi
--          p_canonical_text_digest (Python tinh NGAY TRUOC luc encrypt, tren chinh van ban da
--          encrypt) khop CHINH XAC - chan duoc ciphertext-thay-the/canonical-length-khai-sai/
--          truncated-gia (digest sai la sai ngay, khong con "trong khoang hop ly"). Gioi han con
--          lai: DB van KHONG co khoa giai ma nen khong xac minh duoc ciphertext GIAI MA RA dung
--          plaintext do - digest chi chung minh caller SO HUU dung canonical text goc, ket hop AAD
--          (da co tu truoc) la rang buoc gan nhat co the dat duoc ma khong doi kien truc "plaintext
--          khong bao gio roi Python process".
--   T6-03: close_collection REV6 dung NGUONG TY LE (exclusion_gate, chua duoc PO duyet) de CHO PHEP
--          batch co permanent_failed di tiep - CA noi ro khong duoc dung de xuat chua duyet theo
--          huong "cho phep". Sua: BO HAN dung ty le cho permanent_failed - batch co BAT KY
--          permanent_failed nao (>0) deu RAISE INSUFFICIENT_DATA VO DIEU KIEN cho toi khi co PO
--          decision record that su (chinh sach danh dau ro capture_gate_policy = 'zero_tolerance_
--          pending_po_decision_v1', luu tren batch + dua vao hash chain). Them: tu choi dong corpus
--          RONG (0 candidate committed).
--   T6-04 (P2): normalization_registry REV6 la singleton (1 row, UPDATE tai cho) - van la 1 nguon
--          MUTABLE khong co lich su/immutable, va m4_selection_batches.normalization_version van
--          con DEFAULT 'nfc-v1' (nguon hardcode thu 2 tiem an khi INSERT khong chi dinh cot). Sua:
--          registry doi thanh bang APPEND-ONLY (PK=version, cot is_current - CHI is_current duoc
--          UPDATE, moi truong khac bat bien qua trigger guard, khong bao gio DELETE); ham moi
--          m4_stage0p_set_current_normalization_version(version, approval_ref) doi version hien
--          hanh (doi hoi pinned actor + quyen m4.stage0p.approve, ghi audit). Bo DEFAULT tren
--          m4_selection_batches.normalization_version + them FK toi registry(version) (khong con
--          insert duoc version khong ton tai/khong biet).
--
-- REV 8 (Correction #8, CA Technical Review #7 d05d9fb, doc
-- PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-7-VI): T6-03 CLOSED AT CODE-DESIGN LEVEL (khong sua lai).
-- Sua 2 P1 + 1 P2 T7-01..T7-03:
--   T7-01: session_nonce+TTL (REV7) chan duoc PID-tai-su-dung-sau-khi-chet, nhung CA chi ro
--          CHUA chan duoc 1 connection POOL tai su dung CHINH connection CON SONG cho 1 request/
--          actor KHAC — row/backend_pid/GUC nonce deu con nguyen, request sau "ke thua" pin cua
--          request truoc trong toi da 15 phut. Sua: require_pinned_actor TIEU THU (DELETE) row
--          pin ngay khi validate THANH CONG — 1 pin = dung duoc CHO DUNG 1 hanh dong nghiep vu
--          (consume-on-use). Vi PL/pgSQL khong co autonomous transaction (xem REV7 §3), DELETE
--          nay CHI thuc su COMMIT neu ca ham nghiep vu bao quanh THANH CONG toi cung — 1 hanh
--          dong THAT BAI (vi ly do khac) khong tieu thu pin, dung ngu nghia "retry hop le voi
--          CUNG pin" can co. Gioi han con lai (khai bao minh bach, CHUA dong duoc o tang DB don
--          thuan): pin da tao nhung CHUA TUNG duoc dung THANH CONG (vd bi ngat quang truoc khi
--          goi ham nghiep vu dau tien, hoac trUOc khi goi unpin_actor()) van con hieu luc cho toi
--          khi TTL het han hoac connection dong that su — day la khoang cach CA neu ro can tich
--          hop tang connection-pool that (pool checkin hook goi unpin_actor()) o giai doan
--          production-activation, ngoai kha nang 1 migration DB co the tu dong.
--   T7-02: record_sample REV7 doi hoi digest CHINH XAC cua canonical plaintext, nhung DB van
--          KHONG co khoa giai ma nen KHONG xac minh duoc ciphertext caller gui THAT SU giai ma ra
--          dung plaintext mang digest do — 1 caller da qua duoc fetch_message_content (biet dung
--          canonical text, co du AAD fields hop le) VAN co the gui 1 ciphertext hop le nhung khac
--          (vd tu encrypt lai voi nonce khac) ma DB khong phat hien duoc. CA chi ro KHONG duoc
--          them heuristic nua — hoac dong that su (DB tham gia encrypt trong 1 trusted boundary,
--          doi kien truc "plaintext khong bao gio roi Python process"), hoac trinh CA/PO 1
--          architecture decision. Round nay KHONG sua T7-02 bang code — xem §7 doc Correction #8
--          (architecture decision request, 2 phuong an + de xuat, cho CA/PO quyet dinh).
--   T7-03 (P2): write_predictions doc row is_current=true (registry TOAN CUC) lam authority cho
--          normalization_version — SAI neu registry doi SAU khi batch lock/capture nhung TRUOC
--          prediction (batch hop le theo version DA KHOA co the bi loai hang loat sai lech). Sua:
--          doc v_batch.normalization_version (da khoa tu luc lock_batch, FK dam bao luon ton tai)
--          thay vi doc lai "current" toan cuc — "current" gio CHI quyet dinh version cho batch
--          MOI. Python (run_prediction_writer) sua tuong tu. Them: pg_advisory_xact_lock serialize
--          m4_stage0p_set_current_normalization_version (chong race 2 giao dich doi version dong
--          thoi).
--
-- REV6 tom tat 4 sua doi (T5-01..04):
--   T5-01: CA chi ro pin_actor REV5 (T4-04) VAN co lo hong CUNG LOP voi T4-01 - GUC
--          alpha3s.m4_actor_staff_id la session variable THUONG, BAT KY session nao cung tu
--          set_config duoc bat ke co EXECUTE pin_actor hay khong (restrict EXECUTE tren pin_actor
--          khong bao ve duoc GUC). Sua: bang moi m4_stage0p_actor_session, khoa boi
--          pg_backend_pid() (Postgres tu cap cho CHINH session goi, khong the gia mao - khac han
--          GUC ma bat ky ai cung tu ghi duoc) thay vi set_config. Them: pin_actor REV4 chi kiem
--          staff active - CHUA kiem caller co DUNG LA staff do - sua them bang moi
--          m4_stage0p_actor_credentials (pin_secret rieng tung staff, cap ngoai luong qua
--          provisioning rieng) - pin_actor(staff_id, pin_secret) doi hoi secret khop.
--   T5-02: capability row T4-01 chi chung minh THU TU goi (da fetch dung message), CHUA chung
--          minh p_encrypted_message/p_canonical_text_len/p_truncated do caller truyen THAT SU
--          xuat phat tu noi dung da fetch. Sua: capability row them fetched_char_len/
--          fetched_char_truncated (DB tu tinh luc fetch); record_sample doi chieu
--          canonical_text_len <= fetched_char_len, truncated=true bat buoc neu DB da biet noi
--          dung goc vuot 2000 ky tu, VA sanity ciphertext byte-length so canonical_text_len (AEAD
--          overhead co dinh 30 byte). Rang buoc ve NOI DUNG ciphertext (chong "substituted-
--          ciphertext" cung do dai) VAN CON MO - DB khong co khoa giai ma (thiet ke co y, xem
--          Known Limitations).
--   T5-03: permanent_failed la trang thai terminal nhung close_collection KHONG kiem ty le -
--          batch co the dong du nhieu candidate that bai capture that su. Sua: close_collection
--          them dieu kien tu bang m4_stage0p_exclusion_gate (dung chung nguong voi T4-05,
--          permanent_failed/tong candidate); luu capture_excluded_count/
--          capture_permanent_failed_count tren batch row. mark_candidate_outcome them allowlist
--          cho p_reason (4 gia tri THAT dang dung trong stage0p_sampling.py, khong con free text).
--   T5-04 (P2): normalization version van hardcode O CA 2 NOI (DB literal + Python constant) -
--          khong phai 1 nguon that su. Sua: bang moi m4_stage0p_normalization_registry (singleton)
--          - write_predictions doc tu day thay hardcode; Python (lock_batch + prediction pre-
--          filter) cung doc tu day thay module constant.
--
-- âš ï¸ EXPAND-ONLY, dev/test scope theo CA Design Acceptance Â§4: duoc phep tao migration/role/
-- function tren branch M4 voi du lieu synthetic/test. KHONG duoc doc/copy production data,
-- KHONG cap role/credential production, KHONG dat control row ON, KHONG bat capture that.
--
-- REV5 tom tat 5 sua doi (T4-01..05):
--   T4-01: capability "token" REV4 la custom GUC (set_config/current_setting) - CA chi ro day
--          KHONG phai secret/privileged storage, caller co the tu set_config roi goi record_sample
--          doc lap. Sua: bang moi m4_stage0p_fetch_capability (khong GRANT cho bat ky role m4 nao)
--          - fetch_message_content INSERT 1 row (batch,conversation,message,txid_current()) khi
--          thanh cong; record_sample DELETE...RETURNING dung row do TRONG CUNG transaction (txid
--          khop) - day la bang chung DB-owned, khong the gia mao vi caller khong co INSERT/SELECT/
--          DELETE truc tiep tren bang nay va txid_current() khong the tu chon.
--   T4-02: "current normalization version" van la tham so caller truyen - caller co the khai gia
--          de ep moi row thanh "mismatch". Sua: XOA p_current_normalization_version - DB tu so
--          sanh voi hang so HARDCODE trong than ham (cung quy uoc voi MATCHING_RULE_VERSION/
--          AGGREGATION_VERSION da co trong complete_evaluation - phai khop
--          app/services/pii/stage0p_sampling.py:NORMALIZATION_VERSION, bump ca 2 noi khi doi).
--   T4-03: collector bo qua candidate khi fence timeout (continue) - het danh sach roi dong
--          collection du candidate do CHUA BAO GIO dat trang thai terminal nao. Sua: bang moi
--          m4_stage0p_capture_progress (1 row/candidate, seed 1 lan luc bat dau collector qua ham
--          moi seed_capture_progress) voi state machine 5 gia tri (pending/committed/excluded/
--          retryable_failed/permanent_failed, attempt_count). peek doc tu bang nay (khong con
--          cursor). record_sample chuyen committed TRONG CUNG transaction voi INSERT sample. Ham
--          moi mark_candidate_outcome chuyen retryable_failed/permanent_failed (fence timeout, toi
--          da 3 lan thu) hoac excluded (pending-deletion). close_collection TU CHOI neu con row
--          pending/retryable_failed - chi dong khi MOI candidate da terminal.
--   T4-04: p_actor_staff_id la tham so caller tu khai - 1 nguoi giu chung 1 role DB co the mao
--          danh BAT KY staff active nao. Sua: bo p_actor_staff_id khoi ca 5 ham (set_capture/
--          record_approval/revoke_approval/seal_labels/complete_evaluation) - actor phai duoc
--          "pin" TRUOC vao session qua ham moi m4_stage0p_pin_actor (session-scoped set_config,
--          EXECUTE chi cap cho role moi alpha3s_m4_actor_binder - tach biet moi role nghiep vu).
--          Ham noi bo m4_stage0p_require_pinned_actor(permission) doc actor da pin, kiem active +
--          kiem QUYEN CU THE trong bang moi m4_stage0p_staff_permissions
--          (m4.stage0p.approve/operate/review/evaluate - tach biet theo tung ham).
--   T4-05: nguong exclusion >50% REV4 la Dev tu chon, chua duoc duyet. Sua: bang moi
--          m4_stage0p_exclusion_gate (singleton, seed dung DUNG de xuat CA Review #4:
--          max_exclusion_rate=10%, min_non_excluded_conversations=200, gate_version danh dau ro
--          "CA-proposed, chua co PO decision record"). write_predictions doi ca 2 dieu kien tu
--          bang nay (khong hardcode); tra ve them non_excluded_conversation_count/gate_version.
--
-- 4+5 bang REV5: m4_shadow_review_samples, m4_selection_batches, m4_stage0p_control,
-- m4_stage0p_capture_approvals, m4_stage0p_capture_approval_revocations (khong doi cau truc REV4)
-- + 4 bang MOI: m4_stage0p_fetch_capability (T4-01), m4_stage0p_capture_progress (T4-03),
-- m4_stage0p_staff_permissions (T4-04), m4_stage0p_exclusion_gate (T4-05).
--
-- 9 role least-privilege (REV5 them alpha3s_m4_actor_binder - T4-04): alpha3s_m4_sample_collector
-- (them EXECUTE seed_capture_progress/mark_candidate_outcome; peek doi chu ky 1 tham so),
-- alpha3s_m4_sample_reviewer_api (seal_labels doi chu ky, khong con actor param),
-- alpha3s_m4_sample_evaluator (complete_evaluation doi chu ky), alpha3s_m4_prediction_writer
-- (write_predictions doi chu ky, bot 1 tham so), alpha3s_m4_sample_purge, alpha3s_m4_control_plane
-- (set_capture doi chu ky), alpha3s_m4_pending_checker, alpha3s_m4_approval_recorder
-- (record_approval/revoke_approval doi chu ky), alpha3s_m4_actor_binder (MOI - CHI EXECUTE
-- pin_actor).
--
-- Ham SECURITY DEFINER (owner alpha3s_m4_definer, non-superuser), REV5:
--   m4_stage0p_peek_next_candidate       - doi chu ky: (batch_id) - doc tu capture_progress (T4-03)
--   m4_stage0p_fetch_message_content     - doi: INSERT capability row thay set_config (T4-01)
--   m4_stage0p_seed_capture_progress     - MOI: seed toan bo candidate 1 lan (T4-03)
--   m4_stage0p_mark_candidate_outcome    - MOI: chuyen retryable/permanent_failed/excluded (T4-03)
--   m4_stage0p_close_collection          - them: tu choi neu con row pending/retryable (T4-03)
--   m4_stage0p_record_sample             - doi: doi chieu capability row (DELETE), khong con GUC (T4-01)
--   m4_stage0p_pin_actor                 - MOI: pin actor vao session (T4-04)
--   m4_stage0p_require_pinned_actor      - MOI (noi bo): doc actor da pin + kiem quyen (T4-04)
--   m4_stage0p_set_capture               - doi chu ky: bo p_actor_staff_id (T4-04)
--   m4_stage0p_seal_labels                - doi chu ky: bo p_actor_staff_id (T4-04)
--   m4_stage0p_fetch_sealed_message       - khong doi
--   m4_stage0p_write_predictions          - doi: bo p_current_normalization_version (T4-02); gate
--                                            tu bang exclusion_gate thay hardcode 50% (T4-05)
--   m4_stage0p_complete_evaluation        - doi chu ky: bo p_actor_staff_id (T4-04)
--   m4_stage0p_record_approval            - doi chu ky: bo p_actor_staff_id (T4-04)
--   m4_stage0p_revoke_approval            - doi chu ky: bo p_actor_staff_id (T4-04)
--   m4_stage0p_block_label_after_seal     - trigger, khong doi
--
-- Advisory lock key 4013003 (STAGE0P CONTROL FENCE) khong doi tu REV2/REV3/REV4.
--
-- transactional: true

-- ===========================================================================
-- 1. Role dinh nghia rieng cho SECURITY DEFINER function + pgcrypto
-- ===========================================================================
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_definer') THEN
    CREATE ROLE alpha3s_m4_definer NOLOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB;
  END IF;
END $$;

-- Bug tim thay REV6 (fresh-DB reset regression, khong phai T5 finding): "REVOKE ALL FROM PUBLIC"
-- tren schema public (migration 024) khien KHONG role m4 nao (ke ca definer) co USAGE tren
-- schema public tren 1 DB that su sach - moi ham SECURITY DEFINER m4 khong the duoc RESOLVE boi
-- caller (loi "function ... does not exist", khong phai loi quyen EXECUTE). Chua tung lo ra vi
-- dev lap chua tung reset DB tu dau thuc su. Cap USAGE tuong minh o day (schema-level, khong
-- thay the cho grant bang/ham rieng le da co).
GRANT USAGE ON SCHEMA public TO alpha3s_m4_definer;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ===========================================================================
-- 2. Bang m4_stage0p_control - kill switch DONG. Singleton row.
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
  'M4 Stage 0P kill switch DONG - doc tuoi bang SELECT truoc MOI don vi ghi. Doi CHI qua ham m4_stage0p_set_capture (fence advisory lock 4013003). Nguon tham quyen ON/OFF that: audit_log qua ham nay.';

REVOKE ALL ON m4_stage0p_control FROM PUBLIC;
REVOKE ALL ON m4_stage0p_control FROM alpha3s_app;

-- ===========================================================================
-- 2b. Bang m4_stage0p_capture_approvals - approval record cho phep bat capture (T2-05).
--     Bo cot `status` (T3-05) - row nay BAT BIEN 1 lan ghi qua m4_stage0p_record_approval. Thu
--     hoi la 1 SU KIEN rieng - xem m4_stage0p_capture_approval_revocations duoi day.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_capture_approvals (
  approval_ref      TEXT PRIMARY KEY,
  purpose_code      TEXT NOT NULL CHECK (purpose_code = 'P12_PII_DETECTOR_EVAL'),
  requested_enabled BOOLEAN NOT NULL,
  valid_from        TIMESTAMPTZ NOT NULL,
  valid_until       TIMESTAMPTZ NOT NULL,
  recorded_by       BIGINT NOT NULL REFERENCES staff_users(id),
  recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  note              TEXT,
  CONSTRAINT m4_approval_window_valid CHECK (valid_until > valid_from)
);

COMMENT ON TABLE m4_stage0p_capture_approvals IS
  'REV4 T3-05: approval record BAT BIEN (ghi qua m4_stage0p_record_approval, KHONG con status column). Thu hoi la 1 row rieng trong m4_stage0p_capture_approval_revocations. m4_stage0p_set_capture(ON) doi chieu CA HAI bang.';

REVOKE ALL ON m4_stage0p_capture_approvals FROM PUBLIC;
REVOKE ALL ON m4_stage0p_capture_approvals FROM alpha3s_app;

-- ===========================================================================
-- 2c. Bang m4_stage0p_capture_approval_revocations - revocation event RIENG, tach biet approval
--     record goc (immutable). append-only, 1 revocation/approval_ref (PK).
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_capture_approval_revocations (
  approval_ref TEXT PRIMARY KEY REFERENCES m4_stage0p_capture_approvals(approval_ref),
  revoked_by   BIGINT NOT NULL REFERENCES staff_users(id),
  revoked_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  reason       TEXT NOT NULL
);

COMMENT ON TABLE m4_stage0p_capture_approval_revocations IS
  'REV4 T3-05: 1 row = 1 approval_ref bi thu hoi vinh vien (PK ngan thu hoi lap). Ghi qua m4_stage0p_revoke_approval.';

REVOKE ALL ON m4_stage0p_capture_approval_revocations FROM PUBLIC;
REVOKE ALL ON m4_stage0p_capture_approval_revocations FROM alpha3s_app;

-- ===========================================================================
-- 2c2. Bang m4_stage0p_normalization_approvals / _revocations - REV9 T8-03 (MOI). CA chi ro
--      approval_ref cua set_current_normalization_version (T6-04) chi kiem "khong rong" - 1 actor
--      co quyen co the truyen chuoi tuy y, registry row + audit log sau do TRONG GIONG nhu da co
--      approval that. Sua: bang approval THAT rieng cho normalization (KHONG tai dien giai capture-
--      ON approval — bang/ham hoan toan tach biet), moi row RIENG cho 1 version cu the
--      (requested_version) — 1 approval CHI hop le de doi sang DUNG version do, khong the dung lai
--      cho version khac. Cung mau immutable-record + revocation-event-rieng nhu capture approvals
--      (T3-05).
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_normalization_approvals (
  approval_ref      TEXT PRIMARY KEY,
  requested_version TEXT NOT NULL,
  valid_from        TIMESTAMPTZ NOT NULL,
  valid_until       TIMESTAMPTZ NOT NULL,
  recorded_by       BIGINT NOT NULL REFERENCES staff_users(id),
  recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  note              TEXT,
  CONSTRAINT m4_norm_approval_window_valid CHECK (valid_until > valid_from)
);

COMMENT ON TABLE m4_stage0p_normalization_approvals IS
  'REV9 T8-03: approval record BAT BIEN rieng cho normalization version change (KHONG tai dien giai capture-ON approval — bang/hanh dong hoan toan tach biet). 1 row chi hop le cho DUNG requested_version cua no. Ghi qua m4_stage0p_record_normalization_approval.';

REVOKE ALL ON m4_stage0p_normalization_approvals FROM PUBLIC;
REVOKE ALL ON m4_stage0p_normalization_approvals FROM alpha3s_app;

CREATE TABLE IF NOT EXISTS m4_stage0p_normalization_approval_revocations (
  approval_ref TEXT PRIMARY KEY REFERENCES m4_stage0p_normalization_approvals(approval_ref),
  revoked_by   BIGINT NOT NULL REFERENCES staff_users(id),
  revoked_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  reason       TEXT NOT NULL
);

COMMENT ON TABLE m4_stage0p_normalization_approval_revocations IS
  'REV9 T8-03: 1 row = 1 approval_ref (normalization) bi thu hoi vinh vien (PK ngan thu hoi lap). Ghi qua m4_stage0p_revoke_normalization_approval.';

REVOKE ALL ON m4_stage0p_normalization_approval_revocations FROM PUBLIC;
REVOKE ALL ON m4_stage0p_normalization_approval_revocations FROM alpha3s_app;

-- ===========================================================================
-- 2d. Bang m4_stage0p_staff_permissions - REV5 T4-04 (MOI): quyen CU THE tren tung staff, tach
--     biet theo hanh dong (chong 1 role DB dung chung mao danh BAT KY staff active nao - CA yeu
--     cau ro "approval recorder va control operator phai la principals/permissions tach biet").
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_staff_permissions (
  staff_id    BIGINT NOT NULL REFERENCES staff_users(id),
  permission  TEXT NOT NULL CHECK (permission IN (
                'm4.stage0p.approve', 'm4.stage0p.operate', 'm4.stage0p.review', 'm4.stage0p.evaluate')),
  granted_by  BIGINT NOT NULL REFERENCES staff_users(id),
  granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (staff_id, permission)
);

COMMENT ON TABLE m4_stage0p_staff_permissions IS
  'REV5 T4-04: quyen Stage 0P cu the theo staff - doi chieu boi m4_stage0p_require_pinned_actor SAU khi actor da pin (m4_stage0p_pin_actor). KHONG co role m4 nao duoc GRANT truc tiep tren bang nay (chi doc noi bo qua ham).';

REVOKE ALL ON m4_stage0p_staff_permissions FROM PUBLIC;
REVOKE ALL ON m4_stage0p_staff_permissions FROM alpha3s_app;

-- ===========================================================================
-- 2e. Bang m4_stage0p_exclusion_gate - REV5 T4-05 (MOI): nguong loai-tru CU THE, co the doi qua
--     migration/quyet dinh moi (khong hardcode trong than ham). Seed DUNG de xuat CA Technical
--     Review #4 (F-M4-0P-T4-05) - CHUA co PO decision record chinh thuc, ap dung nhu technical
--     default fail-closed cho Stage 0P dau tien.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_exclusion_gate (
  id                              SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  max_exclusion_rate              NUMERIC NOT NULL CHECK (max_exclusion_rate > 0 AND max_exclusion_rate <= 1),
  min_non_excluded_conversations  INT NOT NULL CHECK (min_non_excluded_conversations >= 0),
  gate_version                    TEXT NOT NULL,
  note                            TEXT,
  set_at                          TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO m4_stage0p_exclusion_gate
  (id, max_exclusion_rate, min_non_excluded_conversations, gate_version, note)
VALUES (1, 0.10, 200, 'ca-review-4-proposed-v1',
        'De xuat CA Technical Review #4 (F-M4-0P-T4-05) - CHUA co PO decision record chinh thuc; ap dung nhu technical default fail-closed cho Stage 0P dau tien, ra soat lai truoc activation')
ON CONFLICT (id) DO NOTHING;

COMMENT ON TABLE m4_stage0p_exclusion_gate IS
  'REV5 T4-05: nguong exclusion CU THE (khong hardcode trong ham) - doi qua migration/quyet dinh PO/CA moi, khong qua tham so caller.';

REVOKE ALL ON m4_stage0p_exclusion_gate FROM PUBLIC;
REVOKE ALL ON m4_stage0p_exclusion_gate FROM alpha3s_app;

-- ===========================================================================
-- 2f. Bang m4_stage0p_actor_credentials / m4_stage0p_actor_session - REV6 T5-01 (MOI).
--     actor_credentials: pin_secret RIENG tung staff (cap ngoai luong qua provisioning rieng,
--     KHONG qua pin_actor) - pin_actor doi hoi secret khop truoc khi pin, chan "binder tu chon
--     tuy y bat ky staff active nao". actor_session: khoa boi pg_backend_pid() - gia tri Postgres
--     TU CAP cho CHINH session dang goi, KHONG the gia mao (khac han custom GUC REV5 ma BAT KY
--     session nao cung tu set_config duoc bat ke co EXECUTE pin_actor hay khong). KHONG GRANT ca
--     2 bang nay cho role m4 nao - chi definer doc/ghi (chay ben trong ham).
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_actor_credentials (
  staff_id         BIGINT PRIMARY KEY REFERENCES staff_users(id),
  -- REV7 T6-01: HASH (pgcrypto crypt()/gen_salt('bf')) - KHONG CON PLAINTEXT (giong quy uoc
  -- staff_users.password_hash da co san trong he thong).
  pin_secret_hash  TEXT NOT NULL,
  failed_attempts  INT NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
  locked_until     TIMESTAMPTZ,
  provisioned_by   BIGINT NOT NULL REFERENCES staff_users(id),
  provisioned_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE m4_stage0p_actor_credentials IS
  'REV7 T6-01: pin_secret_hash (khong con plaintext) rieng tung staff - provisioning THAT (ai tao secret, phat cho staff bang kenh nao) la quyet dinh van hanh thuoc giai doan production-activation, ngoai pham vi Stage 0P dev/test. failed_attempts/locked_until: rate-limit chong brute-force. KHONG GRANT cho role m4 nao.';

REVOKE ALL ON m4_stage0p_actor_credentials FROM PUBLIC;
REVOKE ALL ON m4_stage0p_actor_credentials FROM alpha3s_app;

CREATE TABLE IF NOT EXISTS m4_stage0p_actor_session (
  backend_pid    INT PRIMARY KEY,
  -- REV7 T6-01: UUID ngau nhien (gen_random_uuid()) sinh boi CHINH pin_actor, dat DONG THOI vao
  -- 1) row nay VA 2) GUC session-scoped (set_config(...,false), KHONG phai LOCAL) cua CHINH
  -- connection dang goi. Khac han GUC REV5 (T5-01) — nonce nay KHONG BAO GIO mang DANH TINH actor
  -- (chi la 1 gia tri ngau nhien doi chung), va KHONG bao gio duoc tra ve cho caller/SELECT duoc
  -- tu bang (khong GRANT cho role nao) nen khong the bi "doan" hay doc lai tu 1 session khac.
  -- 1 backend MOI (du OS co the cap lai CHINH so PID cu cho 1 ket noi hoan toan moi sau khi
  -- backend cu chet) LUON bat dau voi GUC tuy chinh RONG — session_nonce so khop that bai ngay,
  -- phat hien duoc PID-reuse-sau-khi-chet MA KHONG can doc pg_stat_activity (cot nhay cam nhu
  -- backend_start bi NULL hoa cho role khong dac quyen — xem bug tu phat hien trong Correction #6).
  session_nonce  UUID NOT NULL,
  staff_id       BIGINT NOT NULL REFERENCES staff_users(id),
  pinned_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- REV7 T6-01: TTL bat buoc - khong con "pin vinh vien" (chong connection-pool tai su dung pin
  -- cu cho 1 request/nguoi dung khac).
  expires_at     TIMESTAMPTZ NOT NULL
);

COMMENT ON TABLE m4_stage0p_actor_session IS
  'REV7 T6-01: actor da pin cho 1 session, khoa boi (backend_pid, session_nonce) - session_nonce la UUID ngau nhien dat dong thoi vao row VA vao 1 GUC session-scoped cua chinh connection do pin_actor, chi require_pinned_actor tren CHINH connection do moi doi chieu khop duoc (khong ai doc lai tu ben ngoai) - phat hien PID tai su dung sau khi backend cu chet (backend moi luon co GUC rong). expires_at bat buoc - pin tu dong het han. KHONG GRANT cho role m4 nao.';

REVOKE ALL ON m4_stage0p_actor_session FROM PUBLIC;
REVOKE ALL ON m4_stage0p_actor_session FROM alpha3s_app;

-- ===========================================================================
-- 2g. Bang m4_stage0p_normalization_registry - REV6 T5-04 (P2), REV7 T6-04: doi tu singleton
--     MUTABLE (1 row, UPDATE tai cho - CA chi ro day van la 1 nguon hardcode "mem" khong co lich
--     su/immutable) sang APPEND-ONLY (PK=version, cot is_current la DUY NHAT duoc phep UPDATE qua
--     trigger guard, khong bao gio DELETE). write_predictions VA Python (lock_batch, pre-filter
--     prediction writer) deu doc row co is_current=true. Doi version qua ham
--     m4_stage0p_set_current_normalization_version (doi hoi pinned actor + quyen
--     m4.stage0p.approve, ghi audit) - khong con UPDATE truc tiep.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_normalization_registry (
  version       TEXT PRIMARY KEY,
  is_current    BOOLEAN NOT NULL DEFAULT FALSE,
  -- ON DELETE SET NULL: day la cot audit-trail (ai duyet), khong phai bat bien nghiep vu — registry
  -- entry (lich su version) van PHAI ton tai vinh vien (append-only) du staff duyet co bi xoa sau
  -- do (vd offboard); khong nen de 1 FK audit chan viec xoa staff_users.
  approved_by   BIGINT REFERENCES staff_users(id) ON DELETE SET NULL,
  approval_ref  TEXT,
  effective_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS m4_normreg_one_current
  ON m4_stage0p_normalization_registry ((is_current))
  WHERE is_current;

INSERT INTO m4_stage0p_normalization_registry (version, is_current, approved_by, approval_ref)
VALUES ('nfc-v1', TRUE, NULL, NULL)
ON CONFLICT (version) DO NOTHING;

COMMENT ON TABLE m4_stage0p_normalization_registry IS
  'REV7 T6-04: nguon THAT DUY NHAT cho normalization version hien hanh, APPEND-ONLY (lich su bat bien qua trigger guard) - doi qua m4_stage0p_set_current_normalization_version, khong con UPDATE truc tiep hay hardcode song song o 2 noi. approved_by/approval_ref NULL cho row seed migration (chua co quyet dinh PO/CA chinh thuc - xem note bang exclusion_gate).';

REVOKE ALL ON m4_stage0p_normalization_registry FROM PUBLIC;
REVOKE ALL ON m4_stage0p_normalization_registry FROM alpha3s_app;

CREATE OR REPLACE FUNCTION m4_stage0p_normalization_registry_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'm4_stage0p_normalization_registry: khong duoc XOA entry (append-only, T6-04)';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    -- approved_by duoc phep chuyen ve NULL (CHI ve NULL) - day la duong ON DELETE SET NULL cua FK
    -- toi staff_users (audit-trail, khong phai bat bien nghiep vu) khi staff bi xoa; MOI thay doi
    -- khac tren approved_by (vd doi sang 1 staff_id khac) van bi chan.
    IF NEW.version IS DISTINCT FROM OLD.version
       OR (NEW.approved_by IS DISTINCT FROM OLD.approved_by AND NEW.approved_by IS NOT NULL)
       OR NEW.approval_ref IS DISTINCT FROM OLD.approval_ref
       OR NEW.effective_at IS DISTINCT FROM OLD.effective_at
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
      RAISE EXCEPTION 'm4_stage0p_normalization_registry: chi duoc doi is_current (hoac approved_by ve NULL qua ON DELETE SET NULL) sau khi tao - moi truong khac bat bien (T6-04)';
    END IF;
  END IF;
  RETURN COALESCE(NEW, OLD);
END;
$$;

ALTER FUNCTION m4_stage0p_normalization_registry_guard() OWNER TO alpha3s_m4_definer;

DROP TRIGGER IF EXISTS m4_normalization_registry_guard ON m4_stage0p_normalization_registry;
CREATE TRIGGER m4_normalization_registry_guard
  BEFORE UPDATE OR DELETE ON m4_stage0p_normalization_registry
  FOR EACH ROW EXECUTE FUNCTION m4_stage0p_normalization_registry_guard();

-- ===========================================================================
-- 3. Bang m4_selection_batches.
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
                             CHECK (status IN ('locked', 'collecting', 'collection_closed',
                                               'labels_sealed', 'predictions_written',
                                               'evaluation_completed')),
  captured_count          INT NOT NULL DEFAULT 0 CHECK (captured_count >= 0),
  retention_days          INT NOT NULL DEFAULT 45 CHECK (retention_days > 0),
  -- REV7 T6-04: BO DEFAULT - Python (lock_batch, T5-04) da tu doc + truyen tuong minh tu
  -- registry; DEFAULT ngam la 1 nguon hardcode thu 2 tiem an neu 1 INSERT nao do quen chi dinh
  -- cot nay. FK toi registry(version) o duoi dam bao khong the insert 1 version khong ton tai.
  normalization_version   TEXT NOT NULL,
  collection_closed_at    TIMESTAMPTZ,
  labels_sealed_at        TIMESTAMPTZ,
  labels_sealed_by        BIGINT REFERENCES staff_users(id),
  labels_sealed_hash      TEXT,
  predictions_written_at  TIMESTAMPTZ,
  result_hash             TEXT,
  -- REV5 T4-05: dau vet minh bach nguong da ap dung luc ghi predictions (khong bat buoc trong
  -- hash chain - xem ghi chu Â§5g - chi de audit/report doc lai duoc).
  exclusion_gate_version  TEXT,
  -- REV6 T5-03: dau vet minh bach so candidate capture-level bi loai/that bai vinh vien, luu tai
  -- thoi diem close_collection.
  capture_excluded_count           INT,
  capture_permanent_failed_count   INT,
  -- REV7 T6-03: chinh sach gate da ap dung luc close_collection - dau vet minh bach, dua vao hash
  -- chain (Â§5h v3). Gia tri duy nhat hien tai: zero-tolerance (batch nao co permanent_failed deu
  -- bi tu choi dong) cho toi khi co PO decision record that su cho phep 1 chinh sach khac.
  capture_gate_policy              TEXT,
  evaluation_completed_at   TIMESTAMPTZ,
  evaluation_completed_by   BIGINT REFERENCES staff_users(id),
  evaluation_report_hash    TEXT,
  CONSTRAINT m4_batch_window_valid CHECK (window_end > window_start),
  CONSTRAINT m4_batch_count_valid CHECK (selected_count <= eligible_count AND selected_count <= 260),
  CONSTRAINT m4_batch_seal_needs_close CHECK (labels_sealed_at IS NULL OR collection_closed_at IS NOT NULL),
  CONSTRAINT m4_batch_predictions_need_seal CHECK (predictions_written_at IS NULL OR labels_sealed_at IS NOT NULL),
  CONSTRAINT m4_batch_eval_needs_predictions CHECK (evaluation_completed_at IS NULL OR predictions_written_at IS NOT NULL),
  CONSTRAINT m4_batch_normalization_version_fk FOREIGN KEY (normalization_version)
    REFERENCES m4_stage0p_normalization_registry(version)
);

COMMENT ON TABLE m4_selection_batches IS
  'M4 Stage 0P - khoa tap conversation_id da chon. status la state machine DB-enforced day du (locked->collecting->collection_closed->labels_sealed->predictions_written->evaluation_completed).';

REVOKE ALL ON m4_selection_batches FROM PUBLIC;
REVOKE ALL ON m4_selection_batches FROM alpha3s_app;

-- ===========================================================================
-- 3b. Bang m4_stage0p_fetch_capability - REV5 T4-01 (MOI, thay the custom GUC REV4). KHONG
--     GRANT cho bat ky role m4 nao - CHI alpha3s_m4_definer (chay ben trong ham) duoc dung. 1 row
--     = 1 lan fetch_message_content thanh cong TRONG 1 transaction cu the (txid_current() -
--     caller khong the tu chon gia tri nay). record_sample tieu thu (DELETE...RETURNING) row
--     nay trong CUNG transaction - day la bang chung DB-owned, khong the gia mao.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_fetch_capability (
  batch_id        UUID NOT NULL,
  conversation_id BIGINT NOT NULL,
  message_id      BIGINT NOT NULL,
  txid            BIGINT NOT NULL,
  -- REV6 T5-02: do dai/trang thai cat DB TU TINH luc fetch - record_sample doi chieu
  -- canonical_text_len/truncated caller khai bao voi 2 cot nay (khong the ket luan dung
  -- ciphertext, nhung chan duoc "wrong-length"/"wrong-truncation" ro rang).
  fetched_char_len       INT NOT NULL,
  fetched_char_truncated BOOLEAN NOT NULL,
  -- REV7 T6-02: SHA-256 (pgcrypto digest()) tren dung van ban canonical DB TU TINH (NFC-normalize
  -- + truncate 2 buoc - GIONG HET thu tu Python _truncate(nfc(...)) ap dung, xem
  -- m4_stage0p_fetch_message_content). record_sample doi hoi p_canonical_text_digest (Python tinh
  -- NGAY TRUOC luc encrypt tren chinh van ban da encrypt) khop CHINH XAC gia tri nay - chan duoc
  -- ciphertext-thay-the/canonical-length-khai-sai cung do dai (T5-02 chi kiem do dai, khong kiem
  -- NOI DUNG).
  fetched_canonical_digest BYTEA NOT NULL,
  issued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (batch_id, conversation_id, message_id, txid)
);

COMMENT ON TABLE m4_stage0p_fetch_capability IS
  'REV5 T4-01: capability row DB-owned (khong phai GUC) - chi definer INSERT (fetch_message_content) va DELETE (record_sample, cung transaction, txid_current() khop). Khong GRANT cho role m4 nao.';

REVOKE ALL ON m4_stage0p_fetch_capability FROM PUBLIC;
REVOKE ALL ON m4_stage0p_fetch_capability FROM alpha3s_app;

-- ===========================================================================
-- 3c. Bang m4_stage0p_capture_progress - REV5 T4-03 (MOI). 1 row/candidate (conversation_id,
--     message_id) cua 1 batch, seed 1 lan qua m4_stage0p_seed_capture_progress. State machine 5
--     gia tri: pending -> committed | excluded | retryable_failed -> permanent_failed. peek doc
--     tu bang nay (khong con truyen cursor). close_collection tu choi neu con row
--     pending/retryable_failed.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS m4_stage0p_capture_progress (
  batch_id        UUID NOT NULL REFERENCES m4_selection_batches(batch_id),
  conversation_id BIGINT NOT NULL,
  message_id      BIGINT NOT NULL,
  customer_id     BIGINT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'committed', 'excluded', 'retryable_failed', 'permanent_failed')),
  attempt_count   INT NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  last_reason     TEXT,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (batch_id, conversation_id, message_id)
);
CREATE INDEX IF NOT EXISTS m4_capture_progress_pending_idx
  ON m4_stage0p_capture_progress (batch_id, status);

COMMENT ON TABLE m4_stage0p_capture_progress IS
  'REV5 T4-03: state machine per-candidate - moi candidate PHAI dat trang thai terminal (committed/excluded/permanent_failed) truoc khi close_collection duoc phep.';

REVOKE ALL ON m4_stage0p_capture_progress FROM PUBLIC;
REVOKE ALL ON m4_stage0p_capture_progress FROM alpha3s_app;

-- ===========================================================================
-- 4. Bang m4_shadow_review_samples - sample zone.
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
  'M4 Stage 0P sample zone (P12_PII_DETECTOR_EVAL). Retention: eval completed OR retention_days cua batch, tuy dieu kien nao truoc (RET-11b). DSR: xoa truc tiep theo customer_ref, khong join (khong orphan).';
COMMENT ON COLUMN m4_shadow_review_samples.encrypted_message IS
  'AES-256-GCM blob v2: version(2 byte ASCII "v1") || nonce(12) || ct+tag. AAD domain-tag a3s-m4-shadow-sample-aad-v1, fields=(customer_ref, conversation_ref, sample_id).';

REVOKE ALL ON m4_shadow_review_samples FROM PUBLIC;
REVOKE ALL ON m4_shadow_review_samples FROM alpha3s_app;

-- Trigger bat bien ground truth sau seal - PHAI SECURITY DEFINER.
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

-- Xoa ham cu se thay the (chu ky doi hoac logic doi hoan toan).
DROP FUNCTION IF EXISTS m4_stage0p_fetch_batch_content(UUID);
DROP FUNCTION IF EXISTS m4_stage0p_fetch_next_message(UUID, BIGINT, BIGINT);
DROP FUNCTION IF EXISTS m4_stage0p_peek_next_candidate(UUID, BIGINT, BIGINT);
DROP FUNCTION IF EXISTS m4_stage0p_write_predictions(UUID, JSONB, TEXT, TEXT);
DROP FUNCTION IF EXISTS m4_stage0p_write_predictions(UUID, TEXT, JSONB, JSONB, TEXT, TEXT);
DROP FUNCTION IF EXISTS m4_stage0p_write_predictions(UUID, TEXT, JSONB, JSONB, TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS m4_stage0p_complete_evaluation(UUID, BIGINT, TEXT);
DROP FUNCTION IF EXISTS m4_stage0p_complete_evaluation(UUID, BIGINT, TEXT, JSONB);
DROP FUNCTION IF EXISTS m4_stage0p_set_capture(BOOLEAN, BIGINT, TEXT);
DROP FUNCTION IF EXISTS m4_stage0p_record_approval(TEXT, BOOLEAN, TIMESTAMPTZ, TIMESTAMPTZ, BIGINT, TEXT);
DROP FUNCTION IF EXISTS m4_stage0p_revoke_approval(TEXT, BIGINT, TEXT);
DROP FUNCTION IF EXISTS m4_stage0p_seal_labels(UUID, BIGINT);
DROP FUNCTION IF EXISTS m4_stage0p_pin_actor(BIGINT);
-- REV7 T6-02: record_sample REV5/REV6 (7 tham so, chua co p_canonical_text_digest).
DROP FUNCTION IF EXISTS m4_stage0p_record_sample(UUID, BIGINT, BIGINT, UUID, BYTEA, INT, BOOLEAN);

-- ===========================================================================
-- 5a. m4_stage0p_peek_next_candidate - REV5 T4-03: doi chu ky con (batch_id) - doc tu
--     m4_stage0p_capture_progress (khong con cursor after_conversation_id/after_message_id;
--     bang progress LA cursor/trang thai).
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_peek_next_candidate(
  p_batch_id UUID
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
  IF v_batch.status NOT IN ('locked', 'collecting') THEN
    RAISE EXCEPTION 'm4_stage0p_peek_next_candidate: batch % khong con o trang thai collecting (status=%) - T3-02',
      p_batch_id, v_batch.status;
  END IF;
  IF v_batch.purpose_code <> 'P12_PII_DETECTOR_EVAL' THEN
    RAISE EXCEPTION 'm4_stage0p_peek_next_candidate: purpose_code khong khop';
  END IF;
  IF now() < v_batch.window_start OR now() > v_batch.window_end + interval '7 days' THEN
    RAISE EXCEPTION 'm4_stage0p_peek_next_candidate: batch ngoai cua so hop le';
  END IF;

  SELECT cp.conversation_id, cp.message_id, cp.customer_id INTO v_row
    FROM public.m4_stage0p_capture_progress AS cp
    WHERE cp.batch_id = p_batch_id AND cp.status IN ('pending', 'retryable_failed')
    ORDER BY cp.conversation_id, cp.message_id
    LIMIT 1;

  IF NOT FOUND THEN
    RETURN QUERY SELECT 'exhausted'::TEXT, NULL::BIGINT, NULL::BIGINT, NULL::BIGINT;
    RETURN;
  END IF;

  RETURN QUERY SELECT 'ok'::TEXT, v_row.conversation_id, v_row.message_id, v_row.customer_id;
END;
$$;

ALTER FUNCTION m4_stage0p_peek_next_candidate(UUID) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_peek_next_candidate(UUID) FROM PUBLIC;

-- ===========================================================================
-- 5a2. m4_stage0p_seed_capture_progress - REV5 T4-03 (MOI). Goi 1 LAN khi collector bat dau
--      (truoc vong lap peek) - vet toan bo candidate hop le cua batch vao m4_stage0p_capture_progress
--      trang thai 'pending'. Idempotent (ON CONFLICT DO NOTHING) - resume 1 batch da seed truoc
--      do (vd sau khi bi control OFF giua chung) khong tao trung row.
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_seed_capture_progress(p_batch_id UUID)
RETURNS TABLE(candidate_count INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_batch RECORD;
  v_count INT;
BEGIN
  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_seed_capture_progress: batch_id khong ton tai';
  END IF;
  IF v_batch.status NOT IN ('locked', 'collecting') THEN
    RAISE EXCEPTION 'm4_stage0p_seed_capture_progress: batch % khong con o trang thai collecting (status=%)',
      p_batch_id, v_batch.status;
  END IF;

  INSERT INTO public.m4_stage0p_capture_progress (batch_id, conversation_id, message_id, customer_id)
  SELECT p_batch_id, ranked.conversation_id, ranked.id, c.customer_id
  FROM (
    SELECT m.conversation_id, m.id,
           ROW_NUMBER() OVER (PARTITION BY m.conversation_id ORDER BY m.id ASC) AS rn
    FROM public.messages m
    WHERE m.role = 'customer' AND m.conversation_id = ANY (v_batch.locked_conversation_ids)
  ) ranked
  JOIN public.conversations c ON c.id = ranked.conversation_id
  WHERE ranked.rn <= 20
  ON CONFLICT (batch_id, conversation_id, message_id) DO NOTHING;

  SELECT count(*) INTO v_count FROM public.m4_stage0p_capture_progress WHERE batch_id = p_batch_id;
  RETURN QUERY SELECT v_count;
END;
$$;

ALTER FUNCTION m4_stage0p_seed_capture_progress(UUID) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_seed_capture_progress(UUID) FROM PUBLIC;

-- ===========================================================================
-- 5a3. m4_stage0p_mark_candidate_outcome - REV5 T4-03 (MOI). Collector goi khi 1 candidate KHONG
--      dat 'ok' qua fenced unit: 'fence_timeout' (tang attempt_count, >=3 lan -> permanent_failed,
--      con lai -> retryable_failed, van con trong tap peek chon lai) hoac 'pending_deletion'
--      (-> excluded, terminal ngay, khong retry - DSR la tham quyen cuoi).
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_mark_candidate_outcome(
  p_batch_id UUID,
  p_conversation_id BIGINT,
  p_message_id BIGINT,
  p_outcome TEXT,
  p_reason TEXT DEFAULT NULL
)
RETURNS TABLE(new_status TEXT, attempt_count INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_row RECORD;
  v_new_status TEXT;
  v_audit_id BIGINT;
  MAX_ATTEMPTS CONSTANT INT := 3;
BEGIN
  IF NOT (p_outcome = ANY (ARRAY['fence_timeout', 'pending_deletion'])) THEN
    RAISE EXCEPTION 'm4_stage0p_mark_candidate_outcome: outcome khong hop le: %', p_outcome;
  END IF;
  -- T5-03: reason PHAI nam trong allowlist DB-side (4 gia tri THAT dang dung trong
  -- stage0p_sampling.py:run_collector) - khong con free text tuy y.
  IF p_reason IS NOT NULL AND NOT (p_reason = ANY (ARRAY[
      'asyncio_wait_for_timeout', 'customer_in_pending_cache',
      'pending_check_before_fence', 'pending_recheck_inside_fence'])) THEN
    RAISE EXCEPTION 'm4_stage0p_mark_candidate_outcome: reason khong nam trong allowlist: % (T5-03)', p_reason;
  END IF;

  SELECT * INTO v_row FROM public.m4_stage0p_capture_progress
    WHERE batch_id = p_batch_id AND conversation_id = p_conversation_id AND message_id = p_message_id
    FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_mark_candidate_outcome: candidate (%,%) khong duoc seed cho batch %',
      p_conversation_id, p_message_id, p_batch_id;
  END IF;
  IF v_row.status NOT IN ('pending', 'retryable_failed') THEN
    RAISE EXCEPTION 'm4_stage0p_mark_candidate_outcome: candidate (%,%) da o trang thai terminal (%) - khong the danh dau lai',
      p_conversation_id, p_message_id, v_row.status;
  END IF;

  IF p_outcome = 'pending_deletion' THEN
    v_new_status := 'excluded';
  ELSE
    IF v_row.attempt_count + 1 >= MAX_ATTEMPTS THEN
      v_new_status := 'permanent_failed';
    ELSE
      v_new_status := 'retryable_failed';
    END IF;
  END IF;

  UPDATE public.m4_stage0p_capture_progress AS cp
    SET status = v_new_status, attempt_count = cp.attempt_count + 1, last_reason = p_reason, updated_at = now()
    WHERE cp.batch_id = p_batch_id AND cp.conversation_id = p_conversation_id AND cp.message_id = p_message_id;

  INSERT INTO public.audit_log (actor_type, actor_ref, action, entity_type, entity_id, after)
  VALUES ('system', 'm4_stage0p_collector', 'm4_candidate_outcome', 'm4_selection_batch', p_batch_id::text,
          jsonb_build_object('conversation_id', p_conversation_id, 'message_id', p_message_id,
                              'outcome', p_outcome, 'new_status', v_new_status, 'reason', p_reason))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_new_status, v_row.attempt_count + 1;
END;
$$;

ALTER FUNCTION m4_stage0p_mark_candidate_outcome(UUID, BIGINT, BIGINT, TEXT, TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_mark_candidate_outcome(UUID, BIGINT, BIGINT, TEXT, TEXT) FROM PUBLIC;

-- ===========================================================================
-- 5b. m4_stage0p_fetch_message_content - fenced. REV5 T4-01: khi thanh cong ('ok'), INSERT 1
--     row vao m4_stage0p_fetch_capability (khong con set_config GUC - CA chi ro GUC khong phai
--     secret/privileged storage, caller co the tu forge). Bang capability KHONG GRANT cho role
--     nao khac ngoai definer - day la bang chung DB-owned that su.
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
  -- T6-02: bien tinh canonical text - PHAI theo DUNG thu tu Python _truncate(nfc(...)) ap dung
  -- tren chinh 'left(v_row.content, 2000)' se duoc RETURN QUERY o duoi (Python nhan gia tri nay,
  -- roi tu nfc()+truncate - DB phai lam LAI y het de digest khop).
  v_received      TEXT;
  v_nfc           TEXT;
  v_char_trunc    BOOLEAN;
  v_bytes         BYTEA;
  v_byte_trunc    BOOLEAN;
  v_canon         TEXT;
  v_cutlen        INT;
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
  IF v_batch.status NOT IN ('locked', 'collecting') THEN
    RAISE EXCEPTION 'm4_stage0p_fetch_message_content: batch % khong con o trang thai collecting (status=%) - T3-02',
      p_batch_id, v_batch.status;
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

  -- T6-02: tinh canonical text DB-side, DUNG thu tu Python se ap dung tren gia tri RETURN QUERY o
  -- duoi (v_received = 'left(content,2000)' - Python nhan CHINH gia tri nay lam fetched["content"]):
  --   (1) raw-truncate 2000 ky tu (giong het RETURN QUERY duoi);
  --   (2) NFC-normalize (Python: nfc());
  --   (3) neu NFC lam vuot lai 2000 ky tu (hiem, mot so chuoi ket hop co the mo rong) thi cat lai
  --       (Python _truncate() kiem tra lai sau nfc());
  --   (4) byte-truncate UTF-8-an-toan ve <=8000 byte (giong het Python _truncate() buoc 2 - dung
  --       vong lap lui dan tung byte cho toi khi convert_from() khong loi, tuong duong
  --       bytes.decode('utf-8', errors='ignore') cua Python tren 1 chuoi bi cat giua ky tu).
  v_received := left(v_row.content, 2000);
  v_char_trunc := char_length(v_row.content) > 2000;
  v_nfc := normalize(v_received, NFC);
  IF char_length(v_nfc) > 2000 THEN
    v_nfc := left(v_nfc, 2000);
    v_char_trunc := TRUE;
  END IF;
  v_bytes := convert_to(v_nfc, 'UTF8');
  v_byte_trunc := octet_length(v_bytes) > 8000;
  IF v_byte_trunc THEN
    v_cutlen := 8000;
    LOOP
      BEGIN
        v_canon := convert_from(substr(v_bytes, 1, v_cutlen), 'UTF8');
        EXIT;
      EXCEPTION WHEN OTHERS THEN
        v_cutlen := v_cutlen - 1;
        IF v_cutlen <= 0 THEN
          v_canon := '';
          EXIT;
        END IF;
      END;
    END LOOP;
  ELSE
    v_canon := v_nfc;
  END IF;

  -- T4-01: capability row DB-owned - chi definer INSERT duoc (khong GRANT cho role nao khac);
  -- txid_current() khong the caller tu chon. T5-02: luu do dai/trang thai cat DB TU TINH (nay tinh
  -- tren CHINH canonical text, khong con tren raw content - chinh xac hon). T6-02: luu them digest
  -- SHA-256 cua canonical text - record_sample doi chieu.
  INSERT INTO public.m4_stage0p_fetch_capability
    (batch_id, conversation_id, message_id, txid, fetched_char_len, fetched_char_truncated,
     fetched_canonical_digest)
  VALUES (p_batch_id, p_conversation_id, p_message_id, txid_current(),
          char_length(v_canon), (v_char_trunc OR v_byte_trunc), digest(v_canon, 'sha256'));

  RETURN QUERY SELECT 'ok'::TEXT, v_received, v_char_trunc, v_row.created_at;
END;
$$;

ALTER FUNCTION m4_stage0p_fetch_message_content(UUID, BIGINT, BIGINT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_fetch_message_content(UUID, BIGINT, BIGINT) FROM PUBLIC;

-- ===========================================================================
-- 5c. m4_stage0p_record_sample - REV5 T4-01: doi chieu capability row (DELETE...RETURNING, khong
--     con set_config/current_setting GUC). REV5 T4-03: chuyen candidate progress -> 'committed'
--     TRONG CUNG transaction voi INSERT sample.
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_record_sample(
  p_batch_id UUID,
  p_conversation_id BIGINT,
  p_message_id BIGINT,
  p_sample_id UUID,
  p_encrypted_message BYTEA,
  p_canonical_text_len INT,
  p_truncated BOOLEAN,
  -- REV7 T6-02: SHA-256 cua canonical text, tinh boi Python NGAY TRUOC luc encrypt (tren chinh
  -- van ban da encrypt) - phai khop CHINH XAC fetched_canonical_digest DB da tinh luc fetch.
  p_canonical_text_digest BYTEA
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
  v_customer_id BIGINT;
  v_enabled BOOLEAN;
  v_capability RECORD;
BEGIN
  PERFORM pg_advisory_xact_lock(4013003);

  -- T4-01: tieu thu capability row DB-owned - chi ton tai neu fetch_message_content da thanh
  -- cong CHO DUNG (batch,conversation,message) TRONG CUNG transaction (txid_current() khop).
  -- Caller khong co INSERT/SELECT/DELETE truc tiep tren bang nay nen khong the gia mao.
  DELETE FROM public.m4_stage0p_fetch_capability
    WHERE batch_id = p_batch_id AND conversation_id = p_conversation_id AND message_id = p_message_id
      AND txid = txid_current()
    RETURNING fetched_char_len, fetched_char_truncated, fetched_canonical_digest INTO v_capability;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: khong co capability fetch hop le cho message (%,%) trong CUNG transaction - tu choi (T4-01)',
      p_conversation_id, p_message_id;
  END IF;

  -- T6-02: doi chieu digest canonical text - day la RANG BUOC CHINH, thay the cho "trong khoang
  -- hop ly" REV6 (T5-02). Digest sai = KHAC noi dung (ciphertext-thay-the/canonical-length-khai-
  -- sai/truncated-gia deu tao ra digest khac) - tu choi ngay, khong con "gan dung la duoc".
  IF p_canonical_text_digest IS NULL OR p_canonical_text_digest <> v_capability.fetched_canonical_digest THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: canonical_text_digest khong khop noi dung da fetch - tu choi (T6-02)';
  END IF;
  -- Digest da chung minh dung canonical text -> do dai/trang thai cat gio la BAT BUOC KHOP CHINH
  -- XAC (khong con chi la "trong khoang", vi chi co DUY NHAT 1 canonical text dung cho 1 fetch).
  IF p_canonical_text_len <> v_capability.fetched_char_len THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: canonical_text_len (%) khong khop do dai da fetch (%) - tu choi (T5-02/T6-02)',
      p_canonical_text_len, v_capability.fetched_char_len;
  END IF;
  IF p_truncated <> v_capability.fetched_char_truncated THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: truncated (%) khong khop trang thai cat da fetch (%) - tu choi (T5-02/T6-02)',
      p_truncated, v_capability.fetched_char_truncated;
  END IF;
  -- AEAD overhead co dinh 30 byte (version 2 + nonce 12 + tag 16); phan ciphertext con lai PHAI
  -- nam trong khoang [1, 4] byte/ky tu UTF-8 hop le cho canonical_text_len da khai. Van giu (defense-
  -- in-depth, khong thay the digest) - bat gross mismatch do dai ciphertext som, thong bao ro hon.
  IF octet_length(p_encrypted_message) < p_canonical_text_len + 30
     OR octet_length(p_encrypted_message) > p_canonical_text_len * 4 + 30 THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: do dai ciphertext (%) khong hop ly so canonical_text_len (%) - tu choi (T5-02)',
      octet_length(p_encrypted_message), p_canonical_text_len;
  END IF;

  SELECT capture_enabled INTO v_enabled FROM public.m4_stage0p_control WHERE id = 1;
  IF v_enabled IS NOT TRUE THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: control da tat - tu choi ghi (T3-01)';
  END IF;

  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: batch_id khong ton tai';
  END IF;
  IF v_batch.status NOT IN ('locked', 'collecting') THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: batch % khong con o trang thai collecting (status=%) - T3-02',
      p_batch_id, v_batch.status;
  END IF;
  IF NOT (p_conversation_id = ANY (v_batch.locked_conversation_ids)) THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: conversation_id % khong thuoc batch %', p_conversation_id, p_batch_id;
  END IF;

  v_cap := v_batch.selected_count * 20;
  IF v_batch.captured_count >= v_cap THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: batch % da dat tran captured_count (%/%)',
      p_batch_id, v_batch.captured_count, v_cap;
  END IF;

  SELECT customer_id INTO v_customer_id FROM public.conversations WHERE id = p_conversation_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: conversation_id % khong ton tai', p_conversation_id;
  END IF;

  INSERT INTO public.m4_shadow_review_samples
    (sample_id, customer_ref, conversation_ref, encrypted_message, canonical_text_len,
     truncated, expires_at, purpose_code, normalization_version, selection_batch)
  VALUES (p_sample_id, v_customer_id::text, p_conversation_id::text, p_encrypted_message,
          p_canonical_text_len, p_truncated, now() + make_interval(days => v_batch.retention_days),
          'P12_PII_DETECTOR_EVAL', v_batch.normalization_version, p_batch_id);

  -- T4-03: chuyen candidate -> committed TRONG CUNG transaction voi INSERT sample.
  UPDATE public.m4_stage0p_capture_progress
    SET status = 'committed', updated_at = now()
    WHERE batch_id = p_batch_id AND conversation_id = p_conversation_id AND message_id = p_message_id
      AND status IN ('pending', 'retryable_failed');
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_record_sample: candidate (%,%) khong o trang thai cho phep ghi (chua duoc seed hoac da terminal) - T4-03',
      p_conversation_id, p_message_id;
  END IF;

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

ALTER FUNCTION m4_stage0p_record_sample(UUID, BIGINT, BIGINT, UUID, BYTEA, INT, BOOLEAN, BYTEA)
  OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_record_sample(UUID, BIGINT, BIGINT, UUID, BYTEA, INT, BOOLEAN, BYTEA)
  FROM PUBLIC;

-- ===========================================================================
-- 5c2. m4_stage0p_close_collection - REV5 T4-03: them dieu kien BAT BUOC - KHONG con row
--      pending/retryable_failed nao trong capture_progress cua batch. Doi chieu 3 chieu:
--      captured_count (cot dem) == so row sample thuc te == so row 'committed' trong progress.
--      REV6 T5-03: them gate ty le permanent_failed (dung chung nguong voi
--      m4_stage0p_exclusion_gate, T4-05) - batch KHONG duoc dong neu qua nhieu candidate that
--      bai capture vinh vien; luu capture_excluded_count/capture_permanent_failed_count tren
--      batch row lam bang chung closure.
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_close_collection(p_batch_id UUID)
RETURNS TABLE(status TEXT, captured_count INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_batch RECORD;
  v_actual_count INT;
  v_committed_count INT;
  v_non_terminal INT;
  v_total_candidates INT;
  v_capture_excluded INT;
  v_capture_permanent_failed INT;
  v_audit_id BIGINT;
  -- REV7 T6-03: CA chi ro khong duoc dung nguong CHUA duyet (exclusion_gate, van la CA-proposed,
  -- xem T4-05) de CHO PHEP batch di tiep - chinh sach duy nhat hop le hien tai la zero-tolerance
  -- VO DIEU KIEN cho toi khi co 1 PO decision record that su.
  v_gate_policy CONSTANT TEXT := 'zero_tolerance_pending_po_decision_v1';
BEGIN
  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_close_collection: batch_id khong ton tai';
  END IF;
  IF v_batch.status NOT IN ('locked', 'collecting') THEN
    RAISE EXCEPTION 'm4_stage0p_close_collection: batch % khong con o trang thai collecting (status=%)',
      p_batch_id, v_batch.status;
  END IF;

  SELECT count(*) INTO v_non_terminal FROM public.m4_stage0p_capture_progress AS cp
    WHERE cp.batch_id = p_batch_id AND cp.status IN ('pending', 'retryable_failed');
  IF v_non_terminal > 0 THEN
    RAISE EXCEPTION 'm4_stage0p_close_collection: batch % con % candidate CHUA o trang thai terminal (pending/retryable_failed) - T4-03',
      p_batch_id, v_non_terminal;
  END IF;

  SELECT count(*) INTO v_actual_count FROM public.m4_shadow_review_samples WHERE selection_batch = p_batch_id;
  SELECT count(*) FILTER (WHERE cp.status = 'committed') INTO v_committed_count
    FROM public.m4_stage0p_capture_progress AS cp WHERE cp.batch_id = p_batch_id;
  IF v_actual_count <> v_batch.captured_count OR v_actual_count <> v_committed_count THEN
    RAISE EXCEPTION 'm4_stage0p_close_collection: captured_count (%) / sample row thuc te (%) / progress committed (%) khong khop nhau - tu choi dong',
      v_batch.captured_count, v_actual_count, v_committed_count;
  END IF;

  SELECT count(*), count(*) FILTER (WHERE cp.status = 'excluded'),
         count(*) FILTER (WHERE cp.status = 'permanent_failed')
    INTO v_total_candidates, v_capture_excluded, v_capture_permanent_failed
    FROM public.m4_stage0p_capture_progress AS cp WHERE cp.batch_id = p_batch_id;

  -- REV7 T6-03: BAT KY permanent_failed nao (>0) deu tu choi dong VO DIEU KIEN - REV6 dung ty le
  -- so voi m4_stage0p_exclusion_gate (van la de xuat CA Review #4, CHUA co PO decision record) de
  -- CHO PHEP mot vai permanent_failed di tiep; CA Review #6 chi ro day KHONG duoc chap nhan lam
  -- can cu "cho phep" khi chua duoc PO duyet chinh thuc. Kiem TRUOC empty-corpus (duoi) vi day la
  -- chan doan cu the hon khi ca 2 dieu kien cung dung.
  IF v_capture_permanent_failed > 0 THEN
    RAISE EXCEPTION 'm4_stage0p_close_collection: batch % co % candidate permanent_failed (/%tong) - CHUA co PO decision record duyet nguong cho phep permanent failure, tu choi dong VO DIEU KIEN (INSUFFICIENT_DATA, chinh sach=%, T6-03)',
      p_batch_id, v_capture_permanent_failed, v_total_candidates, v_gate_policy;
  END IF;

  -- REV7 T6-03: corpus RONG (0 candidate committed) - sanity co ban, khong phai nguong governance
  -- (khac han nguong 200-conversation cua write_predictions, van la de xuat CA chua duoc PO duyet).
  IF v_committed_count = 0 THEN
    RAISE EXCEPTION 'm4_stage0p_close_collection: batch % khong co candidate nao committed (corpus rong) - tu choi dong (T6-03)',
      p_batch_id;
  END IF;

  UPDATE public.m4_selection_batches
    SET status = 'collection_closed', collection_closed_at = now(),
        capture_excluded_count = v_capture_excluded,
        capture_permanent_failed_count = v_capture_permanent_failed,
        capture_gate_policy = v_gate_policy
    WHERE batch_id = p_batch_id;

  INSERT INTO public.audit_log (actor_type, actor_ref, action, entity_type, entity_id, after)
  VALUES ('system', 'm4_stage0p_collector', 'm4_collection_closed', 'm4_selection_batch',
          p_batch_id::text, jsonb_build_object('captured_count', v_actual_count,
                                                'capture_excluded_count', v_capture_excluded,
                                                'capture_permanent_failed_count', v_capture_permanent_failed,
                                                'capture_gate_policy', v_gate_policy))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT 'collection_closed'::TEXT, v_actual_count;
END;
$$;

ALTER FUNCTION m4_stage0p_close_collection(UUID) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_close_collection(UUID) FROM PUBLIC;

-- ===========================================================================
-- 5d. m4_stage0p_pin_actor / m4_stage0p_require_pinned_actor - REV6 T5-01: CA chi ro pin_actor
--     REV5 (T4-04) VAN co lo hong CUNG LOP voi T4-01 - GUC
--     alpha3s.m4_actor_staff_id la session variable THUONG, BAT KY session nao cung tu
--     set_config duoc bat ke co EXECUTE pin_actor hay khong (restrict EXECUTE tren pin_actor
--     KHONG bao ve duoc GUC - day la 2 co che khac nhau, EXECUTE grant chi kiem soat AI GOI DUOC
--     HAM, khong kiem soat AI GHI DUOC 1 session variable). Sua: bang m4_stage0p_actor_session
--     khoa boi pg_backend_pid() (Postgres tu cap cho CHINH session dang goi - khong the gia mao
--     trong CUNG session, khac han GUC ma bat ky ai cung tu ghi duoc). Them: pin_actor REV5 chi
--     kiem staff active, KHONG kiem caller co DUNG LA staff do - sua them bang moi
--     m4_stage0p_actor_credentials (pin_secret rieng tung staff) - pin_actor(staff_id,pin_secret)
--     doi hoi secret khop, chan "binder tu chon tuy y bat ky staff active nao".
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_pin_actor(p_staff_id BIGINT, p_pin_secret TEXT)
RETURNS TABLE(pinned_staff_id BIGINT, expires_at TIMESTAMPTZ)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_audit_id BIGINT;
  v_cred RECORD;
  v_nonce UUID;
  v_expires TIMESTAMPTZ;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.staff_users WHERE id = p_staff_id AND is_active = TRUE) THEN
    RAISE EXCEPTION 'm4_stage0p_pin_actor: staff_id khong ton tai hoac khong active';
  END IF;

  SELECT * INTO v_cred FROM public.m4_stage0p_actor_credentials
    WHERE staff_id = p_staff_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_pin_actor: chua duoc provisioning pin_secret cho staff_id % (T6-01)', p_staff_id;
  END IF;
  -- T6-01: rate-limit chong brute-force pin_secret. KHONG RAISE tai day/duoi — PL/pgSQL KHONG co
  -- autonomous transaction: neu RAISE, UPDATE failed_attempts se bi ROLLBACK CUNG VOI TOAN BO
  -- statement (da xac nhan bang thu nghiem thuc te — 1 lop bug moi tu phat hien round nay, xem
  -- Correction #6 §3), khien counter khong bao gio thuc su tang. Thay vao do: COMMIT UPDATE roi
  -- RETURN QUERY 1 hang "that bai" (pinned_staff_id=NULL) — Python wrapper (pin_actor()) tu RAISE
  -- ActorNotPinnedError dua tren gia tri tra ve, KHONG dua vao loi DB.
  IF v_cred.locked_until IS NOT NULL AND now() < v_cred.locked_until THEN
    RETURN QUERY SELECT NULL::BIGINT, NULL::TIMESTAMPTZ;
    RETURN;
  END IF;

  -- T6-01: pin_secret luu HASH (pgcrypto crypt/gen_salt('bf')) - khong con so sanh plaintext.
  IF p_pin_secret IS NULL OR v_cred.pin_secret_hash <> crypt(p_pin_secret, v_cred.pin_secret_hash) THEN
    UPDATE public.m4_stage0p_actor_credentials
      SET failed_attempts = failed_attempts + 1,
          locked_until = CASE WHEN failed_attempts + 1 >= 5 THEN now() + interval '15 minutes'
                               ELSE locked_until END
      WHERE staff_id = p_staff_id;
    RETURN QUERY SELECT NULL::BIGINT, NULL::TIMESTAMPTZ;
    RETURN;
  END IF;

  UPDATE public.m4_stage0p_actor_credentials
    SET failed_attempts = 0, locked_until = NULL WHERE staff_id = p_staff_id;

  -- T6-01: sinh 1 UUID ngau nhien, dat DONG THOI vao row (session_nonce) VA vao 1 GUC session-
  -- scoped cua CHINH connection dang goi (set_config(...,false) - KHONG phai LOCAL, sinh ton qua
  -- transaction boundary nhung MAT khi backend dong/chet - khac han GUC REV5 T5-01, gia tri nay
  -- KHONG BAO GIO mang danh tinh actor, chi la 1 nonce doi chung ngau nhien khong ai doan duoc).
  v_nonce := gen_random_uuid();
  v_expires := now() + interval '15 minutes';
  PERFORM set_config('alpha3s.m4_session_nonce', v_nonce::text, false);

  INSERT INTO public.m4_stage0p_actor_session
    (backend_pid, session_nonce, staff_id, pinned_at, expires_at)
  VALUES (pg_backend_pid(), v_nonce, p_staff_id, now(), v_expires)
  ON CONFLICT (backend_pid) DO UPDATE
    SET session_nonce = EXCLUDED.session_nonce, staff_id = EXCLUDED.staff_id,
        pinned_at = now(), expires_at = EXCLUDED.expires_at;

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id, after)
  VALUES ('staff', p_staff_id, 'm4_stage0p_pin_actor', 'staff_users', p_staff_id::text,
          jsonb_build_object('expires_at', v_expires))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT p_staff_id, v_expires;
END;
$$;

ALTER FUNCTION m4_stage0p_pin_actor(BIGINT, TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_pin_actor(BIGINT, TEXT) FROM PUBLIC;

CREATE OR REPLACE FUNCTION m4_stage0p_require_pinned_actor(p_permission TEXT)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_actor_id BIGINT;
  v_session RECORD;
  v_current_nonce TEXT;
BEGIN
  SELECT * INTO v_session FROM public.m4_stage0p_actor_session WHERE backend_pid = pg_backend_pid();
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_require_pinned_actor: chua pin actor cho session nay - goi m4_stage0p_pin_actor truoc (T5-01/T6-01)';
  END IF;

  -- T6-01: PID co the bi He dieu hanh TAI SU DUNG cho 1 ket noi HOAN TOAN MOI sau khi backend cu
  -- da chet - 1 backend MOI LUON bat dau voi GUC tuy chinh RONG (session_nonce khong sinh ton qua
  -- 1 ket noi/backend process moi, chi sinh ton trong CUNG 1 session con song), nen doi chieu GUC
  -- hien tai voi session_nonce da luu luc pin phat hien chinh xac truong hop nay ma KHONG can doc
  -- pg_stat_activity (cot backend_start bi Postgres NULL hoa cho role khong dac quyen nhu
  -- alpha3s_m4_definer - xem bug tu phat hien Correction #6). Khac nhau = row cu la STALE -> tu
  -- choi. KHONG DELETE row tai day (PL/pgSQL khong co autonomous transaction — DELETE se bi
  -- ROLLBACK cung voi RAISE ngay sau, thanh vo tac dung — da xac nhan bang thu nghiem thuc te,
  -- xem Correction #6 §3); khong sao ve mat bao mat vi kiem tra nay danh gia LAI TU DAU moi lan
  -- goi, du row cu con ton tai — pin lai (ON CONFLICT DO UPDATE trong pin_actor) se tu ghi de.
  v_current_nonce := current_setting('alpha3s.m4_session_nonce', true);
  IF v_current_nonce IS NULL OR v_current_nonce IS DISTINCT FROM v_session.session_nonce::text THEN
    RAISE EXCEPTION 'm4_stage0p_require_pinned_actor: pin session STALE (session_nonce khong khop - backend_pid co the da bi tai su dung tu 1 ket noi da chet) - tu choi, pin lai (T6-01)';
  END IF;

  -- T6-01: TTL bat buoc - pin qua han khong con hieu luc, du backend_pid van con song (chong
  -- connection-pool tai su dung pin cu cho 1 request/nguoi dung khac).
  IF now() > v_session.expires_at THEN
    RAISE EXCEPTION 'm4_stage0p_require_pinned_actor: pin da het han (expires_at=%) - tu choi, pin lai (T6-01)', v_session.expires_at;
  END IF;

  v_actor_id := v_session.staff_id;
  IF NOT EXISTS (SELECT 1 FROM public.staff_users WHERE id = v_actor_id AND is_active = TRUE) THEN
    RAISE EXCEPTION 'm4_stage0p_require_pinned_actor: actor da pin (%) khong con active', v_actor_id;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.m4_stage0p_staff_permissions
    WHERE staff_id = v_actor_id AND permission = p_permission
  ) THEN
    RAISE EXCEPTION 'm4_stage0p_require_pinned_actor: actor % khong co quyen % (T5-01)', v_actor_id, p_permission;
  END IF;

  -- REV8 T7-01: TIEU THU pin ngay khi validate THANH CONG (consume-on-use, 1 pin = DUNG DUOC
  -- CHO DUNG 1 hanh dong nghiep vu) - dong khoang cach CA Review #7 chi ro: connection-pool tai
  -- su dung CHINH connection cu (khac PID-reuse T6-01 da dong) van con nguyen row/backend_pid/GUC,
  -- khien 1 request/actor SAU co the "ke thua" pin cua request/actor TRUOC trong toi da 15 phut.
  -- DELETE tai day CHI thuc su COMMIT neu toan bo ham nghiep vu goi ham nay (set_capture/
  -- record_approval/.../set_current_normalization_version) THANH CONG toi cung - neu ham nghiep
  -- vu that bai vi 1 ly do KHAC sau buoc nay, DELETE bi rollback CUNG VOI loi do (dung y - retry
  -- hop le voi CUNG pin khong nen bi chan bat 1 hanh dong THAT SU chua bao gio xay ra); chi hanh
  -- dong THANH CONG moi tieu thu pin, dung ngu nghia can co.
  DELETE FROM public.m4_stage0p_actor_session WHERE backend_pid = pg_backend_pid();

  RETURN v_actor_id;
END;
$$;

ALTER FUNCTION m4_stage0p_require_pinned_actor(TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_require_pinned_actor(TEXT) FROM PUBLIC;

-- T6-01: "logout" tuong minh - tu xoa pin cua CHINH session dang goi (khong doi hoi permission,
-- chi tac dong toi row cua chinh backend_pid nay). Bo sung expiry lam lop phong thu thu 2.
CREATE OR REPLACE FUNCTION m4_stage0p_unpin_actor()
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  DELETE FROM public.m4_stage0p_actor_session WHERE backend_pid = pg_backend_pid();
END;
$$;

ALTER FUNCTION m4_stage0p_unpin_actor() OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_unpin_actor() FROM PUBLIC;

-- ===========================================================================
-- 5d2. m4_stage0p_set_current_normalization_version - REV7 T6-04 (MOI). Duy nhat cach doi
--      "normalization version hien hanh" - doi hoi pinned actor + quyen m4.stage0p.approve, ghi
--      audit. Version MOI hoan toan (khong tao lai 1 version da dung - lich su bat bien).
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_set_current_normalization_version(
  p_version TEXT, p_approval_ref TEXT
)
RETURNS TABLE(version TEXT, effective_at TIMESTAMPTZ)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE v_actor_id BIGINT; v_now TIMESTAMPTZ := now(); v_audit_id BIGINT;
BEGIN
  v_actor_id := m4_stage0p_require_pinned_actor('m4.stage0p.approve');

  -- REV8 T7-03: serialize registry transition - 2 lenh doi version dong thoi khong duoc dam bao
  -- thu tu boi chi rieng row-lock UPDATE/INSERT ben duoi (2 transaction cung doc is_current=true
  -- TRUOC khi 1 ben UPDATE co the tao race dieu kien is_current gia dinh sai). Khoa xact-scoped
  -- theo ten ham, tu nha khi transaction ket thuc.
  PERFORM pg_advisory_xact_lock(hashtext('m4_stage0p_normalization_registry'));

  IF p_version IS NULL OR length(btrim(p_version)) = 0 THEN
    RAISE EXCEPTION 'm4_stage0p_set_current_normalization_version: version khong duoc rong';
  END IF;
  IF EXISTS (SELECT 1 FROM public.m4_stage0p_normalization_registry AS nr WHERE nr.version = p_version) THEN
    RAISE EXCEPTION 'm4_stage0p_set_current_normalization_version: version % da ton tai (lich su bat bien, khong tao lai - T6-04)', p_version;
  END IF;
  -- REV9 T8-03: approval_ref gio PHAI tro toi 1 approval record THAT (rieng, khong tai dien giai
  -- capture-ON) — con hieu luc (chua het han/chua bi thu hoi) VA dung DUNG cho p_version nay (1
  -- approval CHI hop le cho version no de xuat, khong the "muon" cho version khac). CA chi ro
  -- REV8 chi kiem "khong rong" la KHONG DU — 1 actor co quyen truoc day co the truyen chuoi tuy y.
  IF NOT EXISTS (
    SELECT 1 FROM public.m4_stage0p_normalization_approvals a
    WHERE a.approval_ref = p_approval_ref
      AND a.requested_version = p_version
      AND now() BETWEEN a.valid_from AND a.valid_until
      AND NOT EXISTS (
        SELECT 1 FROM public.m4_stage0p_normalization_approval_revocations r
        WHERE r.approval_ref = a.approval_ref
      )
  ) THEN
    RAISE EXCEPTION 'm4_stage0p_set_current_normalization_version: approval_ref % khong hop le cho version % (khong ton tai/het han/bi thu hoi/sai version - T8-03)',
      p_approval_ref, p_version;
  END IF;

  UPDATE public.m4_stage0p_normalization_registry SET is_current = FALSE WHERE is_current = TRUE;
  INSERT INTO public.m4_stage0p_normalization_registry
    (version, is_current, approved_by, approval_ref, effective_at)
  VALUES (p_version, TRUE, v_actor_id, p_approval_ref, v_now);

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id, after)
  VALUES ('staff', v_actor_id, 'm4_stage0p_normalization_version_changed',
          'm4_stage0p_normalization_registry', p_version,
          jsonb_build_object('approval_ref', p_approval_ref))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT p_version, v_now;
END;
$$;

ALTER FUNCTION m4_stage0p_set_current_normalization_version(TEXT, TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_set_current_normalization_version(TEXT, TEXT) FROM PUBLIC;

-- ===========================================================================
-- 5e. m4_stage0p_set_capture - REV5 T4-04: bo p_actor_staff_id, doc actor qua
--     require_pinned_actor('m4.stage0p.operate'). T3-05 (khong doi): kiem KHONG bi revoke.
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_set_capture(
  p_enabled BOOLEAN,
  p_approval_ref TEXT
)
RETURNS TABLE(before_enabled BOOLEAN, after_enabled BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_actor_id BIGINT;
  v_before BOOLEAN;
  v_audit_id BIGINT;
BEGIN
  PERFORM pg_advisory_xact_lock(4013003);

  v_actor_id := m4_stage0p_require_pinned_actor('m4.stage0p.operate');

  IF p_enabled THEN
    IF p_approval_ref IS NULL OR length(btrim(p_approval_ref)) = 0 THEN
      RAISE EXCEPTION 'm4_stage0p_set_capture: approval_ref bat buoc khi bat ON';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM public.m4_stage0p_capture_approvals a
      WHERE a.approval_ref = p_approval_ref
        AND a.purpose_code = 'P12_PII_DETECTOR_EVAL'
        AND a.requested_enabled = TRUE
        AND now() BETWEEN a.valid_from AND a.valid_until
        AND NOT EXISTS (
          SELECT 1 FROM public.m4_stage0p_capture_approval_revocations r
          WHERE r.approval_ref = a.approval_ref
        )
    ) THEN
      RAISE EXCEPTION 'm4_stage0p_set_capture: approval_ref % khong hop le cho ON (khong ton tai/het han/bi thu hoi/sai purpose/sai trang thai yeu cau)',
        p_approval_ref;
    END IF;
  END IF;

  SELECT capture_enabled INTO v_before FROM public.m4_stage0p_control WHERE id = 1;

  UPDATE public.m4_stage0p_control
    SET capture_enabled = p_enabled,
        updated_at = now(),
        updated_by_note = 'actor_staff_id=' || v_actor_id
                           || ' approval_ref=' || coalesce(p_approval_ref, '(none-off)')
    WHERE id = 1;

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id,
                                before, after, reason)
  VALUES ('staff', v_actor_id, 'm4_stage0p_set_capture', 'm4_stage0p_control', '1',
          jsonb_build_object('capture_enabled', v_before),
          jsonb_build_object('capture_enabled', p_enabled), p_approval_ref)
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_before, p_enabled;
END;
$$;

ALTER FUNCTION m4_stage0p_set_capture(BOOLEAN, TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_set_capture(BOOLEAN, TEXT) FROM PUBLIC;

-- ===========================================================================
-- 5f. m4_stage0p_record_approval / m4_stage0p_revoke_approval - REV5 T4-04: bo p_actor_staff_id,
--     doc actor qua require_pinned_actor('m4.stage0p.approve').
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_record_approval(
  p_approval_ref TEXT,
  p_requested_enabled BOOLEAN,
  p_valid_from TIMESTAMPTZ,
  p_valid_until TIMESTAMPTZ,
  p_note TEXT
)
RETURNS TABLE(approval_ref TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE v_actor_id BIGINT; v_audit_id BIGINT;
BEGIN
  v_actor_id := m4_stage0p_require_pinned_actor('m4.stage0p.approve');

  IF p_approval_ref IS NULL OR length(btrim(p_approval_ref)) = 0 THEN
    RAISE EXCEPTION 'm4_stage0p_record_approval: approval_ref khong duoc rong';
  END IF;
  IF p_valid_until <= p_valid_from THEN
    RAISE EXCEPTION 'm4_stage0p_record_approval: valid_until phai sau valid_from';
  END IF;

  INSERT INTO public.m4_stage0p_capture_approvals
    (approval_ref, purpose_code, requested_enabled, valid_from, valid_until, recorded_by, note)
  VALUES (p_approval_ref, 'P12_PII_DETECTOR_EVAL', p_requested_enabled, p_valid_from, p_valid_until,
          v_actor_id, p_note);

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id, after)
  VALUES ('staff', v_actor_id, 'm4_stage0p_record_approval', 'm4_stage0p_capture_approval',
          p_approval_ref, jsonb_build_object('requested_enabled', p_requested_enabled,
                                              'valid_from', p_valid_from, 'valid_until', p_valid_until))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT p_approval_ref;
END;
$$;

ALTER FUNCTION m4_stage0p_record_approval(TEXT, BOOLEAN, TIMESTAMPTZ, TIMESTAMPTZ, TEXT)
  OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_record_approval(TEXT, BOOLEAN, TIMESTAMPTZ, TIMESTAMPTZ, TEXT)
  FROM PUBLIC;

CREATE OR REPLACE FUNCTION m4_stage0p_revoke_approval(
  p_approval_ref TEXT,
  p_reason TEXT
)
RETURNS TABLE(revoked_at TIMESTAMPTZ)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE v_actor_id BIGINT; v_audit_id BIGINT; v_now TIMESTAMPTZ := now();
BEGIN
  v_actor_id := m4_stage0p_require_pinned_actor('m4.stage0p.approve');

  IF p_reason IS NULL OR length(btrim(p_reason)) = 0 THEN
    RAISE EXCEPTION 'm4_stage0p_revoke_approval: reason khong duoc rong';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.m4_stage0p_capture_approvals WHERE approval_ref = p_approval_ref) THEN
    RAISE EXCEPTION 'm4_stage0p_revoke_approval: approval_ref % khong ton tai', p_approval_ref;
  END IF;
  IF EXISTS (SELECT 1 FROM public.m4_stage0p_capture_approval_revocations WHERE approval_ref = p_approval_ref) THEN
    RAISE EXCEPTION 'm4_stage0p_revoke_approval: approval_ref % da bi thu hoi truoc do', p_approval_ref;
  END IF;

  INSERT INTO public.m4_stage0p_capture_approval_revocations (approval_ref, revoked_by, revoked_at, reason)
  VALUES (p_approval_ref, v_actor_id, v_now, p_reason);

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id, after)
  VALUES ('staff', v_actor_id, 'm4_stage0p_revoke_approval', 'm4_stage0p_capture_approval',
          p_approval_ref, jsonb_build_object('reason', p_reason))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_now;
END;
$$;

ALTER FUNCTION m4_stage0p_revoke_approval(TEXT, TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_revoke_approval(TEXT, TEXT) FROM PUBLIC;

-- ===========================================================================
-- 5g0. m4_stage0p_record_normalization_approval / m4_stage0p_revoke_normalization_approval -
--      REV9 T8-03 (MOI). Cung mau immutable-record + revocation-event-rieng nhu record_approval/
--      revoke_approval (T3-05) o tren, nhung HOAN TOAN TACH BIET bang/hanh dong - khong tai dien
--      giai capture-ON approval cho normalization change.
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_record_normalization_approval(
  p_approval_ref TEXT,
  p_requested_version TEXT,
  p_valid_from TIMESTAMPTZ,
  p_valid_until TIMESTAMPTZ,
  p_note TEXT
)
RETURNS TABLE(approval_ref TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE v_actor_id BIGINT; v_audit_id BIGINT;
BEGIN
  v_actor_id := m4_stage0p_require_pinned_actor('m4.stage0p.approve');

  IF p_approval_ref IS NULL OR length(btrim(p_approval_ref)) = 0 THEN
    RAISE EXCEPTION 'm4_stage0p_record_normalization_approval: approval_ref khong duoc rong';
  END IF;
  IF p_requested_version IS NULL OR length(btrim(p_requested_version)) = 0 THEN
    RAISE EXCEPTION 'm4_stage0p_record_normalization_approval: requested_version khong duoc rong (T8-03)';
  END IF;
  IF p_valid_until <= p_valid_from THEN
    RAISE EXCEPTION 'm4_stage0p_record_normalization_approval: valid_until phai sau valid_from';
  END IF;

  INSERT INTO public.m4_stage0p_normalization_approvals
    (approval_ref, requested_version, valid_from, valid_until, recorded_by, note)
  VALUES (p_approval_ref, p_requested_version, p_valid_from, p_valid_until, v_actor_id, p_note);

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id, after)
  VALUES ('staff', v_actor_id, 'm4_stage0p_record_normalization_approval', 'm4_stage0p_normalization_approval',
          p_approval_ref, jsonb_build_object('requested_version', p_requested_version,
                                              'valid_from', p_valid_from, 'valid_until', p_valid_until))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT p_approval_ref;
END;
$$;

ALTER FUNCTION m4_stage0p_record_normalization_approval(TEXT, TEXT, TIMESTAMPTZ, TIMESTAMPTZ, TEXT)
  OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_record_normalization_approval(TEXT, TEXT, TIMESTAMPTZ, TIMESTAMPTZ, TEXT)
  FROM PUBLIC;

CREATE OR REPLACE FUNCTION m4_stage0p_revoke_normalization_approval(
  p_approval_ref TEXT,
  p_reason TEXT
)
RETURNS TABLE(revoked_at TIMESTAMPTZ)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE v_actor_id BIGINT; v_audit_id BIGINT; v_now TIMESTAMPTZ := now();
BEGIN
  v_actor_id := m4_stage0p_require_pinned_actor('m4.stage0p.approve');

  IF p_reason IS NULL OR length(btrim(p_reason)) = 0 THEN
    RAISE EXCEPTION 'm4_stage0p_revoke_normalization_approval: reason khong duoc rong';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.m4_stage0p_normalization_approvals WHERE approval_ref = p_approval_ref) THEN
    RAISE EXCEPTION 'm4_stage0p_revoke_normalization_approval: approval_ref % khong ton tai', p_approval_ref;
  END IF;
  IF EXISTS (SELECT 1 FROM public.m4_stage0p_normalization_approval_revocations WHERE approval_ref = p_approval_ref) THEN
    RAISE EXCEPTION 'm4_stage0p_revoke_normalization_approval: approval_ref % da bi thu hoi truoc do', p_approval_ref;
  END IF;

  INSERT INTO public.m4_stage0p_normalization_approval_revocations (approval_ref, revoked_by, revoked_at, reason)
  VALUES (p_approval_ref, v_actor_id, v_now, p_reason);

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id, after)
  VALUES ('staff', v_actor_id, 'm4_stage0p_revoke_normalization_approval', 'm4_stage0p_normalization_approval',
          p_approval_ref, jsonb_build_object('reason', p_reason))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_now;
END;
$$;

ALTER FUNCTION m4_stage0p_revoke_normalization_approval(TEXT, TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_revoke_normalization_approval(TEXT, TEXT) FROM PUBLIC;

-- ===========================================================================
-- 5g. m4_stage0p_seal_labels - REV5 T4-04: bo p_actor_staff_id, doc actor qua
--     require_pinned_actor('m4.stage0p.review'). T3-02/T3-06 (khong doi): doi hoi
--     status='collection_closed'; hash v2 bind them batch_id/normalization_version/truncated/
--     canonical_text_len.
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_seal_labels(
  p_batch_id UUID
)
RETURNS TABLE(sealed_hash TEXT, sample_count INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_actor_id BIGINT;
  v_batch RECORD;
  v_unlabeled INT;
  v_count INT;
  v_hash TEXT;
  v_audit_id BIGINT;
BEGIN
  v_actor_id := m4_stage0p_require_pinned_actor('m4.stage0p.review');

  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_seal_labels: batch_id khong ton tai';
  END IF;
  IF v_batch.status <> 'collection_closed' THEN
    RAISE EXCEPTION 'm4_stage0p_seal_labels: batch % phai o trang thai collection_closed truoc khi seal (status hien tai=%) - T3-02',
      p_batch_id, v_batch.status;
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

  -- REV7 T6-03: bump v2->v3 - them capture_excluded_count/capture_permanent_failed_count/
  -- capture_gate_policy (moi tu close_collection, chua tung nam trong hash chain) de "bind counts,
  -- gate version va quyet dinh closure vao tamper-evident evidence/hash" (yeu cau CA Review #6).
  SELECT encode(digest(
    'm4-stage0p-label-hash-v3|' || p_batch_id::text || '|' ||
    'capture_excluded=' || coalesce(v_batch.capture_excluded_count::text, 'null') || '|' ||
    'capture_permanent_failed=' || coalesce(v_batch.capture_permanent_failed_count::text, 'null') || '|' ||
    'capture_gate_policy=' || coalesce(v_batch.capture_gate_policy, 'null') || '|' ||
    string_agg(
      sample_id::text || ':' || normalization_version || ':' || truncated::text || ':' ||
      canonical_text_len::text || ':' || coalesce(labeled_slots::text, 'null'),
      '|' ORDER BY sample_id),
    'sha256'), 'hex')
    INTO v_hash
    FROM public.m4_shadow_review_samples WHERE selection_batch = p_batch_id;

  UPDATE public.m4_selection_batches
    SET labels_sealed_at = now(), labels_sealed_by = v_actor_id, labels_sealed_hash = v_hash,
        status = 'labels_sealed'
    WHERE batch_id = p_batch_id;

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id, after)
  VALUES ('staff', v_actor_id, 'm4_stage0p_seal_labels', 'm4_selection_batch',
          p_batch_id::text, jsonb_build_object('labels_sealed_hash', v_hash, 'sample_count', v_count))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_hash, v_count;
END;
$$;

ALTER FUNCTION m4_stage0p_seal_labels(UUID) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_seal_labels(UUID) FROM PUBLIC;

-- ===========================================================================
-- 5h. m4_stage0p_fetch_sealed_message - khong doi.
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
    RAISE EXCEPTION 'm4_stage0p_fetch_sealed_message: batch % chua sealed - KHONG duoc doc raw content', p_batch_id;
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
-- 5i. m4_stage0p_write_predictions - REV5:
--     - T4-02: XOA p_current_normalization_version - DB tu so sanh voi hang so HARDCODE
--       v_current_normalization_version (PHAI khop app/services/pii/stage0p_sampling.py:
--       NORMALIZATION_VERSION, bump ca 2 noi khi doi - cung quy uoc voi MATCHING_RULE_VERSION/
--       AGGREGATION_VERSION trong complete_evaluation).
--     - T4-05: tran exclusion doc tu bang m4_stage0p_exclusion_gate (khong hardcode 50%) - 2 dieu
--       kien: ty le exclusion <= max_exclusion_rate VA so conversation KHONG bi loai >=
--       min_non_excluded_conversations. Tra them non_excluded_conversation_count/gate_version.
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_write_predictions(
  p_batch_id UUID,
  p_expected_labels_sealed_hash TEXT,
  p_predictions JSONB,
  p_exclusions JSONB,
  p_detector_version TEXT,
  p_evaluation_batch TEXT
)
RETURNS TABLE(updated_count INT, excluded_count INT, result_hash TEXT,
              non_excluded_conversation_count INT, gate_version TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_current_normalization_version TEXT;
  v_batch RECORD;
  v_gate RECORD;
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
  v_row_norm_version TEXT;
  v_non_excluded_conv_count INT;
BEGIN
  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: batch_id khong ton tai';
  END IF;
  IF v_batch.status <> 'labels_sealed' THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: batch % phai o trang thai labels_sealed (status hien tai=%) - T3-02',
      p_batch_id, v_batch.status;
  END IF;
  IF v_batch.labels_sealed_hash IS DISTINCT FROM p_expected_labels_sealed_hash THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: labels_sealed_hash khong khop (stale/forged corpus reference)';
  END IF;

  SELECT eg.max_exclusion_rate, eg.min_non_excluded_conversations, eg.gate_version
    INTO v_gate FROM public.m4_stage0p_exclusion_gate AS eg WHERE eg.id = 1;
  IF v_gate IS NULL THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: exclusion gate config chua duoc thiet lap - tu choi ghi (fail-closed, T4-05)';
  END IF;

  -- REV8 T7-03: CA chi ro doc row is_current=true (REV7 T6-04) la SAI authority cho 1 batch DANG
  -- CHAY - neu registry doi SAU khi batch lock/capture nhung TRUOC prediction, 1 batch hop le
  -- theo version DA KHOA co the bi xem la mismatch hang loat mot cach sai lech. v_batch.
  -- normalization_version (da khoa tu luc lock_batch, FK dam bao luon ton tai trong registry) moi
  -- la expected version DUNG cho CHINH batch nay - "current" toan cuc chi nen quyet dinh version
  -- cho batch MOI (xem stage0p_sampling.py:lock_batch), khong phai authority cho batch dang chay.
  v_current_normalization_version := v_batch.normalization_version;

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

    IF NOT (v_item ->> 'reason' = ANY (ARRAY['normalization_version_mismatch'])) THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: exclusion reason khong nam trong allowlist (sample %): %',
        v_sample_id, v_item ->> 'reason';
    END IF;
    SELECT normalization_version INTO v_row_norm_version FROM public.m4_shadow_review_samples
      WHERE sample_id = v_sample_id AND selection_batch = p_batch_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: exclusion sample_id % khong thuoc batch %', v_sample_id, p_batch_id;
    END IF;
    -- T4-02: so sanh voi hang so HARDCODE (khong con nhan tu tham so caller).
    IF v_item ->> 'reason' = 'normalization_version_mismatch' AND v_row_norm_version = v_current_normalization_version THEN
      RAISE EXCEPTION 'm4_stage0p_write_predictions: exclusion normalization_version_mismatch SAI cho sample % (normalization_version thuc te (%) khop voi hien hanh (%)) - T3-03/T4-02',
        v_sample_id, v_row_norm_version, v_current_normalization_version;
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

  -- T4-05: 2 dieu kien tu bang exclusion_gate (khong hardcode).
  IF array_length(v_all_ids, 1) > 0
     AND coalesce(array_length(v_excl_ids, 1), 0)::numeric / array_length(v_all_ids, 1) > v_gate.max_exclusion_rate THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: ty le exclusion (%/%) vuot nguong % (gate_version=%) - INSUFFICIENT_DATA (T4-05)',
      coalesce(array_length(v_excl_ids, 1), 0), array_length(v_all_ids, 1), v_gate.max_exclusion_rate, v_gate.gate_version;
  END IF;

  SELECT count(DISTINCT conversation_ref) INTO v_non_excluded_conv_count
    FROM public.m4_shadow_review_samples
    WHERE selection_batch = p_batch_id AND sample_id = ANY (v_pred_ids);
  IF v_non_excluded_conv_count < v_gate.min_non_excluded_conversations THEN
    RAISE EXCEPTION 'm4_stage0p_write_predictions: so conversation khong bi loai (%) duoi nguong toi thieu % (gate_version=%) - INSUFFICIENT_DATA (T4-05)',
      v_non_excluded_conv_count, v_gate.min_non_excluded_conversations, v_gate.gate_version;
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

  SELECT encode(digest(
    'm4-stage0p-result-hash-v2|' || p_expected_labels_sealed_hash || '|' || p_detector_version || '|' ||
    p_evaluation_batch || '|' ||
    string_agg(
      sample_id::text || ':' || coalesce(predicted_slots::text, 'excluded:' || coalesce(prediction_excluded_reason, '')),
      '|' ORDER BY sample_id),
    'sha256'), 'hex')
    INTO v_result_hash
    FROM public.m4_shadow_review_samples WHERE selection_batch = p_batch_id;

  UPDATE public.m4_selection_batches
    SET predictions_written_at = now(), result_hash = v_result_hash, status = 'predictions_written',
        exclusion_gate_version = v_gate.gate_version
    WHERE batch_id = p_batch_id;

  INSERT INTO public.audit_log (actor_type, actor_ref, action, entity_type, entity_id, after)
  VALUES ('system', 'm4_stage0p_prediction_writer', 'm4_stage0p_write_predictions',
          'm4_selection_batch', p_batch_id::text,
          jsonb_build_object('updated_count', v_updated, 'excluded_count', v_excluded,
                              'result_hash', v_result_hash, 'detector_version', p_detector_version,
                              'evaluation_batch', p_evaluation_batch,
                              'non_excluded_conversation_count', v_non_excluded_conv_count,
                              'gate_version', v_gate.gate_version))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_updated, v_excluded, v_result_hash, v_non_excluded_conv_count, v_gate.gate_version;
END;
$$;

ALTER FUNCTION m4_stage0p_write_predictions(UUID, TEXT, JSONB, JSONB, TEXT, TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_write_predictions(UUID, TEXT, JSONB, JSONB, TEXT, TEXT) FROM PUBLIC;

-- ===========================================================================
-- 5j. m4_stage0p_complete_evaluation - REV5 T4-04: bo p_actor_staff_id, doc actor qua
--     require_pinned_actor('m4.stage0p.evaluate'). T3-04 (khong doi): DB TU TINH exact-span
--     metrics.
-- ===========================================================================
CREATE OR REPLACE FUNCTION m4_stage0p_complete_evaluation(
  p_batch_id UUID,
  p_expected_result_hash TEXT
)
RETURNS TABLE(completed_at TIMESTAMPTZ, report_hash TEXT, metrics JSONB)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_actor_id BIGINT;
  v_batch RECORD;
  v_uncovered INT;
  v_metrics JSONB;
  v_report_hash TEXT;
  v_audit_id BIGINT;
  v_now TIMESTAMPTZ := now();
BEGIN
  v_actor_id := m4_stage0p_require_pinned_actor('m4.stage0p.evaluate');

  SELECT * INTO v_batch FROM public.m4_selection_batches WHERE batch_id = p_batch_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: batch_id khong ton tai';
  END IF;
  IF v_batch.status <> 'predictions_written' THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: batch % phai o trang thai predictions_written (status hien tai=%) - T3-02',
      p_batch_id, v_batch.status;
  END IF;
  IF v_batch.result_hash IS DISTINCT FROM p_expected_result_hash THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: result_hash khong khop (stale/forged)';
  END IF;

  SELECT count(*) INTO v_uncovered FROM public.m4_shadow_review_samples
    WHERE selection_batch = p_batch_id AND predicted_slots IS NULL AND prediction_excluded_reason IS NULL;
  IF v_uncovered > 0 THEN
    RAISE EXCEPTION 'm4_stage0p_complete_evaluation: batch % con % sample chua co prediction/exclusion',
      p_batch_id, v_uncovered;
  END IF;

  WITH gt AS (
    SELECT s.sample_id, e ->> 'slot_type' AS slot_type, (e ->> 'start')::int AS start_pos, (e ->> 'end')::int AS end_pos
    FROM public.m4_shadow_review_samples s, jsonb_array_elements(coalesce(s.labeled_slots, '[]'::jsonb)) e
    WHERE s.selection_batch = p_batch_id AND s.prediction_excluded_reason IS NULL
  ),
  pred AS (
    SELECT s.sample_id, e ->> 'slot_type' AS slot_type, (e ->> 'start')::int AS start_pos, (e ->> 'end')::int AS end_pos
    FROM public.m4_shadow_review_samples s, jsonb_array_elements(coalesce(s.predicted_slots, '[]'::jsonb)) e
    WHERE s.selection_batch = p_batch_id AND s.prediction_excluded_reason IS NULL
  ),
  gt_counts AS (SELECT sample_id, slot_type, start_pos, end_pos, count(*) c FROM gt GROUP BY 1, 2, 3, 4),
  pred_counts AS (SELECT sample_id, slot_type, start_pos, end_pos, count(*) c FROM pred GROUP BY 1, 2, 3, 4),
  matched AS (
    SELECT coalesce(g.slot_type, p.slot_type) AS slot_type,
           LEAST(coalesce(g.c, 0), coalesce(p.c, 0)) AS tp,
           coalesce(g.c, 0) AS gt_c,
           coalesce(p.c, 0) AS pred_c
    FROM gt_counts g
    FULL OUTER JOIN pred_counts p
      ON g.sample_id = p.sample_id AND g.slot_type = p.slot_type
         AND g.start_pos = p.start_pos AND g.end_pos = p.end_pos
  ),
  agg AS (
    SELECT slot_type, sum(tp)::int AS tp, (sum(gt_c) - sum(tp))::int AS fn, (sum(pred_c) - sum(tp))::int AS fp
    FROM matched GROUP BY slot_type
  )
  SELECT jsonb_object_agg(
    slot_type,
    jsonb_build_object('tp', tp, 'fn', fn, 'fp', fp,
      'recall', CASE WHEN (tp + fn) > 0 THEN round(tp::numeric / (tp + fn), 6) ELSE NULL END,
      'precision', CASE WHEN (tp + fp) > 0 THEN round(tp::numeric / (tp + fp), 6) ELSE NULL END)
  )
  INTO v_metrics
  FROM agg;

  v_metrics := coalesce(v_metrics, '{}'::jsonb);

  v_report_hash := encode(
    digest('m4-stage0p-report-hash-v1|exact-span-v1|micro-v1|' || v_batch.result_hash || '|' || v_metrics::text,
           'sha256'), 'hex');

  UPDATE public.m4_selection_batches
    SET evaluation_completed_at = v_now, evaluation_completed_by = v_actor_id,
        evaluation_report_hash = v_report_hash, status = 'evaluation_completed'
    WHERE batch_id = p_batch_id;

  INSERT INTO public.audit_log (actor_type, actor_staff_id, action, entity_type, entity_id, after)
  VALUES ('staff', v_actor_id, 'm4_stage0p_complete_evaluation', 'm4_selection_batch',
          p_batch_id::text, jsonb_build_object('evaluation_report_hash', v_report_hash, 'metrics', v_metrics))
  RETURNING id INTO v_audit_id;

  RETURN QUERY SELECT v_now, v_report_hash, v_metrics;
END;
$$;

ALTER FUNCTION m4_stage0p_complete_evaluation(UUID, TEXT) OWNER TO alpha3s_m4_definer;
REVOKE EXECUTE ON FUNCTION m4_stage0p_complete_evaluation(UUID, TEXT) FROM PUBLIC;

-- Quyen NOI BO can cho toan bo ham hoat dong (chay boi alpha3s_m4_definer, khong phai caller)
GRANT SELECT ON public.messages TO alpha3s_m4_definer;
GRANT SELECT (id, customer_id) ON public.conversations TO alpha3s_m4_definer;
GRANT SELECT, UPDATE ON public.m4_selection_batches TO alpha3s_m4_definer;
GRANT SELECT, INSERT, UPDATE ON public.m4_shadow_review_samples TO alpha3s_m4_definer;
GRANT SELECT, UPDATE (capture_enabled, updated_at, updated_by_note) ON public.m4_stage0p_control
  TO alpha3s_m4_definer;
GRANT SELECT, INSERT ON public.m4_stage0p_capture_approvals TO alpha3s_m4_definer;
GRANT SELECT, INSERT ON public.m4_stage0p_capture_approval_revocations TO alpha3s_m4_definer;
-- REV9 T8-03.
GRANT SELECT, INSERT ON public.m4_stage0p_normalization_approvals TO alpha3s_m4_definer;
GRANT SELECT, INSERT ON public.m4_stage0p_normalization_approval_revocations TO alpha3s_m4_definer;
GRANT SELECT, INSERT, DELETE ON public.m4_stage0p_fetch_capability TO alpha3s_m4_definer;
GRANT SELECT, INSERT, UPDATE ON public.m4_stage0p_capture_progress TO alpha3s_m4_definer;
GRANT SELECT ON public.m4_stage0p_staff_permissions TO alpha3s_m4_definer;
GRANT SELECT ON public.m4_stage0p_exclusion_gate TO alpha3s_m4_definer;
-- T6-01: SELECT ... FOR UPDATE + UPDATE (failed_attempts/locked_until) tren credentials.
GRANT SELECT, UPDATE ON public.m4_stage0p_actor_credentials TO alpha3s_m4_definer;
-- T6-01: DELETE them (unpin_actor + tu don stale/expired row trong require_pinned_actor).
GRANT SELECT, INSERT, UPDATE, DELETE ON public.m4_stage0p_actor_session TO alpha3s_m4_definer;
-- T6-04: INSERT/UPDATE them (set_current_normalization_version - INSERT version moi + UPDATE
-- is_current tren row cu).
GRANT SELECT, INSERT, UPDATE ON public.m4_stage0p_normalization_registry TO alpha3s_m4_definer;
GRANT SELECT (id, is_active) ON public.staff_users TO alpha3s_m4_definer;
GRANT INSERT, UPDATE, SELECT (id) ON public.audit_log TO alpha3s_m4_definer;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_definer;

-- ===========================================================================
-- 6. 9 role least-privilege (REV5 them alpha3s_m4_actor_binder - T4-04).
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
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_approval_recorder') THEN
    CREATE ROLE alpha3s_m4_approval_recorder NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_m4_actor_binder') THEN
    CREATE ROLE alpha3s_m4_actor_binder NOLOGIN;
  END IF;
END $$;

-- Cung bug tren (fresh-DB reset regression) - 9 role nghiep vu cung khong co USAGE tren schema
-- public tren 1 DB sach, nen KHONG the resolve duoc bat ky ham m4 nao caller can goi truc tiep.
GRANT USAGE ON SCHEMA public TO alpha3s_m4_sample_collector, alpha3s_m4_sample_reviewer_api,
  alpha3s_m4_sample_evaluator, alpha3s_m4_prediction_writer, alpha3s_m4_sample_purge,
  alpha3s_m4_control_plane, alpha3s_m4_pending_checker, alpha3s_m4_approval_recorder,
  alpha3s_m4_actor_binder;

-- 6a. collector: EXECUTE peek(1 tham so)/fetch_content/record_sample + close_collection +
-- seed_capture_progress/mark_candidate_outcome (MOI, T4-03).
GRANT SELECT (id, customer_id, created_at) ON orders TO alpha3s_m4_sample_collector;
GRANT SELECT (id, customer_id, created_at) ON conversations TO alpha3s_m4_sample_collector;
GRANT SELECT (batch_id) ON m4_selection_batches TO alpha3s_m4_sample_collector;
GRANT INSERT ON m4_selection_batches TO alpha3s_m4_sample_collector;
GRANT EXECUTE ON FUNCTION m4_stage0p_peek_next_candidate(UUID) TO alpha3s_m4_sample_collector;
GRANT EXECUTE ON FUNCTION m4_stage0p_fetch_message_content(UUID, BIGINT, BIGINT) TO alpha3s_m4_sample_collector;
GRANT EXECUTE ON FUNCTION m4_stage0p_record_sample(UUID, BIGINT, BIGINT, UUID, BYTEA, INT, BOOLEAN, BYTEA)
  TO alpha3s_m4_sample_collector;
GRANT EXECUTE ON FUNCTION m4_stage0p_close_collection(UUID) TO alpha3s_m4_sample_collector;
GRANT EXECUTE ON FUNCTION m4_stage0p_seed_capture_progress(UUID) TO alpha3s_m4_sample_collector;
GRANT EXECUTE ON FUNCTION m4_stage0p_mark_candidate_outcome(UUID, BIGINT, BIGINT, TEXT, TEXT)
  TO alpha3s_m4_sample_collector;
-- T5-04: lock_batch() doc normalization version hien hanh tu registry (nguon THAT duy nhat).
GRANT SELECT ON m4_stage0p_normalization_registry TO alpha3s_m4_sample_collector;

-- 6b. reviewer-api: SELECT/UPDATE nhan TRUOC seal; EXECUTE seal_labels (REV5: 1 tham so).
GRANT SELECT (sample_id, encrypted_message, canonical_text_len, normalization_version,
              customer_ref, conversation_ref, captured_at, label_status, selection_batch,
              labeled_slots)
  ON m4_shadow_review_samples TO alpha3s_m4_sample_reviewer_api;
GRANT UPDATE (labeled_slots, label_status) ON m4_shadow_review_samples TO alpha3s_m4_sample_reviewer_api;
GRANT EXECUTE ON FUNCTION m4_stage0p_seal_labels(UUID) TO alpha3s_m4_sample_reviewer_api;
GRANT INSERT ON audit_log TO alpha3s_m4_sample_reviewer_api;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_sample_reviewer_api;

-- 6c. evaluator: SELECT chi cot nhan/du doan + metadata, KHONG noi dung/dinh danh. EXECUTE
-- complete_evaluation (REV5: 2 tham so - khong con actor).
GRANT SELECT (sample_id, label_status, labeled_slots, predicted_slots, prediction_excluded_reason,
              canonical_text_len, normalization_version, detector_version, evaluation_batch,
              selection_batch, truncated)
  ON m4_shadow_review_samples TO alpha3s_m4_sample_evaluator;
GRANT SELECT (batch_id, labels_sealed_at, labels_sealed_hash, predictions_written_at, result_hash,
              evaluation_completed_at)
  ON m4_selection_batches TO alpha3s_m4_sample_evaluator;
GRANT EXECUTE ON FUNCTION m4_stage0p_complete_evaluation(UUID, TEXT) TO alpha3s_m4_sample_evaluator;
GRANT INSERT ON audit_log TO alpha3s_m4_sample_evaluator;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_sample_evaluator;

-- 6d. prediction_writer: KHONG SELECT truc tiep tren cot noi dung; CHI EXECUTE fetch_sealed_message
-- + write_predictions (REV5: 6 tham so - bo p_current_normalization_version, T4-02).
-- REV8 T7-03: them normalization_version - run_prediction_writer gio doc version DA KHOA cua
-- CHINH batch (khong con goi get_current_normalization_version() toan cuc, xem stage0p_prediction.py).
GRANT SELECT (batch_id, labels_sealed_hash, normalization_version) ON m4_selection_batches
  TO alpha3s_m4_prediction_writer;
GRANT EXECUTE ON FUNCTION m4_stage0p_fetch_sealed_message(UUID, UUID) TO alpha3s_m4_prediction_writer;
GRANT EXECUTE ON FUNCTION m4_stage0p_write_predictions(UUID, TEXT, JSONB, JSONB, TEXT, TEXT)
  TO alpha3s_m4_prediction_writer;
-- T5-04: pre-filter client-side doc normalization version hien hanh tu registry.
GRANT SELECT ON m4_stage0p_normalization_registry TO alpha3s_m4_prediction_writer;

-- 6e. purge: DELETE + SELECT chi cot can cho WHERE.
GRANT SELECT (customer_ref, expires_at, sample_id, selection_batch) ON m4_shadow_review_samples
  TO alpha3s_m4_sample_purge;
GRANT DELETE ON m4_shadow_review_samples TO alpha3s_m4_sample_purge;
GRANT SELECT (batch_id, evaluation_completed_at) ON m4_selection_batches TO alpha3s_m4_sample_purge;

-- 6f. control_plane: KHONG UPDATE truc tiep tren control; CHI EXECUTE set_capture (REV5: 2 tham so).
GRANT SELECT (capture_enabled, updated_at) ON m4_stage0p_control TO alpha3s_m4_control_plane;
GRANT EXECUTE ON FUNCTION m4_stage0p_set_capture(BOOLEAN, TEXT) TO alpha3s_m4_control_plane;

-- 6g. pending_checker: CHI role duoc doc customers.psid trong pham vi M4.
GRANT SELECT (id, psid) ON customers TO alpha3s_m4_pending_checker;
GRANT INSERT ON audit_log TO alpha3s_m4_pending_checker;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO alpha3s_m4_pending_checker;

-- 6h. approval_recorder: KHONG INSERT/SELECT bang truc tiep; CHI EXECUTE record_approval +
-- revoke_approval (REV5: 5/2 tham so - bo p_actor_staff_id, T4-04) + set_current_normalization_
-- version (REV7 T6-04, MOI - cung doi hoi quyen m4.stage0p.approve nen dat chung role).
GRANT EXECUTE ON FUNCTION m4_stage0p_record_approval(TEXT, BOOLEAN, TIMESTAMPTZ, TIMESTAMPTZ, TEXT)
  TO alpha3s_m4_approval_recorder;
GRANT EXECUTE ON FUNCTION m4_stage0p_revoke_approval(TEXT, TEXT) TO alpha3s_m4_approval_recorder;
GRANT EXECUTE ON FUNCTION m4_stage0p_set_current_normalization_version(TEXT, TEXT)
  TO alpha3s_m4_approval_recorder;
-- REV9 T8-03 (MOI): approval record THAT rieng cho normalization version change.
GRANT EXECUTE ON FUNCTION m4_stage0p_record_normalization_approval(TEXT, TEXT, TIMESTAMPTZ, TIMESTAMPTZ, TEXT)
  TO alpha3s_m4_approval_recorder;
GRANT EXECUTE ON FUNCTION m4_stage0p_revoke_normalization_approval(TEXT, TEXT)
  TO alpha3s_m4_approval_recorder;

-- 6i. actor_binder - REV5 T4-04 (MOI): role RIENG, CHI EXECUTE pin_actor + unpin_actor (REV7
-- T6-01, MOI). Dai dien lop trung gian DA xac thuc staff (vd HTTP session/JWT) truoc khi goi vao
-- Stage 0P - tach biet HOAN TOAN moi role nghiep vu khac (mot holder cua
-- alpha3s_m4_approval_recorder KHONG the tu pin actor).
GRANT EXECUTE ON FUNCTION m4_stage0p_pin_actor(BIGINT, TEXT) TO alpha3s_m4_actor_binder;
GRANT EXECUTE ON FUNCTION m4_stage0p_unpin_actor() TO alpha3s_m4_actor_binder;

-- 6j. DSR: process_deletion() qua runtime alpha3s_app.
GRANT DELETE ON m4_shadow_review_samples TO alpha3s_app;
GRANT SELECT (customer_ref) ON m4_shadow_review_samples TO alpha3s_app;

-- runtime app + vendor-path: KHONG quyen nao khac ngoai DSR delete o tren.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_vendor_path') THEN
    REVOKE ALL ON m4_shadow_review_samples, m4_selection_batches, m4_stage0p_control,
      m4_stage0p_capture_approvals, m4_stage0p_capture_approval_revocations,
      m4_stage0p_fetch_capability, m4_stage0p_capture_progress, m4_stage0p_staff_permissions,
      m4_stage0p_exclusion_gate, m4_stage0p_actor_credentials, m4_stage0p_actor_session,
      m4_stage0p_normalization_registry, m4_stage0p_normalization_approvals,
      m4_stage0p_normalization_approval_revocations FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_peek_next_candidate(UUID) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_fetch_message_content(UUID, BIGINT, BIGINT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_record_sample(UUID, BIGINT, BIGINT, UUID, BYTEA, INT, BOOLEAN, BYTEA)
      FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_close_collection(UUID) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_seed_capture_progress(UUID) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_mark_candidate_outcome(UUID, BIGINT, BIGINT, TEXT, TEXT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_pin_actor(BIGINT, TEXT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_unpin_actor() FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_set_current_normalization_version(TEXT, TEXT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_set_capture(BOOLEAN, TEXT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_record_approval(TEXT, BOOLEAN, TIMESTAMPTZ, TIMESTAMPTZ, TEXT)
      FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_revoke_approval(TEXT, TEXT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_record_normalization_approval(TEXT, TEXT, TIMESTAMPTZ, TIMESTAMPTZ, TEXT)
      FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_revoke_normalization_approval(TEXT, TEXT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_seal_labels(UUID) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_fetch_sealed_message(UUID, UUID) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_write_predictions(UUID, TEXT, JSONB, JSONB, TEXT, TEXT) FROM alpha3s_vendor_path;
    REVOKE EXECUTE ON FUNCTION m4_stage0p_complete_evaluation(UUID, TEXT) FROM alpha3s_vendor_path;
  END IF;
END $$;

-- ===========================================================================
-- 7. Postcondition fail-closed - REV5: chung minh T4-01..05 (cong voi toan bo bat bien
--    REV2/REV3/REV4 truoc do)
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
  IF to_regclass('public.m4_stage0p_capture_approval_revocations') IS NULL THEN
    problems := problems || ' approval_revocations_table_missing'; END IF;
  IF to_regclass('public.m4_stage0p_fetch_capability') IS NULL THEN
    problems := problems || ' fetch_capability_table_missing'; END IF;
  IF to_regclass('public.m4_stage0p_capture_progress') IS NULL THEN
    problems := problems || ' capture_progress_table_missing'; END IF;
  IF to_regclass('public.m4_stage0p_staff_permissions') IS NULL THEN
    problems := problems || ' staff_permissions_table_missing'; END IF;
  IF to_regclass('public.m4_stage0p_exclusion_gate') IS NULL THEN
    problems := problems || ' exclusion_gate_table_missing'; END IF;
  IF to_regclass('public.m4_stage0p_actor_credentials') IS NULL THEN
    problems := problems || ' actor_credentials_table_missing'; END IF;
  IF to_regclass('public.m4_stage0p_actor_session') IS NULL THEN
    problems := problems || ' actor_session_table_missing'; END IF;
  IF to_regclass('public.m4_stage0p_normalization_registry') IS NULL THEN
    problems := problems || ' normalization_registry_table_missing'; END IF;
  IF (SELECT count(*) FROM m4_stage0p_control) <> 1 THEN
    problems := problems || ' control_not_singleton'; END IF;
  IF (SELECT capture_enabled FROM m4_stage0p_control WHERE id=1) IS DISTINCT FROM FALSE THEN
    problems := problems || ' control_not_default_off'; END IF;
  IF (SELECT count(*) FROM m4_stage0p_exclusion_gate) <> 1 THEN
    problems := problems || ' exclusion_gate_not_singleton'; END IF;
  IF (SELECT count(*) FROM m4_stage0p_normalization_registry WHERE is_current) <> 1 THEN
    problems := problems || ' normalization_registry_no_single_current'; END IF;
  IF to_regclass('public.m4_stage0p_normalization_registry') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'm4_normalization_registry_guard') THEN
    problems := problems || ' normalization_registry_guard_trigger_missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'm4_batch_normalization_version_fk') THEN
    problems := problems || ' batch_normalization_version_fk_missing'; END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_m4_definer'
                 AND NOT rolsuper AND NOT rolcreaterole AND NOT rolcreatedb) THEN
    problems := problems || ' definer_role_privileged'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_m4_actor_binder') THEN
    problems := problems || ' actor_binder_role_missing'; END IF;

  IF EXISTS (
    SELECT 1 FROM pg_proc WHERE proname IN (
      'm4_stage0p_peek_next_candidate','m4_stage0p_fetch_message_content','m4_stage0p_record_sample',
      'm4_stage0p_close_collection','m4_stage0p_seed_capture_progress','m4_stage0p_mark_candidate_outcome',
      'm4_stage0p_pin_actor','m4_stage0p_require_pinned_actor','m4_stage0p_set_capture',
      'm4_stage0p_record_approval','m4_stage0p_revoke_approval','m4_stage0p_seal_labels',
      'm4_stage0p_fetch_sealed_message','m4_stage0p_write_predictions','m4_stage0p_complete_evaluation',
      'm4_stage0p_block_label_after_seal','m4_stage0p_record_normalization_approval',
      'm4_stage0p_revoke_normalization_approval')
      AND (proowner::regrole::text <> 'alpha3s_m4_definer' OR prosecdef IS NOT TRUE
           OR proconfig IS NULL
           OR NOT EXISTS (SELECT 1 FROM unnest(proconfig) c WHERE c LIKE 'search_path=%'))
  ) THEN
    problems := problems || ' definer_function_hardening_incomplete'; END IF;

  IF has_function_privilege('public', 'm4_stage0p_peek_next_candidate(uuid)', 'EXECUTE') THEN
    problems := problems || ' peek_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_fetch_message_content(uuid,bigint,bigint)', 'EXECUTE') THEN
    problems := problems || ' fetch_content_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_record_sample(uuid,bigint,bigint,uuid,bytea,int,boolean,bytea)', 'EXECUTE') THEN
    problems := problems || ' record_sample_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_close_collection(uuid)', 'EXECUTE') THEN
    problems := problems || ' close_collection_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_seed_capture_progress(uuid)', 'EXECUTE') THEN
    problems := problems || ' seed_capture_progress_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_mark_candidate_outcome(uuid,bigint,bigint,text,text)', 'EXECUTE') THEN
    problems := problems || ' mark_candidate_outcome_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_pin_actor(bigint,text)', 'EXECUTE') THEN
    problems := problems || ' pin_actor_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_require_pinned_actor(text)', 'EXECUTE') THEN
    problems := problems || ' require_pinned_actor_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_set_capture(boolean,text)', 'EXECUTE') THEN
    problems := problems || ' set_capture_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_record_approval(text,boolean,timestamptz,timestamptz,text)', 'EXECUTE') THEN
    problems := problems || ' record_approval_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_revoke_approval(text,text)', 'EXECUTE') THEN
    problems := problems || ' revoke_approval_execute_public'; END IF;
  IF has_function_privilege('public',
       'm4_stage0p_record_normalization_approval(text,text,timestamptz,timestamptz,text)', 'EXECUTE') THEN
    problems := problems || ' record_normalization_approval_execute_public_dup'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_revoke_normalization_approval(text,text)', 'EXECUTE') THEN
    problems := problems || ' revoke_normalization_approval_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_seal_labels(uuid)', 'EXECUTE') THEN
    problems := problems || ' seal_labels_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_fetch_sealed_message(uuid,uuid)', 'EXECUTE') THEN
    problems := problems || ' fetch_sealed_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_write_predictions(uuid,text,jsonb,jsonb,text,text)', 'EXECUTE') THEN
    problems := problems || ' write_predictions_execute_public'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_complete_evaluation(uuid,text)', 'EXECUTE') THEN
    problems := problems || ' complete_evaluation_execute_public'; END IF;

  IF NOT has_function_privilege('alpha3s_m4_sample_collector',
       'm4_stage0p_peek_next_candidate(uuid)', 'EXECUTE') THEN
    problems := problems || ' collector_no_execute_peek'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_collector',
       'm4_stage0p_fetch_message_content(uuid,bigint,bigint)', 'EXECUTE') THEN
    problems := problems || ' collector_no_execute_fetch_content'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_collector',
       'm4_stage0p_record_sample(uuid,bigint,bigint,uuid,bytea,int,boolean,bytea)', 'EXECUTE') THEN
    problems := problems || ' collector_no_execute_record_sample'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_collector',
       'm4_stage0p_close_collection(uuid)', 'EXECUTE') THEN
    problems := problems || ' collector_no_execute_close_collection'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_collector',
       'm4_stage0p_seed_capture_progress(uuid)', 'EXECUTE') THEN
    problems := problems || ' collector_no_execute_seed_progress'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_collector',
       'm4_stage0p_mark_candidate_outcome(uuid,bigint,bigint,text,text)', 'EXECUTE') THEN
    problems := problems || ' collector_no_execute_mark_outcome'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_actor_binder',
       'm4_stage0p_pin_actor(bigint,text)', 'EXECUTE') THEN
    problems := problems || ' actor_binder_no_execute_pin'; END IF;
  IF has_function_privilege('alpha3s_m4_control_plane', 'm4_stage0p_pin_actor(bigint,text)', 'EXECUTE') THEN
    problems := problems || ' control_plane_can_pin_actor'; END IF;
  IF has_function_privilege('alpha3s_m4_approval_recorder', 'm4_stage0p_pin_actor(bigint,text)', 'EXECUTE') THEN
    problems := problems || ' approval_recorder_can_pin_actor'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_control_plane',
       'm4_stage0p_set_capture(boolean,text)', 'EXECUTE') THEN
    problems := problems || ' control_plane_no_execute_set_capture'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_approval_recorder',
       'm4_stage0p_record_approval(text,boolean,timestamptz,timestamptz,text)', 'EXECUTE') THEN
    problems := problems || ' approval_recorder_no_execute_record'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_approval_recorder',
       'm4_stage0p_revoke_approval(text,text)', 'EXECUTE') THEN
    problems := problems || ' approval_recorder_no_execute_revoke'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_reviewer_api',
       'm4_stage0p_seal_labels(uuid)', 'EXECUTE') THEN
    problems := problems || ' reviewer_no_execute_seal'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_prediction_writer',
       'm4_stage0p_fetch_sealed_message(uuid,uuid)', 'EXECUTE') THEN
    problems := problems || ' prediction_writer_no_execute_fetch_sealed'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_prediction_writer',
       'm4_stage0p_write_predictions(uuid,text,jsonb,jsonb,text,text)', 'EXECUTE') THEN
    problems := problems || ' prediction_writer_no_execute_write'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_sample_evaluator',
       'm4_stage0p_complete_evaluation(uuid,text)', 'EXECUTE') THEN
    problems := problems || ' evaluator_no_execute_complete'; END IF;

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
  IF has_table_privilege('alpha3s_m4_sample_collector','m4_stage0p_fetch_capability','SELECT') THEN
    problems := problems || ' collector_can_select_fetch_capability'; END IF;
  IF has_table_privilege('alpha3s_m4_sample_collector','m4_stage0p_fetch_capability','INSERT') THEN
    problems := problems || ' collector_can_insert_fetch_capability'; END IF;
  IF has_table_privilege('alpha3s_m4_sample_collector','m4_stage0p_actor_session','SELECT') THEN
    problems := problems || ' collector_can_select_actor_session'; END IF;
  IF has_table_privilege('alpha3s_m4_actor_binder','m4_stage0p_actor_credentials','SELECT') THEN
    problems := problems || ' actor_binder_can_select_actor_credentials'; END IF;
  IF has_table_privilege('alpha3s_m4_actor_binder','m4_stage0p_actor_session','SELECT') THEN
    problems := problems || ' actor_binder_can_select_actor_session'; END IF;

  -- REV7 T6-01: pin_secret KHONG con plaintext; unpin_actor CHI actor_binder EXECUTE duoc.
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name='m4_stage0p_actor_credentials' AND column_name='pin_secret') THEN
    problems := problems || ' actor_credentials_still_has_plaintext_pin_secret_column'; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='m4_stage0p_actor_credentials' AND column_name='pin_secret_hash') THEN
    problems := problems || ' actor_credentials_missing_pin_secret_hash_column'; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='m4_stage0p_actor_session' AND column_name='session_nonce') THEN
    problems := problems || ' actor_session_missing_session_nonce_column'; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='m4_stage0p_actor_session' AND column_name='expires_at') THEN
    problems := problems || ' actor_session_missing_expires_at_column'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_unpin_actor()', 'EXECUTE') THEN
    problems := problems || ' unpin_actor_execute_public'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_actor_binder', 'm4_stage0p_unpin_actor()', 'EXECUTE') THEN
    problems := problems || ' actor_binder_no_execute_unpin'; END IF;
  IF has_function_privilege('public', 'm4_stage0p_set_current_normalization_version(text,text)', 'EXECUTE') THEN
    problems := problems || ' set_current_normalization_version_execute_public'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_approval_recorder',
       'm4_stage0p_set_current_normalization_version(text,text)', 'EXECUTE') THEN
    problems := problems || ' approval_recorder_no_execute_set_normalization_version'; END IF;

  -- REV9 T8-03: normalization approval authority - table ton tai + EXECUTE dung role.
  IF to_regclass('public.m4_stage0p_normalization_approvals') IS NULL THEN
    problems := problems || ' normalization_approvals_table_missing'; END IF;
  IF to_regclass('public.m4_stage0p_normalization_approval_revocations') IS NULL THEN
    problems := problems || ' normalization_approval_revocations_table_missing'; END IF;
  IF has_function_privilege('public',
       'm4_stage0p_record_normalization_approval(text,text,timestamptz,timestamptz,text)', 'EXECUTE') THEN
    problems := problems || ' record_normalization_approval_execute_public'; END IF;
  IF has_function_privilege('public',
       'm4_stage0p_revoke_normalization_approval(text,text)', 'EXECUTE') THEN
    problems := problems || ' revoke_normalization_approval_execute_public'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_approval_recorder',
       'm4_stage0p_record_normalization_approval(text,text,timestamptz,timestamptz,text)', 'EXECUTE') THEN
    problems := problems || ' approval_recorder_no_execute_record_normalization_approval'; END IF;
  IF NOT has_function_privilege('alpha3s_m4_approval_recorder',
       'm4_stage0p_revoke_normalization_approval(text,text)', 'EXECUTE') THEN
    problems := problems || ' approval_recorder_no_execute_revoke_normalization_approval'; END IF;

  -- REV7 T6-02: fetch_capability co digest; REV7 T6-03: batch co capture_gate_policy.
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='m4_stage0p_fetch_capability' AND column_name='fetched_canonical_digest') THEN
    problems := problems || ' fetch_capability_missing_canonical_digest_column'; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='m4_selection_batches' AND column_name='capture_gate_policy') THEN
    problems := problems || ' batch_missing_capture_gate_policy_column'; END IF;

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

  IF has_table_privilege('alpha3s_m4_approval_recorder','m4_stage0p_capture_approvals','INSERT') THEN
    problems := problems || ' approval_recorder_has_direct_insert'; END IF;
  IF has_table_privilege('alpha3s_m4_approval_recorder','m4_stage0p_capture_approvals','SELECT') THEN
    problems := problems || ' approval_recorder_has_direct_select'; END IF;
  IF has_table_privilege('alpha3s_m4_approval_recorder','m4_stage0p_capture_approval_revocations','INSERT') THEN
    problems := problems || ' approval_recorder_has_direct_insert_revocations'; END IF;
  IF has_table_privilege('alpha3s_m4_control_plane','m4_stage0p_capture_approvals','INSERT') THEN
    problems := problems || ' control_plane_can_insert_approval'; END IF;
  IF has_table_privilege('alpha3s_m4_control_plane','m4_stage0p_capture_approvals','SELECT') THEN
    problems := problems || ' control_plane_can_select_approval'; END IF;
  IF has_table_privilege('alpha3s_m4_sample_collector','m4_stage0p_capture_approvals','INSERT') THEN
    problems := problems || ' collector_can_insert_approval'; END IF;

  -- REV5 T4-04: khong role m4 nghiep vu nao (ngoai actor_binder) duoc EXECUTE pin_actor; khong
  -- role nao duoc doc/ghi truc tiep bang staff_permissions.
  IF has_table_privilege('alpha3s_m4_sample_collector','m4_stage0p_staff_permissions','SELECT') THEN
    problems := problems || ' collector_can_select_staff_permissions'; END IF;
  IF has_table_privilege('alpha3s_m4_approval_recorder','m4_stage0p_staff_permissions','INSERT') THEN
    problems := problems || ' approval_recorder_can_insert_staff_permissions'; END IF;
  IF has_table_privilege('public','m4_stage0p_staff_permissions','SELECT') THEN
    problems := problems || ' public_can_select_staff_permissions'; END IF;
  IF has_table_privilege('public','m4_stage0p_exclusion_gate','SELECT') THEN
    problems := problems || ' public_can_select_exclusion_gate'; END IF;
  IF has_table_privilege('alpha3s_m4_prediction_writer','m4_stage0p_exclusion_gate','UPDATE') THEN
    problems := problems || ' prediction_writer_can_update_exclusion_gate'; END IF;

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
    IF has_function_privilege('alpha3s_vendor_path', 'm4_stage0p_pin_actor(bigint,text)','EXECUTE') THEN
      problems := problems || ' vendor_can_execute_pin_actor'; END IF;
    IF has_function_privilege('alpha3s_vendor_path', 'm4_stage0p_unpin_actor()','EXECUTE') THEN
      problems := problems || ' vendor_can_execute_unpin_actor'; END IF;
    IF has_function_privilege('alpha3s_vendor_path',
                              'm4_stage0p_set_current_normalization_version(text,text)','EXECUTE') THEN
      problems := problems || ' vendor_can_execute_set_normalization_version'; END IF;
    IF has_function_privilege('alpha3s_vendor_path',
         'm4_stage0p_record_normalization_approval(text,text,timestamptz,timestamptz,text)','EXECUTE') THEN
      problems := problems || ' vendor_can_execute_record_normalization_approval'; END IF;
    IF has_function_privilege('alpha3s_vendor_path',
                              'm4_stage0p_revoke_normalization_approval(text,text)','EXECUTE') THEN
      problems := problems || ' vendor_can_execute_revoke_normalization_approval'; END IF;
  END IF;

  IF has_table_privilege('public','m4_shadow_review_samples','SELECT') THEN
    problems := problems || ' public_can_select_sample'; END IF;
  IF has_table_privilege('public','m4_selection_batches','SELECT') THEN
    problems := problems || ' public_can_select_batches'; END IF;
  IF has_table_privilege('public','m4_stage0p_control','SELECT') THEN
    problems := problems || ' public_can_select_control'; END IF;
  IF has_table_privilege('public','m4_stage0p_capture_approvals','SELECT') THEN
    problems := problems || ' public_can_select_approvals'; END IF;
  IF has_table_privilege('public','m4_stage0p_capture_approval_revocations','SELECT') THEN
    problems := problems || ' public_can_select_approval_revocations'; END IF;
  IF has_table_privilege('public','m4_stage0p_normalization_approvals','SELECT') THEN
    problems := problems || ' public_can_select_normalization_approvals'; END IF;
  IF has_table_privilege('public','m4_stage0p_normalization_approval_revocations','SELECT') THEN
    problems := problems || ' public_can_select_normalization_approval_revocations'; END IF;
  IF has_table_privilege('public','m4_stage0p_fetch_capability','SELECT') THEN
    problems := problems || ' public_can_select_fetch_capability'; END IF;
  IF has_table_privilege('public','m4_stage0p_capture_progress','SELECT') THEN
    problems := problems || ' public_can_select_capture_progress'; END IF;
  IF has_table_privilege('public','m4_stage0p_actor_credentials','SELECT') THEN
    problems := problems || ' public_can_select_actor_credentials'; END IF;
  IF has_table_privilege('public','m4_stage0p_actor_session','SELECT') THEN
    problems := problems || ' public_can_select_actor_session'; END IF;
  IF has_table_privilege('public','m4_stage0p_normalization_registry','SELECT') THEN
    problems := problems || ' public_can_select_normalization_registry'; END IF;

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

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'public.m4_selection_batches'::regclass
      AND pg_get_constraintdef(oid) LIKE '%collection_closed%'
      AND pg_get_constraintdef(oid) LIKE '%evaluation_completed%'
  ) THEN
    problems := problems || ' status_state_machine_incomplete'; END IF;

  -- REV5 T4-03: capture_progress status CHECK phai co du 5 gia tri.
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'public.m4_stage0p_capture_progress'::regclass
      AND pg_get_constraintdef(oid) LIKE '%retryable_failed%'
      AND pg_get_constraintdef(oid) LIKE '%permanent_failed%'
  ) THEN
    problems := problems || ' capture_progress_state_machine_incomplete'; END IF;

  -- REV5 T4-05: gate config phai la de xuat 10%/200 (chua PO chinh thuc, nhung phai la gia tri
  -- CA de xuat - khong duoc am tham quay lai 50% cu).
  IF NOT EXISTS (
    SELECT 1 FROM m4_stage0p_exclusion_gate
    WHERE id = 1 AND max_exclusion_rate = 0.10 AND min_non_excluded_conversations = 200
  ) THEN
    problems := problems || ' exclusion_gate_not_ca_proposed_default'; END IF;

  IF problems <> '' THEN
    RAISE EXCEPTION '039 postcondition FAIL -%', problems; END IF;
END $$;
