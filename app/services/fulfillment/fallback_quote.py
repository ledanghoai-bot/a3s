"""CA Directive 340 — GHN fallback price policy GHN_FALLBACK_PO_V2 (khi route=GHN nhung API khong goi duoc/ambiguous).

Amount + config policy LUU O DB (shipping_fallback_policy.spec), KHONG hard-code trong source (340 §3.3).
Trong luong tinh cuoc `W = max(actual_kg, volumetric_kg)`; volumetric theo the tich san pham + overhead dong thung:
  raw_volume_cm3 = Σ(quantity_i × L_i × W_i × H_i); N>1 -> packed = raw × (1 + x/100); N=1 -> packed = raw;
  volumetric_kg = packed_volume_cm3 / 5000.
Lam tron theo bac GHN (`ghn_tier_round_up_v1`), packing `product_volume_overhead_v1`.
Fail-closed (340 §1.5): thieu kich thuoc hop le / actual thieu-hoac-khong-duong / x khong hop le / tinh dich khong phan
loai duoc -> None (caller -> manual/staff). KHONG gia dinh kich thuoc = 0, KHONG dung rieng can thuc lam ngoai le, KHONG bao 0d.
"""
from __future__ import annotations

import json
import math

POLICY_VERSION = "GHN_FALLBACK_PO_V2"
# Version CONG THUC do code nay implement (policy DB phai khai bao dung version nay, khac -> fail-closed).
ROUNDING_VERSION = "ghn_tier_round_up_v1"
PACKING_VERSION = "product_volume_overhead_v1"
# CA Review 341-01: kich thuoc request GHN dung CHUNG input dong thung voi fallback. N=1 (1 dong, qty 1) -> kich thuoc
# THAT cua san pham (the tich = packed, chinh xac); N>1 -> hop lap phuong canh nguyen nho nhat co the tich >= packed.
BOX_SHAPE_VERSION = "single_actual_else_cube_ceil_v1"
# CA Review 342-01: trong luong quy doi tinh tu THE TICH HOP THUC GUI GHN (L×W×H cua request), KHONG tu packed_volume.
# W = max(actual, provider_box_volume/5000) dung cho CA request snapshot VA fallback fee. packed_volume chi la input dong goi.
CHARGEABLE_BASIS_VERSION = "provider_box_volumetric_v1"
VOLUMETRIC_DIVISOR = 5000.0


async def load_policy(conn, policy_version: str = POLICY_VERSION) -> dict | None:
    row = await conn.fetchrow(
        "SELECT policy_version, rounding_version, packing_version, spec, shop_province_code "
        "FROM shipping_fallback_policy WHERE policy_version=$1 AND active", policy_version)
    if not row:
        return None
    spec = row["spec"]
    spec = json.loads(spec) if isinstance(spec, str) else spec
    return {"policy_version": row["policy_version"], "rounding_version": row["rounding_version"],
            "packing_version": row["packing_version"], "shop_province_code": row["shop_province_code"], "spec": spec}


def _pos_finite(v) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 0


