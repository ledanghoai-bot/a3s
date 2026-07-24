-- Migration 013: luu yeu cau xoa du lieu (Meta Data Deletion Callback)
-- Chay THU CONG tren DB dang chay (initdb chi chay luc tao volume lan dau):
--   docker compose exec -T db psql -U alpha3s -d alpha3s -f /docker-entrypoint-initdb.d/013_data_deletion_requests.sql
-- hoac copy-paste noi dung vao:
--   docker compose exec db psql -U alpha3s -d alpha3s
--
-- Chi luu confirmation_code + trang thai de trang /datadeletion/status tra cuu.
-- CO Y khong luu psid lau dai (dang xoa du lieu khach thi khong luu nguoc lai
-- dinh danh cua ho) - viec xoa that chay inline ngay trong callback.

CREATE TABLE IF NOT EXISTS data_deletion_requests (
  id BIGSERIAL PRIMARY KEY,
  confirmation_code TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL DEFAULT 'received',  -- received | completed | failed
  requested_at TIMESTAMPTZ DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS data_deletion_requests_code_idx
  ON data_deletion_requests(confirmation_code);
