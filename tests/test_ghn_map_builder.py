"""CA Directive 377 §4 — map builder offline (du lieu tong hop, KHONG DB/network)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import ghn_map_builder as B  # noqa: E402

sys.path.pop(0)

LINEAGE = {"version": "t", "lineage": {"66": ["Đắk Lắk", "Phú Yên"], "52": ["Gia Lai", "Bình Định"], "99": ["Không Có"]}}
GPROV = [{"ProvinceID": 210, "ProvinceName": "Đắk Lắk"}, {"ProvinceID": 211, "ProvinceName": "Phú Yên"},
         {"ProvinceID": 207, "ProvinceName": "Gia Lai"}, {"ProvinceID": 206, "ProvinceName": "Bình Định"},
         {"ProvinceID": 900, "ProvinceName": "Test Tỉnh"}]
GDIST = [{"DistrictID": 1954, "ProvinceID": 210, "DistrictName": "Huyện Krông Pắc"},
         {"DistrictID": 1552, "ProvinceID": 210, "DistrictName": "Thành phố Buôn Ma Thuột"},
         {"DistrictID": 1700, "ProvinceID": 211, "DistrictName": "Thành phố Tuy Hòa"},
         {"DistrictID": 1546, "ProvinceID": 207, "DistrictName": "Thành phố Pleiku"}]
GWARD = [{"WardCode": "400701", "DistrictID": 1954, "WardName": "Thị trấn Phước An"},
         {"WardCode": "400710", "DistrictID": 1954, "WardName": "Xã Ea Yông"},
         {"WardCode": "400105", "DistrictID": 1552, "WardName": "Phường Tân Lập"},
         {"WardCode": "400199", "DistrictID": 1552, "WardName": "Phường Ea Tam"},
         {"WardCode": "500101", "DistrictID": 1700, "WardName": "Phường 1"},
         {"WardCode": "500102", "DistrictID": 1700, "WardName": "Xã An Phú"},
         {"WardCode": "380104", "DistrictID": 1546, "WardName": "Phường Hoa Lư"},
         {"WardCode": "400800", "DistrictID": 1954, "WardName": "Xã Hoa Dong"}]          # GHN khong dau
ADMIN = {"dataset_version": "T", "provinces": [{"code": "66", "name": "Tỉnh Đắk Lắk"}, {"code": "52", "name": "Tỉnh Gia Lai"},
                                                  {"code": "99", "name": "Tỉnh Ma"}],
         "wards": [{"code": "A1", "name": "Xã Krông Pắc", "parent_code": "66"},      # 2 ung vien cung quan
                   {"code": "A2", "name": "Phường Tân Lập", "parent_code": "66"},    # continuity
                   {"code": "A3", "name": "Phường Tuy Hòa", "parent_code": "66"},    # phuong cu o Phu Yen (tinh gop)
                   {"code": "A4", "name": "Xã Hòa Đông", "parent_code": "66"},       # GHN khong dau -> unmatched + diag
                   {"code": "A5", "name": "Phường Buôn Ma Thuột", "parent_code": "66"},  # cross-district
                   {"code": "B1", "name": "Phường Pleiku", "parent_code": "52"},     # single candidate
                   {"code": "Z1", "name": "Xã Ma", "parent_code": "99"}],            # lineage khong resolve
         "legacy_aliases": {"A1": [{"name": "Thị trấn Phước An"}, {"name": "Xã Ea Yông"}],
                            "A2": [{"name": "Phường Tân Lập"}],
                            "A3": [{"name": "Phường 1"}],
                            "A4": [{"name": "Xã Hòa Đông"}],
                            "A5": [{"name": "Phường Tân Lập"}, {"name": "Phường 1"}],
                            "B1": [{"name": "Phường Hoa Lư"}],
                            "Z1": [{"name": "Xã Ma"}]},
         "self_zone_allowlist": ["66/A2"]}


def _snap(tmp_path):
    d = tmp_path / "snap"
    d.mkdir()
    for n, rows in (("provinces", GPROV), ("districts", GDIST), ("wards", GWARD)):
        (d / f"{n}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return str(d)


def _by(results):
    return {r["ward_code"]: r for r in results}


def test_classification_and_scope(tmp_path):
    results, summary, resolution, empirical = B.build(ADMIN, _snap(tmp_path), LINEAGE)
    r = _by(results)
    assert r["A1"]["classification"] == "ambiguous" and r["A1"]["ambiguity"] == "same_district"
    assert "carrier_ward_code" not in r["A1"]                                   # KHONG tu chon
    assert r["A2"]["classification"] == "matched" and r["A2"]["basis"] == "name_continuity"
    assert r["A2"]["carrier_ward_code"] == "400105" and r["A2"]["self_zone"] is True
    # phuong cu thuoc Phu Yen (tinh gop vao Dak Lak) van tim thay nho lineage
    assert r["A3"]["classification"] == "matched" and r["A3"]["carrier_district_id"] == 1700
    assert r["A5"]["classification"] == "ambiguous" and r["A5"]["ambiguity"] == "cross_district"
    assert r["B1"]["classification"] == "matched" and r["B1"]["basis"] == "single_candidate"
    assert r["Z1"]["classification"] == "invalid-source"


def test_accent_insensitive_is_diagnostic_only(tmp_path):
    results, *_ = B.build(ADMIN, _snap(tmp_path), LINEAGE)
    a4 = _by(results)["A4"]
    assert a4["classification"] == "unmatched"                                  # giu dau: KHONG match "Hoa Dong"
    assert a4["diagnostic_accent_insensitive_candidates"] == ["1954:400800"]


def test_lineage_resolution_and_unused(tmp_path):
    _, summary, resolution, _ = B.build(ADMIN, _snap(tmp_path), LINEAGE)
    assert [x["ghn_province_id"] for x in resolution["66"]] == [210, 211]
    assert summary["lineage"]["issues"] == [{"new_province": "99", "old_name": "Không Có", "ghn_matches": []}]
    assert [p["ProvinceID"] for p in summary["lineage"]["ghn_provinces_not_in_lineage"]] == [900]
    assert summary["totals"]["wards"] == 7 and summary["totals"]["matched"] == 3


def test_empirical_lineage_agrees(tmp_path):
    _, _, _, empirical = B.build(ADMIN, _snap(tmp_path), LINEAGE)
    e = {x["ghn_province_id"]: x for x in empirical}
    assert e[211]["dominant_new"] == "66" and e[211]["agree"] is True          # Phu Yen -> Dak Lak moi


def test_main_writes_outputs_no_db(tmp_path):
    adm = tmp_path / "admin.json"
    adm.write_text(json.dumps(ADMIN, ensure_ascii=False), encoding="utf-8")
    lin = tmp_path / "lin.json"
    lin.write_text(json.dumps(LINEAGE, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    assert B.main(["--admin", str(adm), "--snapshot", _snap(tmp_path), "--lineage", str(lin), "--out", str(out)]) == 0
    for f in ("results.jsonl", "summary.json", "ambiguous_for_PO.csv", "unmatched_for_PO.csv", "invalid_source.csv",
              "matched.csv", "lineage_resolution.json", "lineage_empirical.json"):
        assert (out / f).exists(), f
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert set(s["inputs_sha256"]) == {"admin_export", "lineage", "snapshot/provinces.json",
                                       "snapshot/districts.json", "snapshot/wards.json"}
