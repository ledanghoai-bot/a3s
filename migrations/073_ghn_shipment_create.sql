-- 073 — CA Directive 393: GHN shipment create (Bot + Dashboard Staff), MOT lifecycle chung, idempotent. CANDIDATE:
-- gate mac dinh OFF (config), migration chi them cau truc — KHONG tao operation, KHONG goi provider.
-- Additive + reversible (ROLLBACK cuoi file). Khong sua migration da deploy (CHECK duoc DROP/ADD lai, chi mo rong).

-- ============================ Operation (1 dong / yeu cau tao van don) ============================
CREATE TABLE IF NOT EXISTS ghn_shipment_create_operations (
    id                      BIGSERIAL PRIMARY KEY,
    order_id                BIGINT NOT NULL REFERENCES orders (id),
    shipment_id             BIGINT REFERENCES shipments (id),
    source                  TEXT NOT NULL CHECK (source IN ('bot', 'dashboard')),
    initiator_staff_id      BIGINT REFERENCES staff_users (id),
    initiator_customer_id   BIGINT REFERENCES customers (id),
    command_key             TEXT NOT NULL CHECK (char_length(command_key) BETWEEN 1 AND 200),
    request_fingerprint     TEXT NOT NULL,                 -- sha256 cua request_snapshot (replay/conflict)
    mode                    TEXT NOT NULL CHECK (mode IN ('staging', 'production')),
    integration_id          BIGINT,                        -- snapshot (KHONG FK: khong chan purge/rotate integration)
    config_revision         INTEGER NOT NULL,
    client_order_code       TEXT NOT NULL UNIQUE,          -- correlation tat dinh tu operation id (gui GHN)
    state                   TEXT NOT NULL DEFAULT 'prepared' CHECK (state IN (
                                'prepared', 'dispatching', 'succeeded', 'failed_retryable', 'failed_terminal',
                                'unknown_reconciliation_required', 'cancelled_before_dispatch')),
    policy_version          TEXT NOT NULL,
    request_snapshot        JSONB NOT NULL,                -- BAT BIEN (trigger): adapter chi doc snapshot nay
    note                    TEXT CHECK (note IS NULL OR char_length(note) <= 500),
    provider_order_code     TEXT,                          -- ma van don GHN (chi khi co provider evidence)
    provider_result         JSONB,                         -- redacted (khong PII/token/raw payload)
    attempt_count           INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts            INTEGER NOT NULL DEFAULT 4 CHECK (max_attempts BETWEEN 1 AND 10),
    next_attempt_at         TIMESTAMPTZ,
    lease_owner             TEXT,
    lease_expires_at        TIMESTAMPTZ,
    last_error_class        TEXT,
    last_http_status        INTEGER,
    gate_blocked_reason     TEXT,
    terminal_reason         TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatched_at           TIMESTAMPTZ,
    succeeded_at            TIMESTAMPTZ,
    terminal_at             TIMESTAMPTZ,
    CONSTRAINT ck_gsco_initiator CHECK (
        (source = 'dashboard' AND initiator_staff_id IS NOT NULL) OR
        (source = 'bot' AND initiator_customer_id IS NOT NULL)),
    CONSTRAINT ck_gsco_success_evidence CHECK (state <> 'succeeded' OR provider_order_code IS NOT NULL),
    CONSTRAINT uq_gsco_source_command UNIQUE (source, command_key)
);
-- MOT operation "active" / order (succeeded cung tinh: khong tao van don thu 2). Terminal-fail/cancel -> duoc tao lai.
CREATE UNIQUE INDEX IF NOT EXISTS uq_gsco_one_active_per_order ON ghn_shipment_create_operations (order_id)
    WHERE state IN ('prepared', 'dispatching', 'succeeded', 'failed_retryable', 'unknown_reconciliation_required');
CREATE INDEX IF NOT EXISTS idx_gsco_due ON ghn_shipment_create_operations (state, next_attempt_at);

-- request_snapshot / identity / correlation BAT BIEN sau khi tao (adapter khong doc du lieu mutable luc gui).
CREATE OR REPLACE FUNCTION ghn_shipment_create_operations_freeze() RETURNS trigger AS $$
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
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS gsco_freeze ON ghn_shipment_create_operations;
CREATE TRIGGER gsco_freeze BEFORE UPDATE OR DELETE ON ghn_shipment_create_operations
    FOR EACH ROW EXECUTE FUNCTION ghn_shipment_create_operations_freeze();

