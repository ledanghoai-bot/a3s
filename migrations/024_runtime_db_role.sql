-- Migration 024: runtime DB role tách migration-owner (I-B M2 — AC-M2-14). Spec §9.8, §10; Directive §Slice1.
-- Tạo role RUNTIME least-privilege `alpha3s_app`, TÁCH khỏi migration-owner (`alpha3s`).
-- Runtime KHÔNG: DDL, ghi schema_migrations, UPDATE/DELETE append-only ledger (inventory_movements,
--   order_events, delivery_attempts), UPDATE/DELETE audit_log (no audit bypass).
-- Runtime CÓ: CRUD tables vận hành + INSERT/SELECT append-only + USAGE sequences.
-- AN TOÀN trên stack đang chạy: chỉ THÊM role mới + grant; KHÔNG đụng role `alpha3s` hiện tại,
--   KHÔNG đổi credential app. Role tạo NOLOGIN (không commit secret); cutover (ALTER ROLE ... LOGIN
--   PASSWORD + đổi DATABASE_URL) là bước ops tại release, gated readiness (Spec §885: không start
--   runtime bằng migration-owner credential). Forward-only, idempotent, self-validating.
-- transactional: true

-- ===========================================================================
-- 1. Runtime role (NOLOGIN; ops flip LOGIN+PASSWORD tại cutover)
-- ===========================================================================
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha3s_app') THEN
    CREATE ROLE alpha3s_app NOLOGIN;
  END IF;
END $$;

-- ===========================================================================
-- 2. Base grants — vận hành CRUD trên schema public
-- ===========================================================================
GRANT USAGE ON SCHEMA public TO alpha3s_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO alpha3s_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO alpha3s_app;

-- Future tables/sequences (M3+) do migration-owner tạo cũng cấp CRUD cho runtime.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO alpha3s_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO alpha3s_app;

-- ===========================================================================
-- 3. Least-privilege REVOKEs (defense-in-depth, độc lập với trigger)
-- ===========================================================================
-- 3a. Không DDL / không tạo object mới trong schema.
REVOKE CREATE ON SCHEMA public FROM alpha3s_app;

-- 3b. Append-only ledgers/history: runtime chỉ INSERT/SELECT, KHÔNG UPDATE/DELETE.
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['inventory_movements','order_events','delivery_attempts'] LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      EXECUTE format('REVOKE UPDATE, DELETE ON public.%I FROM alpha3s_app', t);
    END IF;
  END LOOP;
END $$;

-- 3c. Audit: không bypass — runtime INSERT/SELECT được, KHÔNG UPDATE/DELETE audit_log.
DO $$
BEGIN
  IF to_regclass('public.audit_log') IS NOT NULL THEN
    REVOKE UPDATE, DELETE ON public.audit_log FROM alpha3s_app;
  END IF;
END $$;

-- 3d. Migration tracking: runtime KHÔNG đọc/ghi schema_migrations (chỉ migration-owner).
DO $$
BEGIN
  IF to_regclass('public.schema_migrations') IS NOT NULL THEN
    REVOKE ALL ON public.schema_migrations FROM alpha3s_app;
  END IF;
END $$;

-- ===========================================================================
-- 4. Postcondition fail-closed — chứng minh least privilege
-- ===========================================================================
DO $$
DECLARE problems TEXT := '';
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_app') THEN
    problems := problems || ' role_missing'; END IF;
  -- runtime KHÔNG được là superuser / createrole / createdb
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='alpha3s_app'
             AND (rolsuper OR rolcreaterole OR rolcreatedb)) THEN
    problems := problems || ' role_overprivileged'; END IF;
  -- CÓ INSERT nhưng KHÔNG UPDATE trên ledger
  IF NOT has_table_privilege('alpha3s_app','public.inventory_movements','INSERT') THEN
    problems := problems || ' ledger_no_insert'; END IF;
  IF has_table_privilege('alpha3s_app','public.inventory_movements','UPDATE') THEN
    problems := problems || ' ledger_has_update'; END IF;
  IF has_table_privilege('alpha3s_app','public.order_events','DELETE') THEN
    problems := problems || ' events_has_delete'; END IF;
  -- audit không bị xoá được
  IF has_table_privilege('alpha3s_app','public.audit_log','DELETE') THEN
    problems := problems || ' audit_has_delete'; END IF;
  -- không DDL
  IF has_schema_privilege('alpha3s_app','public','CREATE') THEN
    problems := problems || ' schema_has_create'; END IF;
  -- không ghi migration tracking
  IF to_regclass('public.schema_migrations') IS NOT NULL
     AND has_table_privilege('alpha3s_app','public.schema_migrations','INSERT') THEN
    problems := problems || ' can_write_schema_migrations'; END IF;
  -- CÓ CRUD bình thường trên bảng vận hành (sanity)
  IF NOT has_table_privilege('alpha3s_app','public.orders','SELECT') THEN
    problems := problems || ' no_orders_select'; END IF;
  IF NOT has_table_privilege('alpha3s_app','public.inventory_balances','UPDATE') THEN
    problems := problems || ' no_balance_update'; END IF;
  IF problems <> '' THEN
    RAISE EXCEPTION '024 postcondition FAIL —%', problems; END IF;
END $$;
