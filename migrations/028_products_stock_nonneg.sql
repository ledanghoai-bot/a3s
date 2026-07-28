-- Migration 028: products.stock >= 0 (I-B M2 — CA M2-S2-F01 defense-in-depth).
-- Mirror contract (materialize stock := balance.available) đã đảm bảo stock == available >= 0 cho MỌI
-- M2 write path. CHECK này chặn stock âm từ BẤT KỲ path nào (kể cả dashboard staff sửa stock trực tiếp).
-- Production 0 negative stock (Slice0 audit) -> ADD CONSTRAINT an toàn. Expand-only, forward.
-- transactional: true

ALTER TABLE products DROP CONSTRAINT IF EXISTS products_stock_nonneg;
ALTER TABLE products ADD CONSTRAINT products_stock_nonneg CHECK (stock >= 0);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='products_stock_nonneg') THEN
    RAISE EXCEPTION '028 postcondition FAIL: thieu products_stock_nonneg'; END IF;
END $$;
