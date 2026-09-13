-- 064 M6 Delivery & Payment/COD baseline (CA Directive 265). ADDITIVE / EXPAND-ONLY.
-- Delivery & payment la DOMAIN SONG SONG, khoa theo order_id (FK) — KHONG sua orders.status M2/M5.
-- Tien = so nguyen VND. Tach 3 nghia: amount_due / evidence-reported / shop-confirmed (khong boolean `paid`).
-- Fee/region unknown = quote_required (khong phai 0). Mutation di qua command bus (idempotency/audit) o tang service.
-- Runtime role alpha3s_app nhan SELECT/INSERT/UPDATE qua ALTER DEFAULT PRIVILEGES (migration 024); cac bang
-- evidence append-only duoc khoa bang trigger forbid-UPDATE/DELETE (cho phep INSERT).
-- Migration khong renumber/backfill; khong sua auth/Messenger. Rollback: DROP cac object o cuoi file (runbook).

-- ============================ Shipping weight (products) ============================
-- CHI shipping/gross weight moi dung tinh cuoc (net_weight_g la net, khong dung). NULL -> manual quote.
ALTER TABLE products ADD COLUMN IF NOT EXISTS shipping_weight_g INTEGER
    CHECK (shipping_weight_g IS NULL OR shipping_weight_g >= 0);

