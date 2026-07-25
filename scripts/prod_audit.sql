-- prod_audit.sql — Alpha3S I-B M0.0 Production Database Audit (READ-ONLY).
-- =====================================================================================
-- TRANG THAI: SOAN SAN — CHUA CHAY. Chi chay tren VPS SAU khi PO cap quyen truy cap
-- read-only (CA-REVIEW-IMPL-M0-001 §2). KHONG chay tu dong; KHONG ghi bat ky gi.
--
-- Cach chay (khi duoc phep), tren VPS:
--   docker compose exec -T db psql -U alpha3s -d alpha3s -v ON_ERROR_STOP=1 -f - < scripts/prod_audit.sql | tee prod_audit_out.txt
--
-- An toan: toan bo boc trong transaction READ ONLY + ket thuc ROLLBACK -> moi lenh
-- ghi (UPDATE/INSERT/DDL) neu lot vao se bi Postgres tu choi. Chi SELECT/DO(read).
--
-- KHONG xuat PII (CA-REVIEW-IMPL-M0-001 §7.2): chi counts/aggregate/prefix/metadata.
-- KHONG xuat raw psid, phone, address, message content, session token, secret.
--
-- Report identity (CA §7.3): phan SQL cung cap DB name / server version / timestamp /
-- schema fingerprint. Cac truong sau do RUNBOOK/nguoi chay phai ghi tay vao report
-- docs/PHASE1B-PROD-AUDIT-VI.md (SQL khong lay duoc):
--   [ ] Host / environment (VPS 160.30.157.235 ?)
--   [ ] Git commit / image tag dang chay  (git rev-parse HEAD ; docker inspect ... Image)
--   [ ] Nguoi thuc hien
--   [ ] Read-only statement (da dam bao boi transaction READ ONLY duoi day)
-- =====================================================================================

\pset pager off
\set ON_ERROR_STOP on
\timing off

BEGIN;
SET TRANSACTION READ ONLY;   -- moi lenh ghi se bi tu choi tu day tro di

\echo '===== [0] REPORT IDENTITY (SQL-side) ====='
SELECT 'db_name'            AS key, current_database()                         AS value
UNION ALL SELECT 'server_version', version()
UNION ALL SELECT 'audit_time_utc', (now() AT TIME ZONE 'utc')::text
UNION ALL SELECT 'transaction_read_only', current_setting('transaction_read_only');

\echo '===== [1] SCHEMA OBJECTS (tables public) ====='
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name;

\echo '===== [2] SCHEMA FINGERPRINT (md5 layout cot — so sanh giua moi truong) ====='
SELECT md5(string_agg(table_name || '.' || column_name || ':' || data_type,
                      ',' ORDER BY table_name, ordinal_position)) AS schema_fingerprint,
       count(*) AS column_count
FROM information_schema.columns
WHERE table_schema = 'public';

\echo '===== [3] CONSTRAINTS + INDEXES quan trong ====='
SELECT conname AS constraint_name, conrelid::regclass::text AS on_table, contype AS type
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace AND contype IN ('c','u','p','f')
ORDER BY on_table, constraint_name;

SELECT tablename AS on_table, indexname
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;

\echo '===== [4] MIGRATION DRIFT / BASELINE-THRESHOLD DETECTION ====='
-- Xac dinh moi truong nay dang o dau -> baseline threshold bao nhieu (nuance §5.10):
SELECT 'has schema_migrations (da dung runner?)'                    AS check,
       (to_regclass('public.schema_migrations') IS NOT NULL)::text AS value
UNION ALL SELECT 'has products.net_weight_g (>=012?)',
       EXISTS(SELECT 1 FROM information_schema.columns
              WHERE table_name='products' AND column_name='net_weight_g')::text
UNION ALL SELECT 'has products.serving_size_g (>=012?)',
       EXISTS(SELECT 1 FROM information_schema.columns
              WHERE table_name='products' AND column_name='serving_size_g')::text
UNION ALL SELECT 'has data_deletion_requests (013 da ap ngoai luong?)',
       (to_regclass('public.data_deletion_requests') IS NOT NULL)::text
