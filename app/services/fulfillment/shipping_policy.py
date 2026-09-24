"""CA Directive 354 / PO Record 353 — policy hang nang: don co trong luong shipping > 20.000 g KHONG duoc bao gia tu dong.

Guard CHUNG, versioned, KHONG phu thuoc `light_max_g` cua provider. Ap truoc moi duong bao gia tu dong (dung request GHN,
provider quote, route_operation, route_and_quote, fallback). Bien 20.000 g van theo quote contract thuong; 20.001 g -> guard.
Doi nguong/policy = PO ban hanh policy moi versioned (khong sua tai cho)."""
from __future__ import annotations

HEAVY_GOODS_POLICY_VERSION = "po_record_353_v1"
HEAVY_GOODS_MAX_G = 20000
HEAVY_GOODS_REASON = "heavy_goods_manual"


def is_heavy(weight_g) -> bool:
    """True khi trong luong shipping (gram) > 20.000. None/khong hop le -> False (de nhanh khac xu ly weight_missing)."""
    try:
        return weight_g is not None and int(weight_g) > HEAVY_GOODS_MAX_G
    except (TypeError, ValueError):
        return False


def heavy_detail(weight_g) -> dict:
    """Snapshot/audit redacted: ly do + policy version + nguong + trong luong (khong secret/PII)."""
    return {"reason": HEAVY_GOODS_REASON, "policy_version": HEAVY_GOODS_POLICY_VERSION,
            "max_weight_g": HEAVY_GOODS_MAX_G, "weight_g": int(weight_g)}
