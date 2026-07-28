-- Migration 027: orders.origin_channel (I-B M2 — CA M2-S1-F06 fix, AC-M2-15).
-- Lưu kênh gốc của đơn (messenger/telegram_customer/dashboard) tại order.create -> transition có thể
-- gửi customer notification deterministic ĐÚNG kênh (KHÔNG suy luận kênh từ prefix psid). Expand-only.
-- transactional: true

ALTER TABLE orders ADD COLUMN IF NOT EXISTS origin_channel TEXT;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='orders' AND column_name='origin_channel') THEN
    RAISE EXCEPTION '027 postcondition FAIL: thieu orders.origin_channel'; END IF;
END $$;
