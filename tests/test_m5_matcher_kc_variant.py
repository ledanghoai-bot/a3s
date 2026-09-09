"""M5 matcher k/c variant — unit tests (logic thuan). CA Directive 258 + Amendments 259/260.

Augment alias kind 'orthographic_kc_v1' den matcher nhu alias (resolver da merge). Amendment 260:
- positive: input k-variant ('Krong Pak'/'Ea Knuek') -> AUTO_VERIFIED (tier 0.96 < canonical 1.00),
  method 'current', rule 'orthographic_kc' de audit phan biet (KHONG gia danh canonical/accentless).
- canonical/accentless van uu tien; province k-cuoi hop le ('Dak Lak') KHONG bi bien doi.
- negative: intra-ambiguous -> staff/clarify; wrong-province scope -> hierarchy conflict; augment KHONG lan
  at current canonical (canonical thang khi collision).
"""
from app.services.address import matcher as m

# 2-tier (province|ward) mirroring dataset thuc. P66 = 'Tinh Dak Lak' (canonical k-cuoi HOP LE).
_UNITS = [
    {"level": "province", "code": "66", "name": "Tỉnh Đắk Lắk", "parent_code": None},
    {"level": "province", "code": "95", "name": "Tỉnh Bạc Liêu", "parent_code": None},
    {"level": "ward", "code": "24490", "name": "Xã Krông Pắc", "parent_code": "66"},   # -> 'xa krong pac'
    {"level": "ward", "code": "24505", "name": "Xã Ea Knuếc", "parent_code": "66"},    # -> 'xa ea knuec'
    {"level": "ward", "code": "24999", "name": "Xã Đắk Sắk", "parent_code": "66"},     # -> 'xa dak sak' (k-cuoi hop le)
]
# augment batch: c$->k variant, kind 'orthographic_kc_v1' (auto tier 0.96). Chi cho ward c-cuoi an toan.
_AUG = [
    {"unit_code": "24490", "alias_name": "xa krong pak", "alias_kind": "orthographic_kc_v1"},
    {"unit_code": "24505", "alias_name": "xa ea knuek", "alias_kind": "orthographic_kc_v1"},
]


def test_variant_krong_pak_auto_verified():
    r = m.resolve(_UNITS, _AUG, province="Đắk Lắk", district=None, ward="Krong Pak")
    assert r["ward_code"] == "24490"
    assert r["status"] == "auto_verified" and r["method"] == "current"
    assert r["confidence"] == 0.96                                   # auto tier, < canonical 1.00
    assert "orthographic_kc:ward" in r["rules_applied"]              # audit attribution (§3.3)


def test_variant_ea_knuek_auto_verified():
    r = m.resolve(_UNITS, _AUG, province="Dak Lak", district=None, ward="Ea Knuek")
    assert r["ward_code"] == "24505" and r["status"] == "auto_verified"
    assert "orthographic_kc:ward" in r["rules_applied"]


def test_variant_kind_distinct_not_accentless():
    # kind rieng 'orthographic_kc_v1' xuat hien trong candidates (phan biet canonical/accentless) — §3.3.
    r = m.resolve(_UNITS, _AUG, province="Dak Lak", district=None, ward="Krong Pak")
    ward_cands = [c for c in r["candidates"] if c["level"] == "ward" and c["code"] == "24490"]
    assert ward_cands and ward_cands[0]["kind"] == "orthographic_kc_v1"
    assert r["confidence"] < m._KIND_SCORE["canonical"]             # khong bang canonical
    assert r["confidence"] >= 0.95                                  # dung auto tier


def test_canonical_accentless_still_auto_and_full_confidence():
    # 'Krong Pac' (accentless cua canonical 'Krông Pắc') VAN auto_verified qua current canonical (1.0).
    r = m.resolve(_UNITS, _AUG, province="Dak Lak", district=None, ward="Krong Pac")
    assert r["ward_code"] == "24490" and r["status"] == "auto_verified" and r["method"] == "current"
    assert "orthographic_kc:ward" not in r["rules_applied"]         # dung canonical, khong phai augment


def test_valid_k_final_province_unchanged():
    r = m.resolve(_UNITS, _AUG, province="Dak Lak", district=None, ward=None)
    assert r["province_code"] == "66" and r["status"] == "auto_verified"


def test_valid_k_final_ward_unchanged():
    # 'Dak Sak' (ward k-cuoi hop le) van auto_verified; upgrade mot chieu c->k khong dung toi.
    r = m.resolve(_UNITS, _AUG, province="Dak Lak", district=None, ward="Dak Sak")
    assert r["ward_code"] == "24999" and r["status"] == "auto_verified"
    assert "orthographic_kc:ward" not in r["rules_applied"]


def test_wrong_province_scope_variant_rejected():
    # Krong Pak nhung province Bac Lieu (95) — W parent 66 -> hierarchy conflict, KHONG false-positive bind.
    r = m.resolve(_UNITS, _AUG, province="Bạc Liêu", district=None, ward="Krong Pak")
    assert r["status"] == "needs_staff_review"
    assert any(x.startswith("hierarchy_conflict") for x in r["rules_applied"])


def test_intra_ambiguous_variant_clarifies():
    # 2 augment alias trung key (intra-ambiguous, seed DA loai) -> one_to_many -> staff/clarify, KHONG auto.
    units = _UNITS + [{"level": "ward", "code": "24777", "name": "Xã Krông Pặc", "parent_code": "66"}]
    aug = _AUG + [{"unit_code": "24777", "alias_name": "xa krong pak", "alias_kind": "orthographic_kc_v1"}]
    r = m.resolve(units, aug, province="Dak Lak", district=None, ward="Krong Pak")
    assert r["status"] == "needs_staff_review"
    assert any(x.startswith("one_to_many") for x in r["rules_applied"])


def test_current_canonical_beats_augment_variant():
    # Neu augment variant trung CANONICAL hien hanh cua unit KHAC (seed DA loai) -> canonical THANG (§3.2).
    units = _UNITS + [{"level": "ward", "code": "25000", "name": "Xã Krong Pak", "parent_code": "66"}]  # canonical 'xa krong pak'
    r = m.resolve(units, _AUG, province="Dak Lak", district=None, ward="Krong Pak")
    assert r["ward_code"] == "25000"                                # current canonical thang augment
    assert r["status"] == "auto_verified"
    assert any(x.startswith("current_over_variant") for x in r["rules_applied"])
    assert "orthographic_kc:ward" not in r["rules_applied"]         # khong ap augment khi canonical thang
