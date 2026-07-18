-- Migration 010: dang nhap that theo tung nhan vien (issue #8, Bat 4) - thay
-- the hoan toan ADMIN_API_TOKEN tinh dung chung truoc day. Mat khau hash
-- bang PBKDF2 (Python stdlib hashlib), session token rieng cho tung lan dang
-- nhap - KHONG dung JWT de tranh phai them dependency PyJWT + rebuild lai
-- Docker image (anh Hoai da gap nhieu kho khan voi viec build lai truoc day).
--
-- Chay THU CONG tren DB da ton tai, giong cac migration truoc:
--   docker compose exec db psql -U alpha3s -d alpha3s -f /docker-entrypoint-initdb.d/010_staff_auth.sql

CREATE TABLE IF NOT EXISTS staff_users (
  id BIGSERIAL PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  password_salt TEXT NOT NULL,
  name TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staff_sessions (
  id BIGSERIAL PRIMARY KEY,
  staff_id BIGINT NOT NULL REFERENCES staff_users(id) ON DELETE CASCADE,
  token TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS staff_sessions_token_idx ON staff_sessions(token);
CREATE INDEX IF NOT EXISTS staff_sessions_staff_id_idx ON staff_sessions(staff_id);
