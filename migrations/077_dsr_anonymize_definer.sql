-- 077 — CA Review 415 §3.2 + CA Review 416: duong DSR QUYEN HEP cho kho bat bien/append-only.
-- Van de: audit_log/order_events/inventory_movements/address_*/ghn_shipment_create_*/fulfillment_conversation_events/
-- payment_events/shipment_delivery_attempts bi trigger (va REVOKE cho alpha3s_app) cam UPDATE -> sau khi khach xoa du
-- lieu van con PSID/ChatID/dia chi/ten nguoi nhan trong DB active.
-- Giai phap (KHONG mo quyen UPDATE chung):
--   1. Role NOLOGIN `alpha3s_dsr` — khong ai dang nhap/khong role ung dung nao la thanh vien.
--   2. Hai ham SECURITY DEFINER (OWNER alpha3s_dsr) la duong DUY NHAT:
--      - `dsr_open_request(p_ref)`: tao yeu cau xoa + GAN subject (customers.id — ID noi bo, KHONG luu PSID) ngay luc
--        tao, tren dong customer khoa FOR UPDATE. CA 417: subject gan TRUOC khi cho phep xoa, qua duong DB kiem soat.
--      - `dsr_erase_subject(p_code)`: CHI nhan ma; subject lay TU yeu cau (khoa FOR UPDATE) -> caller khong the ghep ma
--        cua A voi customer B. CA 416: caller KHONG truyen dinh danh/PII — ham TU doc PSID/ChatID/ten/SDT/dia chi tu
--        chinh dong customer (khoa), don va draft cua customer do; 1 ma = 1 lan (erased_at); tu tombstone customer.
--      - Trigger ddr_subject_guard: subject_customer_id/erased_at CHI do alpha3s_dsr ghi; role khac (ke ca app) khong
--        INSERT yeu cau co subject va khong doi/xoa subject/erased_at da gan.
-- Moi UPDATE gioi han bang LIEN KET chac chan (customer_id/order_id/payment_id/shipment_id/
--      operation_id/resolution_id/entity_id cua chinh subject, hoac so khop BANG nguyen truong voi dinh danh duy nhat).
--      KHONG dung gia tri PII lam khoa so huu, KHONG LIKE/wildcard. Gia tri PII chi duoc THAY BEN TRONG dong da lien ket.
--   3. Quyen cua alpha3s_dsr: SELECT + UPDATE THEO COT (chi cot dinh danh), DELETE pii_slots, INSERT audit_log.
--   4. Trigger bat bien them DUNG 1 ngoai le: TG_OP='UPDATE' AND current_user='alpha3s_dsr'. DELETE van cam; cac cot
--      nghiep vu (so tien/trang thai/ma van don/ma don...) KHONG duoc cap quyen nen khong doi duoc.
-- Giu toan ven so: thay PSID/ChatID bang tombstone 'deleted:<code>', dia chi chi tiet/ten/SDT -> NULL, nhan hoac
-- '***xyz'; giu ma hanh chinh, ma don, ma van don, so tien, thoi gian.
-- transactional: true

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_dsr') THEN
    CREATE ROLE alpha3s_dsr NOLOGIN;
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO alpha3s_dsr;

-- ---------------------------------------------------------------- yeu cau xoa (CA 415 §3.5 + CA 416)
-- subject_hmac: HMAC(DSR_HMAC_KEY, psid) CHI ton tai khi status='redis_pending'; detail.hmac_key_id = id khoa (rotation).
ALTER TABLE data_deletion_requests ADD COLUMN IF NOT EXISTS subject_hmac TEXT;
ALTER TABLE data_deletion_requests ADD COLUMN IF NOT EXISTS detail JSONB;
-- CA 417: yeu cau gan subject (ID noi bo) TU LUC TAO; erased_at = thoi diem ham xoa da dung ma (1 lan).
ALTER TABLE data_deletion_requests ADD COLUMN IF NOT EXISTS subject_customer_id BIGINT;
ALTER TABLE data_deletion_requests ADD COLUMN IF NOT EXISTS erased_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_ddr_redis_pending ON data_deletion_requests (status) WHERE status = 'redis_pending';