-- ============================ Region / zone config ============================
-- Map verified address (province_code[, ward_code]) -> zone. Thieu mapping -> resolver tra 'unknown' (manual).
-- 'bmt_inner' = noi thanh Buon Ma Thuot (ward-level; ban do noi thanh do PO cau hinh sau — seed rong).
CREATE TABLE IF NOT EXISTS delivery_zones (
    id            BIGSERIAL PRIMARY KEY,
    province_code TEXT NOT NULL,
    ward_code     TEXT,                              -- NULL = ap cho ca province
    zone          TEXT NOT NULL CHECK (zone IN ('bmt_inner', 'province', 'unknown')),
    version       INTEGER NOT NULL DEFAULT 1,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Mot mapping active cho moi (province, ward) cu the.
CREATE UNIQUE INDEX IF NOT EXISTS uq_delivery_zone_active
    ON delivery_zones (province_code, COALESCE(ward_code, '')) WHERE active;

-- ============================ Shipping fee rules (policy Robanme) ============================
-- (zone, weight tier) -> fee cu the HOAC quote_required. Khong match rule nao -> resolver mac dinh quote_required.
CREATE TABLE IF NOT EXISTS shipping_fee_rules (
    id             BIGSERIAL PRIMARY KEY,
    zone           TEXT NOT NULL CHECK (zone IN ('bmt_inner', 'province', 'unknown')),
    weight_min_g   INTEGER NOT NULL CHECK (weight_min_g >= 0),
    weight_max_g   INTEGER NOT NULL CHECK (weight_max_g >= weight_min_g),
    fee_vnd        INTEGER CHECK (fee_vnd IS NULL OR fee_vnd >= 0),
    quote_required BOOLEAN NOT NULL DEFAULT FALSE,
    version        INTEGER NOT NULL DEFAULT 1,
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- fee_vnd va quote_required loai tru: rule co fee cu the HOAC yeu cau quote, khong ca hai.
    CONSTRAINT fee_rule_fee_xor_quote CHECK (
        (quote_required AND fee_vnd IS NULL) OR (NOT quote_required AND fee_vnd IS NOT NULL)),
    -- CA 266 §4: business key de seed IDEMPOTENT (chay lai migration khong nhan ban rule).
    CONSTRAINT uq_fee_rule UNIQUE (zone, weight_min_g, weight_max_g, version)
);
CREATE INDEX IF NOT EXISTS idx_fee_rule_lookup ON shipping_fee_rules (zone, weight_min_g, weight_max_g) WHERE active;

-- Seed policy Robanme (giao-nhan-hang, doc 13/09). Khoang website KHONG xac dinh -> khong seed -> quote_required.
-- ON CONFLICT tren business key -> re-run migration KHONG dup (CA 266 §4: truoc day 8 rows, nay giu 4).
INSERT INTO shipping_fee_rules (zone, weight_min_g, weight_max_g, fee_vnd, quote_required, version) VALUES
    ('bmt_inner', 500, 5000, 0, FALSE, 1),        -- noi thanh BMT 500-5000g mien phi
    ('bmt_inner', 5500, 10000, 0, FALSE, 1),      -- noi thanh BMT 5500-10000g mien phi
    ('province', 500, 5000, 30000, FALSE, 1),     -- tinh khac 500-5000g = 30.000d
    ('province', 5500, 10000, NULL, TRUE, 1)      -- tinh khac 5500-10000g = 36.000-60.000d (khoang) -> staff chot
ON CONFLICT (zone, weight_min_g, weight_max_g, version) DO NOTHING;

-- ============================ Shipments ============================
-- Mot shipment active cho moi order (baseline). Lich su cac lan giao thuoc shipment (attempts).
CREATE TABLE IF NOT EXISTS shipments (
    id               BIGSERIAL PRIMARY KEY,
    order_id         BIGINT NOT NULL UNIQUE REFERENCES orders (id),
    status           TEXT NOT NULL DEFAULT 'pending_prep'
        CHECK (status IN ('pending_prep', 'ready_to_ship', 'in_transit',
                          'delivered', 'delivery_failed', 'return_pending')),
    carrier          TEXT,                            -- nhap tay (Grab/GHN/GHTK/ViettelPost/noi bo); khong tich hop API
    tracking_text    TEXT,
    zone             TEXT NOT NULL DEFAULT 'unknown'
        CHECK (zone IN ('bmt_inner', 'province', 'unknown')),
    weight_g         INTEGER CHECK (weight_g IS NULL OR weight_g >= 0),
    delivery_fee_vnd INTEGER CHECK (delivery_fee_vnd IS NULL OR delivery_fee_vnd >= 0),
    fee_status       TEXT NOT NULL DEFAULT 'unknown'
        CHECK (fee_status IN ('quoted', 'quote_required', 'unknown')),
    eta_text         TEXT,
    eta_start_at     TIMESTAMPTZ,                     -- CA 266-08: moc bat dau ETA (COD confirm / transfer received)
    eta_start_source TEXT,                            -- 'cod_confirmed' | 'transfer_received' | 'manual'
    handover_at      TIMESTAMPTZ,
    policy_version   TEXT,                            -- snapshot label policy luc quote
    quote_rule_version INTEGER,                       -- CA 266-04: snapshot version RULE thuc ap (config co the doi)
    quote_source     TEXT,                            -- 'auto_rule' | 'staff_manual'
    version          INTEGER NOT NULL DEFAULT 1,      -- optimistic concurrency
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- fee_status='quoted' <-> co fee cu the; 'quote_required'/'unknown' -> fee NULL.
    CONSTRAINT shipment_fee_consistency CHECK (
        (fee_status = 'quoted' AND delivery_fee_vnd IS NOT NULL)
        OR (fee_status IN ('quote_required', 'unknown') AND delivery_fee_vnd IS NULL))
);

CREATE TABLE IF NOT EXISTS shipment_delivery_attempts (
    id              BIGSERIAL PRIMARY KEY,
    shipment_id     BIGINT NOT NULL REFERENCES shipments (id),
    attempt_no      INTEGER NOT NULL CHECK (attempt_no >= 1 AND attempt_no <= 3),
    attempted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    result          TEXT NOT NULL CHECK (result IN ('success', 'failed', 'no_contact', 'rescheduled')),
    reason          TEXT,
    note            TEXT,
    next_contact_at TIMESTAMPTZ,
    recorded_by     TEXT NOT NULL,
    command_key     TEXT NOT NULL,                   -- CA 266-03: client idempotency key (retry cung key = 1 attempt)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_attempt_no UNIQUE (shipment_id, attempt_no),
    CONSTRAINT uq_attempt_cmd UNIQUE (shipment_id, command_key)  -- DB-atomic: replay khong tao attempt moi
);
-- Attempts la append-only (evidence lich su giao). Cho phep INSERT, cam UPDATE/DELETE.

-- ============================ Bank accounts (receiving config) ============================
CREATE TABLE IF NOT EXISTS bank_accounts (
    id             BIGSERIAL PRIMARY KEY,
    bank           TEXT NOT NULL,
    account_number TEXT NOT NULL,                     -- TEXT: giu so 0 dau
    holder_name    TEXT NOT NULL,
    branch         TEXT,
    version        INTEGER NOT NULL DEFAULT 1,
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    is_test        BOOLEAN NOT NULL DEFAULT FALSE,    -- fixture nhan ro "TEST — KHONG CHUYEN TIEN"
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_bank_account_active ON bank_accounts (active) WHERE active;  -- 1 active du

-- ============================ Payments ============================
-- Tach 3 nghia: amount_due_vnd (can thu) / evidence (payment_events) / status (shop da xac nhan toi dau).
CREATE TABLE IF NOT EXISTS payments (
    id            BIGSERIAL PRIMARY KEY,
    order_id      BIGINT NOT NULL UNIQUE REFERENCES orders (id),
    method        TEXT NOT NULL CHECK (method IN ('COD', 'BANK_TRANSFER')),
    amount_due_vnd INTEGER CHECK (amount_due_vnd IS NULL OR amount_due_vnd >= 0),  -- NULL khi fee chua chot
    -- CA 266-05: TONG shop THUC nhan (cumulative shop_confirmed/reconciled) — tach voi due va evidence khach bao.
    amount_received_vnd INTEGER NOT NULL DEFAULT 0 CHECK (amount_received_vnd >= 0),
    currency      TEXT NOT NULL DEFAULT 'VND' CHECK (currency = 'VND'),
    -- BANK_TRANSFER: awaiting -> reported -> confirmed ; COD: awaiting -> collected -> reconciled
    -- CA 266-05: 'discrepancy' = da co evidence nhung thieu/thua, CHO staff xu ly (khong auto-confirm).
    status        TEXT NOT NULL DEFAULT 'awaiting'
        CHECK (status IN ('awaiting', 'reported', 'confirmed', 'collected', 'reconciled', 'discrepancy')),
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Evidence append-only: moi lan ghi nhan (khach bao / COD thu / shop xac nhan / reconcile / correction).
CREATE TABLE IF NOT EXISTS payment_events (
    id             BIGSERIAL PRIMARY KEY,
    payment_id     BIGINT NOT NULL REFERENCES payments (id),
    kind           TEXT NOT NULL CHECK (kind IN
        ('customer_reported', 'cod_collected', 'shop_confirmed_received', 'reconciled', 'correction')),
    -- CA 266-05: correction la delta dieu chinh received, CO THE AM (ghi du -> tru lai); cac kind khac >= 0.
    amount_vnd     INTEGER CHECK (amount_vnd IS NULL OR amount_vnd >= 0 OR kind = 'correction'),
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    recorded_by    TEXT NOT NULL,
    reference      TEXT,                             -- business ref (vd ma giao dich CK) — chong ghi lai CUNG chung tu
    note           TEXT,
    attachment_ref TEXT,
    command_key    TEXT NOT NULL,                    -- CA 266-03: client idempotency key (replay cung key = 1 event)
    corrects_event_id BIGINT REFERENCES payment_events (id),  -- CA 266-05: correction tro ve event goc bi sua
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_pe_cmd UNIQUE (payment_id, command_key)      -- DB-atomic: replay khong tao event moi
);
CREATE INDEX IF NOT EXISTS idx_payment_events_payment ON payment_events (payment_id, occurred_at);

-- Payment instruction (chuyen khoan): snapshot account version + noi dung deterministic tu ma don.
CREATE TABLE IF NOT EXISTS payment_instructions (
    id               BIGSERIAL PRIMARY KEY,
    order_id         BIGINT NOT NULL REFERENCES orders (id),
    payment_id       BIGINT NOT NULL REFERENCES payments (id),
    bank_account_id  BIGINT NOT NULL REFERENCES bank_accounts (id),
    account_version  INTEGER NOT NULL,                -- snapshot version dung luc phat
    bank_snapshot            TEXT NOT NULL,
    account_number_snapshot  TEXT NOT NULL,
    holder_snapshot          TEXT NOT NULL,
    transfer_content TEXT NOT NULL,                   -- deterministic tu ma don
    amount_vnd       INTEGER,
    is_test          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_payment_instr_order ON payment_instructions (order_id);

-- ============================ Immutability (append-only evidence) ============================
CREATE OR REPLACE FUNCTION m6_forbid_mutate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Cho phep DELETE khi session dat tuong minh `SET LOCAL m6.cleanup='on'` (chi script cleanup test batch
    -- lam vay; runtime app KHONG BAO GIO dat -> immutability giu nguyen cho du lieu that). UPDATE luon cam.
    IF TG_OP = 'DELETE' AND current_setting('m6.cleanup', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION '% la ho so bat bien (append-only) — khong duoc %', TG_TABLE_NAME, TG_OP;
END;
$$;
DROP TRIGGER IF EXISTS sda_no_mutate ON shipment_delivery_attempts;
CREATE TRIGGER sda_no_mutate BEFORE UPDATE OR DELETE ON shipment_delivery_attempts
    FOR EACH ROW EXECUTE FUNCTION m6_forbid_mutate();
DROP TRIGGER IF EXISTS pe_no_mutate ON payment_events;
CREATE TRIGGER pe_no_mutate BEFORE UPDATE OR DELETE ON payment_events
    FOR EACH ROW EXECUTE FUNCTION m6_forbid_mutate();
DROP TRIGGER IF EXISTS pi_no_mutate ON payment_instructions;
CREATE TRIGGER pi_no_mutate BEFORE UPDATE OR DELETE ON payment_instructions
    FOR EACH ROW EXECUTE FUNCTION m6_forbid_mutate();

-- ============================ RBAC (reuse + additive) ============================
-- Reuse forward-declared: payment.cod_record (ghi evidence COD), payment.reconcile (COD da doi soat = admin/PO),
-- fulfillment.status_change (doi shipment status). Them phan biet ro authority.
INSERT INTO permissions (key, description) VALUES
    ('payment.transfer_confirm', 'Xac nhan da nhan tien chuyen khoan (tach voi cod_record va reconcile)'),
    ('bank.config',              'Nhap/sua tai khoan ngan hang nhan tien'),
    ('shipment.manage',          'Tao shipment, ghi attempt, quote fee')
ON CONFLICT DO NOTHING;
-- Gan role: admin co full qua wildcard/seed hien huu; bo sung cac role van hanh.
INSERT INTO role_permissions (role_key, permission_key) VALUES
    ('delivery', 'shipment.manage'),
    ('sales',    'shipment.manage'),
    ('admin',    'shipment.manage'),
    ('admin',    'payment.transfer_confirm'),
    ('admin',    'payment.reconcile'),
    ('admin',    'bank.config')
ON CONFLICT DO NOTHING;

-- ============================ Outbox: cho phep M6 notify khong-command-backed ============================
-- Giong escalation (062): M6 notify event dedupe theo (destination, dedupe_key) dam bao effective-once,
-- khong can command_executions row. Mo rong allowlist CHECK (additive).
ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS outbox_command_id_required_unless_escalation;
ALTER TABLE outbox_events ADD CONSTRAINT outbox_command_id_required_unless_escalation
    CHECK (
        command_id IS NOT NULL
        OR event_type IN (
            'order.escalated.notify', 'handoff.escalated.notify',
            'shipment.handover.notify', 'shipment.delivered.notify', 'shipment.failed.notify',
            'payment.check_request.notify', 'payment.confirmed.notify')
    );

-- ROLLBACK (runbook — chi khi chua co du lieu M6 that su can giu):
--   ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS outbox_command_id_required_unless_escalation;
--   ALTER TABLE outbox_events ADD CONSTRAINT outbox_command_id_required_unless_escalation
--     CHECK (command_id IS NOT NULL OR event_type IN ('order.escalated.notify','handoff.escalated.notify'));
--   DROP TABLE IF EXISTS payment_instructions, payment_events, payments,
--     shipment_delivery_attempts, shipments, bank_accounts, shipping_fee_rules, delivery_zones CASCADE;
--   DROP FUNCTION IF EXISTS m6_forbid_mutate();
--   ALTER TABLE products DROP COLUMN IF EXISTS shipping_weight_g;
--   DELETE FROM role_permissions WHERE permission_key IN ('payment.transfer_confirm','bank.config','shipment.manage');
--   DELETE FROM permissions WHERE key IN ('payment.transfer_confirm','bank.config','shipment.manage');