-- ============================ Attempt ledger (append-only) ============================
CREATE TABLE IF NOT EXISTS ghn_shipment_create_attempts (
    id              BIGSERIAL PRIMARY KEY,
    operation_id    BIGINT NOT NULL REFERENCES ghn_shipment_create_operations (id),
    attempt_no      INTEGER NOT NULL CHECK (attempt_no >= 1),
    kind            TEXT NOT NULL CHECK (kind IN ('create', 'reconcile')),
    outcome         TEXT NOT NULL CHECK (outcome IN ('created', 'rejected', 'retryable', 'unknown', 'found',
                                                     'not_found', 'lease_expired')),
    http_status     INTEGER,
    error_class     TEXT,
    retry_after_s   INTEGER,
    duration_ms     INTEGER,
    response_redacted JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor           TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gsca_op_attempt_kind UNIQUE (operation_id, attempt_no, kind)
);
CREATE OR REPLACE FUNCTION ghn_shipment_create_attempts_no_mutate() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ghn_shipment_create_attempts la append-only — khong duoc %', TG_OP;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS gsca_no_mutate ON ghn_shipment_create_attempts;
CREATE TRIGGER gsca_no_mutate BEFORE UPDATE OR DELETE ON ghn_shipment_create_attempts
    FOR EACH ROW EXECUTE FUNCTION ghn_shipment_create_attempts_no_mutate();

-- ============================ Hoi thoai bot cho xac nhan giao + ly do attention ============================
ALTER TABLE fulfillment_conversations DROP CONSTRAINT IF EXISTS fulfillment_conversations_step_check;
ALTER TABLE fulfillment_conversations ADD CONSTRAINT fulfillment_conversations_step_check CHECK (step IN
    ('routing', 'awaiting_method', 'cod_handoff', 'awaiting_transfer', 'staff_attention', 'completed', 'cancelled',
     'ship_confirm'));

ALTER TABLE staff_attention DROP CONSTRAINT IF EXISTS staff_attention_reason_check;
ALTER TABLE staff_attention ADD CONSTRAINT staff_attention_reason_check CHECK (reason IN
    ('address', 'quote', 'account', 'method', 'payment_mismatch', 'unmatched_webhook', 'payment_timeout',
     'large_order_review', 'quantity_unit_review', 'provider_error', 'other',
     'refund_required', 'order_cancel_exception', 'shipment_create'));

-- ============================ Outbox: thong bao "da tao van don" (khong command-backed, worker-context) ============
ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS outbox_command_id_required_unless_escalation;
ALTER TABLE outbox_events ADD CONSTRAINT outbox_command_id_required_unless_escalation
    CHECK (
        command_id IS NOT NULL
        OR event_type IN (
            'order.escalated.notify', 'handoff.escalated.notify',
            'shipment.handover.notify', 'shipment.delivered.notify', 'shipment.failed.notify',
            'payment.check_request.notify', 'payment.confirmed.notify',
            'fulfillment.prompt.notify', 'fulfillment.instruction.notify', 'fulfillment.reminder.notify',
            'fulfillment.staff.notify', 'fulfillment.cod.notify',
            'shipment.ghn_created.notify')
    );

-- ============================ RBAC ============================
INSERT INTO permissions (key, description) VALUES
    ('shipment.ghn.create', 'Tao yeu cau van don GHN tu Dashboard (review + xac nhan) va xu ly doi soat')
ON CONFLICT DO NOTHING;
INSERT INTO role_permissions (role_key, permission_key) VALUES
    ('admin', 'shipment.ghn.create')
ON CONFLICT DO NOTHING;

-- ============================ ROLLBACK (chay tay khi CA/PO quyet; KHONG tu dong) ============================
-- Precheck: SELECT count(*) FROM ghn_shipment_create_operations; > 0 -> DUNG, bao CA (ho so audit).
--           SELECT count(*) FROM fulfillment_conversations WHERE step='ship_confirm'; > 0 -> DUNG.
--           SELECT count(*) FROM staff_attention WHERE reason='shipment_create'; > 0 -> DUNG.
-- DELETE FROM role_permissions WHERE permission_key='shipment.ghn.create'; DELETE FROM permissions WHERE key='shipment.ghn.create';
-- DROP TABLE ghn_shipment_create_attempts; DROP TABLE ghn_shipment_create_operations;
-- DROP FUNCTION ghn_shipment_create_attempts_no_mutate(); DROP FUNCTION ghn_shipment_create_operations_freeze();
-- ADD lai CHECK step/reason cua 072 (bo 'ship_confirm' / 'shipment_create').
-- Outbox: SELECT count(*) FROM outbox_events WHERE event_type='shipment.ghn_created.notify' AND command_id IS NULL;
--   > 0 -> giu CHECK moi; = 0 -> ADD lai CHECK cua 065 (bo 'shipment.ghn_created.notify').
