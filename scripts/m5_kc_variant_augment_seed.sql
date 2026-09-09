-- M5 Matcher k/c variant — augmentation SEED (CA Directive 258 + Amendment 259, Option 3).
-- Inserts deterministic k-variant aliases into the OPERATIONAL augmentation store
-- admin_unit_alias_augment (NOT the authoritative admin_unit_alias, which stays immutable). Scoped to the
-- ACTIVE dataset version. This is the SAME INSERT embedded in migration 063 — kept standalone so the
-- batch apply / repeat-apply / rollback+re-apply lifecycle can be rehearsed on an isolated DB that already
-- holds the dataset (the one-shot migration runs only once via the ledger).
--
-- Rule (deterministic): variant = regexp_replace(name_normalized,'c$','k')  (final char of last token).
-- Collision-safe PER LEVEL (2-tier province|ward): insert ONLY when the variant is NOT intra-ambiguous,
--   NOT equal to a different unit's canonical name, and NOT equal to a different unit's authoritative alias.
-- alias_kind='orthographic_kc_v1' (CA Amendment 260): matcher auto-verify tier (0.96 < canonical 1.00),
-- unique+parent-scoped -> auto_verified with rule 'orthographic_kc'; yields to current canonical on collision.
-- Idempotent: PK (dataset_version, unit_code, alias_normalized) + ON CONFLICT DO NOTHING -> re-run delta 0.
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
