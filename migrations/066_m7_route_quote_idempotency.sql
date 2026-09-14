-- 066 M7 route/quote server-side idempotency (CA Review 276 blocker 276-01). ADDITIVE / EXPAND-ONLY.
-- Khong sua 064/065; khong DROP/truncate; code cu tuong thich (bang moi doc lap).
-- Van de: endpoint route-quote goi GHN (HTTP) NGOAI transaction roi apply quote. Double-click / retry sau timeout /
--   hai request dong thoi co the goi GHN nhieu lan + apply quote nhieu lan khi GHN staging bat. UI da gui command_key
--   nhung server chua doc/validate/luu -> khong thuc thi contract idempotency.
-- Fix: receipt BEN VUNG cho tung thao tac (order_id, action, command_key):
--   claim ATOMIC truoc khi goi provider; lease/recovery cho crash; luu provider_result de retry KHONG goi GHN lan hai
--   khi ket qua da ghi; replay ket qua da apply; cung key/khac payload -> conflict (fingerprint).
-- State machine: claimed -> provider_recorded -> done ; hoac -> failed. Chi owner (owner_token) moi apply.
-- KHONG gan trigger m6_forbid_mutate (bang nay co vong doi update hop le).

CREATE TABLE IF NOT EXISTS fulfillment_route_operations (
    id                  BIGSERIAL PRIMARY KEY,
    order_id            BIGINT NOT NULL REFERENCES orders(id),
    action              TEXT NOT NULL DEFAULT 'route_quote',
    command_key         TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'claimed'
                          CHECK (state IN ('claimed', 'provider_recorded', 'done', 'failed')),
    owner_token         TEXT NOT NULL,
    lease_expires_at    TIMESTAMPTZ NOT NULL,
    provider            TEXT,                    -- 'ghn' | 'none' (self/manual) | NULL
    provider_result     JSONB,                   -- QuoteResult.snapshot() (KHONG secret) hoac NULL
    result_payload      JSONB,                   -- ket qua cuoi rut gon (JSON-safe) de replay/audit
    error_code          TEXT,
    attempts            INTEGER NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_route_op_order_action_key UNIQUE (order_id, action, command_key)
);

CREATE INDEX IF NOT EXISTS idx_route_op_lease ON fulfillment_route_operations (state, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_route_op_order ON fulfillment_route_operations (order_id, created_at);
