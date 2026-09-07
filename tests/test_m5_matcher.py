"""M5 Phase 2 — Address matcher unit tests (logic thuan). CA Directive 108.

Phu: current exact/accentless auto; legacy -> customer confirmation; one-to-many -> staff; hierarchy conflict
-> staff; missing province / no candidate -> failed; as_of effective range; alias khong override canonical.
"""
import datetime as dt

from app.services.address import matcher as m


def _ds():
    units = [
        {"level": "province", "code": "P01", "name": "Cà Mau", "parent_code": None},
        {"level": "province", "code": "P02", "name": "Bạc Liêu", "parent_code": None},
        {"level": "district", "code": "D01", "name": "Đầm Dơi", "parent_code": "P01"},
        {"level": "district", "code": "D02", "name": "Hòa Bình", "parent_code": "P02"},
        {"level": "ward", "code": "W01", "name": "Tân Duyệt", "parent_code": "D01"},
    ]
    aliases = [
        {"unit_code": "P01", "alias_name": "Ca Mau", "alias_kind": "accentless"},
        {"unit_code": "P01", "alias_name": "Minh Hải", "alias_kind": "legacy"},
        {"unit_code": "D01", "alias_name": "Dam Doi", "alias_kind": "accentless"},
    ]
    return units, aliases


def test_current_exact_auto():
    u, a = _ds()
    r = m.resolve(u, a, province="Cà Mau", district="Đầm Dơi", ward="Tân Duyệt")
    assert r["status"] == "auto_verified" and r["method"] == "current"
    assert (r["province_code"], r["district_code"], r["ward_code"]) == ("P01", "D01", "W01")
    assert r["confidence"] == 1.0


def test_accentless_auto():
    u, a = _ds()
    r = m.resolve(u, a, province="Ca Mau", district="Dam Doi", ward=None)
    assert r["status"] == "auto_verified" and r["method"] == "current"
    assert r["province_code"] == "P01" and r["confidence"] >= 0.95


def test_legacy_needs_customer_confirmation():
    u, a = _ds()
    r = m.resolve(u, a, province="Minh Hải", district=None, ward=None)
    assert r["method"] == "legacy_mapping"
    assert r["status"] == "needs_customer_confirmation"
    assert r["province_code"] == "P01" and 0.80 <= r["confidence"] < 0.95


def test_one_to_many_blocks_auto_staff():
    u, a = _ds()
    u.append({"level": "province", "code": "P03", "name": "Cà Mau", "parent_code": None})  # trung canonical
    r = m.resolve(u, a, province="Cà Mau", district=None, ward=None)
    assert r["status"] == "needs_staff_review"
    assert any(x.startswith("one_to_many") for x in r["rules_applied"])


def test_hierarchy_conflict_staff():
    u, a = _ds()
    r = m.resolve(u, a, province="Cà Mau", district="Hòa Bình", ward=None)  # D02 parent P02 != P01
    assert r["status"] == "needs_staff_review"
    assert any(x.startswith("hierarchy_conflict") for x in r["rules_applied"])


def test_missing_province_failed():
    u, a = _ds()
    r = m.resolve(u, a, province=None, district="Đầm Dơi", ward=None)
    assert r["status"] == "failed" and "missing_province" in r["rules_applied"]


def test_no_candidate_failed():
    u, a = _ds()
    r = m.resolve(u, a, province="Không Có Tỉnh Này", district=None, ward=None)
    assert r["status"] == "failed"
    assert any(x.startswith("no_candidate:province") for x in r["rules_applied"])


def test_as_of_effective_range():
    u, a = _ds()
    u.append({"level": "province", "code": "P09", "name": "Sóc Trăng", "parent_code": None,
              "effective_from": dt.date(2020, 1, 1), "effective_to": dt.date(2025, 6, 30)})
    # sau khi het hieu luc -> khong tim thay
    r_after = m.resolve(u, a, province="Sóc Trăng", district=None, ward=None, as_of=dt.date(2025, 7, 1))
    assert r_after["status"] == "failed"
    # trong hieu luc -> tim thay
    r_in = m.resolve(u, a, province="Sóc Trăng", district=None, ward=None, as_of=dt.date(2025, 6, 1))
    assert r_in["province_code"] == "P09"


def test_legacy_alias_canonical_collision_ambiguous():
    # CA Review 126: alias(P02) trung canonical cua P01 -> GIU CA HAI -> one_to_many -> needs_staff_review
    # (canonical KHONG am tham thang, khong auto-select, khong ha xuong customer confirmation).
    u, a = _ds()
    a.append({"unit_code": "P02", "alias_name": "Cà Mau", "alias_kind": "legacy"})
    r = m.resolve(u, a, province="Cà Mau", district=None, ward=None)
    assert r["status"] == "needs_staff_review"
    assert any(x.startswith("one_to_many") for x in r["rules_applied"])
    assert r["province_code"] is None


# --- M5 upgrade (Directive 214 §6.A): tien to hanh chinh + viet tat ---

