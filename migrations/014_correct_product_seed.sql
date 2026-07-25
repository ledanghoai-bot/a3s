-- Migration 014: CORRECTIVE data cho SKU '3S-100G' (issue I-B M0, CA-CHECK-IMPL-M0-002).
-- (Danh so 014, KHONG 013: 013_data_deletion_requests da ton tai trong repo — collision phat hien
--  khi rehearsal; corrective van chay TRUOC cac migration M0 moi 015/016/017.)
--
-- Sua 2 loi du lieu seed lich su, forward-only (KHONG sua file 001/012 da ton tai):
--   1) Description claim "100% Robusta" (superseded) — trai Brand Truth (SKL-PRD-002/FAQ-001/BRAND-001).
--   2) serving_size_g=2 KHONG co canonical support (tool suy ~50 ly/hu = Product Fact chua duyet)
--      -> dat NULL (tools._serving_info tra None khi serving_size_g falsy -> bot khong suy so ly/gia-ly).
-- Approved description: CA-CHECK-IMPL-M0-002 §2.
--
-- transactional: true
--
-- CA-REVIEW-M0-DEV-001 §6: pre/postcondition la EXECUTABLE (DO block RAISE EXCEPTION -> rollback ->
-- runner KHONG ghi schema_migrations). Validation script ngoai la lop thu hai, khong thay the.
-- An toan: exact-match IN (khong LIKE '%Robusta%') -> khong ghi de mo ta hop le staff da sua;
-- postcondition chap nhan approved HOAC "explicitly accepted newer description" (bat buoc: khong
-- con claim "100% Robusta" cho SKU nay, serving NULL, net_weight=100). Unknown-bad variant con sot
-- -> postcondition FAIL -> rollback (buoc bo sung variant vao IN-list roi chay lai).

DO $mig$
DECLARE
  v_approved CONSTANT text :=
    '3S Coffee – Cà phê hòa tan sấy lạnh, sử dụng cà phê nhân xanh Robusta và Arabica của Việt Nam. Hũ 100 g, kèm muỗng; 1 muỗng khoảng 1 g. Có thể pha với nước nóng hoặc nước nguội và điều chỉnh độ đậm nhạt theo khẩu vị.';
  v_bad1 CONSTANT text :=
    'Cà phê sấy lạnh nguyên chất, 100% Robusta (phôi Ro-Express R100). Hòa tan nhanh với nước nóng ~85°C, nước nguội hoặc nước đá. Hũ 100g, muỗng đi kèm (1 muỗng khoảng 1g), pha đậm/nhạt tùy chỉnh số muỗng.';
  v_bad2 CONSTANT text :=
    'Cà phê sấy lạnh nguyên chất, 100% Robusta (phôi Ro-Express R100). Hòa tan 3 giây với nước nguội/đá.';
  cnt int; d text; sg numeric; nw int;
BEGIN
  -- (1) Precondition: SKU ton tai dung 1 lan
  SELECT count(*) INTO cnt FROM products WHERE sku = '3S-100G';
  IF cnt <> 1 THEN
    RAISE EXCEPTION '014 precondition FAIL: 3S-100G count=% (expect 1)', cnt;
  END IF;

  -- (2) Apply: exact-match known-bad description -> approved + bo serving unsupported
  UPDATE products
     SET description = v_approved, serving_size_g = NULL
   WHERE sku = '3S-100G' AND description IN (v_bad1, v_bad2);

  -- (3) Correct: description da hop le nhung serving_size_g=2 unsupported van con
  UPDATE products
     SET serving_size_g = NULL
   WHERE sku = '3S-100G' AND serving_size_g = 2;

  -- (4) Postcondition (fail-closed)
  SELECT description, serving_size_g, net_weight_g
    INTO d, sg, nw FROM products WHERE sku = '3S-100G';
  IF strpos(d, '100% Robusta') > 0 THEN
    RAISE EXCEPTION '014 postcondition FAIL: 3S-100G description van chua "100%% Robusta" (unknown-bad variant? bo sung IN-list roi chay lai)';
  END IF;
  IF sg IS NOT NULL THEN
    RAISE EXCEPTION '014 postcondition FAIL: 3S-100G serving_size_g khong NULL (=%)', sg;
  END IF;
  IF nw <> 100 THEN
    RAISE EXCEPTION '014 postcondition FAIL: 3S-100G net_weight_g=% (expect 100)', nw;
  END IF;

  RAISE NOTICE '014 OK: 3S-100G corrected (khong con 100%% Robusta, serving_size_g NULL, net_weight_g=100)';
END
$mig$;