def compute_chargeable_weight(items: list[dict], actual_weight_g: int | None,
                              packing_overhead_percent) -> tuple:
    """Tra (chargeable_weight_kg|None, reason, detail). reason: 'ok' | 'weight_missing' | 'dimension_missing' |
    'packing_overhead_invalid' | 'no_items'. items = [{quantity, length_cm, width_cm, height_cm}, ...].
    Fail-closed 340 §1.5: bat ky san pham thieu kich thuoc hop le / actual thieu-hoac-khong-duong / x khong hop le -> None."""
    if actual_weight_g is None or actual_weight_g <= 0:
        return None, "weight_missing", {}
    if packing_overhead_percent is None:
        return None, "packing_overhead_invalid", {}
    try:
        x = float(packing_overhead_percent)
    except (TypeError, ValueError):
        return None, "packing_overhead_invalid", {}
    if not math.isfinite(x) or x < 0:
        return None, "packing_overhead_invalid", {}
    if not items:
        return None, "no_items", {}

    raw_volume_cm3 = 0.0
    total_qty = 0
    vol_lines = []
    for it in items:
        q = it.get("quantity")
        length, width, height = it.get("length_cm"), it.get("width_cm"), it.get("height_cm")
        if not isinstance(q, int) or isinstance(q, bool) or q <= 0:
            return None, "dimension_missing", {}
        if not (_pos_finite(length) and _pos_finite(width) and _pos_finite(height)):
            return None, "dimension_missing", {}
        line_vol = q * float(length) * float(width) * float(height)
        raw_volume_cm3 += line_vol
        total_qty += q
        vol_lines.append({"product_id": it.get("product_id"), "quantity": q,
                          "length_cm": float(length), "width_cm": float(width), "height_cm": float(height)})

    packed_volume_cm3 = raw_volume_cm3 * (1.0 + x / 100.0) if total_qty > 1 else raw_volume_cm3
    dims = box_dims(items, packed_volume_cm3)
    if dims is None:
        return None, "box_invalid", {}
    # CA 342-01: volumetric tu hop THUC gui GHN (cung dims request), khong tu packed.
    provider_box_volume_cm3 = dims[0] * dims[1] * dims[2]
    provider_volumetric_weight_kg = provider_box_volume_cm3 / VOLUMETRIC_DIVISOR
    actual_weight_kg = actual_weight_g / 1000.0
    chargeable_weight_kg = max(actual_weight_kg, provider_volumetric_weight_kg)
    detail = {
        "actual_weight_g": int(actual_weight_g), "actual_weight_kg": actual_weight_kg,
        "product_volumes": vol_lines, "total_quantity": total_qty,
        "raw_volume_cm3": raw_volume_cm3, "packing_overhead_percent": x,
        "packed_volume_cm3": packed_volume_cm3,                              # input dong goi (khong dung tinh W)
        "packed_volumetric_weight_kg": packed_volume_cm3 / VOLUMETRIC_DIVISOR,   # chi tham chieu
        "request_dims_cm": list(dims), "provider_box_volume_cm3": provider_box_volume_cm3,
        "provider_volumetric_weight_kg": provider_volumetric_weight_kg,
        "chargeable_weight_kg": chargeable_weight_kg,
        "weight_basis": "provider_volumetric" if provider_volumetric_weight_kg > actual_weight_kg else "actual_weight",
        "box_shape_version": BOX_SHAPE_VERSION, "chargeable_basis_version": CHARGEABLE_BASIS_VERSION,
    }
    return chargeable_weight_kg, "ok", detail


def _noi_tinh_fee(spec_nt: dict, w_kg: float) -> int:
    base_max = float(spec_nt["base_max_kg"])
    base_fee = int(spec_nt["base_fee_vnd"])
    per_extra = int(spec_nt["per_extra_kg_vnd"])
    if w_kg <= base_max:
        return base_fee
    extra_kg = math.ceil(w_kg) - base_max      # ghn_tier_round_up_v1: 16500 + (ceil(W)-3)*7000
    return base_fee + int(extra_kg) * per_extra


def _lien_tinh_fee(spec_lt: dict, w_kg: float) -> int:
    tiers = spec_lt["tiers"]                    # [[max_kg, fee], ...] tang dan
    per_extra = int(spec_lt["per_extra_kg_vnd"])
    after = float(spec_lt["per_extra_after_kg"])
    last_max, last_fee = float(tiers[-1][0]), int(tiers[-1][1])
    if w_kg <= last_max:
        for max_kg, fee in tiers:               # bac nho nhat khong nho hon W (0<W<=0.5 -> bac 0.5)
            if w_kg <= float(max_kg):
                return int(fee)
        return last_fee
    extra_kg = math.ceil(w_kg - after)          # >5kg: 40000 + ceil(W-5)*7000
    return last_fee + int(extra_kg) * per_extra


def compute_fallback_fee(policy: dict, dest_province_code: str | None, chargeable_weight_kg: float | None) -> tuple:
    """Tra (fee_vnd|None, reason, detail). reason: 'ok' | 'weight_missing' | 'province_unclassified'.
    dest == shop_province -> noi_tinh; dest hop le khac -> lien_tinh. Thieu W/province -> fail-closed None."""
    if policy.get("rounding_version") != ROUNDING_VERSION or policy.get("packing_version") != PACKING_VERSION:
        return None, "policy_version_unsupported", {}
    if chargeable_weight_kg is None or chargeable_weight_kg <= 0:
        return None, "weight_missing", {}
    if not dest_province_code:
        return None, "province_unclassified", {}
    spec = policy["spec"]
    if str(dest_province_code) == str(policy["shop_province_code"]):
        route_class = "noi_tinh"
        fee = _noi_tinh_fee(spec["noi_tinh"], chargeable_weight_kg)
    else:
        route_class = "lien_tinh"
        fee = _lien_tinh_fee(spec["lien_tinh"], chargeable_weight_kg)
    detail = {"quote_source": "fallback_policy", "policy_version": policy["policy_version"],
              "rounding_version": policy["rounding_version"], "packing_version": policy["packing_version"],
              "route_class": route_class, "chargeable_weight_kg": chargeable_weight_kg}
    return int(fee), "ok", detail


