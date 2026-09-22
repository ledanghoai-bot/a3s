"""CA Directive 340 — GHN fallback price policy GHN_FALLBACK_PO_V2 (rounding ghn_tier_round_up_v1 + packing
product_volume_overhead_v1). Logic thuan (khong DB): policy dict dung theo seed migration 069.

Bao phu 340 §3.5: toan bo bac phi; nguong 0.5/1/2/3/4/5 kg; N=1; nhieu quantity/mixed; x=0 va x>0;
actual > volumetric va nguoc lai; missing/invalid dimension/weight/x/province -> manual. KHONG bao 0d.
"""
from app.services.fulfillment import fallback_quote as fb

# Fixture = seed migration 069 (spec o DB, KHONG hard-code trong source app).
POLICY = {
    "policy_version": "GHN_FALLBACK_PO_V2",
    "rounding_version": "ghn_tier_round_up_v1",
    "packing_version": "product_volume_overhead_v1",
    "shop_province_code": "66",
    "spec": {
        "noi_tinh": {"base_max_kg": 3, "base_fee_vnd": 16500, "per_extra_kg_vnd": 7000},
        "lien_tinh": {"tiers": [[0.5, 25000], [1, 27000], [2, 29000], [3, 32000], [4, 35000], [5, 40000]],
                      "per_extra_kg_vnd": 7000, "per_extra_after_kg": 5},
    },
}
SHOP = "66"          # noi tinh (Dak Lak)
OTHER = "79"         # lien tinh (HCM)


def _cube(side_cm, q=1, pid=1):
    return {"product_id": pid, "quantity": q, "length_cm": side_cm, "width_cm": side_cm, "height_cm": side_cm}


# ============================ FEE ROUNDING (compute_fallback_fee, W truc tiep) ============================
def test_noi_tinh_base_and_round_up():
    def f(w):
        return fb.compute_fallback_fee(POLICY, SHOP, w)[0]
    for w in (0.001, 0.5, 1, 3):
        assert f(w) == 16500, w
    assert f(3.001) == 16500 + 1 * 7000      # ceil 4
    assert f(4) == 16500 + 1 * 7000
    assert f(4.001) == 16500 + 2 * 7000
    assert f(5) == 16500 + 2 * 7000          # 30500
    assert f(10) == 16500 + 7 * 7000         # 65500


def test_lien_tinh_tier_boundaries_0p5_to_5():
    def f(w):
        return fb.compute_fallback_fee(POLICY, OTHER, w)[0]
    assert f(0.5) == 25000 and f(1) == 27000 and f(2) == 29000
    assert f(3) == 32000 and f(4) == 35000 and f(5) == 40000


def test_lien_tinh_round_up_within_and_below_half():
    def f(w):
        return fb.compute_fallback_fee(POLICY, OTHER, w)[0]
    assert f(0.001) == 25000 and f(0.3) == 25000    # 0<W<=0.5 -> bac 0.5
    assert f(0.6) == 27000 and f(1.5) == 29000 and f(2.001) == 32000


def test_lien_tinh_over_5kg_per_extra():
    def f(w):
        return fb.compute_fallback_fee(POLICY, OTHER, w)[0]
    assert f(5.001) == 40000 + 1 * 7000
    assert f(5.5) == 40000 + 1 * 7000
    assert f(6) == 40000 + 1 * 7000
    assert f(10) == 40000 + 5 * 7000                 # 75000


def test_fee_fail_closed_no_zero():
    assert fb.compute_fallback_fee(POLICY, SHOP, None)[:2] == (None, "weight_missing")
    assert fb.compute_fallback_fee(POLICY, SHOP, 0)[:2] == (None, "weight_missing")
    assert fb.compute_fallback_fee(POLICY, None, 2)[:2] == (None, "province_unclassified")
    assert fb.compute_fallback_fee(POLICY, "", 2)[:2] == (None, "province_unclassified")


def test_fee_shop_province_from_policy_not_hardcoded():
    p = {**POLICY, "shop_province_code": "79"}
    fee, reason, d = fb.compute_fallback_fee(p, "66", 2)
    assert reason == "ok" and d["route_class"] == "lien_tinh" and fee == 29000


# ============================ CHARGEABLE WEIGHT (volumetric + packing) ============================
def test_chargeable_actual_gt_volumetric():
    # cube 10cm N=1 -> vol 0.2kg; actual 2kg -> chargeable = actual 2kg
    w, r, d = fb.compute_chargeable_weight([_cube(10)], 2000, 0)
    assert r == "ok" and abs(w - 2.0) < 1e-9 and d["weight_basis"] == "actual_weight"
    assert d["raw_volume_cm3"] == 1000.0 and abs(d["volumetric_weight_kg"] - 0.2) < 1e-9


