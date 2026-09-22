-- 070_carrier_master_snapshot.sql — CA Directive 345 §2B: master-data snapshot co provider/time/version + lich su chay.
-- Additive/idempotent. KHONG nap du lieu that (snapshot/map thuc chi chay trong operational closure rieng).

-- Header append-only cho MOI lan chay snapshot (ke ca aborted): so request, endpoint+status (khong token), pham vi.
CREATE TABLE IF NOT EXISTS carrier_master_snapshot (
    id               BIGSERIAL PRIMARY KEY,
    provider         TEXT NOT NULL,
    snapshot_version TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('completed', 'aborted')),
    request_count    INTEGER NOT NULL CHECK (request_count >= 0),
    request_cap      INTEGER NOT NULL CHECK (request_cap > 0),
    requests         JSONB NOT NULL,          -- [{path, http_status, error}] — KHONG token/header/body secret
    scope            JSONB NOT NULL,          -- targets province/district da yeu cau
    report           JSONB NOT NULL,          -- ket qua match/abort reason (khong secret)
    created_by       TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_carrier_master_snapshot UNIQUE (provider, snapshot_version)
);

-- Dong master-data mang version snapshot da nap no (upsert giu ban moi nhat; lich su chay o header tren).
ALTER TABLE carrier_master_data ADD COLUMN IF NOT EXISTS snapshot_version TEXT;

-- ============================ ROLLBACK (batch, chay tay khi can) ============================
-- ALTER TABLE carrier_master_data DROP COLUMN IF EXISTS snapshot_version;
-- DROP TABLE IF EXISTS carrier_master_snapshot;