def box_dims(items: list[dict], packed_volume_cm3: float) -> tuple[int, int, int] | None:
    """BOX_SHAPE_VERSION. Items da validate (compute_chargeable_weight ok). None neu the tich khong hop le."""
    if not (isinstance(packed_volume_cm3, (int, float)) and math.isfinite(packed_volume_cm3) and packed_volume_cm3 > 0):
        return None
    if len(items) == 1 and items[0].get("quantity") == 1:
        it = items[0]
        return (math.ceil(float(it["length_cm"])), math.ceil(float(it["width_cm"])), math.ceil(float(it["height_cm"])))
    side = max(1, math.ceil(packed_volume_cm3 ** (1.0 / 3.0)))
    while side ** 3 < packed_volume_cm3:        # chong sai so float
        side += 1
    while side > 1 and (side - 1) ** 3 >= packed_volume_cm3:
        side -= 1
    return side, side, side


def ghn_request_dims(items: list[dict], actual_weight_g: int | None, packing_overhead_percent) -> tuple:
    """Kich thuoc request GHN tu CUNG input/cong thuc D340 voi fallback. Tra (dims|None, reason, detail).
    Thieu dims/weight/x -> None (caller: KHONG goi provider, manual)."""
    w_kg, reason, d = compute_chargeable_weight(items, actual_weight_g, packing_overhead_percent)
    if w_kg is None:
        return None, reason, {"dims_source": None, "packing_reason": reason}
    # dims + chargeable tinh 1 LAN trong compute_chargeable_weight -> request va fallback cung W (342-01 invariant).
    detail = {**d, "dims_source": "packed_volume_box", "packing_version": PACKING_VERSION}
    return tuple(d["request_dims_cm"]), "ok", detail


async def load_packing_inputs(conn, order_id: int) -> tuple[list[dict], float | None]:
    """Item + kich thuoc san pham + x (Shipping Settings). Conn-based (cung transaction caller)."""
    from app.services.fulfillment import shipping_settings as _ss
    items = [dict(r) for r in await conn.fetch(
        "SELECT oi.product_id, oi.quantity, p.length_cm, p.width_cm, p.height_cm "
        "FROM order_items oi JOIN products p ON p.id=oi.product_id WHERE oi.order_id=$1 ORDER BY oi.id", order_id)]
    return items, await _ss.get_packing_overhead(conn)


async def build_ghn_request(conn, order_id: int, route, weight_g: int | None) -> tuple:
    """NGUON DUY NHAT dung QuoteRequest GHN (prepare_ghn_quote goi HTTP + route_and_quote kiem fingerprint +
    route_operation tag provider). Tra (QuoteRequest|None, reason, request_detail). None -> KHONG goi provider."""
    from app.services.providers.base import QuoteRequest
    if weight_g is None or weight_g <= 0:
        return None, "weight_missing", {"dims_source": None, "packing_reason": "weight_missing"}
    items, x = await load_packing_inputs(conn, order_id)
    dims, reason, detail = ghn_request_dims(items, weight_g, x)
    if dims is None:
        return None, reason, detail
    req = QuoteRequest(order_id=order_id, province_code=route.province_code or "", ward_code=route.ward_code or "",
                       weight_g=int(weight_g), length_cm=dims[0], width_cm=dims[1], height_cm=dims[2])
    detail["request_fingerprint"] = req.fingerprint()
    return req, "ok", detail


def quote_fallback(policy: dict, dest_province_code: str | None, items: list[dict], actual_weight_g: int | None,
                   packing_overhead_percent) -> tuple:
    """Ket hop: chargeable weight (volumetric/packing) -> fee theo bac GHN. Tra (fee|None, reason, snapshot_detail).
    Bat ky fail-closed nao (weight/dimension/x/province) -> (None, reason, detail-phan-da-tinh). KHONG bao 0d."""
    w_kg, w_reason, w_detail = compute_chargeable_weight(items, actual_weight_g, packing_overhead_percent)
    if w_kg is None:
        return None, w_reason, {"fallback_reason": w_reason}
    fee, f_reason, f_detail = compute_fallback_fee(policy, dest_province_code, w_kg)
    detail = {**w_detail, **f_detail}
    if fee is None:
        detail["fallback_reason"] = f_reason
        return None, f_reason, detail
    detail["fee_vnd"] = int(fee)
    return int(fee), "ok", detail
