-- Migration 025: mở rộng orders.status CHECK cho M2 order_status (I-B M2 Slice 4). Spec §7.1.
-- Legacy 003 chỉ cho {new,confirmed,shipped,done,cancelled} -> chặn processing/ready/fulfilled...
-- Giữ 'shipped'/'done' hợp lệ trong compatibility window (production hiện 0 đơn shipped/done, nhưng
-- không rewrite mù). Expand-only, forward, self-validating.
-- transactional: true

ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_status_check;
ALTER TABLE orders ADD CONSTRAINT orders_status_check CHECK (status IN (
  'new','confirmed','processing','ready_for_fulfillment','fulfilled','delivery_failed',
  'return_requested','return_inspection','completed','cancelled','cancelled_by_exception',
  'shipped','done'
));

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='orders_status_check') THEN
    RAISE EXCEPTION '025 postcondition FAIL: thieu orders_status_check'; END IF;
  -- xac minh status moi cua M2 duoc chap nhan (probe bang cach kiem tra dinh nghia constraint)
  IF NOT (pg_get_constraintdef((SELECT oid FROM pg_constraint WHERE conname='orders_status_check'))
          LIKE '%ready_for_fulfillment%') THEN
    RAISE EXCEPTION '025 postcondition FAIL: constraint thieu M2 status'; END IF;
END $$;
