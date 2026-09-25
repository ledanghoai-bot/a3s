-- 072 — CA Directive 387: huy don thong nhat (lifecycle cancelled cho M6/M7), identity kenh TUONG MINH + ChatID bat buoc.
-- KHONG sua migration 064/065 da deploy: CHECK duoc DROP/ADD lai trong migration MOI nay (mo rong gia tri, khong thu hep).
-- Additive + reversible (ROLLBACK o cuoi file). Backfill identity theo QUY TAC KHAI BAO + guard: dong nao khong khop quy
-- tac -> RAISE (migration that bai, KHONG gan identity gia). Bao cao tung dong legacy nop CA truoc apply (Directive 387 §5).

-- ============================ (A) Lifecycle huy cho M6/M7 ============================
ALTER TABLE shipments DROP CONSTRAINT IF EXISTS shipments_status_check;
ALTER TABLE shipments ADD CONSTRAINT shipments_status_check CHECK (status IN
    ('pending_prep', 'ready_to_ship', 'in_transit', 'delivered', 'delivery_failed', 'return_pending', 'cancelled'));
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;

ALTER TABLE payments DROP CONSTRAINT IF EXISTS payments_status_check;
ALTER TABLE payments ADD CONSTRAINT payments_status_check CHECK (status IN
    ('awaiting', 'reported', 'confirmed', 'collected', 'reconciled', 'discrepancy', 'cancelled'));
ALTER TABLE payments ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;

-- payment_instructions la ho so BAT BIEN (trigger pi_no_mutate, 064) -> KHONG sua. Void = ban ghi APPEND-ONLY rieng
-- (1 dong / instruction); matching SePay + UI coi instruction co dong void la da huy.
CREATE TABLE IF NOT EXISTS payment_instruction_voids (
    instruction_id BIGINT PRIMARY KEY REFERENCES payment_instructions (id),
    order_id       BIGINT NOT NULL REFERENCES orders (id),
    voided_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason         TEXT NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 600),
    command_id     TEXT,
    voided_by      TEXT NOT NULL
);
CREATE OR REPLACE FUNCTION payment_instruction_voids_no_mutate() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'payment_instruction_voids la append-only — khong duoc %', TG_OP;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS piv_no_mutate ON payment_instruction_voids;
CREATE TRIGGER piv_no_mutate BEFORE UPDATE OR DELETE ON payment_instruction_voids
    FOR EACH ROW EXECUTE FUNCTION payment_instruction_voids_no_mutate();

ALTER TABLE fulfillment_conversations DROP CONSTRAINT IF EXISTS fulfillment_conversations_step_check;
ALTER TABLE fulfillment_conversations ADD CONSTRAINT fulfillment_conversations_step_check CHECK (step IN
    ('routing', 'awaiting_method', 'cod_handoff', 'awaiting_transfer', 'staff_attention', 'completed', 'cancelled'));

ALTER TABLE staff_attention DROP CONSTRAINT IF EXISTS staff_attention_reason_check;
ALTER TABLE staff_attention ADD CONSTRAINT staff_attention_reason_check CHECK (reason IN
    ('address', 'quote', 'account', 'method', 'payment_mismatch', 'unmatched_webhook', 'payment_timeout',
     'large_order_review', 'quantity_unit_review', 'provider_error', 'other',
     'refund_required', 'order_cancel_exception'));

-- ============================ (B) Identity kenh tuong minh (PO Record 386) ============================
ALTER TABLE customers ADD COLUMN IF NOT EXISTS channel TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS external_chat_id TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_by_staff_id BIGINT REFERENCES staff_users (id);

-- Backfill MOT LAN theo quy uoc luu tru DA KIEM CHUNG TRONG CODE (khong phai suy doan runtime):
--   * telegram_customer_listener.py luon ghi psid = 'tg:<chat_id>'           -> channel telegram_customer
--   * orders.py (don Dashboard cu) ghi psid = 'manual:<nonce>'                 -> channel dashboard
--   * webhook Messenger ghi psid = PSID so nguyen goc (chi gom chu so)         -> channel messenger
-- Moi dong KHONG khop 1 trong 3 quy tac -> RAISE, KHONG gan gia tri.
UPDATE customers SET channel = 'telegram_customer', external_chat_id = substr(psid, 4)
    WHERE channel IS NULL AND psid LIKE 'tg:%' AND length(psid) > 3;