def test_chargeable_volumetric_gt_actual():
    # cube 50cm N=1 -> raw 125000 -> vol 25kg; actual 0.5kg -> chargeable = 25kg
    w, r, d = fb.compute_chargeable_weight([_cube(50)], 500, 0)
    assert r == "ok" and abs(w - 25.0) < 1e-9 and d["weight_basis"] == "volumetric"


def test_n1_no_packing_overhead_applied():
    # N=1: packed == raw bat ke x
    _, _, d0 = fb.compute_chargeable_weight([_cube(10, q=1)], 100, 0)
    _, _, d9 = fb.compute_chargeable_weight([_cube(10, q=1)], 100, 99)
    assert d0["packed_volume_cm3"] == d0["raw_volume_cm3"] == 1000.0
    assert d9["packed_volume_cm3"] == 1000.0            # x KHONG ap khi N=1


def test_packing_overhead_x0_vs_xpos_changes_tier():
    # 2 cube 10cm raw=2000; actual 0.3kg. x=0 -> vol 0.4kg (bac 0.5=25000); x=100 -> vol 0.8kg (bac 1=27000)
    w0, _, d0 = fb.compute_chargeable_weight([_cube(10, q=2)], 300, 0)
    wx, _, dx = fb.compute_chargeable_weight([_cube(10, q=2)], 300, 100)
    assert d0["packed_volume_cm3"] == 2000.0 and abs(w0 - 0.4) < 1e-9
    assert dx["packed_volume_cm3"] == 4000.0 and abs(wx - 0.8) < 1e-9
    assert fb.compute_fallback_fee(POLICY, OTHER, w0)[0] == 25000
    assert fb.compute_fallback_fee(POLICY, OTHER, wx)[0] == 27000


def test_mixed_products_raw_volume_sum():
    # [1x cube10=1000] + [3x cube20=3*8000=24000] = 25000; N=4 x=25 -> packed 31250 -> vol 6.25kg
    items = [_cube(10, q=1, pid=1), _cube(20, q=3, pid=2)]
    w, r, d = fb.compute_chargeable_weight(items, 1000, 25)
    assert r == "ok" and d["raw_volume_cm3"] == 25000.0 and d["total_quantity"] == 4
    assert d["packed_volume_cm3"] == 31250.0 and abs(w - 6.25) < 1e-9
    assert len(d["product_volumes"]) == 2


def test_chargeable_fail_closed():
    good = _cube(10)
    # weight missing / nonpositive
    assert fb.compute_chargeable_weight([good], None, 0)[1] == "weight_missing"
    assert fb.compute_chargeable_weight([good], 0, 0)[1] == "weight_missing"
    assert fb.compute_chargeable_weight([good], -5, 0)[1] == "weight_missing"
    # dimension missing / invalid (khong gia dinh = 0)
    assert fb.compute_chargeable_weight([{"quantity": 1, "length_cm": None, "width_cm": 10, "height_cm": 10}], 100, 0)[1] == "dimension_missing"
    assert fb.compute_chargeable_weight([{"quantity": 1, "length_cm": 0, "width_cm": 10, "height_cm": 10}], 100, 0)[1] == "dimension_missing"
    assert fb.compute_chargeable_weight([{"quantity": 0, "length_cm": 10, "width_cm": 10, "height_cm": 10}], 100, 0)[1] == "dimension_missing"
    # x invalid
    assert fb.compute_chargeable_weight([good], 100, None)[1] == "packing_overhead_invalid"
    assert fb.compute_chargeable_weight([good], 100, -1)[1] == "packing_overhead_invalid"
    assert fb.compute_chargeable_weight([good], 100, "abc")[1] == "packing_overhead_invalid"
    # no items
    assert fb.compute_chargeable_weight([], 100, 0)[1] == "no_items"


# ============================ quote_fallback (ket hop) + snapshot ============================
def test_quote_fallback_end_to_end_lien_tinh():
    items = [_cube(10, q=2)]                    # vol 0.4kg (x=0); actual 5kg -> chargeable 5kg
    fee, reason, d = fb.quote_fallback(POLICY, OTHER, items, 5000, 0)
    assert reason == "ok" and fee == 40000
    assert d["quote_source"] == "fallback_policy" and d["policy_version"] == "GHN_FALLBACK_PO_V2"
    assert d["rounding_version"] == "ghn_tier_round_up_v1" and d["packing_version"] == "product_volume_overhead_v1"
    assert d["route_class"] == "lien_tinh" and d["fee_vnd"] == 40000
    # snapshot audit day du (340 §1.4)
    for k in ("actual_weight_g", "raw_volume_cm3", "packing_overhead_percent", "packed_volume_cm3",
              "volumetric_weight_kg", "chargeable_weight_kg", "product_volumes", "weight_basis"):
        assert k in d, k


