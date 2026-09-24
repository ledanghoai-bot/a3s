-- 071_carrier_mode_separation.sql — CA Directive 357 §2.1: tach TUYET DOI du lieu carrier theo mode (staging|production).
-- Additive + reversible. Du lieu hien huu = staging (snapshot/map v2 cua G1) -> backfill 'staging', KHONG doi business data.
-- Sau migration: master-data/snapshot/map deu khoa theo (provider, mode) -> khong the dung nham du lieu staging cho production.

-- ============================ (A) carrier_master_data ============================
ALTER TABLE carrier_master_data ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'staging';
DO $$ BEGIN
    ALTER TABLE carrier_master_data ADD CONSTRAINT ck_cmd_mode CHECK (mode IN ('staging', 'production'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- PK (provider, kind, key) -> (provider, mode, kind, key)
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'carrier_master_data_pkey') THEN
        ALTER TABLE carrier_master_data DROP CONSTRAINT carrier_master_data_pkey;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'carrier_master_data_mode_pkey') THEN
        ALTER TABLE carrier_master_data ADD CONSTRAINT carrier_master_data_mode_pkey
            PRIMARY KEY (provider, mode, kind, key);
    END IF;
END $$;

-- ============================ (B) carrier_master_snapshot (header lan chay) ============================
ALTER TABLE carrier_master_snapshot ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'staging';
DO $$ BEGIN
    ALTER TABLE carrier_master_snapshot ADD CONSTRAINT ck_cms_mode CHECK (mode IN ('staging', 'production'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_carrier_master_snapshot') THEN
        ALTER TABLE carrier_master_snapshot DROP CONSTRAINT uq_carrier_master_snapshot;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_carrier_master_snapshot_mode') THEN
        ALTER TABLE carrier_master_snapshot ADD CONSTRAINT uq_carrier_master_snapshot_mode
            UNIQUE (provider, mode, snapshot_version);
    END IF;
END $$;

-- ============================ (C) carrier_address_map ============================
ALTER TABLE carrier_address_map ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'staging';
DO $$ BEGIN
    ALTER TABLE carrier_address_map ADD CONSTRAINT ck_cam_mode CHECK (mode IN ('staging', 'production'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- map_version doc lap theo mode -> unique phai gom mode
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_carrier_addr_map') THEN
        ALTER TABLE carrier_address_map DROP CONSTRAINT uq_carrier_addr_map;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_carrier_addr_map_mode') THEN
        ALTER TABLE carrier_address_map ADD CONSTRAINT uq_carrier_addr_map_mode
            UNIQUE (provider, mode, map_version, province_code, ward_code);
    END IF;
END $$;

-- ============================ ROLLBACK (batch, chay tay khi can) ============================
-- ALTER TABLE carrier_address_map DROP CONSTRAINT IF EXISTS uq_carrier_addr_map_mode;
-- ALTER TABLE carrier_address_map ADD CONSTRAINT uq_carrier_addr_map UNIQUE (provider, map_version, province_code, ward_code);
-- ALTER TABLE carrier_address_map DROP CONSTRAINT IF EXISTS ck_cam_mode; ALTER TABLE carrier_address_map DROP COLUMN IF EXISTS mode;
-- ALTER TABLE carrier_master_snapshot DROP CONSTRAINT IF EXISTS uq_carrier_master_snapshot_mode;
-- ALTER TABLE carrier_master_snapshot ADD CONSTRAINT uq_carrier_master_snapshot UNIQUE (provider, snapshot_version);
-- ALTER TABLE carrier_master_snapshot DROP CONSTRAINT IF EXISTS ck_cms_mode; ALTER TABLE carrier_master_snapshot DROP COLUMN IF EXISTS mode;
-- ALTER TABLE carrier_master_data DROP CONSTRAINT IF EXISTS carrier_master_data_mode_pkey;
-- ALTER TABLE carrier_master_data ADD CONSTRAINT carrier_master_data_pkey PRIMARY KEY (provider, kind, key);
-- ALTER TABLE carrier_master_data DROP CONSTRAINT IF EXISTS ck_cmd_mode; ALTER TABLE carrier_master_data DROP COLUMN IF EXISTS mode;