UPDATE customers SET channel = 'dashboard', external_chat_id = psid
    WHERE channel IS NULL AND psid LIKE 'manual:%';
UPDATE customers SET channel = 'messenger', external_chat_id = psid
    WHERE channel IS NULL AND psid ~ '^[0-9]+$';
DO $$
DECLARE n INTEGER;
BEGIN
    SELECT count(*) INTO n FROM customers WHERE channel IS NULL OR external_chat_id IS NULL;
    IF n > 0 THEN
        RAISE EXCEPTION '072: % customer khong khop quy tac identity — can PO/CA xu ly tung dong, KHONG gan gia', n;
    END IF;
END $$;

-- orders.origin_channel NULL (don legacy) -> kenh cua CHINH customer da gan (khong tao identity moi).
UPDATE orders o SET origin_channel = c.channel
    FROM customers c WHERE o.customer_id = c.id AND o.origin_channel IS NULL;
DO $$
DECLARE n INTEGER;
BEGIN
    SELECT count(*) INTO n FROM orders WHERE customer_id IS NULL OR origin_channel IS NULL;
    IF n > 0 THEN
        RAISE EXCEPTION '072: % order thieu customer/origin_channel sau backfill — dung, bao CA', n;
    END IF;
END $$;

ALTER TABLE customers ALTER COLUMN channel SET NOT NULL;
ALTER TABLE customers ALTER COLUMN external_chat_id SET NOT NULL;
DO $$ BEGIN
    ALTER TABLE customers ADD CONSTRAINT ck_customers_channel
        CHECK (channel IN ('telegram_customer', 'messenger', 'dashboard'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    ALTER TABLE customers ADD CONSTRAINT uq_customers_channel_chat UNIQUE (channel, external_chat_id);
EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL; END $$;
ALTER TABLE orders ALTER COLUMN customer_id SET NOT NULL;
ALTER TABLE orders ALTER COLUMN origin_channel SET NOT NULL;
-- Don Dashboard MOI phai gan staff tao don (don dashboard legacy khong co -> NOT VALID, chi ap dong moi)
DO $$ BEGIN
    ALTER TABLE orders ADD CONSTRAINT ck_orders_dashboard_staff
        CHECK (origin_channel <> 'dashboard' OR created_by_staff_id IS NOT NULL) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ============================ ROLLBACK (chay tay khi can; KHONG tu dong) ============================
-- Truoc khi rollback (A): chuyen moi dong 'cancelled' ve trang thai hop le cu hoac xoa (khong con gia tri trong CHECK cu).
-- ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_orders_dashboard_staff;
-- ALTER TABLE orders ALTER COLUMN origin_channel DROP NOT NULL; ALTER TABLE orders ALTER COLUMN customer_id DROP NOT NULL;
-- ALTER TABLE customers DROP CONSTRAINT IF EXISTS uq_customers_channel_chat; ALTER TABLE customers DROP CONSTRAINT IF EXISTS ck_customers_channel;
-- ALTER TABLE customers DROP COLUMN IF EXISTS external_chat_id; ALTER TABLE customers DROP COLUMN IF EXISTS channel;
-- ALTER TABLE orders DROP COLUMN IF EXISTS created_by_staff_id;
-- DROP TABLE IF EXISTS payment_instruction_voids; DROP FUNCTION IF EXISTS payment_instruction_voids_no_mutate();
-- ALTER TABLE payments DROP COLUMN IF EXISTS cancelled_at; ALTER TABLE shipments DROP COLUMN IF EXISTS cancelled_at;
-- (CHECK cu cua 064/065: xem migration goc, ADD lai sau khi khong con gia tri moi)
