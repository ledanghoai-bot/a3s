"""M6 shipping quote — region/zone + fee + ETA (logic THUAN, khong cham DB). CA Directive 265 §3/§4.1.

Nhan config da nap (zone rows + fee-rule rows) + verified address + weight -> zone, fee, fee_status, eta.
Nguyen tac (Directive 265):
- Region tu verified address + mapping cau hinh; thieu mapping -> 'unknown' (nhan vien xac nhan).
- Fee unknown/khong match rule -> quote_required, KHONG phai 0.
- Weight thieu -> quote_required (khong dung serving size thay khoi luong van chuyen).
- ETA hien thi khoang du kien, khong hua ngay chac chan; moc bat dau theo payment method (COD=confirm order,
  transfer=nhan tien) — moc do luu o payment/shipment, ham nay chi tra text duration.
"""
from __future__ import annotations

ZONES = ("bmt_inner", "province", "unknown")


def resolve_zone(province_code: str | None, ward_code: str | None, zone_rows: list[dict]) -> str:
    """Match (province, ward) active truoc, roi (province, NULL); khong co -> 'unknown' (manual)."""
    if not province_code:
        return "unknown"
    active = [z for z in zone_rows if z.get("active", True)]
    # uu tien mapping ward cu the
    for z in active:
        if z.get("province_code") == province_code and z.get("ward_code") and z.get("ward_code") == ward_code:
            return z["zone"]
    # fallback mapping cap province (ward_code NULL)
    for z in active:
        if z.get("province_code") == province_code and not z.get("ward_code"):
            return z["zone"]
    return "unknown"


def matched_rule(zone: str, weight_g: int | None, fee_rules: list[dict]) -> dict | None:
    """Rule active dau tien khop (zone + weight in [min,max]). None neu weight thieu hoac khong match."""
    if weight_g is None:
        return None
    for r in fee_rules:
        if r.get("active", True) and r.get("zone") == zone and r["weight_min_g"] <= weight_g <= r["weight_max_g"]:
            return r
    return None


def quote_fee(zone: str, weight_g: int | None, fee_rules: list[dict]) -> tuple[int | None, str]:
    """Tra (fee_vnd, fee_status). fee_status in {'quoted','quote_required','unknown'}.

    - weight_g None -> (None, 'unknown') (chua co khoi luong van chuyen -> manual quote).
    - match rule active co fee -> (fee, 'quoted').
    - match rule active quote_required -> (None, 'quote_required').
    - khong match rule nao (gap/qua nang/unknown zone) -> (None, 'quote_required') fail-closed.
    """
    if weight_g is None:
        return None, "unknown"
    for r in fee_rules:
        if not r.get("active", True):
            continue
        if r.get("zone") != zone:
            continue
        if r["weight_min_g"] <= weight_g <= r["weight_max_g"]:
            if r.get("quote_required"):
                return None, "quote_required"
            return int(r["fee_vnd"]), "quoted"
    return None, "quote_required"


# ETA duration text theo policy Robanme (khong hua ngay chac chan). Moc bat dau luu rieng theo payment method.
_ETA_BY_ZONE = {
    "bmt_inner": "khoảng 3 giờ (nội thành Buôn Ma Thuột)",
    "province": "dự kiến 1–7 ngày tùy khu vực (nhân viên xác nhận cụ thể)",
    "unknown": "sẽ xác nhận sau khi kiểm tra địa chỉ",
}


def eta_text(zone: str) -> str:
    return _ETA_BY_ZONE.get(zone, _ETA_BY_ZONE["unknown"])


def order_shipping_weight_g(items: list[dict]) -> int | None:
    """Tong khoi luong van chuyen tu shipping_weight_g cua tung san pham x quantity. Neu BAT KY item nao thieu
    shipping_weight_g -> tra None (manual quote) — KHONG suy tu net_weight/serving size (Directive 265 §3)."""
    total = 0
    for it in items:
        w = it.get("shipping_weight_g")
        if w is None:
            return None
        total += int(w) * int(it.get("quantity", 1))
    return total
