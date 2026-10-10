-- 077 — CA Review 415 §3.2: duong DSR QUYEN HEP cho kho bat bien/append-only.
-- Van de: audit_log/order_events/inventory_movements/address_*/ghn_shipment_create_*/fulfillment_conversation_events/
-- payment_events/shipment_delivery_attempts bi trigger (va REVOKE cho alpha3s_app) cam UPDATE -> sau khi khach xoa du
-- lieu van con PSID/ChatID/dia chi/ten nguoi nhan trong DB active.
-- Giai phap (KHONG mo quyen UPDATE chung):
--   1. Role NOLOGIN `alpha3s_dsr` — khong ai dang nhap/khong role ung dung nao la thanh vien.
--   2. Ham SECURITY DEFINER `dsr_anonymize_identity(...)` (OWNER alpha3s_dsr) la duong DUY NHAT; chi chay khi customer
--      DA tombstone (psid = external_chat_id = p_tomb) TRONG CUNG transaction voi DSR cua app -> khong the dung de sua
--      so cua khach dang hoat dong. Ghi audit_log 'dsr.anonymize' (counts, khong dinh danh).
--   3. Quyen cua alpha3s_dsr: SELECT + UPDATE THEO COT (chi cot dinh danh), DELETE pii_slots, INSERT audit_log.
--   4. Trigger bat bien them DUNG 1 ngoai le: TG_OP='UPDATE' AND current_user='alpha3s_dsr'. DELETE van cam; cac cot
--      nghiep vu (so tien/trang thai/ma van don/ma don...) KHONG duoc cap quyen nen khong doi duoc.
-- Giu toan ven so: thay PSID/ChatID bang tombstone 'deleted:<code>' (cung gia tri voi customers.psid), dia chi chi tiet/
-- ten/SDT -> NULL hoac '***xyz'; giu ma hanh chinh, ma don, ma van don, so tien, thoi gian.
-- transactional: true

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_dsr') THEN
    CREATE ROLE alpha3s_dsr NOLOGIN;
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO alpha3s_dsr;

-- ---------------------------------------------------------------- quyen theo cot
GRANT SELECT ON customers, orders, payments, shipments TO alpha3s_dsr;
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

