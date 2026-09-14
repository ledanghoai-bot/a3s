-- 065 M7 Conversational Fulfillment PRE-CUSTOMER (CA Directive 272). ADDITIVE / EXPAND-ONLY.
-- Khong sua migration 064; khong DROP/truncate; code cu (M6 dashboard) tuong thich (cot moi NULL-able).
-- Pham vi: (A) routing allowlist tu giao co version/effective date + snapshot route/quote tren shipments,
--          hoi thoai fulfillment sau chot don (state machine tat dinh), VietQR snapshot tren instruction,
--          hang doi staff_attention; (B) GHN read-only quote: master-data cache + address map co version +
--          provider quote log; (C0) SePay Test Mode: provider_events ingest (unique provider event) +
--          payment_events kind 'bank_auto_confirmed'.
-- AI KHONG ghi bat ky bang nao truc tiep: moi transition qua service tat dinh (command_key idempotency).

-- ============================ (A) Delivery routing allowlist (PO 272 §2 / §3.2) ============================
-- Allowlist = DU LIEU CAU HINH van hanh (khong hard-code trong prompt). Moi version co effective_from/to;
-- resolver chon version hieu luc tai thoi diem quote va SNAPSHOT version vao shipments -> doi config sau
-- KHONG doi quote da gui.
CREATE TABLE IF NOT EXISTS delivery_routing_versions (
    version         INTEGER PRIMARY KEY,
    effective_from  TIMESTAMPTZ NOT NULL,
    effective_to    TIMESTAMPTZ,                    -- NULL = con hieu luc
    dataset_version TEXT NOT NULL,                  -- dataset dia gioi dung de lap ma phuong (VN-ADMIN-...)
    note            TEXT,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (effective_to IS NULL OR effective_to > effective_from)
);

-- Phuong tu giao (SELF_DELIVERY) theo version. Ma phuong theo dataset chinh phu (2 cap: tinh -> phuong/xa).
CREATE TABLE IF NOT EXISTS delivery_self_wards (
    id              BIGSERIAL PRIMARY KEY,
    routing_version INTEGER NOT NULL REFERENCES delivery_routing_versions (version),
    province_code   TEXT NOT NULL,
    ward_code       TEXT NOT NULL,
    ward_name       TEXT NOT NULL,
    source_note     TEXT,                           -- nguon: alias legacy (phuong/xa cu) tu dataset
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_self_ward UNIQUE (routing_version, province_code, ward_code)
);

-- Seed v1 (PO 271 §4 / 272 §2): noi thanh Do thi Buon Ma Thuot = 5 PHUONG hinh thanh tu TP Buon Ma Thuot cu
-- (dataset VN-ADMIN-2025-07-v2, tinh Dak Lak ma 66). Phuong Buon Ho (24305) + Cu Bao (24340) la phuong phia Tay
-- nhung goc THI XA BUON HO (cach BMT ~40km) -> KHONG dua vao v1 (fail-closed -> GHN); PO quyet rieng neu muon.
INSERT INTO delivery_routing_versions (version, effective_from, effective_to, dataset_version, note, created_by)
VALUES (1, TIMESTAMPTZ '2026-09-13 00:00:00+07', NULL, 'VN-ADMIN-2025-07-v2',
        'v1 — 5 phuong goc TP Buon Ma Thuot (PO 2026-09-13). Buon Ho/Cu Bao ngoai allowlist (PO decision).',
        'm7-seed')
ON CONFLICT (version) DO NOTHING;

INSERT INTO delivery_self_wards (routing_version, province_code, ward_code, ward_name, source_note) VALUES
    (1, '66', '24121', 'Phường Tân Lập',        'legacy: P. Tân Hòa | P. Tân Lập | X. Hòa Thắng'),
    (1, '66', '24133', 'Phường Buôn Ma Thuột',  'legacy: P. Tân Lợi | P. Tân Thành | P. Tân Tiến | P. Thành Công | P. Tự An | X. Cư Êbur'),
    (1, '66', '24154', 'Phường Thành Nhất',     'legacy: P. Khánh Xuân | P. Thành Nhất'),
    (1, '66', '24163', 'Phường Tân An',         'legacy: P. Tân An | X. Ea Tu | X. Hòa Thuận'),
    (1, '66', '24169', 'Phường Ea Kao',         'legacy: P. Ea Tam | X. Ea Kao')