CREATE OR REPLACE FUNCTION ddr_subject_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF current_user = 'alpha3s_dsr' THEN RETURN NEW; END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.subject_customer_id IS NOT NULL OR NEW.erased_at IS NOT NULL THEN
      RAISE EXCEPTION 'data_deletion_requests: subject/erased_at chi duoc gan qua dsr_open_request/dsr_erase_subject';
    END IF;
  ELSIF NEW.subject_customer_id IS DISTINCT FROM OLD.subject_customer_id
     OR NEW.erased_at IS DISTINCT FROM OLD.erased_at
     OR NEW.confirmation_code IS DISTINCT FROM OLD.confirmation_code THEN
    RAISE EXCEPTION 'data_deletion_requests: subject/erased_at/confirmation_code bat bien voi role ung dung';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS ddr_subject_guard ON data_deletion_requests;
CREATE TRIGGER ddr_subject_guard BEFORE INSERT OR UPDATE ON data_deletion_requests
  FOR EACH ROW EXECUTE FUNCTION ddr_subject_guard();

-- ---------------------------------------------------------------- quyen theo cot
GRANT SELECT ON orders, order_items, payments, payment_instructions, shipments, command_executions, outbox_events,
  fulfillment_conversations, inventory_reservations, address_review_queue, order_intents TO alpha3s_dsr;
GRANT SELECT, UPDATE (psid, external_chat_id, name, phone, address, current_address_resolution_id) ON customers
  TO alpha3s_dsr;
GRANT SELECT, INSERT, UPDATE (erased_at) ON data_deletion_requests TO alpha3s_dsr;
DO $$ BEGIN EXECUTE format('GRANT USAGE ON SEQUENCE %s TO alpha3s_dsr',
                           pg_get_serial_sequence('data_deletion_requests', 'id')); END $$;
GRANT SELECT, INSERT ON audit_log TO alpha3s_dsr;
DO $$ BEGIN EXECUTE format('GRANT USAGE ON SEQUENCE %s TO alpha3s_dsr', pg_get_serial_sequence('audit_log', 'id')); END $$;
GRANT SELECT, UPDATE (actor_ref, before, after) ON audit_log TO alpha3s_dsr;
GRANT SELECT, UPDATE (actor_id, causation_id, idempotency_key, metadata_redacted) ON order_events TO alpha3s_dsr;
GRANT SELECT, UPDATE (actor_id, idempotency_key) ON inventory_movements TO alpha3s_dsr;
GRANT SELECT, UPDATE (raw_province, raw_district, raw_ward, street_text, idempotency_key) ON address_resolution
  TO alpha3s_dsr;
GRANT SELECT, UPDATE (street_text) ON order_address_snapshot TO alpha3s_dsr;
GRANT SELECT, UPDATE (customer_ref, old_value, new_value) ON address_change_log TO alpha3s_dsr;
GRANT SELECT, UPDATE (bound_ref) ON address_confirmation_request TO alpha3s_dsr;
GRANT SELECT, UPDATE (payload) ON address_confirmation_outbox TO alpha3s_dsr;
GRANT SELECT, UPDATE (request_snapshot, command_key, note) ON ghn_shipment_create_operations TO alpha3s_dsr;
GRANT SELECT, UPDATE (actor) ON ghn_shipment_create_attempts TO alpha3s_dsr;
GRANT SELECT, UPDATE (command_key, detail, reply_text) ON fulfillment_conversation_events TO alpha3s_dsr;
GRANT SELECT, UPDATE (command_key, recorded_by, note) ON payment_events TO alpha3s_dsr;
GRANT SELECT, UPDATE (command_key, recorded_by, note) ON shipment_delivery_attempts TO alpha3s_dsr;
GRANT SELECT, UPDATE (raw) ON provider_events TO alpha3s_dsr;
GRANT SELECT, UPDATE (detail, resolution_note) ON staff_attention TO alpha3s_dsr;
GRANT SELECT, UPDATE (note) ON price_overrides TO alpha3s_dsr;
GRANT SELECT, DELETE ON pii_slots TO alpha3s_dsr;

