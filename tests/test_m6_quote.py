"""M6 shipping quote — unit tests (logic thuan). CA Directive 265 §5 Fee/ETA table.

Boundary weights: 499/500/5000/5001/5499/5500/10000/10001 g; zone noi thanh/tinh/unknown; fee unknown != 0;
weight thieu -> quote_required; region thieu mapping -> unknown.
"""
from app.services.fulfillment import quote as q

# Fixture = seed migration 064.
_RULES = [
    {"zone": "bmt_inner", "weight_min_g": 500, "weight_max_g": 5000, "fee_vnd": 0, "quote_required": False, "active": True},
    {"zone": "bmt_inner", "weight_min_g": 5500, "weight_max_g": 10000, "fee_vnd": 0, "quote_required": False, "active": True},
    {"zone": "province", "weight_min_g": 500, "weight_max_g": 5000, "fee_vnd": 30000, "quote_required": False, "active": True},
    {"zone": "province", "weight_min_g": 5500, "weight_max_g": 10000, "fee_vnd": None, "quote_required": True, "active": True},
]


def _fee(zone, w):
    return q.quote_fee(zone, w, _RULES)


# ---- fee boundaries (Directive §5) ----
def test_bmt_inner_500_to_5000_free():
    for w in (500, 3000, 5000):
        assert _fee("bmt_inner", w) == (0, "quoted")


def test_province_500_to_5000_is_30k():
    for w in (500, 5000):
        assert _fee("province", w) == (30000, "quoted")


def test_gap_5001_to_5499_quote_required_both_zones():
    for w in (5001, 5499):
        assert _fee("bmt_inner", w) == (None, "quote_required")
        assert _fee("province", w) == (None, "quote_required")


def test_bmt_inner_5500_to_10000_free_province_quote():
    for w in (5500, 8000, 10000):
        assert _fee("bmt_inner", w) == (0, "quoted")
        assert _fee("province", w) == (None, "quote_required")


def test_below_500_quote_required():
    assert _fee("bmt_inner", 499) == (None, "quote_required")
    assert _fee("province", 499) == (None, "quote_required")


def test_above_10000_quote_required():
    assert _fee("bmt_inner", 10001) == (None, "quote_required")
    assert _fee("province", 10001) == (None, "quote_required")


def test_unknown_zone_always_quote_required():
    for w in (500, 3000, 10000):
        assert _fee("unknown", w) == (None, "quote_required")


def test_weight_missing_is_unknown_not_zero():
    fee, status = _fee("bmt_inner", None)
    assert fee is None and status == "unknown"   # KHONG thanh 0


def test_fee_unknown_never_becomes_zero():
    # moi ket qua khong 'quoted' phai co fee is None (khong bao gio 0 gia)
    for zone in ("bmt_inner", "province", "unknown"):
        for w in (499, 5001, 10001, None):
            fee, status = _fee(zone, w)
            assert not (status != "quoted" and fee == 0)


# ---- region/zone resolution ----
_ZONES = [
    {"province_code": "66", "ward_code": "24169", "zone": "bmt_inner", "active": True},   # 1 ward noi thanh mau
    {"province_code": "66", "ward_code": None, "zone": "province", "active": True},        # default Dak Lak = province
]


def test_zone_ward_specific_wins():
    assert q.resolve_zone("66", "24169", _ZONES) == "bmt_inner"


def test_zone_province_fallback():
    assert q.resolve_zone("66", "99999", _ZONES) == "province"   # ward khong map -> province default


def test_zone_no_mapping_unknown():
    assert q.resolve_zone("95", "00001", _ZONES) == "unknown"    # province khong co mapping -> manual
    assert q.resolve_zone(None, None, _ZONES) == "unknown"


def test_zone_inactive_ignored():
    zones = [{"province_code": "66", "ward_code": None, "zone": "bmt_inner", "active": False}]
    assert q.resolve_zone("66", None, zones) == "unknown"


# ---- order shipping weight ----
def test_order_weight_sum():
    items = [{"shipping_weight_g": 120, "quantity": 2}, {"shipping_weight_g": 100, "quantity": 1}]
    assert q.order_shipping_weight_g(items) == 340


def test_order_weight_missing_any_returns_none():
    items = [{"shipping_weight_g": 120, "quantity": 1}, {"shipping_weight_g": None, "quantity": 1}]
    assert q.order_shipping_weight_g(items) is None   # thieu 1 item -> manual quote