def test_quote_fallback_manual_when_dimension_missing():
    items = [{"quantity": 1, "length_cm": None, "width_cm": 10, "height_cm": 10}]
    fee, reason, d = fb.quote_fallback(POLICY, OTHER, items, 5000, 0)
    assert fee is None and reason == "dimension_missing" and d["fallback_reason"] == "dimension_missing"


def test_quote_fallback_manual_when_province_unclassified():
    items = [_cube(10)]
    fee, reason, d = fb.quote_fallback(POLICY, None, items, 5000, 0)
    assert fee is None and reason == "province_unclassified"
    assert d["chargeable_weight_kg"] and d["fallback_reason"] == "province_unclassified"  # da tinh weight, fail o province


def test_quote_fallback_never_zero():
    items = [_cube(10, q=2)]
    for dest in (SHOP, OTHER):
        for actual in (100, 5000, 30000):
            fee, reason, _ = fb.quote_fallback(POLICY, dest, items, actual, 10)
            assert reason == "ok" and fee and fee > 0


# ============================ CA 341-01: request dims GHN tu CUNG input dong thung ============================
def test_box_dims_n1_uses_actual_product_dims():
    items = [{"product_id": 1, "quantity": 1, "length_cm": 30, "width_cm": 10, "height_cm": 5}]
    dims, reason, d = fb.ghn_request_dims(items, 500, 20)
    assert reason == "ok" and dims == (30, 10, 5)                   # N=1: kich thuoc that, KHONG ap x
    assert d["request_box_volume_cm3"] == d["packed_volume_cm3"] == 1500.0
    assert d["dims_source"] == "packed_volume" and d["box_shape_version"] == fb.BOX_SHAPE_VERSION


def test_box_dims_n_gt_1_cube_ceil_covers_packed_volume():
    # 2 x cube10 = 2000; x=10 -> packed 2200 -> canh nho nhat side^3 >= 2200 la 14 (13^3=2197 < 2200)
    dims, reason, d = fb.ghn_request_dims([_cube(10, q=2)], 300, 10)
    assert reason == "ok" and dims == (14, 14, 14)
    assert d["request_box_volume_cm3"] >= d["packed_volume_cm3"]
    assert 13 ** 3 < d["packed_volume_cm3"]                          # canh NHO NHAT
    # packed dung bang lap phuong -> khong phong to
    dims2, _, _ = fb.ghn_request_dims([_cube(10, q=8)], 300, 0)      # raw 8000 = 20^3
    assert dims2 == (20, 20, 20)


def test_request_dims_not_default_weight_table():
    # truoc 341: default_dims_cm(600) = (20,15,10). Nay theo the tich thuc.
    dims, _, _ = fb.ghn_request_dims([_cube(8, q=1)], 600, 0)
    assert dims == (8, 8, 8) and dims != (20, 15, 10)


def test_request_dims_missing_inputs_fail_closed():
    assert fb.ghn_request_dims([{"quantity": 1, "length_cm": None, "width_cm": 1, "height_cm": 1}], 500, 0)[:2] \
        == (None, "dimension_missing")
    assert fb.ghn_request_dims([_cube(10)], 500, None)[:2] == (None, "packing_overhead_invalid")
    assert fb.ghn_request_dims([_cube(10)], None, 0)[:2] == (None, "weight_missing")
    assert fb.ghn_request_dims([], 500, 0)[:2] == (None, "no_items")


def test_api_request_and_fallback_share_chargeable_inputs():
    items = [_cube(20, q=3)]
    dims, _, rd = fb.ghn_request_dims(items, 1000, 25)
    fee, _, qd = fb.quote_fallback(POLICY, OTHER, items, 1000, 25)
    assert rd["chargeable_weight_kg"] == qd["chargeable_weight_kg"]
    assert rd["packed_volume_cm3"] == qd["packed_volume_cm3"] and fee is not None


def test_policy_version_mismatch_fail_closed():
    for bad in ({**POLICY, "rounding_version": "other_v9"}, {**POLICY, "packing_version": "other_v9"}):
        assert fb.compute_fallback_fee(bad, OTHER, 2)[:2] == (None, "policy_version_unsupported")
