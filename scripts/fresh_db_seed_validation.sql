-- fresh_db_seed_validation.sql — FRESH-INSTALL-ONLY canonical seed assertion (exact values).
-- CA F-R1-01 §4.2: assert EXACT canonical seed (3S-100G = dung 3 tier: 1/170k, 5/160k, 20/140k).
-- KHONG nam trong `post_migration_validations` (deploy path `up`) nua — vi existing production co the co
-- them price tier hop le (staff tao qua chuc nang M0) khien exact-count fail sai. Lop nay CHI chay o
-- fresh-DB bootstrap/test, goi TUONG MINH qua `migrate.py fresh-validate` (manifest fresh_install_validations).
-- Operational (existing-safe) layer = scripts/operational_seed_validation.sql (nam trong post_migration_validations).
-- RAISE EXCEPTION -> asyncpg raise -> FRESH VALIDATION FAIL -> exit != 0.
DO $val$
DECLARE
  v_approved CONSTANT text :=
    '3S Coffee – Cà phê hòa tan sấy lạnh, sử dụng cà phê nhân xanh Robusta và Arabica của Việt Nam. Hũ 100 g, kèm muỗng; 1 muỗng khoảng 1 g. Có thể pha với nước nóng hoặc nước nguội và điều chỉnh độ đậm nhạt theo khẩu vị.';
  n int; d text; sg numeric; nw int; bad_tiers int;
BEGIN
  -- SKU count
  SELECT count(*) INTO n FROM products WHERE sku = '3S-100G';
  IF n <> 1 THEN RAISE EXCEPTION 'SEED FAIL: 3S-100G ton tai % lan (expect 1)', n; END IF;

  SELECT description, serving_size_g, net_weight_g
    INTO d, sg, nw FROM products WHERE sku = '3S-100G';

  -- Exact approved description (khong con claim, khong con "nguyen chat")
  IF d <> v_approved THEN
    RAISE EXCEPTION 'SEED FAIL: 3S-100G description KHONG khop exact approved description';
  END IF;
  IF strpos(d, '100% Robusta') > 0 THEN
    RAISE EXCEPTION 'SEED FAIL: 3S-100G description con chua "100%% Robusta"';
  END IF;

  -- serving NULL + net_weight giu 100
  IF sg IS NOT NULL THEN
    RAISE EXCEPTION 'SEED FAIL: 3S-100G serving_size_g khong NULL (=%) -> tool se suy ~50 ly/hu', sg;
  END IF;
  IF nw <> 100 THEN
    RAISE EXCEPTION 'SEED FAIL: 3S-100G net_weight_g=% (expect 100)', nw;
  END IF;

  -- Exact price/tier values theo source hien hanh: 1->170000, 5->160000, 20->140000
  SELECT count(*) INTO bad_tiers
  FROM price_tiers pt JOIN products p ON p.id = pt.product_id
  WHERE p.sku = '3S-100G'
    AND NOT ( (pt.min_qty=1 AND pt.unit_price_vnd=170000)
           OR (pt.min_qty=5 AND pt.unit_price_vnd=160000)
           OR (pt.min_qty=20 AND pt.unit_price_vnd=140000) );
  IF bad_tiers > 0 THEN
    RAISE EXCEPTION 'SEED FAIL: 3S-100G co % tier khong khop source (expect 1/170k, 5/160k, 20/140k)', bad_tiers;
  END IF;
  IF (SELECT count(*) FROM price_tiers pt JOIN products p ON p.id=pt.product_id WHERE p.sku='3S-100G') <> 3 THEN
    RAISE EXCEPTION 'SEED FAIL: 3S-100G khong co dung 3 tier';
  END IF;

  RAISE NOTICE 'SEED PASS: 3S-100G (exact approved description, serving NULL, net_weight=100, 3 tiers dung values)';
END
$val$;
