-- Migration 029: thêm 'delivered' vào orders.status + cột delivered_at (I-B M3 Slice 1).
-- Spec A3S-PHASE1B-M3-SPEC-001 §7.2; Directive A3S-PHASE1B-M3-DEV-DIRECTIVE-001 §5-S1, §6 (đầu M3 = 029).
-- Baseline 028: CHECK đã có 'delivery_failed' (M2/025) nhưng CHƯA có 'delivered'; chưa có delivered_at.
-- Expand-only, forward, self-validating. Forward-fix: nếu fail giữa chừng, chạy lại toàn bộ file (idempotent).
-- Runtime estimate: <1s (ALTER CHECK + ADD COLUMN NULL, không rewrite table).
-- Quy ước data_class/purpose_code (hiệu lực từ 029 — spec §6.1): khai báo bằng COMMENT.
-- transactional: true

-- Precondition: constraint hiện hành tồn tại và chưa có 'delivered'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='orders_status_check') THEN
    RAISE EXCEPTION '029 precondition FAIL: thieu orders_status_check (can 001..028 truoc)'; END IF;
END $$;

ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_status_check;
ALTER TABLE orders ADD CONSTRAINT orders_status_check CHECK (status IN (
  'new','confirmed','processing','ready_for_fulfillment','fulfilled','delivered','delivery_failed',
  'return_requested','return_inspection','completed','cancelled','cancelled_by_exception',
  'shipped','done'
));

ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at timestamptz NULL;

COMMENT ON COLUMN orders.delivered_at IS
  'Thời điểm commit sang delivered (observed, source=order_events). Chỉ set khi transition delivered; '
  'idempotent retry không overwrite. data_class=D1_PERSONAL_BASIC(ref); purpose_code=P02_COMMERCE,'
  'P03_TRANSACTIONAL; retention_rule_id=RET-03; owner_system=alpha3s; lineage_ref=order_events';

-- Postcondition
DO $$
BEGIN
  IF NOT (pg_get_constraintdef((SELECT oid FROM pg_constraint WHERE conname='orders_status_check'))
          LIKE '%''delivered''%') THEN
    RAISE EXCEPTION '029 postcondition FAIL: constraint thieu delivered'; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='orders' AND column_name='delivered_at') THEN
    RAISE EXCEPTION '029 postcondition FAIL: thieu cot delivered_at'; END IF;
END $$;