UNION ALL SELECT 'has staff_users.role_key (015 RBAC da ap?)',
       EXISTS(SELECT 1 FROM information_schema.columns
              WHERE table_name='staff_users' AND column_name='role_key')::text
UNION ALL SELECT 'has audit_log (015 audit da ap?)',
       (to_regclass('public.audit_log') IS NOT NULL)::text;

-- Neu da co schema_migrations: liet ke version da applied (dung DO de an toan neu bang thieu)
DO $$
DECLARE r record;
BEGIN
  IF to_regclass('public.schema_migrations') IS NULL THEN
    RAISE NOTICE 'schema_migrations: KHONG TON TAI -> DB chua dung runner (baseline se can).';
  ELSE
    FOR r IN EXECUTE 'SELECT version, applied_at FROM schema_migrations ORDER BY version' LOOP
      RAISE NOTICE 'applied: % @ %', r.version, r.applied_at;
    END LOOP;
  END IF;
END $$;

\echo '===== [5] ROW COUNTS (aggregate, KHONG PII) ====='
SELECT 'customers' AS t, count(*) AS n FROM customers
UNION ALL SELECT 'conversations', count(*) FROM conversations
UNION ALL SELECT 'messages',      count(*) FROM messages
UNION ALL SELECT 'products',      count(*) FROM products
UNION ALL SELECT 'orders',        count(*) FROM orders
UNION ALL SELECT 'order_items',   count(*) FROM order_items
UNION ALL SELECT 'price_overrides', count(*) FROM price_overrides
UNION ALL SELECT 'escalations',   count(*) FROM escalations
UNION ALL SELECT 'staff_users',   count(*) FROM staff_users
UNION ALL SELECT 'kb_units',      count(*) FROM kb_units
UNION ALL SELECT 'knowledge_chunks', count(*) FROM knowledge_chunks
ORDER BY t;

\echo '===== [6] ORDER STATUS DISTRIBUTION (mapping cu -> model moi M2) ====='
SELECT status, count(*) AS n FROM orders GROUP BY status ORDER BY n DESC;

\echo '===== [7] CUSTOMER CHANNEL PREFIX (chi dem theo prefix, KHONG raw psid) ====='
SELECT
  count(*) FILTER (WHERE psid LIKE 'tg:%')      AS telegram_prefix,
  count(*) FILTER (WHERE psid LIKE 'manual:%')  AS manual_prefix,
  count(*) FILTER (WHERE psid NOT LIKE 'tg:%' AND psid NOT LIKE 'manual:%') AS messenger_or_other
FROM customers;

\echo '===== [8] DATA ANOMALY: known-bad "100% Robusta" (quet toan bo de hoan thien IN-list 014) ====='
-- Chi xuat sku + co/khong, KHONG xuat noi dung mo ta.
SELECT sku, (strpos(description, '100% Robusta') > 0) AS has_100pct_robusta_claim
FROM products
WHERE strpos(description, '100% Robusta') > 0
ORDER BY sku;

\echo '===== [9] DATA ANOMALY: serving_size_g co gia tri (review canonical support — CA-CHECK §3) ====='
SELECT sku, serving_size_g, net_weight_g
FROM products
WHERE serving_size_g IS NOT NULL
ORDER BY sku;

ROLLBACK;   -- read-only: khong co gi de commit

\echo '===== CUTOVER / CHANNEL AUDIT — KHONG lam bang SQL (CA-REVIEW-IMPL-M0-001 §7.1) ====='
\echo 'Nguoi chay bo sung evidence ngoai DB vao docs/PHASE1B-PROD-AUDIT-VI.md:'
\echo '  [ ] Meta webhook: subscription dang tro ve VPS? (Graph API /subscribed_apps, hoac Meta App dashboard)'
\echo '  [ ] Telegram bot: getMe + ai dang polling (admin bot / customer bot)'
\echo '  [ ] Deployment identity: docker compose ps ; docker inspect <api> --format {{.Config.Image}}'
\echo '  [ ] Git commit dang chay tren VPS: git -C <repo> rev-parse HEAD'
\echo '  [ ] Backup/restore readiness: pg_dump gan nhat, cron pg_dump ngay (memory vps-production)'
\echo '===== HET AUDIT (READ-ONLY) ====='