ON CONFLICT ON CONSTRAINT uq_self_ward DO NOTHING;

-- ============================ (A) Shipments: route + quote snapshot ============================
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS routing_source TEXT
    CHECK (routing_source IS NULL OR routing_source IN ('SELF_DELIVERY', 'GHN', 'MANUAL_REVIEW'));
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS routing_version  INTEGER;      -- delivery_routing_versions.version
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS routing_province_code TEXT;
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS routing_ward_code TEXT;
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS routing_reason   TEXT;         -- vi sao MANUAL_REVIEW/GHN
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS routed_at        TIMESTAMPTZ;
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS quote_provider   TEXT;         -- self_rule | ghn | manual
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS quote_snapshot   JSONB;        -- request fingerprint, fee breakdown, leadtime, inputs
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS quoted_at        TIMESTAMPTZ;

-- ============================ (A) Products sales unit (CA Amendment 273 §2) ============================
-- Don vi ban theo catalog (vd 'hũ'). Nguong large-order CHI tinh khi MOI item co unit xac dinh = policy.unit;
-- NULL/khac unit -> quantity_unit_review (khong tu coi moi item la 1 hu). Cot NULL-able -> tuong thich M6.
ALTER TABLE products ADD COLUMN IF NOT EXISTS sales_unit TEXT;

-- ============================ (A) Fulfillment policy versions (CA Amendment 273 §2/§3) ============================
-- Config CO VERSION + effective time cho: nguong so luong large-order + don vi tinh + moc timeout/reminder.
-- Order SNAPSHOT policy_version luc chot don -> doi config sau KHONG doi quyet dinh don cu (tru khi staff re-eval).
CREATE TABLE IF NOT EXISTS fulfillment_policy_versions (
    version               INTEGER PRIMARY KEY,
    effective_from        TIMESTAMPTZ NOT NULL,
    effective_to          TIMESTAMPTZ,                      -- NULL = con hieu luc
    large_order_threshold INTEGER NOT NULL,                 -- tong so luong >= nguong -> large_order_review
    large_order_unit      TEXT NOT NULL,                    -- don vi tinh nguong (vd 'hũ')
    reminder1_minutes     INTEGER NOT NULL,                 -- 273: t+7
    reminder2_minutes     INTEGER NOT NULL,                 -- 273: t+13
    timeout_minutes       INTEGER NOT NULL,                 -- 273: t+15
    note                  TEXT,
    created_by            TEXT NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (effective_to IS NULL OR effective_to > effective_from),
    CHECK (reminder1_minutes > 0 AND reminder1_minutes < reminder2_minutes AND reminder2_minutes < timeout_minutes),
    CHECK (large_order_threshold > 0)
);
-- Seed v1 (PO Revision 001 + CA Amendment 273): 100 hũ; nhắc t+7/t+13; timeout t+15.
INSERT INTO fulfillment_policy_versions (version, effective_from, effective_to, large_order_threshold,
    large_order_unit, reminder1_minutes, reminder2_minutes, timeout_minutes, note, created_by)
VALUES (1, TIMESTAMPTZ '2026-09-14 00:00:00+07', NULL, 100, 'hũ', 7, 13, 15,
        'v1 — CA Amendment 273 (PO 2026-09-14): >=100 hũ -> staff; CK 15 phút, nhắc t+7/t+13, timeout t+15.',
        'm7-seed')
ON CONFLICT (version) DO NOTHING;

