-- 068_settings_integrations.sql — CA Directive 305: Shop Settings platform + GHN staging config path.
-- Additive/idempotent. Rollback theo batch chuan (cuoi file). KHONG migrate bank/GHN .env o day (chi platform).
-- Secret KHONG bao gio luu plaintext: integration_secrets giu ciphertext (AES-256-GCM) + nonce + keyed fingerprint.

-- ============================ integrations (public config) ============================
CREATE TABLE IF NOT EXISTS integrations (
    id                       BIGSERIAL PRIMARY KEY,
    kind                     TEXT NOT NULL CHECK (kind IN ('shipping', 'payment', 'general')),
    provider                 TEXT NOT NULL,                 -- 'ghn' | 'sepay' | 'bank_transfer' | 'self_delivery'
    label                    TEXT NOT NULL,
    mode                     TEXT NOT NULL DEFAULT 'test',   -- allowlist per-provider enforce o service (vd ghn: staging)
    enabled                  BOOLEAN NOT NULL DEFAULT false,
    config_public            JSONB NOT NULL DEFAULT '{}'::jsonb,   -- KHONG chua secret
    version                  INTEGER NOT NULL DEFAULT 1,           -- CAS cho mutation config_public/mode/label
    last_test_status         TEXT CHECK (last_test_status IN ('pass', 'fail')),
    last_test_at             TIMESTAMPTZ,
    last_test_config_version INTEGER,                              -- bind test-connection voi config version
    last_test_secret_version INTEGER,                             -- ... va secret version (enable gate)
    last_test_detail         JSONB,                               -- redacted (latency/error class), KHONG token/header
    archived_at              TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by               TEXT,
    updated_by               TEXT
);
-- Deterministic: toi da MOT integration active (enabled + chua archive) cho moi (provider, mode).
CREATE UNIQUE INDEX IF NOT EXISTS uq_integrations_active_provider_mode
    ON integrations (provider, mode) WHERE enabled AND archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_integrations_kind ON integrations (kind, provider);

-- ============================ integration_secrets (ciphertext only) ============================
CREATE TABLE IF NOT EXISTS integration_secrets (
    integration_id INTEGER NOT NULL REFERENCES integrations (id) ON DELETE CASCADE,
    key_name       TEXT NOT NULL,                 -- 'token' | 'api_key' | 'hmac' | 'account_number' | 'shop_id'
    key_id         TEXT NOT NULL,                 -- encryption key ring id da dung (rotation doc key cu)
    ciphertext     BYTEA NOT NULL,                -- AES-256-GCM ciphertext+tag (AAD bind integration/provider/key/version)
    nonce          BYTEA NOT NULL,
    fingerprint    TEXT NOT NULL,                 -- HMAC-SHA256(plaintext) keyed (CONFIG_SECRET_FP_KEY) — KHONG SHA raw
    last4          TEXT,                          -- chi khi field cho phep hien last4 (vd account_number)
    version        INTEGER NOT NULL DEFAULT 1,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by     TEXT,
    PRIMARY KEY (integration_id, key_name)
);

-- ============================ audit trigger: KHONG cho SELECT lo plaintext (khong the — chi ciphertext) ============================
-- (integration_secrets khong bao gio chua plaintext; audit redaction o service layer.)

-- ============================ RBAC (additive) — CA Review 304-03 granular ============================
INSERT INTO roles (key, name, is_system, is_active) VALUES
    ('shop_manager', 'Quản lý shop', false, true)
ON CONFLICT (key) DO NOTHING;

INSERT INTO permissions (key, description) VALUES
    ('settings.integration.view',           'Xem trạng thái tích hợp (đã redact)'),
    ('settings.integration.manage_public',  'Sửa cấu hình public của tích hợp (không secret)'),
    ('settings.integration.secret_write',   'Ghi/xoay secret tích hợp (write-only, không đọc lại)'),
    ('settings.integration.test',           'Chạy test-connection read-only'),
    ('settings.integration.activate',       'Bật/tắt tích hợp'),
    ('settings.integration.live_financial',  'Kích hoạt/xoay secret tài chính LIVE (SePay live) — reserved')
ON CONFLICT DO NOTHING;

-- admin = PO/owner: toan bo. shop_manager: view/manage_public/test (secret_write/activate cap explicit sau).
INSERT INTO role_permissions (role_key, permission_key) VALUES
    ('admin', 'settings.integration.view'),
    ('admin', 'settings.integration.manage_public'),
    ('admin', 'settings.integration.secret_write'),
    ('admin', 'settings.integration.test'),
    ('admin', 'settings.integration.activate'),
    ('admin', 'settings.integration.live_financial'),
    ('shop_manager', 'settings.integration.view'),
    ('shop_manager', 'settings.integration.manage_public'),
    ('shop_manager', 'settings.integration.test')
ON CONFLICT DO NOTHING;

-- ============================ ROLLBACK (batch, chay tay khi can) ============================
-- DELETE FROM role_permissions WHERE permission_key LIKE 'settings.integration.%';
-- DELETE FROM permissions WHERE key LIKE 'settings.integration.%';
-- DELETE FROM roles WHERE key='shop_manager';
-- DROP TABLE IF EXISTS integration_secrets;
-- DROP TABLE IF EXISTS integrations;