-- ---------------------------------------------------------------- ngoai le trigger (chi UPDATE boi alpha3s_dsr)
CREATE OR REPLACE FUNCTION ar_forbid_mutate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND current_user = 'alpha3s_dsr' THEN RETURN NEW; END IF;  -- 077: an danh DSR
  RAISE EXCEPTION 'address_resolution la ho so bat bien — khong duoc %; tao ban ghi moi', TG_OP;
END;
$$;

CREATE OR REPLACE FUNCTION m5_forbid_mutate_p4() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND current_user = 'alpha3s_dsr' THEN RETURN NEW; END IF;  -- 077: an danh DSR
  RAISE EXCEPTION '% la ho so bat bien — khong duoc %', TG_TABLE_NAME, TG_OP;
END;
$$;

CREATE OR REPLACE FUNCTION m5_guard_outbox() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'address_confirmation_outbox la ho so durable — khong duoc DELETE';
  END IF;
  IF current_user = 'alpha3s_dsr' THEN RETURN NEW; END IF;  -- 077: an danh DSR (chi cot payload duoc cap quyen)
  IF NEW.request_id <> OLD.request_id OR NEW.payload::text <> OLD.payload::text
     OR NEW.dedupe_key <> OLD.dedupe_key OR NEW.created_at <> OLD.created_at THEN
    RAISE EXCEPTION 'address_confirmation_outbox: request_id/payload/dedupe_key/created_at bat bien';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION m6_forbid_mutate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Cho phep DELETE khi session dat tuong minh `SET LOCAL m6.cleanup='on'` (chi script cleanup test batch
    -- lam vay; runtime app KHONG BAO GIO dat -> immutability giu nguyen cho du lieu that). UPDATE luon cam.
    IF TG_OP = 'DELETE' AND current_setting('m6.cleanup', true) = 'on' THEN
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND current_user = 'alpha3s_dsr' THEN RETURN NEW; END IF;  -- 077: an danh DSR
    RAISE EXCEPTION '% la ho so bat bien (append-only) — khong duoc %', TG_TABLE_NAME, TG_OP;
END;
$$;

CREATE OR REPLACE FUNCTION ghn_shipment_create_operations_freeze() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ghn_shipment_create_operations: cam DELETE (audit trail)';
    END IF;
    -- 077: an danh DSR — chi request_snapshot/command_key/note duoc cap quyen; state/ma don van khoa.
    IF current_user = 'alpha3s_dsr' THEN RETURN NEW; END IF;
    IF NEW.request_snapshot IS DISTINCT FROM OLD.request_snapshot
       OR NEW.request_fingerprint IS DISTINCT FROM OLD.request_fingerprint
       OR NEW.client_order_code IS DISTINCT FROM OLD.client_order_code
       OR NEW.order_id IS DISTINCT FROM OLD.order_id OR NEW.source IS DISTINCT FROM OLD.source
       OR NEW.command_key IS DISTINCT FROM OLD.command_key OR NEW.mode IS DISTINCT FROM OLD.mode
       OR NEW.config_revision IS DISTINCT FROM OLD.config_revision
       OR NEW.initiator_staff_id IS DISTINCT FROM OLD.initiator_staff_id
       OR NEW.initiator_customer_id IS DISTINCT FROM OLD.initiator_customer_id THEN
        RAISE EXCEPTION 'ghn_shipment_create_operations: snapshot/identity bat bien';
    END IF;
    IF OLD.state IN ('succeeded', 'failed_terminal', 'cancelled_before_dispatch') AND NEW.state IS DISTINCT FROM OLD.state THEN
        RAISE EXCEPTION 'ghn_shipment_create_operations: state terminal % khong doi duoc', OLD.state;
    END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION ghn_shipment_create_attempts_no_mutate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND current_user = 'alpha3s_dsr' THEN RETURN NEW; END IF;  -- 077: an danh DSR
    RAISE EXCEPTION 'ghn_shipment_create_attempts la append-only — khong duoc %', TG_OP;
END $$;

