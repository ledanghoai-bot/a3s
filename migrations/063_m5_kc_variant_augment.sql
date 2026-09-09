-- 063 M5 matcher k/c variant — OPERATIONAL alias augmentation store (CA Directive 258 + Amendment 259,
-- Option 3). The authoritative GSO dataset (admin_unit / admin_unit_alias) is immutable when active
-- (guard au_guard_content_immutable, migration 052) — so typo-variant aliases live in a SEPARATE
-- operational store, merged by the resolver at read time, active-version scoped. Authoritative tables,
-- guards and matcher core are NOT changed.
--
-- Additive + reversible. Runtime role alpha3s_app is READ-ONLY here (writes only via this migration /
-- deployer path — no runtime API/CLI mutation). Seed is deterministic (c$->k final token), collision-safe
-- per level, idempotent (ON CONFLICT DO NOTHING), and rollback is batch-scoped by source_batch.
-- On a fresh DB (no dataset loaded) the seed inserts 0 rows; on a DB with the active dataset it inserts the
-- computed safe set (recomputed from the exact snapshot — not hard-coded).

CREATE TABLE admin_unit_alias_augment (
    dataset_version  TEXT        NOT NULL,
    unit_code        TEXT        NOT NULL,
    alias_name       TEXT        NOT NULL,
    alias_normalized TEXT        NOT NULL,
    alias_kind       TEXT        NOT NULL
        -- CA Amendment 260: distinct kind 'orthographic_kc_v1' (auto-tier, NOT 'accentless') for k/c variants
        CHECK (alias_kind IN ('legacy', 'accentless', 'abbrev', 'other', 'orthographic_kc_v1')),
    source_batch     TEXT        NOT NULL,
    confidence       NUMERIC     CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT admin_unit_alias_augment_pkey
        PRIMARY KEY (dataset_version, unit_code, alias_normalized),
    -- no-orphan: augment row must reference a real (version, unit) identity
    CONSTRAINT admin_unit_alias_augment_unit_fk
        FOREIGN KEY (dataset_version, unit_code) REFERENCES admin_unit (dataset_version, code)
);

-- bounded/indexed active-version lookup (resolver filters by dataset_version)
CREATE INDEX idx_aua_augment_ver_lookup ON admin_unit_alias_augment (dataset_version);

-- Runtime role READ-ONLY (Amendment 259 §3.1): migration 024 ALTER DEFAULT PRIVILEGES auto-grants
-- SELECT/INSERT/UPDATE/DELETE to alpha3s_app on new tables — revoke writes, keep SELECT only.
REVOKE INSERT, UPDATE, DELETE ON admin_unit_alias_augment FROM alpha3s_app;
GRANT SELECT ON admin_unit_alias_augment TO alpha3s_app;

-- SEED (identical to scripts/m5_kc_variant_augment_seed.sql): deterministic c$->k variants for the ACTIVE
-- dataset, collision-safe per level. alias_kind='orthographic_kc_v1' (CA Amendment 260): matcher scores it at
-- the auto-verify tier (0.96, < current canonical 1.00) and, when unique + parent-scoped, resolves auto_verified
-- with rule 'orthographic_kc' for audit attribution; it YIELDS to current canonical on any collision.
INSERT INTO admin_unit_alias_augment
    (dataset_version, unit_code, alias_name, alias_normalized, alias_kind, source_batch, confidence)
WITH ds AS (
    SELECT version FROM admin_unit_dataset WHERE status = 'active'
), cand AS (
    SELECT u.dataset_version, u.level, u.code AS unit_code,
           regexp_replace(u.name_normalized, 'c$', 'k') AS kv
    FROM admin_unit u JOIN ds ON ds.version = u.dataset_version
    WHERE u.name_normalized ~ 'c$'
), amb AS (
    SELECT dataset_version, level, kv
    FROM cand GROUP BY dataset_version, level, kv HAVING count(DISTINCT unit_code) > 1
), safe AS (
    SELECT c.dataset_version, c.unit_code, c.kv
    FROM cand c
    WHERE NOT EXISTS (SELECT 1 FROM amb a
                      WHERE a.dataset_version=c.dataset_version AND a.level=c.level AND a.kv=c.kv)
      AND NOT EXISTS (SELECT 1 FROM admin_unit u2
                      WHERE u2.dataset_version=c.dataset_version AND u2.level=c.level
                        AND u2.code<>c.unit_code AND u2.name_normalized=c.kv)
      AND NOT EXISTS (SELECT 1 FROM admin_unit_alias al JOIN admin_unit u3
                        ON u3.dataset_version=al.dataset_version AND u3.code=al.unit_code
                      WHERE al.dataset_version=c.dataset_version AND u3.level=c.level
                        AND al.unit_code<>c.unit_code AND al.alias_normalized=c.kv)
)
SELECT dataset_version, unit_code, kv, kv, 'orthographic_kc_v1', 'kc_variant_c2k_v1', 0.96
FROM safe
ON CONFLICT (dataset_version, unit_code, alias_normalized) DO NOTHING;

-- ROLLBACK (runbook):
--   DROP TABLE IF EXISTS admin_unit_alias_augment;
--   (batch-only, keep table: DELETE FROM admin_unit_alias_augment WHERE source_batch='kc_variant_c2k_v1';)
