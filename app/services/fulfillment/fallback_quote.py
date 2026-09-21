"""CA Amendment 338 — GHN fallback price policy (khi route=GHN nhung API khong goi duoc/ambiguous).

Amount LUU O DB (shipping_fallback_policy.spec), KHONG hard-code trong source. Chargeable weight = MAX(thuc, quy_doi);
hien quy_doi chi khi co dims THAT (chua luu per-product) -> dung cAN THUC (PO chot). Rounding = round_up_v1 (lam tron LEN).
Fail-closed: thieu weight / khong phan loai duoc noi-lien tinh -> None (caller -> manual/staff). KHONG bao 0d.
"""
from __future__ import annotations

import json
import math

POLICY_VERSION = "GHN_FALLBACK_PO_V1"


async def load_policy(conn, policy_version: str = POLICY_VERSION) -> dict | None:
    row = await conn.fetchrow(
        "SELECT policy_version, rounding_version, spec, shop_province_code FROM shipping_fallback_policy "
        "WHERE policy_version=$1 AND active", policy_version)
    if not row:
        return None
    spec = row["spec"]
    spec = json.loads(spec) if isinstance(spec, str) else spec
    return {"policy_version": row["policy_version"], "rounding_version": row["rounding_version"],
            "shop_province_code": row["shop_province_code"], "spec": spec}


def _noi_tinh_fee(spec_nt: dict, w_kg: float) -> int:
    base_max = float(spec_nt["base_max_kg"])
    base_fee = int(spec_nt["base_fee_vnd"])
    per_extra = int(spec_nt["per_extra_kg_vnd"])
    if w_kg <= base_max:
        return base_fee
    extra_kg = math.ceil(w_kg) - base_max      # round_up_v1: lam tron LEN kg roi tru base
    return base_fee + int(extra_kg) * per_extra


def _lien_tinh_fee(spec_lt: dict, w_kg: float) -> int:
    tiers = spec_lt["tiers"]                    # [[max_kg, fee], ...] tang dan
    per_extra = int(spec_lt["per_extra_kg_vnd"])
    after = float(spec_lt["per_extra_after_kg"])
    last_max, last_fee = float(tiers[-1][0]), int(tiers[-1][1])
    if w_kg <= last_max:
        # round_up_v1: chon bac nho nhat co max_kg >= w_kg (gom <0.5kg -> bac 0.5)
        for max_kg, fee in tiers:
            if w_kg <= float(max_kg):
                return int(fee)
        return last_fee
    extra_kg = math.ceil(w_kg - after)          # >5kg: +per_extra moi kg lam tron len
    return last_fee + int(extra_kg) * per_extra


def compute_fallback_fee(policy: dict, dest_province_code: str | None, weight_g: int | None) -> tuple:
    """Tra (fee_vnd|None, reason, detail). reason: 'ok' | 'weight_missing' | 'province_unclassified'.
    dest == shop_province -> noi_tinh; dest hop le khac -> lien_tinh. Thieu weight/province -> fail-closed None."""
    if weight_g is None or weight_g <= 0:
        return None, "weight_missing", {}
    if not dest_province_code:
        return None, "province_unclassified", {}
    w_kg = weight_g / 1000.0
    spec = policy["spec"]
    if str(dest_province_code) == str(policy["shop_province_code"]):
        route_class = "noi_tinh"
        fee = _noi_tinh_fee(spec["noi_tinh"], w_kg)
    else:
        route_class = "lien_tinh"
        fee = _lien_tinh_fee(spec["lien_tinh"], w_kg)
    detail = {"quote_source": "fallback_policy", "policy_version": policy["policy_version"],
              "rounding_version": policy["rounding_version"], "route_class": route_class,
              "chargeable_weight_g": weight_g, "weight_basis": "real_weight"}
    return int(fee), "ok", detail
