"""CA Amendment 338 — GHN fallback price policy (GHN_FALLBACK_PO_V1, rounding round_up_v1).

Logic thuan (khong DB): dung policy dict dung theo seed migration 069. Kiem tra:
- Bang phi noi tinh / lien tinh + lam tron LEN (round_up_v1); bac 0.5kg cho lien tinh <0.5kg.
- Weight tiers 337 §4.3: 1/499/500/5000/5001/5499/5500/10000/19999/20001 g.
- Fail-closed: thieu weight -> None(weight_missing); khong co province -> None(province_unclassified). KHONG bao 0d.
- Self-zone (dest == shop province 66) -> noi_tinh; khac -> lien_tinh. Detail snapshot dung field.
"""
from app.services.fulfillment import fallback_quote as fb

# Fixture = seed migration 069 (spec o DB, KHONG hard-code trong source app).
POLICY = {
    "policy_version": "GHN_FALLBACK_PO_V1",
    "rounding_version": "round_up_v1",
    "shop_province_code": "66",
    "spec": {
        "noi_tinh": {"base_max_kg": 3, "base_fee_vnd": 16500, "per_extra_kg_vnd": 7000},
        "lien_tinh": {"tiers": [[0.5, 25000], [1, 27000], [2, 29000], [3, 32000], [4, 35000], [5, 40000]],
                      "per_extra_kg_vnd": 7000, "per_extra_after_kg": 5},
    },
}

SHOP = "66"          # noi tinh (Dak Lak)
OTHER = "79"         # lien tinh (HCM)


def _fee(dest, w_g):
    fee, reason, detail = fb.compute_fallback_fee(POLICY, dest, w_g)
    return fee, reason, detail


# ---- noi tinh (dest == shop province) ----
def test_noi_tinh_base_le_3kg():
    for w in (1, 499, 500, 1000, 3000):
        fee, reason, _ = _fee(SHOP, w)
        assert (fee, reason) == (16500, "ok"), w


def test_noi_tinh_round_up_over_3kg():
    # >3kg: 16500 + (ceil(w_kg)-3)*7000
    assert _fee(SHOP, 3001)[0] == 16500 + 1 * 7000     # 3.001kg -> ceil 4
    assert _fee(SHOP, 4000)[0] == 16500 + 1 * 7000     # 4kg -> ceil 4
    assert _fee(SHOP, 4001)[0] == 16500 + 2 * 7000     # 4.001 -> ceil 5
    assert _fee(SHOP, 5000)[0] == 16500 + 2 * 7000     # 5kg -> ceil 5 = 30500
    assert _fee(SHOP, 10000)[0] == 16500 + 7 * 7000    # 10kg = 65500


# ---- lien tinh (dest != shop province) ----
def test_lien_tinh_tier_boundaries():
    # bac dung 338 §2 (VAT 8% gom)
    assert _fee(OTHER, 500)[0] == 25000      # 0.5kg
    assert _fee(OTHER, 1000)[0] == 27000     # 1kg
    assert _fee(OTHER, 2000)[0] == 29000     # 2kg
    assert _fee(OTHER, 3000)[0] == 32000     # 3kg
    assert _fee(OTHER, 4000)[0] == 35000     # 4kg
    assert _fee(OTHER, 5000)[0] == 40000     # 5kg


def test_lien_tinh_round_up_within_tiers():
    assert _fee(OTHER, 300)[0] == 25000      # <0.5kg -> bac 0.5 (PO chot)
    assert _fee(OTHER, 600)[0] == 27000      # 0.6 -> bac 1kg
    assert _fee(OTHER, 1500)[0] == 29000     # 1.5 -> bac 2kg
    assert _fee(OTHER, 2001)[0] == 32000     # 2.001 -> bac 3kg


def test_lien_tinh_over_5kg_per_extra():
    # >5kg: 40000 + ceil(w_kg-5)*7000
    assert _fee(OTHER, 5001)[0] == 40000 + 1 * 7000     # 5.001 -> +1
    assert _fee(OTHER, 5500)[0] == 40000 + 1 * 7000     # 5.5 -> ceil(0.5)=1
    assert _fee(OTHER, 6000)[0] == 40000 + 1 * 7000     # 6.0 -> ceil(1)=1
    assert _fee(OTHER, 10000)[0] == 40000 + 5 * 7000    # 10kg = 75000


# ---- weight tiers 337 §4.3 (ca 2 tuyen) ----
def test_weight_tier_matrix_337():
    tiers_g = [1, 499, 500, 5000, 5001, 5499, 5500, 10000, 19999, 20001]
    noi = {1: 16500, 499: 16500, 500: 16500, 5000: 30500, 5001: 37500, 5499: 37500,
           5500: 37500, 10000: 65500, 19999: 135500, 20001: 142500}
    lien = {1: 25000, 499: 25000, 500: 25000, 5000: 40000, 5001: 47000, 5499: 47000,
            5500: 47000, 10000: 75000, 19999: 145000, 20001: 152000}
    for w in tiers_g:
        assert _fee(SHOP, w)[0] == noi[w], ("noi", w, _fee(SHOP, w)[0])
        assert _fee(OTHER, w)[0] == lien[w], ("lien", w, _fee(OTHER, w)[0])


# ---- fail-closed (338 §3) — KHONG bao 0d ----
def test_weight_missing_fail_closed():
    for w in (None, 0, -5):
        fee, reason, detail = _fee(SHOP, w)
        assert fee is None and reason == "weight_missing" and detail == {}


def test_province_unclassified_fail_closed():
    for dest in (None, ""):
        fee, reason, detail = _fee(dest, 600)
        assert fee is None and reason == "province_unclassified" and detail == {}


def test_fee_never_zero_when_computed():
    for dest in (SHOP, OTHER):
        for w in (1, 500, 5000, 10000, 20001):
            fee, reason, _ = _fee(dest, w)
            assert reason == "ok" and fee and fee > 0


# ---- snapshot detail (audit) ----
def test_detail_fields_noi_tinh():
    _, _, d = _fee(SHOP, 2000)
    assert d["quote_source"] == "fallback_policy"
    assert d["policy_version"] == "GHN_FALLBACK_PO_V1"
    assert d["rounding_version"] == "round_up_v1"
    assert d["route_class"] == "noi_tinh"
    assert d["chargeable_weight_g"] == 2000
    assert d["weight_basis"] == "real_weight"


def test_detail_route_class_lien_tinh():
    _, _, d = _fee(OTHER, 2000)
    assert d["route_class"] == "lien_tinh" and d["chargeable_weight_g"] == 2000


def test_shop_province_from_policy_not_hardcoded():
    # doi shop province trong policy -> dest cu thanh lien tinh (khong hard-code '66' trong logic)
    p = {**POLICY, "shop_province_code": "79"}
    fee, reason, d = fb.compute_fallback_fee(p, "66", 2000)
    assert reason == "ok" and d["route_class"] == "lien_tinh" and fee == 29000
