-- M5 Matcher k/c variant — CENSUS / collision-exclusion report (CA Directive 258 §3.3).
-- Read-only. Reproducible from exact dataset snapshot. Deterministic rule identical to the seed:
--   variant = replace the FINAL character 'c' (end of last token) of name_normalized with 'k'.
-- Collision evaluated PER LEVEL (dataset is 2-tier: province|ward). Prints raw counts:
--   candidates, excluded(intra-ambiguity | canonical-collision | existing-alias-collision), inserted-safe.
-- Usage: psql ... -f scripts/m5_kc_variant_census.sql
WITH ds AS (
    SELECT version FROM admin_unit_dataset WHERE status = 'active'
), cand AS (
    SELECT u.dataset_version, u.level, u.code AS unit_code, u.name_normalized AS canon,
           regexp_replace(u.name_normalized, 'c$', 'k') AS kv
    FROM admin_unit u JOIN ds ON ds.version = u.dataset_version
    WHERE u.name_normalized ~ 'c$'
), amb AS (
    SELECT dataset_version, level, kv
    FROM cand GROUP BY dataset_version, level, kv HAVING count(DISTINCT unit_code) > 1
), tagged AS (
    SELECT c.*,
        EXISTS (SELECT 1 FROM amb a WHERE a.dataset_version=c.dataset_version AND a.level=c.level AND a.kv=c.kv) AS is_ambiguous,
        EXISTS (SELECT 1 FROM admin_unit u2 WHERE u2.dataset_version=c.dataset_version AND u2.level=c.level
                AND u2.code<>c.unit_code AND u2.name_normalized=c.kv) AS hits_canonical,
        EXISTS (SELECT 1 FROM admin_unit_alias al JOIN admin_unit u3
                  ON u3.dataset_version=al.dataset_version AND u3.code=al.unit_code
                WHERE al.dataset_version=c.dataset_version AND u3.level=c.level
                  AND al.unit_code<>c.unit_code AND al.alias_normalized=c.kv) AS hits_alias
    FROM cand c
)
SELECT
    (SELECT version FROM ds)                                              AS dataset_version,
    (SELECT count(*) FROM cand)                                           AS candidates,
    (SELECT count(*) FROM tagged WHERE is_ambiguous)                      AS excl_intra_ambiguous,
    (SELECT count(*) FROM tagged WHERE NOT is_ambiguous AND hits_canonical)          AS excl_canonical_collision,
    (SELECT count(*) FROM tagged WHERE NOT is_ambiguous AND NOT hits_canonical AND hits_alias) AS excl_existing_alias_collision,
    (SELECT count(*) FROM tagged WHERE NOT is_ambiguous AND NOT hits_canonical AND NOT hits_alias) AS inserted_safe;