-- ============================ (A) Conversation state (server-owned, tat dinh) ============================
-- 1 hoi thoai fulfillment / order. Step chuyen qua service co command_key (duplicate inbound/outbox -> replay).
CREATE TABLE IF NOT EXISTS fulfillment_conversations (
    id                   BIGSERIAL PRIMARY KEY,
    order_id             BIGINT NOT NULL UNIQUE REFERENCES orders (id),
    channel              TEXT NOT NULL,                     -- telegram_customer | messenger
    customer_ref         TEXT NOT NULL,                     -- psid (tg:<chat_id>)
    step                 TEXT NOT NULL CHECK (step IN
        ('routing', 'awaiting_method', 'cod_handoff', 'awaiting_transfer', 'staff_attention', 'completed')),
    method               TEXT CHECK (method IS NULL OR method IN ('COD', 'BANK_TRANSFER')),
    instruction_id       BIGINT REFERENCES payment_instructions (id),
    policy_version       INTEGER REFERENCES fulfillment_policy_versions (version),  -- 273: snapshot luc chot don
    large_order_qty      INTEGER,                           -- tong so luong (hũ) computed; NULL neu unit mo ho
    transfer_started_at  TIMESTAMPTZ,                       -- = payment_instruction.created_at committed (moc 273)
    transfer_deadline_at TIMESTAMPTZ,                       -- = transfer_started_at + timeout_minutes (t+15)
    method_prompts       INTEGER NOT NULL DEFAULT 0,        -- so lan hoi lai method (reply mo ho)
    attention_reason     TEXT,
    attention_at         TIMESTAMPTZ,
    completed_at         TIMESTAMPTZ,
    version              INTEGER NOT NULL DEFAULT 1,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fc_step_deadline ON fulfillment_conversations (step, transfer_deadline_at);
CREATE INDEX IF NOT EXISTS idx_fc_step_started ON fulfillment_conversations (step, transfer_started_at);

-- CA Amendment 273 §3: dedupe MOI reminder theo (payment_instruction_id, reminder_no) — restart/retry khong nhac 2 lan.
CREATE TABLE IF NOT EXISTS fulfillment_reminders (
    payment_instruction_id BIGINT NOT NULL REFERENCES payment_instructions (id),
    reminder_no            SMALLINT NOT NULL CHECK (reminder_no IN (1, 2)),
    sent_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (payment_instruction_id, reminder_no)
);

-- Append-only journal moi transition (command_key idempotency: replay tra lai reply cu, khong effect moi).
CREATE TABLE IF NOT EXISTS fulfillment_conversation_events (
    id           BIGSERIAL PRIMARY KEY,
    order_id     BIGINT NOT NULL REFERENCES orders (id),
    command_key  TEXT NOT NULL,
    source       TEXT NOT NULL CHECK (source IN ('system', 'customer', 'worker', 'staff', 'provider')),
    from_step    TEXT,
    to_step      TEXT NOT NULL,
    detail       JSONB,
    reply_text   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_fce_cmd UNIQUE (order_id, command_key)
);
DROP TRIGGER IF EXISTS fce_no_mutate ON fulfillment_conversation_events;
CREATE TRIGGER fce_no_mutate BEFORE UPDATE OR DELETE ON fulfillment_conversation_events
    FOR EACH ROW EXECUTE FUNCTION m6_forbid_mutate();

-- Hang doi staff_attention (272 §4): 1 dong OPEN / (order, reason). Resolve = UPDATE (co audit o service).
CREATE TABLE IF NOT EXISTS staff_attention (
    id              BIGSERIAL PRIMARY KEY,
    order_id        BIGINT REFERENCES orders (id),
    reason          TEXT NOT NULL CHECK (reason IN
        ('address', 'quote', 'account', 'method', 'payment_mismatch', 'unmatched_webhook',
         'payment_timeout', 'large_order_review', 'quantity_unit_review',   -- CA Amendment 273
         'provider_error', 'other')),
    detail          JSONB,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT,
    resolution_note TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_staff_attention_open ON staff_attention (order_id, reason) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_staff_attention_status ON staff_attention (status, created_at);

-- ============================ (A) VietQR snapshot tren instruction (272 §3.3) ============================
ALTER TABLE bank_accounts ADD COLUMN IF NOT EXISTS bin TEXT
    CHECK (bin IS NULL OR bin ~ '^[0-9]{6}$');                  -- NAPAS BIN 6 chu so (VietinBank 970415)
ALTER TABLE payment_instructions ADD COLUMN IF NOT EXISTS bin_snapshot TEXT;
ALTER TABLE payment_instructions ADD COLUMN IF NOT EXISTS qr_payload   TEXT;    -- EMVCo/NAPAS payload (tai tao anh tat dinh)
ALTER TABLE payment_instructions ADD COLUMN IF NOT EXISTS qr_version   INTEGER NOT NULL DEFAULT 1;
ALTER TABLE payment_instructions ADD COLUMN IF NOT EXISTS command_key  TEXT;    -- idempotent generate (replay = cung row)
ALTER TABLE payment_instructions ADD COLUMN IF NOT EXISTS instruction_version INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS uq_pi_cmd ON payment_instructions (payment_id, command_key) WHERE command_key IS NOT NULL;

-- ============================ (C0) Provider events (SePay Test Mode) ============================
-- Raw envelope tach khoi payment domain. UNIQUE (provider, provider_event_id) -> retry/duplicate khong tao 2 effect.
CREATE TABLE IF NOT EXISTS provider_events (
    id                BIGSERIAL PRIMARY KEY,
    provider          TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    mode              TEXT NOT NULL DEFAULT 'test' CHECK (mode IN ('test', 'live')),
    payload_hash      TEXT NOT NULL,
    raw               JSONB NOT NULL,                          -- toi thieu can thiet (khong secret)
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    processing_state  TEXT NOT NULL DEFAULT 'received' CHECK (processing_state IN
        ('received', 'matched', 'unmatched', 'discrepancy', 'ignored', 'error')),
    match_reason      TEXT,
    order_id          BIGINT,
    payment_id        BIGINT,
    payment_event_id  BIGINT,
    attempts          INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT,
    processed_at      TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_provider_event UNIQUE (provider, provider_event_id)
);
CREATE INDEX IF NOT EXISTS idx_provider_events_pending ON provider_events (processing_state, received_at)
    WHERE processing_state = 'received';

-- payment_events: them kind tu dong xac nhan tu provider (chi payment service tat dinh ghi sau khi match pass).
ALTER TABLE payment_events DROP CONSTRAINT IF EXISTS payment_events_kind_check;
ALTER TABLE payment_events ADD CONSTRAINT payment_events_kind_check CHECK (kind IN
    ('customer_reported', 'cod_collected', 'shop_confirmed_received', 'reconciled', 'correction',
     'bank_auto_confirmed'));

-- ============================ (B) GHN read-only quote: cache + address map + log ============================
CREATE TABLE IF NOT EXISTS carrier_master_data (
    provider    TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('province', 'district', 'ward')),
    key         TEXT NOT NULL,                                 -- provider id (province_id/district_id/ward_code)
    parent_key  TEXT,
    name        TEXT NOT NULL,
    payload     JSONB NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, kind, key)
);

