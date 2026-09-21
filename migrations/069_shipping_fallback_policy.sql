-- 069_shipping_fallback_policy.sql — CA Amendment 338: bang phi fallback GHN khi API khong goi duoc.
-- Additive/idempotent. Amount LUU O DB (spec JSONB), KHONG hard-code trong source (338 §4.1). Versioned + immutable seed.
-- Nguon: PO IMG_20260917_110551.jpg (SHA e6016d1a...), policy_version GHN_FALLBACK_PO_V1, rounding round_up_v1 (PO chot 21/09).
-- Flag bat/tat = config `ghn_fallback_enabled` (mac dinh OFF); bang nay chi la DU LIEU policy.

CREATE TABLE IF NOT EXISTS shipping_fallback_policy (
    policy_version   TEXT PRIMARY KEY,
    rounding_version TEXT NOT NULL,
    -- spec: cau truc phi (VAT 8% da gom, theo anh nguon). shop_province_code = tinh cua shop (noi tinh <=> dest == day).
    --   noi_tinh: {base_max_kg, base_fee_vnd, per_extra_kg_vnd}  (>base -> +per_extra moi kg lam tron len)
    --   lien_tinh: {tiers:[[max_kg,fee_vnd],...] tang dan, per_extra_kg_vnd, per_extra_after_kg}
    spec             JSONB NOT NULL,
    shop_province_code TEXT NOT NULL,       -- '66' = Dak Lak (noi tinh)
    source_note      TEXT,
    active           BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO shipping_fallback_policy (policy_version, rounding_version, shop_province_code, source_note, spec) VALUES
('GHN_FALLBACK_PO_V1', 'round_up_v1', '66',
 'PO IMG_20260917_110551.jpg SHA e6016d1a; VAT 8% included; rounding round_up_v1 (PO 2026-09-21)',
 '{
   "noi_tinh":  {"base_max_kg": 3, "base_fee_vnd": 16500, "per_extra_kg_vnd": 7000},
   "lien_tinh": {"tiers": [[0.5,25000],[1,27000],[2,29000],[3,32000],[4,35000],[5,40000]],
                 "per_extra_kg_vnd": 7000, "per_extra_after_kg": 5}
 }'::jsonb)
ON CONFLICT (policy_version) DO NOTHING;

-- ============================ ROLLBACK (batch, chay tay khi can) ============================
-- DROP TABLE IF EXISTS shipping_fallback_policy;
