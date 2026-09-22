-- 069_ghn_fallback_v2.sql — CA Directive 340: GHN fallback price GHN_FALLBACK_PO_V2 (rounding + packing/volumetric).
-- Additive/idempotent. Amount + config policy LUU O DB (KHONG hard-code source, 340 §3.3). Migration khong sua snapshot lich su.
-- Gom: (A) kich thuoc san pham; (B) Shipping Settings packing_overhead_percent (versioned+audit); (C) bang policy fallback + seed V2;
--      (D) permission catalog.manage (role quan tri san pham) + grant admin.

-- ============================ (A) Kich thuoc san pham (340 §1.1) ============================
-- length/width/height cm: huu han, DUONG (CHECK > 0). NULL -> chua khai bao -> fallback fail-closed (manual). Audit qua audit_log.
ALTER TABLE products ADD COLUMN IF NOT EXISTS length_cm INTEGER CHECK (length_cm IS NULL OR length_cm > 0);
ALTER TABLE products ADD COLUMN IF NOT EXISTS width_cm  INTEGER CHECK (width_cm  IS NULL OR width_cm  > 0);
ALTER TABLE products ADD COLUMN IF NOT EXISTS height_cm INTEGER CHECK (height_cm IS NULL OR height_cm > 0);

-- ============================ (B) Shipping Settings: packing_overhead_percent (340 §1.2) ============================
-- Singleton (id=1). x = phan tram the tich tang them khi dong chung nhieu don vi (N>1). KHONG am. version = CAS + audit trail = lich su.
-- readback KHONG secret (x cong khai). Sua qua role quan tri shipping (shipment.manage) -> audit before/after.
CREATE TABLE IF NOT EXISTS shipping_settings (
    id                        SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    packing_overhead_percent  NUMERIC(6,2) CHECK (packing_overhead_percent IS NULL OR packing_overhead_percent >= 0),
    version                   INTEGER NOT NULL DEFAULT 1,
    updated_by                TEXT,
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Seed hang singleton: x = NULL (CHUA cau hinh) -> fallback fail-closed (manual) toi khi PO nhap. Admin nhap qua dashboard.
INSERT INTO shipping_settings (id, packing_overhead_percent) VALUES (1, NULL) ON CONFLICT (id) DO NOTHING;

-- ============================ (C) Bang policy fallback + seed V2 (340 §1) ============================
CREATE TABLE IF NOT EXISTS shipping_fallback_policy (
    policy_version   TEXT PRIMARY KEY,
    rounding_version TEXT NOT NULL,       -- 'ghn_tier_round_up_v1'
    packing_version  TEXT NOT NULL,       -- 'product_volume_overhead_v1'
    -- spec: cau truc phi (VAT 8% da gom theo anh nguon PO). shop_province_code = tinh shop (noi tinh <=> dest == day).
    --   noi_tinh: {base_max_kg, base_fee_vnd, per_extra_kg_vnd}  (>base -> +per_extra moi kg lam tron len)
    --   lien_tinh: {tiers:[[max_kg,fee_vnd],...] tang dan, per_extra_kg_vnd, per_extra_after_kg}
    spec             JSONB NOT NULL,
    shop_province_code TEXT NOT NULL,     -- '66' = Dak Lak (noi tinh)
    source_note      TEXT,
    active           BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO shipping_fallback_policy (policy_version, rounding_version, packing_version, shop_province_code, source_note, spec) VALUES
('GHN_FALLBACK_PO_V2', 'ghn_tier_round_up_v1', 'product_volume_overhead_v1', '66',
 'CA Directive 340; PO IMG_20260917_110551.jpg SHA e6016d1a; VAT 8% included',
 '{
   "noi_tinh":  {"base_max_kg": 3, "base_fee_vnd": 16500, "per_extra_kg_vnd": 7000},
   "lien_tinh": {"tiers": [[0.5,25000],[1,27000],[2,29000],[3,32000],[4,35000],[5,40000]],
                 "per_extra_kg_vnd": 7000, "per_extra_after_kg": 5}
 }'::jsonb)
ON CONFLICT (policy_version) DO NOTHING;

-- ============================ (D) Permission catalog.manage + grant admin (340 §1.1 RBAC) ============================
INSERT INTO permissions (key, description) VALUES
  ('catalog.manage', 'Quản lý danh mục sản phẩm — kích thước/đóng gói (D340)')
ON CONFLICT (key) DO NOTHING;
INSERT INTO role_permissions (role_key, permission_key)
  SELECT 'admin', 'catalog.manage' WHERE EXISTS (SELECT 1 FROM roles WHERE key='admin')
ON CONFLICT (role_key, permission_key) DO NOTHING;

-- ============================ ROLLBACK (batch, chay tay khi can) ============================
-- DELETE FROM role_permissions WHERE permission_key='catalog.manage';
-- DELETE FROM permissions WHERE key='catalog.manage';
-- DROP TABLE IF EXISTS shipping_fallback_policy;
-- DROP TABLE IF EXISTS shipping_settings;
-- ALTER TABLE products DROP COLUMN IF EXISTS length_cm;
-- ALTER TABLE products DROP COLUMN IF EXISTS width_cm;
-- ALTER TABLE products DROP COLUMN IF EXISTS height_cm;
