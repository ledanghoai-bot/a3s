-- Migration 017: auth hardening columns (I-B M0.5). CA-CHECK-IMPL-M0 §7.1.
-- must_change_password + temporary_password_expires_at (giu contract "password tam co TTL")
-- + last_login_at. Throttling nam o Redis (khong cot DB).
-- transactional: true
ALTER TABLE staff_users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE staff_users ADD COLUMN IF NOT EXISTS temporary_password_expires_at TIMESTAMPTZ;
ALTER TABLE staff_users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
