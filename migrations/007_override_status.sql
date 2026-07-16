-- Migration 007: trang thai ro rang cho price_overrides (issue #8 - nang cap
-- UX 16/7 lan 5: khong xoa/an han note/approve da xu ly, ma hien "frozen" +
-- them luong Tu choi (Reject) cho approve bi huy vi ly do khac.
-- Chay THU CONG tren DB da ton tai, giong cac migration truoc:
--   docker compose exec db psql -U alpha3s -d alpha3s -f /docker-entrypoint-initdb.d/007_override_status.sql

ALTER TABLE price_overrides
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';

ALTER TABLE price_overrides
  ADD COLUMN IF NOT EXISTS reject_reason TEXT;

ALTER TABLE price_overrides
  ADD CONSTRAINT price_overrides_status_check
  CHECK (status IN ('active', 'used', 'rejected'));

-- Dong bo du lieu cu: cac ban ghi da used=TRUE tu truoc migration nay (qua nut
-- "Da tao don" cu) duoc coi la status='used'.
UPDATE price_overrides SET status = 'used' WHERE used = TRUE AND status = 'active';
