-- Rollback migration 077 (CA Review 415 — duong DSR quyen hep). CHAY TAY khi CA/PO quyet; KHONG tu dong.
-- Hieu ung: code DSR moi (goi dsr_anonymize_identity) se FAIL-CLOSED (rollback ca DSR, request 'failed') -> chi chay
-- rollback nay CUNG luc revert code ve ban khong goi ham. Du lieu da an danh KHONG khoi phuc (dung yeu cau DSR).
-- Precheck: SELECT count(*) FROM data_deletion_requests WHERE status='redis_pending'; > 0 -> cho worker xu ly xong.
BEGIN;

DROP FUNCTION IF EXISTS dsr_anonymize_identity(bigint, text[], text, text, text[]);
DROP FUNCTION IF EXISTS dsr_scrub_json(jsonb, text[], text);
DROP FUNCTION IF EXISTS dsr_scrub_text(text, text[], text);

-- Trigger function ve dung ban truoc 077 (053/055/057/064/073/022/021).
CREATE OR REPLACE FUNCTION ar_forbid_mutate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'address_resolution la ho so bat bien — khong duoc %; tao ban ghi moi', TG_OP;
END;
$$;
CREATE OR REPLACE FUNCTION m5_forbid_mutate_p4() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% la ho so bat bien — khong duoc %', TG_TABLE_NAME, TG_OP;
END;
$$;
CREATE OR REPLACE FUNCTION m5_guard_outbox() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'address_confirmation_outbox la ho so durable — khong duoc DELETE';
  END IF;
  IF NEW.request_id <> OLD.request_id OR NEW.payload::text <> OLD.payload::text
     OR NEW.dedupe_key <> OLD.dedupe_key OR NEW.created_at <> OLD.created_at THEN
    RAISE EXCEPTION 'address_confirmation_outbox: request_id/payload/dedupe_key/created_at bat bien';
  END IF;
  RETURN NEW;
END;
$$;
CREATE OR REPLACE FUNCTION m6_forbid_mutate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_setting('m6.cleanup', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION '% la ho so bat bien (append-only) — khong duoc %', TG_TABLE_NAME, TG_OP;
END;
$$;
CREATE OR REPLACE FUNCTION ghn_shipment_create_operations_freeze() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ghn_shipment_create_operations: cam DELETE (audit trail)';
    END IF;
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
    RAISE EXCEPTION 'ghn_shipment_create_attempts la append-only — khong duoc %', TG_OP;
END $$;
CREATE OR REPLACE FUNCTION order_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'order_events la append-only (khong UPDATE/DELETE)';
END;
$$;
CREATE OR REPLACE FUNCTION inventory_movements_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'inventory_movements la append-only (khong UPDATE/DELETE); correction phai tao movement moi';
END;
$$;

-- Thu hoi moi quyen cua alpha3s_dsr roi xoa role.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_dsr') THEN
    EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM alpha3s_dsr';
    EXECUTE 'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM alpha3s_dsr';
    EXECUTE 'REVOKE USAGE ON SCHEMA public FROM alpha3s_dsr';
    BEGIN
      EXECUTE 'DROP ROLE alpha3s_dsr';
    EXCEPTION WHEN dependent_objects_still_exist THEN
      -- Role la doi tuong CLUSTER: con quyen o DB khac (vd DB rehearsal) -> giu role (NOLOGIN, khong quyen o DB nay).
      RAISE NOTICE 'alpha3s_dsr con phu thuoc o DB khac — giu role (da thu hoi moi quyen trong DB nay)';
    END;
  END IF;
END $$;

DELETE FROM schema_migrations WHERE version = '077_dsr_anonymize_definer';
-- Cot data_deletion_requests.subject_hmac/detail + index: additive, code cu bo qua -> giu nguyen.

-- Hau kiem
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_proc WHERE proname LIKE 'dsr\_%') THEN
    RAISE EXCEPTION 'rollback 077: con ham dsr_*';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_proc WHERE prosrc LIKE '%alpha3s_dsr%') THEN
    RAISE EXCEPTION 'rollback 077: trigger con ngoai le alpha3s_dsr';
  END IF;
END $$;
COMMIT;
