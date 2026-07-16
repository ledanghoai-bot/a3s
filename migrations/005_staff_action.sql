-- Migration 005: cot theo doi trang thai xu ly noi bo cua staff (issue #8 -
-- nang cap UX bang hoi thoai: cot "Status" + "Action").
-- Chay THU CONG tren DB da ton tai, giong 002/003/004:
--   docker compose exec db psql -U alpha3s -d alpha3s -f /docker-entrypoint-initdb.d/005_staff_action.sql

ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS staff_action TEXT NOT NULL DEFAULT 'moi';

ALTER TABLE conversations
  ADD CONSTRAINT conversations_staff_action_check
  CHECK (staff_action IN ('moi', 'da_xem', 'da_tao_don', 'bo_qua'));
