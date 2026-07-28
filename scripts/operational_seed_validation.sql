-- operational_seed_validation.sql — OPERATIONAL post-migration validation (existing-safe).
-- CA F-R1-01 §4.1: lop LUON chay trong post_migration_validations cua `migrate.py up` (fresh + existing prod).
-- Existing-safe = KHONG assert exact price-tier count / exact canonical values (production co them tier hop le
-- do staff tao qua chuc nang M0). Exact canonical seed = LOP FRESH-ONLY rieng (scripts/fresh_db_seed_validation.sql),
-- goi tuong minh qua `migrate.py fresh-validate`, KHONG nam trong deploy path `up`.
-- Scope theo SKU '3S-100G'. RAISE EXCEPTION -> asyncpg raise -> VALIDATION FAIL -> service khong exit 0.
DO $val$
DECLARE
  v_approved CONSTANT text :=
    '3S Coffee – Cà phê hòa tan sấy lạnh, sử dụng cà phê nhân xanh Robusta và Arabica của Việt Nam. Hũ 100 g, kèm muỗng; 1 muỗng khoảng 1 g. Có thể pha với nước nóng hoặc nước nguội và điều chỉnh độ đậm nhạt theo khẩu vị.';
  n int; d text; sg numeric; nw int; n_tiers int; bad_struct int;
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

  -- EXISTING-SAFE (CA F-R1-01 §4.1): KHONG assert exact count / exact canonical values —
  -- production co the co them price tier hop le do staff tao (chuc nang M0 price override/tier).
  -- (a) it nhat 1 price tier ton tai
  SELECT count(*) INTO n_tiers
  FROM price_tiers pt JOIN products p ON p.id = pt.product_id
  WHERE p.sku = '3S-100G';
  IF n_tiers < 1 THEN
    RAISE EXCEPTION 'SEED FAIL: 3S-100G khong co price tier nao (expect >=1)';
  END IF;
  -- (b) structural invariant moi tier: min_qty>=1 va unit_price_vnd>0 (khong NULL/am/0).
  --     Dup min_qty da bi chan boi UNIQUE(product_id,min_qty) o schema (001_init).
  SELECT count(*) INTO bad_struct
  FROM price_tiers pt JOIN products p ON p.id = pt.product_id
  WHERE p.sku = '3S-100G'
    AND (pt.min_qty IS NULL OR pt.min_qty < 1 OR pt.unit_price_vnd IS NULL OR pt.unit_price_vnd <= 0);
  IF bad_struct > 0 THEN
    RAISE EXCEPTION 'SEED FAIL: 3S-100G co % price tier structural khong hop le (min_qty>=1, unit_price_vnd>0)', bad_struct;
  END IF;

  RAISE NOTICE 'OP SEED PASS: 3S-100G (approved description, serving NULL, net_weight=100, >=1 price tier, structural valid)';
END
$val$;