def _ds_pref():
    """Fixture mo phong dataset v2 THAT: ten CO tien to hanh chinh ("Tinh ...", "Phuong ...")."""
    units = [
        {"level": "province", "code": "66", "name": "Tỉnh Đắk Lắk", "parent_code": None},
        {"level": "province", "code": "44", "name": "Tỉnh Khác", "parent_code": None},
        {"level": "ward", "code": "24169", "name": "Phường Ea Kao", "parent_code": "66"},
        {"level": "ward", "code": "24121", "name": "Phường Tân Lập", "parent_code": "66"},
        {"level": "ward", "code": "19462", "name": "Xã Tân Lập", "parent_code": "44"},
    ]
    aliases = [{"unit_code": "24169", "alias_name": "Xã Ea Kao", "alias_kind": "legacy"}]
    return units, aliases


def test_prod_regression_bare_prov_abbrev_ward_auto():
    # Chinh ca that lam order #4 fail: "Dak Lak" (thieu "Tinh") + "P. Ea Kao" (viet tat) -> gio AUTO.
    u, a = _ds_pref()
    r = m.resolve(u, a, province="Dak Lak", district=None, ward="P. Ea Kao")
    assert r["status"] == "auto_verified" and r["method"] == "current"
    assert r["province_code"] == "66" and r["ward_code"] == "24169"
    assert r["confidence"] == 1.0


def test_prefixed_full_still_auto():
    u, a = _ds_pref()
    r = m.resolve(u, a, province="Tỉnh Đắk Lắk", district=None, ward="Phường Ea Kao")
    assert r["status"] == "auto_verified" and r["ward_code"] == "24169"


def test_abbrev_province_tinh():
    u, a = _ds_pref()
    r = m.resolve(u, a, province="T. Đắk Lắk", district=None, ward=None)
    assert r["status"] == "auto_verified" and r["province_code"] == "66"


def test_specificity_preserved_not_downgraded():
    # "Phuong Tan Lap" phai khop DUNG 1 phuong (24121), KHONG roi xuong "tan lap" gay one_to_many
    # voi "Xa Tan Lap" (19462) o tinh khac.
    u, a = _ds_pref()
    r = m.resolve(u, a, province="Đắk Lắk", district=None, ward="Phường Tân Lập")
    assert r["status"] == "auto_verified" and r["ward_code"] == "24121"
    assert not any(x.startswith("one_to_many") for x in r["rules_applied"])


def test_old_name_alias_needs_confirmation():
    # Ten cu "Xa Ea Kao" -> mapped nhung method legacy -> needs_customer_confirmation (khong auto).
    u, a = _ds_pref()
    r = m.resolve(u, a, province="Đắk Lắk", district=None, ward="Xã Ea Kao")
    assert r["method"] == "legacy_mapping" and r["status"] == "needs_customer_confirmation"
    assert r["ward_code"] == "24169"


def test_match_keys_abbrev_families():
    # Corpus §7.3: moi ho viet tat hanh chinh -> mo rong dung + sinh dang tran.
    assert m._match_keys("T. Đắk Lắk") == ["tinh dak lak", "dak lak"]
    assert m._match_keys("TP. Hà Nội") == ["thanh pho ha noi", "ha noi"]
    assert m._match_keys("P. Ea Kao") == ["phuong ea kao", "ea kao"]
    assert m._match_keys("Q. 1") == ["quan 1", "1"]
    assert m._match_keys("H. Đầm Dơi") == ["huyen dam doi", "dam doi"]
    assert m._match_keys("X. Tân Lập") == ["xa tan lap", "tan lap"]
    # Ten tran (khong tien to) -> 1 key duy nhat; ten thuong bat dau bang tu 2 ky tu khong bi coi la viet tat
    assert m._match_keys("Đắk Lắk") == ["dak lak"]
    assert m._match_keys("Ea Kao") == ["ea kao"]


def test_bare_ambiguous_same_parent_staff():
    # Hai phuong cung ten tran + cung parent -> input tran -> one_to_many -> staff (khong tu chon).
    u, a = _ds_pref()
    u.append({"level": "ward", "code": "24170", "name": "Xã Ea Kao", "parent_code": "66"})  # trung "ea kao"
    r = m.resolve(u, a, province="Đắk Lắk", district=None, ward="Ea Kao")
    assert r["status"] == "needs_staff_review"
    assert any(x.startswith("one_to_many") for x in r["rules_applied"])
    assert r["ward_code"] is None


def test_duplicate_legacy_alias_stays_ambiguous():
    # CA Review 122: ten xa cu trung giua nhieu don vi -> nhieu candidate -> KHONG auto-select.
    units = [
        {"level": "province", "code": "01", "name": "Thành phố Hà Nội", "parent_code": None},
        {"level": "ward", "code": "W1", "name": "Phường A", "parent_code": "01"},
        {"level": "ward", "code": "W2", "name": "Phường B", "parent_code": "01"},
    ]
    aliases = [
        {"unit_code": "W1", "alias_name": "Xã Cũ Trùng", "alias_kind": "legacy"},
        {"unit_code": "W2", "alias_name": "Xã Cũ Trùng", "alias_kind": "legacy"},
    ]
    r = m.resolve(units, aliases, province="Thành phố Hà Nội", district=None, ward="Xã Cũ Trùng")
    assert r["status"] == "needs_staff_review"
    assert any(x.startswith("one_to_many") for x in r["rules_applied"])
    assert r["ward_code"] is None  # khong tu chon