-- Adapter dia chi co version: (province_code, ward_code) chinh phu -> ID provider. KHONG gan ma chinh phu truc tiep.
CREATE TABLE IF NOT EXISTS carrier_address_map (
    id                  BIGSERIAL PRIMARY KEY,
    provider            TEXT NOT NULL,
    map_version         INTEGER NOT NULL,
    province_code       TEXT NOT NULL,
    ward_code           TEXT NOT NULL,
    carrier_province_id INTEGER,
    carrier_district_id INTEGER,
    carrier_ward_code   TEXT,
    status              TEXT NOT NULL CHECK (status IN ('matched', 'ambiguous', 'manual', 'unmatched')),
    method              TEXT,                                  -- legacy_alias_exact | legacy_alias_district | staff
    confidence          NUMERIC(4, 3),
    note                TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_carrier_addr_map UNIQUE (provider, map_version, province_code, ward_code)
);

CREATE TABLE IF NOT EXISTS provider_quote_log (
    id                  BIGSERIAL PRIMARY KEY,
    provider            TEXT NOT NULL,
    order_id            BIGINT,
    request_fingerprint TEXT NOT NULL,
    request             JSONB NOT NULL,                        -- KHONG token/secret
    response            JSONB,
    status              TEXT NOT NULL CHECK (status IN ('ok', 'error', 'timeout', 'skipped')),
    http_status         INTEGER,
    duration_ms         INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_provider_quote_log_order ON provider_quote_log (order_id, created_at);
DROP TRIGGER IF EXISTS pql_no_mutate ON provider_quote_log;
CREATE TRIGGER pql_no_mutate BEFORE UPDATE OR DELETE ON provider_quote_log
    FOR EACH ROW EXECUTE FUNCTION m6_forbid_mutate();

-- ============================ RBAC (additive) ============================
INSERT INTO permissions (key, description) VALUES
    ('fulfillment.attention_resolve', 'Dong hang doi staff_attention (M7)'),
    ('routing.config',                'Cau hinh allowlist tu giao / address map (M7)'),
    ('provider.events_view',          'Xem provider events (SePay test) va quote log (M7)')
ON CONFLICT DO NOTHING;
INSERT INTO role_permissions (role_key, permission_key) VALUES
    ('delivery', 'fulfillment.attention_resolve'),
    ('sales',    'fulfillment.attention_resolve'),
    ('admin',    'fulfillment.attention_resolve'),
    ('admin',    'routing.config'),
    ('admin',    'provider.events_view'),
    ('sales',    'provider.events_view')
ON CONFLICT DO NOTHING;

-- ============================ Outbox allowlist: M7 notify khong-command-backed ============================
ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS outbox_command_id_required_unless_escalation;
ALTER TABLE outbox_events ADD CONSTRAINT outbox_command_id_required_unless_escalation
    CHECK (
        command_id IS NOT NULL
        OR event_type IN (
            'order.escalated.notify', 'handoff.escalated.notify',
            'shipment.handover.notify', 'shipment.delivered.notify', 'shipment.failed.notify',
            'payment.check_request.notify', 'payment.confirmed.notify',
            'fulfillment.prompt.notify', 'fulfillment.instruction.notify', 'fulfillment.reminder.notify',
            'fulfillment.staff.notify', 'fulfillment.cod.notify')
    );

-- ROLLBACK (runbook — rollback bang code/config truoc; schema additive giu lai):
--   ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS outbox_command_id_required_unless_escalation;
--   ALTER TABLE outbox_events ADD CONSTRAINT outbox_command_id_required_unless_escalation CHECK (command_id IS NOT NULL
--     OR event_type IN ('order.escalated.notify','handoff.escalated.notify','shipment.handover.notify',
--     'shipment.delivered.notify','shipment.failed.notify','payment.check_request.notify','payment.confirmed.notify'));
--   ALTER TABLE payment_events DROP CONSTRAINT IF EXISTS payment_events_kind_check;
--   ALTER TABLE payment_events ADD CONSTRAINT payment_events_kind_check CHECK (kind IN
--     ('customer_reported','cod_collected','shop_confirmed_received','reconciled','correction'));
--   DROP TABLE IF EXISTS provider_quote_log, carrier_address_map, carrier_master_data, provider_events,
--     fulfillment_reminders, staff_attention, fulfillment_conversation_events, fulfillment_conversations,
--     fulfillment_policy_versions, delivery_self_wards, delivery_routing_versions CASCADE;
--   ALTER TABLE products DROP COLUMN IF EXISTS sales_unit;
--   ALTER TABLE payment_instructions DROP COLUMN IF EXISTS bin_snapshot, DROP COLUMN IF EXISTS qr_payload,
--     DROP COLUMN IF EXISTS qr_version, DROP COLUMN IF EXISTS command_key, DROP COLUMN IF EXISTS instruction_version;
--   ALTER TABLE bank_accounts DROP COLUMN IF EXISTS bin;
--   ALTER TABLE shipments DROP COLUMN IF EXISTS routing_source, DROP COLUMN IF EXISTS routing_version,
--     DROP COLUMN IF EXISTS routing_province_code, DROP COLUMN IF EXISTS routing_ward_code,
--     DROP COLUMN IF EXISTS routing_reason, DROP COLUMN IF EXISTS routed_at, DROP COLUMN IF EXISTS quote_provider,
--     DROP COLUMN IF EXISTS quote_snapshot, DROP COLUMN IF EXISTS quoted_at;
--   DELETE FROM role_permissions WHERE permission_key IN ('fulfillment.attention_resolve','routing.config','provider.events_view');
--   DELETE FROM permissions WHERE key IN ('fulfillment.attention_resolve','routing.config','provider.events_view');