-- ---------------------------------------------------------------- helper thay dinh danh (ranh gioi ky tu)
-- Thay moi lan xuat hien cua tung ref (khong dinh lien chu/so khac) bang tomb. Ref ngan (<5) bi bo qua (tranh thay nham).
CREATE OR REPLACE FUNCTION dsr_scrub_text(t text, refs text[], tomb text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE r text; esc text;
BEGIN
  IF t IS NULL THEN RETURN NULL; END IF;
  FOREACH r IN ARRAY refs LOOP
    CONTINUE WHEN r IS NULL OR length(r) < 5 OR position(r IN t) = 0;
    esc := regexp_replace(r, '([.^$*+?()\[\]{}|\\-])', '\\\1', 'g');
    t := regexp_replace(t, '(^|[^0-9A-Za-z])' || esc || '(?=$|[^0-9A-Za-z])', '\1' || tomb, 'g');
  END LOOP;
  RETURN t;
END;
$$;

CREATE OR REPLACE FUNCTION dsr_scrub_json(j jsonb, refs text[], tomb text) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN j IS NULL THEN NULL ELSE dsr_scrub_text(j::text, refs, tomb)::jsonb END
$$;

-- ---------------------------------------------------------------- ham DSR (duong duy nhat)
CREATE OR REPLACE FUNCTION dsr_anonymize_identity(p_customer_id bigint, p_refs text[], p_tomb text, p_code text,
                                                  p_pii text[] DEFAULT '{}')
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_orders bigint[]; v_orders_txt text[]; v_refs text[]; v_res uuid[]; v_like text[]; v_pii text[];
  v_like_pii text[];
  c_mark CONSTANT text := '[đã ẩn theo yêu cầu xóa dữ liệu]';
  n int; v_out jsonb := '{}'::jsonb;
BEGIN
  -- Dieu kien: chi cho customer DA tombstone bang dung p_tomb (cung transaction DSR) -> khong sua so khach dang song.
  IF p_tomb IS NULL OR p_tomb NOT LIKE 'deleted:%' OR p_code IS NULL OR p_tomb <> 'deleted:' || p_code THEN
    RAISE EXCEPTION 'dsr_anonymize_identity: tombstone khong hop le';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM customers WHERE id = p_customer_id AND psid = p_tomb AND external_chat_id = p_tomb) THEN
    RAISE EXCEPTION 'dsr_anonymize_identity: customer % chua tombstone trong transaction nay', p_customer_id;
  END IF;
  SELECT coalesce(array_agg(DISTINCT x), '{}') INTO v_refs FROM unnest(p_refs) x WHERE x IS NOT NULL AND length(x) >= 5;
  IF cardinality(v_refs) = 0 THEN
    RAISE EXCEPTION 'dsr_anonymize_identity: thieu ref';
  END IF;
  SELECT coalesce(array_agg('%' || x || '%'), '{}') INTO v_like FROM unnest(v_refs) x;
  -- PII gia tri (ten/SDT/dia chi cu cua khach) -> chi dung de quet truong JSON/tu do; thay bang c_mark.
  SELECT coalesce(array_agg(DISTINCT x), '{}') INTO v_pii FROM unnest(p_pii) x WHERE x IS NOT NULL AND length(x) >= 5;
  SELECT coalesce(array_agg(id), '{}') INTO v_orders FROM orders WHERE customer_id = p_customer_id;
  SELECT coalesce(array_agg(x::text), '{}') INTO v_orders_txt FROM unnest(v_orders) x;

  SELECT coalesce(array_agg('%' || x || '%'), '{}') INTO v_like_pii FROM unnest(v_pii) x;

  -- audit_log: actor_ref/before/after chua PSID/ChatID (-> tombstone) hoac ten/SDT/dia chi (-> c_mark).
  UPDATE audit_log SET actor_ref = dsr_scrub_text(actor_ref, v_refs, p_tomb),
                       before = dsr_scrub_json(dsr_scrub_json(before, v_refs, p_tomb), v_pii, c_mark),
                       after = dsr_scrub_json(dsr_scrub_json(after, v_refs, p_tomb), v_pii, c_mark)
   WHERE actor_ref LIKE ANY (v_like) OR before::text LIKE ANY (v_like) OR after::text LIKE ANY (v_like)
      OR before::text LIKE ANY (v_like_pii) OR after::text LIKE ANY (v_like_pii);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('audit_log', n);

  UPDATE order_events SET actor_id = dsr_scrub_text(actor_id, v_refs, p_tomb),
                          causation_id = dsr_scrub_text(causation_id, v_refs, p_tomb),
                          idempotency_key = dsr_scrub_text(idempotency_key, v_refs, p_tomb),
                          metadata_redacted = dsr_scrub_json(metadata_redacted, v_refs, p_tomb)
   WHERE actor_id LIKE ANY (v_like) OR causation_id LIKE ANY (v_like) OR idempotency_key LIKE ANY (v_like)
      OR metadata_redacted::text LIKE ANY (v_like);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('order_events', n);

  UPDATE inventory_movements SET actor_id = dsr_scrub_text(actor_id, v_refs, p_tomb),
                                 idempotency_key = dsr_scrub_text(idempotency_key, v_refs, p_tomb)
   WHERE actor_id LIKE ANY (v_like) OR idempotency_key LIKE ANY (v_like);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('inventory_movements', n);

  -- Dia chi: resolution cua khach / don cua khach / snapshot gan don -> bo dia chi chi tiet + input tho; GIU ma hanh chinh.
  SELECT coalesce(array_agg(DISTINCT id), '{}') INTO v_res FROM (
      SELECT id FROM address_resolution
       WHERE (subject_type = 'customer' AND subject_id = p_customer_id::text)
          OR (subject_type = 'order' AND subject_id = ANY (v_orders_txt))
          OR idempotency_key LIKE ANY (v_like)
      UNION SELECT resolution_id FROM order_address_snapshot WHERE order_id = ANY (v_orders)
      UNION SELECT verified_address_id FROM orders WHERE id = ANY (v_orders) AND verified_address_id IS NOT NULL) s;
  UPDATE address_resolution SET raw_province = NULL, raw_district = NULL, raw_ward = NULL, street_text = NULL,
                                idempotency_key = dsr_scrub_text(idempotency_key, v_refs, p_tomb)
   WHERE id = ANY (v_res);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('address_resolution', n);

  UPDATE order_address_snapshot SET street_text = NULL WHERE order_id = ANY (v_orders) AND street_text IS NOT NULL;
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('order_address_snapshot', n);

  UPDATE address_change_log SET customer_ref = dsr_scrub_text(customer_ref, v_refs, p_tomb), old_value = NULL,
                                new_value = NULL
   WHERE customer_ref = p_customer_id::text OR customer_ref LIKE ANY (v_like);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('address_change_log', n);

  UPDATE address_confirmation_request SET bound_ref = dsr_scrub_text(bound_ref, v_refs, p_tomb)
   WHERE bound_ref LIKE ANY (v_like);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('address_confirmation_request', n);
  UPDATE address_confirmation_outbox SET payload = dsr_scrub_json(payload, v_refs, p_tomb)
   WHERE payload::text LIKE ANY (v_like);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('address_confirmation_outbox', n);

  -- GHN: nguoi nhan trong snapshot -> NULL/mask SDT 3 so cuoi; giu ma don/ma van don/khoi luong/phi.
  UPDATE ghn_shipment_create_operations
     SET request_snapshot = CASE WHEN request_snapshot ? 'recipient' THEN jsonb_set(request_snapshot, '{recipient}',
           jsonb_build_object('name', NULL, 'address_text', NULL, 'dsr_anonymized', true,
             'phone', CASE WHEN length(regexp_replace(coalesce(request_snapshot #>> '{recipient,phone}', ''), '\D', '', 'g')) >= 3
                           THEN '***' || right(regexp_replace(request_snapshot #>> '{recipient,phone}', '\D', '', 'g'), 3)
                           ELSE NULL END))
           ELSE request_snapshot END,
         command_key = dsr_scrub_text(command_key, v_refs, p_tomb),
         note = CASE WHEN note IS NULL THEN NULL ELSE c_mark END
   WHERE order_id = ANY (v_orders) OR initiator_customer_id = p_customer_id;
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('ghn_shipment_create_operations', n);
  UPDATE ghn_shipment_create_attempts SET actor = dsr_scrub_text(actor, v_refs, p_tomb) WHERE actor LIKE ANY (v_like);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('ghn_shipment_create_attempts', n);

  -- M7 journal: noi dung tin bot (reply_text) xoa nhu messages; command_key/detail thay ref.
  UPDATE fulfillment_conversation_events SET reply_text = NULL,
         command_key = dsr_scrub_text(command_key, v_refs, p_tomb),
         detail = dsr_scrub_json(dsr_scrub_json(detail, v_refs, p_tomb), v_pii, c_mark)
   WHERE order_id = ANY (v_orders);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('fulfillment_conversation_events', n);

  UPDATE payment_events SET command_key = dsr_scrub_text(command_key, v_refs, p_tomb),
                            recorded_by = dsr_scrub_text(recorded_by, v_refs, p_tomb),
                            note = CASE WHEN note IS NULL THEN NULL ELSE c_mark END
   WHERE payment_id IN (SELECT id FROM payments WHERE order_id = ANY (v_orders))
     AND (command_key LIKE ANY (v_like) OR recorded_by LIKE ANY (v_like) OR note IS NOT NULL);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('payment_events', n);

  UPDATE shipment_delivery_attempts SET command_key = dsr_scrub_text(command_key, v_refs, p_tomb),
                                        recorded_by = dsr_scrub_text(recorded_by, v_refs, p_tomb),
                                        note = CASE WHEN note IS NULL THEN NULL ELSE c_mark END
   WHERE shipment_id IN (SELECT id FROM shipments WHERE order_id = ANY (v_orders))
     AND (command_key LIKE ANY (v_like) OR recorded_by LIKE ANY (v_like) OR note IS NOT NULL);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('shipment_delivery_attempts', n);

  -- SePay: noi dung/dien giai chuyen khoan (co the chua ten nguoi tra) -> an; giu so tien/ma tham chieu/thoi gian.
  UPDATE provider_events SET raw = raw || jsonb_build_object('content', '[dsr]', 'description', '[dsr]')
   WHERE order_id = ANY (v_orders) AND (raw ? 'content' OR raw ? 'description');
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('provider_events', n);

  UPDATE staff_attention SET detail = dsr_scrub_json(dsr_scrub_json(detail, v_refs, p_tomb), v_pii, c_mark),
         resolution_note = CASE WHEN resolution_note IS NULL THEN NULL ELSE c_mark END
   WHERE order_id = ANY (v_orders);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('staff_attention', n);

  UPDATE price_overrides SET note = c_mark WHERE customer_id = p_customer_id AND note IS NOT NULL;
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('price_overrides', n);

  DELETE FROM pii_slots WHERE customer_ref = p_customer_id::text OR customer_ref = ANY (v_refs);
  GET DIAGNOSTICS n = ROW_COUNT; v_out := v_out || jsonb_build_object('pii_slots', n);

  INSERT INTO audit_log (actor_type, actor_ref, action, entity_type, entity_id, after, reason)
  VALUES ('system', 'dsr', 'dsr.anonymize', 'data_deletion_request', p_code,
          v_out || jsonb_build_object('customer', 'customer:' || p_customer_id), 'data subject deletion request');
  RETURN v_out;
END;
$$;

ALTER FUNCTION dsr_anonymize_identity(bigint, text[], text, text, text[]) OWNER TO alpha3s_dsr;
ALTER FUNCTION dsr_scrub_text(text, text[], text) OWNER TO alpha3s_dsr;
ALTER FUNCTION dsr_scrub_json(jsonb, text[], text) OWNER TO alpha3s_dsr;
REVOKE ALL ON FUNCTION dsr_anonymize_identity(bigint, text[], text, text, text[]) FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_app') THEN
    GRANT EXECUTE ON FUNCTION dsr_anonymize_identity(bigint, text[], text, text, text[]) TO alpha3s_app;
  END IF;
END $$;

-- ---------------------------------------------------------------- yeu cau xoa: trang thai Redis (CA 415 §3.5)
-- subject_hmac: HMAC(app secret, psid) CHI ton tai khi status='redis_pending' (de lan retry/worker tim lai key Redis
-- cua chinh khach do ma KHONG luu PSID tho); ve NULL khi hoan tat.
ALTER TABLE data_deletion_requests ADD COLUMN IF NOT EXISTS subject_hmac TEXT;
ALTER TABLE data_deletion_requests ADD COLUMN IF NOT EXISTS detail JSONB;
CREATE INDEX IF NOT EXISTS idx_ddr_redis_pending ON data_deletion_requests (status) WHERE status = 'redis_pending';

-- Postcondition
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
                 WHERE p.proname = 'dsr_anonymize_identity' AND p.prosecdef AND r.rolname = 'alpha3s_dsr') THEN
    RAISE EXCEPTION '077 postcondition: dsr_anonymize_identity phai SECURITY DEFINER owner alpha3s_dsr';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid WHERE r.rolname = 'alpha3s_dsr') THEN
    RAISE EXCEPTION '077 postcondition: alpha3s_dsr khong duoc co thanh vien';
  END IF;
END $$;

-- ============================ ROLLBACK (chay tay khi CA/PO quyet; KHONG tu dong) ============================
-- Code cu KHONG goi ham nay. Rollback: (1) DROP FUNCTION dsr_anonymize_identity(bigint,text[],text,text,text[]),
-- dsr_scrub_json(jsonb,text[],text), dsr_scrub_text(text,text[],text); (2) CREATE OR REPLACE 9 ham trigger ve ban 053/055/
-- 057/064/073/022/021 (bo dong 'current_user = alpha3s_dsr'); (3) REVOKE ALL ... FROM alpha3s_dsr tren cac bang tren;
-- DROP ROLE alpha3s_dsr; (4) cot data_deletion_requests.subject_hmac/detail giu nguyen (additive) hoac DROP khi
-- khong con status='redis_pending'. Du lieu da an danh KHONG khoi phuc (dung yeu cau DSR).