CREATE OR REPLACE FUNCTION order_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND current_user = 'alpha3s_dsr' THEN RETURN NEW; END IF;  -- 077: an danh DSR
  RAISE EXCEPTION 'order_events la append-only (khong UPDATE/DELETE)';
END;
$$;

CREATE OR REPLACE FUNCTION inventory_movements_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND current_user = 'alpha3s_dsr' THEN RETURN NEW; END IF;  -- 077: an danh DSR
  RAISE EXCEPTION 'inventory_movements la append-only (khong UPDATE/DELETE); correction phai tao movement moi';
END;
$$;


-- ---------------------------------------------------------------- helper (khong LIKE/wildcard; khop ranh gioi ky tu)
-- Thay moi lan xuat hien cua tung gia tri (khong dinh lien chu/so khac) bang repl. Gia tri ngan (<5) bi bo qua.
CREATE OR REPLACE FUNCTION dsr_scrub_text(t text, vals text[], repl text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE r text; esc text;
BEGIN
  IF t IS NULL OR vals IS NULL THEN RETURN t; END IF;
  FOREACH r IN ARRAY vals LOOP
    CONTINUE WHEN r IS NULL OR length(r) < 5 OR position(r IN t) = 0;
    esc := regexp_replace(r, '([.^$*+?()\[\]{}|\\-])', '\\\1', 'g');
    t := regexp_replace(t, '(^|[^0-9A-Za-z])' || esc || '(?=$|[^0-9A-Za-z])', '\1' || repl, 'g');
  END LOOP;
  RETURN t;
END;
$$;

CREATE OR REPLACE FUNCTION dsr_scrub_json(j jsonb, vals text[], repl text) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN j IS NULL THEN NULL ELSE dsr_scrub_text(j::text, vals, repl)::jsonb END
$$;

-- Co chua it nhat 1 gia tri (so khop chuoi con bang position — KHONG pattern, '%'/'_' la ky tu thuong).
CREATE OR REPLACE FUNCTION dsr_has_any(t text, vals text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT t IS NOT NULL AND vals IS NOT NULL
     AND EXISTS (SELECT 1 FROM unnest(vals) v WHERE v IS NOT NULL AND length(v) >= 5 AND position(v IN t) > 0)
$$;

-- ---------------------------------------------------------------- mo yeu cau + gan subject (CA 417)
-- p_ref = dinh danh kenh dang luu (customers.psid) cua NGUOI YEU CAU (Messenger PSID / 'tg:<chat_id>'). Chi luu
-- customers.id; khong tim thay (hoac da xoa) -> yeu cau KHONG subject (xoa la no-op). Ma: 16 hex ngau nhien.
CREATE OR REPLACE FUNCTION dsr_open_request(p_ref text)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_code text; v_cid bigint;
BEGIN
  IF p_ref IS NULL OR length(p_ref) < 5 OR left(p_ref, 8) = 'deleted:' THEN
    RAISE EXCEPTION 'dsr_open_request: dinh danh khong hop le';
  END IF;
  SELECT id INTO v_cid FROM customers WHERE psid = p_ref AND left(external_chat_id, 8) <> 'deleted:' FOR UPDATE;
  v_code := left(replace(gen_random_uuid()::text, '-', ''), 16);
  INSERT INTO data_deletion_requests (confirmation_code, status, subject_customer_id)
  VALUES (v_code, 'received', v_cid);
  RETURN v_code;
END;
$$;

-- ---------------------------------------------------------------- ham DSR (duong duy nhat, CA 416 + 417)
CREATE OR REPLACE FUNCTION dsr_erase_subject(p_code text)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_rq record;
  c record;
  v_tomb text; v_refs text[]; v_actor text[]; v_pii text[]; v_all text[];
  v_orders bigint[]; v_ot text[]; v_pay bigint[]; v_ship bigint[]; v_ops bigint[]; v_cmds uuid[]; v_res uuid[];
  v_req uuid[]; v_ent text[];
  n int; v_out jsonb := '{}'::jsonb;
  c_mark CONSTANT text := '[đã ẩn theo yêu cầu xóa dữ liệu]';
BEGIN
  -- (1) Yeu cau that, DA GAN subject luc tao (dsr_open_request), status 'received', CHUA dung (1 ma = 1 lan).
  --     Subject lay TU yeu cau duoi khoa — caller khong chon customer.
  IF p_code IS NULL OR p_code !~ '^[0-9a-f]{16}$' THEN
    RAISE EXCEPTION 'dsr_erase_subject: confirmation code khong hop le';
  END IF;
  SELECT subject_customer_id INTO v_rq FROM data_deletion_requests
   WHERE confirmation_code = p_code AND status = 'received' AND erased_at IS NULL FOR UPDATE;
  IF NOT FOUND OR v_rq.subject_customer_id IS NULL THEN
    RAISE EXCEPTION 'dsr_erase_subject: khong co yeu cau xoa hop le (received, da gan subject, chua dung) cho ma nay';
  END IF;
  -- (2) Dinh danh/PII GOC doc TU CHINH dong customer cua yeu cau (khoa) — caller khong cap gia tri nao.
  SELECT id, psid, external_chat_id, name, phone, address, current_address_resolution_id INTO c
    FROM customers WHERE id = v_rq.subject_customer_id FOR UPDATE;
  IF NOT FOUND OR left(c.psid, 8) = 'deleted:' OR left(c.external_chat_id, 8) = 'deleted:' THEN
    RAISE EXCEPTION 'dsr_erase_subject: customer cua yeu cau khong ton tai hoac da xoa';
  END IF;
  v_tomb := 'deleted:' || p_code;
  v_refs := ARRAY(SELECT DISTINCT x FROM unnest(ARRAY[c.psid, c.external_chat_id]) x WHERE x IS NOT NULL AND length(x) >= 5);
  v_actor := ARRAY(SELECT DISTINCT y FROM unnest(v_refs) r, unnest(ARRAY[r, 'customer:' || r]) y);
  SELECT coalesce(array_agg(id), '{}') INTO v_orders FROM orders WHERE customer_id = c.id;
  v_ot := ARRAY(SELECT x::text FROM unnest(v_orders) x);
  -- PII cua subject (ho so + nguoi nhan cac don + draft) — CHI dung de THAY ben trong dong DA lien ket o duoi.
  SELECT coalesce(array_agg(DISTINCT btrim(v)), '{}') INTO v_pii FROM (
      SELECT unnest(ARRAY[c.name, c.phone, c.address, regexp_replace(coalesce(c.phone, ''), '\D', '', 'g')]) v
      UNION ALL
      SELECT unnest(ARRAY[shipping_name, shipping_phone, shipping_address,
                          regexp_replace(coalesce(shipping_phone, ''), '\D', '', 'g')]) FROM orders WHERE customer_id = c.id
      UNION ALL
      SELECT unnest(ARRAY[draft_customer_name, draft_phone, draft_address,
                          regexp_replace(coalesce(draft_phone, ''), '\D', '', 'g')]) FROM order_intents
       WHERE customer_id = c.id) s
   WHERE v IS NOT NULL AND length(btrim(v)) >= 5;
  v_all := v_refs || v_pii;

  -- (3) Tap LIEN KET chac chan cua subject.
  SELECT coalesce(array_agg(id), '{}') INTO v_pay FROM payments WHERE order_id = ANY (v_orders);
  SELECT coalesce(array_agg(id), '{}') INTO v_ship FROM shipments WHERE order_id = ANY (v_orders);
  SELECT coalesce(array_agg(id), '{}') INTO v_ops FROM ghn_shipment_create_operations
   WHERE order_id = ANY (v_orders) OR initiator_customer_id = c.id;
  SELECT coalesce(array_agg(id), '{}') INTO v_cmds FROM command_executions WHERE customer_id = c.id;
  SELECT coalesce(array_agg(DISTINCT rid), '{}') INTO v_res FROM (
      SELECT id AS rid FROM address_resolution
       WHERE (subject_type = 'customer' AND subject_id = c.id::text)
          OR (subject_type = 'order' AND subject_id = ANY (v_ot))
      UNION SELECT resolution_id FROM order_address_snapshot WHERE order_id = ANY (v_orders)
      UNION SELECT verified_address_id FROM orders WHERE id = ANY (v_orders)
      UNION SELECT c.current_address_resolution_id) s WHERE rid IS NOT NULL;
  SELECT coalesce(array_agg(id), '{}') INTO v_req FROM address_confirmation_request WHERE resolution_id = ANY (v_res);
  v_ent := ARRAY(
      SELECT 'order:' || x FROM unnest(v_ot) x
      UNION ALL SELECT 'orders:' || x FROM unnest(v_ot) x
      UNION ALL SELECT 'customers:' || c.id
      UNION ALL SELECT 'payments:' || x FROM unnest(v_pay) x
      UNION ALL SELECT 'shipments:' || x FROM unnest(v_ship) x
      UNION ALL SELECT 'ghn_shipment_create_operations:' || x FROM unnest(v_ops) x
      UNION ALL SELECT 'command:' || x FROM unnest(v_cmds) x
      UNION ALL SELECT 'address_resolution:' || x FROM unnest(v_res) x
      UNION ALL SELECT 'address_confirmation_request:' || x FROM unnest(v_req) x
      UNION ALL SELECT 'order_address_snapshot:' || id FROM order_address_snapshot WHERE order_id = ANY (v_orders)
      UNION ALL SELECT 'payment_instructions:' || id FROM payment_instructions WHERE order_id = ANY (v_orders)
      UNION ALL SELECT 'fulfillment_conversations:' || id FROM fulfillment_conversations WHERE order_id = ANY (v_orders)
      UNION ALL SELECT 'staff_attention:' || id FROM staff_attention WHERE order_id = ANY (v_orders)
      UNION ALL SELECT 'address_review_queue:' || id FROM address_review_queue
       WHERE (subject_type = 'customer' AND subject_id = c.id::text) OR (subject_type = 'order' AND subject_id = ANY (v_ot))
      UNION ALL SELECT 'address_change_log:' || id FROM address_change_log
       WHERE customer_ref = ANY (v_refs || ARRAY[c.id::text])
      UNION ALL SELECT 'outbox_event:' || id FROM outbox_events
       WHERE command_id = ANY (v_cmds) OR payload->>'customer_ref' = ANY (v_refs) OR payload->>'order_id' = ANY (v_ot));

  -- (4) Kho bat bien — moi UPDATE: dong LIEN KET subject (+ chi khi thuc su chua dinh danh/PII cua subject).
  UPDATE audit_log SET actor_ref = CASE WHEN actor_ref = ANY (v_actor) THEN dsr_scrub_text(actor_ref, v_refs, v_tomb)
                                        ELSE actor_ref END,
         before = dsr_scrub_json(dsr_scrub_json(before, v_refs, v_tomb), v_pii, c_mark),
         after = dsr_scrub_json(dsr_scrub_json(after, v_refs, v_tomb), v_pii, c_mark)
   WHERE (actor_ref = ANY (v_actor) OR (entity_type || ':' || entity_id) = ANY (v_ent))
     AND (actor_ref = ANY (v_actor) OR dsr_has_any(before::text, v_all) OR dsr_has_any(after::text, v_all));
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('audit_log', n);

  UPDATE order_events SET actor_id = dsr_scrub_text(actor_id, v_refs, v_tomb),
         causation_id = dsr_scrub_text(causation_id, v_refs, v_tomb),
         idempotency_key = dsr_scrub_text(idempotency_key, v_refs, v_tomb),
         metadata_redacted = dsr_scrub_json(dsr_scrub_json(metadata_redacted, v_refs, v_tomb), v_pii, c_mark)
   WHERE order_id = ANY (v_orders)
     AND dsr_has_any(concat_ws(' ', actor_id, causation_id, idempotency_key, metadata_redacted::text), v_all);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('order_events', n);

  UPDATE inventory_movements SET actor_id = dsr_scrub_text(actor_id, v_refs, v_tomb),
         idempotency_key = dsr_scrub_text(idempotency_key, v_refs, v_tomb)
   WHERE ((reference_type = 'order' AND reference_id = ANY (v_ot))
       OR (reference_type = 'order_item' AND reference_id IN (SELECT id::text FROM order_items WHERE order_id = ANY (v_orders)))
       OR (reference_type = 'reservation'
           AND reference_id IN (SELECT id::text FROM inventory_reservations WHERE order_id = ANY (v_orders))))
     AND dsr_has_any(concat_ws(' ', actor_id, idempotency_key), v_refs);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('inventory_movements', n);

  UPDATE address_resolution SET raw_province = NULL, raw_district = NULL, raw_ward = NULL, street_text = NULL,
         idempotency_key = dsr_scrub_text(idempotency_key, v_refs, v_tomb)
   WHERE id = ANY (v_res);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('address_resolution', n);

  UPDATE order_address_snapshot SET street_text = NULL WHERE order_id = ANY (v_orders) AND street_text IS NOT NULL;
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('order_address_snapshot', n);

  UPDATE address_change_log SET customer_ref = dsr_scrub_text(customer_ref, v_refs, v_tomb), old_value = NULL,
         new_value = NULL
   WHERE customer_ref = ANY (v_refs || ARRAY[c.id::text]);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('address_change_log', n);

  UPDATE address_confirmation_request SET bound_ref = dsr_scrub_text(bound_ref, v_refs, v_tomb)
   WHERE id = ANY (v_req) AND dsr_has_any(bound_ref, v_refs);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('address_confirmation_request', n);
  UPDATE address_confirmation_outbox SET payload = dsr_scrub_json(dsr_scrub_json(payload, v_refs, v_tomb), v_pii, c_mark)
   WHERE request_id = ANY (v_req) AND dsr_has_any(payload::text, v_all);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('address_confirmation_outbox', n);

  -- GHN: nguoi nhan -> NULL / SDT '***xyz'; giu ma don/ma van don/khoi luong/phi/ma vung.
  UPDATE ghn_shipment_create_operations
     SET request_snapshot = CASE WHEN request_snapshot ? 'recipient' THEN jsonb_set(request_snapshot, '{recipient}',
           jsonb_build_object('name', NULL, 'address_text', NULL, 'dsr_anonymized', true,
             'phone', CASE WHEN length(regexp_replace(coalesce(request_snapshot #>> '{recipient,phone}', ''), '\D', '', 'g')) >= 3
                           THEN '***' || right(regexp_replace(request_snapshot #>> '{recipient,phone}', '\D', '', 'g'), 3)
                           ELSE NULL END))
           ELSE request_snapshot END,
         command_key = dsr_scrub_text(command_key, v_refs, v_tomb),
         note = CASE WHEN note IS NULL THEN NULL ELSE c_mark END
   WHERE id = ANY (v_ops);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('ghn_shipment_create_operations', n);
  UPDATE ghn_shipment_create_attempts SET actor = dsr_scrub_text(actor, v_refs, v_tomb)
   WHERE operation_id = ANY (v_ops) AND dsr_has_any(actor, v_refs);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('ghn_shipment_create_attempts', n);

  -- M7 journal: tin bot (reply_text) xoa nhu messages; command_key/detail thay ref/PII.
  UPDATE fulfillment_conversation_events SET reply_text = NULL,
         command_key = dsr_scrub_text(command_key, v_refs, v_tomb),
         detail = dsr_scrub_json(dsr_scrub_json(detail, v_refs, v_tomb), v_pii, c_mark)
   WHERE order_id = ANY (v_orders);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('fulfillment_conversation_events', n);

  UPDATE payment_events SET command_key = dsr_scrub_text(command_key, v_refs, v_tomb),
         recorded_by = dsr_scrub_text(recorded_by, v_refs, v_tomb),
         note = CASE WHEN note IS NULL THEN NULL ELSE c_mark END
   WHERE payment_id = ANY (v_pay) AND (note IS NOT NULL OR dsr_has_any(concat_ws(' ', command_key, recorded_by), v_refs));
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('payment_events', n);

  UPDATE shipment_delivery_attempts SET command_key = dsr_scrub_text(command_key, v_refs, v_tomb),
         recorded_by = dsr_scrub_text(recorded_by, v_refs, v_tomb),
         note = CASE WHEN note IS NULL THEN NULL ELSE c_mark END
   WHERE shipment_id = ANY (v_ship) AND (note IS NOT NULL OR dsr_has_any(concat_ws(' ', command_key, recorded_by), v_refs));
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('shipment_delivery_attempts', n);

  -- SePay: noi dung/dien giai chuyen khoan (thuong chua ten nguoi tra) -> an; giu so tien/ma tham chieu/thoi gian.
  UPDATE provider_events SET raw = raw || jsonb_build_object('content', '[dsr]', 'description', '[dsr]')
   WHERE order_id = ANY (v_orders) AND (raw ? 'content' OR raw ? 'description');
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('provider_events', n);

  UPDATE staff_attention SET detail = dsr_scrub_json(dsr_scrub_json(detail, v_refs, v_tomb), v_pii, c_mark),
         resolution_note = CASE WHEN resolution_note IS NULL THEN NULL ELSE c_mark END
   WHERE order_id = ANY (v_orders) AND (resolution_note IS NOT NULL OR dsr_has_any(detail::text, v_all));
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('staff_attention', n);

  UPDATE price_overrides SET note = c_mark WHERE customer_id = c.id AND note IS NOT NULL;
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('price_overrides', n);

  DELETE FROM pii_slots WHERE customer_ref = ANY (v_refs || ARRAY[c.id::text]);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('pii_slots', n);

  -- (5) Tombstone customer (psid VA external_chat_id) + gan request (1 lan) + audit (khong dinh danh).
  UPDATE customers SET psid = v_tomb, external_chat_id = v_tomb, name = NULL, phone = NULL, address = NULL,
         current_address_resolution_id = NULL
   WHERE id = c.id;
  UPDATE data_deletion_requests SET erased_at = now() WHERE confirmation_code = p_code;
  INSERT INTO audit_log (actor_type, actor_ref, action, entity_type, entity_id, after, reason)
  VALUES ('system', 'dsr', 'dsr.anonymize', 'data_deletion_request', p_code,
          v_out || jsonb_build_object('customer', 'customer:' || c.id), 'data subject deletion request');
  RETURN v_out || jsonb_build_object('customer_id', c.id);
END;
$$;

ALTER FUNCTION dsr_open_request(text) OWNER TO alpha3s_dsr;
ALTER FUNCTION dsr_erase_subject(text) OWNER TO alpha3s_dsr;
ALTER FUNCTION dsr_scrub_text(text, text[], text) OWNER TO alpha3s_dsr;
ALTER FUNCTION dsr_scrub_json(jsonb, text[], text) OWNER TO alpha3s_dsr;
ALTER FUNCTION dsr_has_any(text, text[]) OWNER TO alpha3s_dsr;
REVOKE ALL ON FUNCTION dsr_open_request(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION dsr_erase_subject(text) FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_app') THEN
    GRANT EXECUTE ON FUNCTION dsr_open_request(text) TO alpha3s_app;
    GRANT EXECUTE ON FUNCTION dsr_erase_subject(text) TO alpha3s_app;
  END IF;
END $$;

-- Postcondition
DO $$
BEGIN
  IF (SELECT count(*) FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
      WHERE p.proname IN ('dsr_erase_subject', 'dsr_open_request') AND p.prosecdef AND r.rolname = 'alpha3s_dsr') <> 2 THEN
    RAISE EXCEPTION '077 postcondition: dsr_erase_subject/dsr_open_request phai SECURITY DEFINER owner alpha3s_dsr';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'dsr_erase_subject' AND pronargs <> 1) THEN
    RAISE EXCEPTION '077 postcondition: dsr_erase_subject chi duoc nhan (code) — subject lay tu yeu cau da gan';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'ddr_subject_guard') THEN
    RAISE EXCEPTION '077 postcondition: thieu trigger ddr_subject_guard';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid WHERE r.rolname = 'alpha3s_dsr') THEN
    RAISE EXCEPTION '077 postcondition: alpha3s_dsr khong duoc co thanh vien';
  END IF;
END $$;

-- ============================ ROLLBACK ============================
-- scripts/rollback_077_dsr_definer.sql (chay tay khi CA/PO quyet). Du lieu da an danh KHONG khoi phuc.
