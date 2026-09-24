"""CA Directive 379 — candidate map v2 (du lieu tong hop, OFFLINE)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import ghn_map_candidate_v2 as C  # noqa: E402

sys.path.pop(0)

DIST = [{"DistrictID": 10, "ProvinceID": 1, "DistrictName": "Q1"}, {"DistrictID": 20, "ProvinceID": 1, "DistrictName": "Q2"},
        {"DistrictID": 30, "ProvinceID": 1, "DistrictName": "Q3"}]
WARD = [{"WardCode": "500", "DistrictID": 10, "WardName": "Xã Bê"}, {"WardCode": "90", "DistrictID": 10, "WardName": "Xã A"},
        {"WardCode": "1A01", "DistrictID": 30, "WardName": "Xã Chữ"}, {"WardCode": "1A02", "DistrictID": 30, "WardName": "Xã Chữ 2"},
        {"WardCode": "700", "DistrictID": 20, "WardName": "Xã Đắk Na"}, {"WardCode": "701", "DistrictID": 20, "WardName": "Xã Đắk Sao"},
        {"WardCode": "800", "DistrictID": 20, "WardName": "Xã Rơ Kơi"}, {"WardCode": "400712", "DistrictID": 10, "WardName": "Xã V1"}]


def _snap(tmp_path):
    d = tmp_path / "snap"
    d.mkdir()
    for n, rows in (("provinces", [{"ProvinceID": 1, "ProvinceName": "T"}]), ("districts", DIST), ("wards", WARD)):
        (d / f"{n}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return str(d)


def _r(wc, cls, **kw):
    base = {"province_code": "66", "ward_code": wc, "ward_name": kw.pop("name", "Xã X"), "province_name": "T",
            "self_zone": kw.pop("self_zone", False), "classification": cls, "aliases": kw.pop("aliases", []),
            "scope_ghn_provinces": [1]}
    base.update(kw)
    return base


def _c(*keys):
    return [{"key": k} for k in keys]


RES = [
    _r("S1", "ambiguous", ambiguity="same_district", candidates=_c("10:500", "10:90")),          # chon 90 (so, khong chu)
    _r("S2", "ambiguous", ambiguity="same_district", candidates=_c("30:1A01", "30:1A02")),      # khong parse -> exception
    _r("X1", "ambiguous", ambiguity="cross_district", candidates=_c("10:500", "20:700")),       # staff
    _r("M1", "matched", basis="name_continuity", carrier_district_id=20, carrier_ward_code="701", candidates=_c("20:701")),
    _r("U1", "unmatched", name="Xã Rờ Kơi", aliases=["Xã Rờ Kơi"], diagnostic_accent_insensitive_candidates=["20:800"]),
    _r("U2", "unmatched", name="Xã Đăk Sao", aliases=["Xã Đăk Na", "Xã Đăk Sao"],
       diagnostic_accent_insensitive_candidates=["20:700", "20:701"]),                          # 2 -> exception staff
    _r("U3", "unmatched", name="Đặc khu Z"),                                                    # staff
    _r("Z1", "matched", self_zone=True, basis="name_continuity", carrier_district_id=10, carrier_ward_code="500"),
    _r("V1", "ambiguous", ambiguity="same_district", candidates=_c("10:90", "10:400712")),      # v1 giu 400712
]
V1 = [{"province_code": "66", "ward_code": "V1", "carrier_district_id": 10, "carrier_ward_code": "400712"}]


def test_states_and_rows(tmp_path):
    snap = _snap(tmp_path)
    states, rows = C.build(RES, snap, V1, rule="v2")
    s = {x["ward_code"]: x for x in states}
    assert s["S1"]["state"] == "mapped_same_district" and s["S1"]["selected"] == "10:90"       # so nho nhat, khong theo chuoi
    assert s["S2"]["state"] == "exception" and s["S2"]["reason"] == "ward_code_not_numeric_po_rule_undefined"
    assert s["X1"]["state"] == "staff_required"
    assert s["M1"]["state"] == "mapped_matched_v1"
    assert s["U1"]["state"] == "mapped_spelling" and s["U1"]["selected"] == "20:800"
    assert s["U2"]["state"] == "exception" and s["U2"]["reason"] == "spelling_not_unique_keep_staff"
    assert s["U3"]["state"] == "staff_required"
    assert s["Z1"]["state"] == "self_delivery"
    assert s["V1"]["state"] == "mapped_existing_v1" and s["V1"]["selected"] == "10:400712"
    assert s["V1"]["same_district_rule_would_pick"] == "10:90"                                  # bao cao, KHONG remap
    mapped = {r["ward_code"] for r in rows}
    assert mapped == {"S1", "M1", "U1", "V1"}                                                   # staff/self/exception: khong row
    assert C.verify(states, rows, snap, V1) == []


def test_spelling_recompute_must_equal_d377(tmp_path):
    bad = [_r("U9", "unmatched", name="Xã Rờ Kơi", aliases=["Xã Rờ Kơi"], diagnostic_accent_insensitive_candidates=["20:701"])]
    states, rows = C.build(bad, _snap(tmp_path), [], rule="v2")
    assert states[0]["state"] == "exception" and states[0]["reason"] == "spelling_recompute_differs_from_d377" and not rows


def test_same_district_recheck_against_snapshot(tmp_path):
    lie = [_r("S9", "ambiguous", ambiguity="same_district", candidates=_c("10:500", "20:700"))]   # thuc ra khac quan
    states, rows = C.build(lie, _snap(tmp_path), [], rule="v2")
    assert states[0]["state"] == "exception" and not rows


def test_v21_adds_only_string_sort_and_spelling_continuity(tmp_path):
    """Amendment 380: S2 (WardCode chu) -> nho nhat theo chuoi; U2 -> continuity duy nhat; phan con lai GIONG v2."""
    snap = _snap(tmp_path)
    s2, r2 = C.build(RES, snap, V1, rule="v2")
    s21, r21 = C.build(RES, snap, V1, rule="v2.1")
    a = {x["ward_code"]: x for x in s21}
    assert a["S2"]["state"] == "mapped_same_district_string" and a["S2"]["selected"] == "30:1A01"
    assert a["S2"]["reason"] == "po_same_district_lowest_ward_code_string"
    assert a["U2"]["state"] == "mapped_spelling_continuity" and a["U2"]["selected"] == "20:701"   # Đắk Sao trung ten
    assert a["V1"]["selected"] == "10:400712"                                                    # Record 367 van thang
    old = {x["ward_code"]: (x["carrier_district_id"], x["carrier_ward_code"]) for x in r2}
    new = {x["ward_code"]: (x["carrier_district_id"], x["carrier_ward_code"]) for x in r21}
    assert set(new) - set(old) == {"S2", "U2"} and all(new[k] == v for k, v in old.items())      # chi THEM, khong doi
    assert C.verify(s21, r21, snap, V1) == []


def test_v21_spelling_without_continuity_stays_staff(tmp_path):
    nb = [_r("U8", "unmatched", name="Xã Măng Bút", aliases=["Xã Đăk Na", "Xã Đăk Sao"],
             diagnostic_accent_insensitive_candidates=["20:700", "20:701"])]
    states, rows = C.build(nb, _snap(tmp_path), [], rule="v2.1")
    assert states[0]["state"] == "exception" and states[0]["continuity_hits"] == [] and not rows


def test_main_diff_vs_baseline(tmp_path):
    snap = _snap(tmp_path)
    res = tmp_path / "res.jsonl"
    res.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in RES), encoding="utf-8")
    v1 = tmp_path / "v1.json"
    v1.write_text(json.dumps(V1), encoding="utf-8")
    for f in ("adm.json", "lin.json"):
        (tmp_path / f).write_text("{}", encoding="utf-8")
    base = ["--results", str(res), "--snapshot", snap, "--v1", str(v1), "--admin", str(tmp_path / "adm.json"),
            "--lineage", str(tmp_path / "lin.json")]
    assert C.main(base + ["--rule", "v2", "--out", str(tmp_path / "o2")]) == 0
    assert C.main(base + ["--rule", "v2.1", "--out", str(tmp_path / "o21"),
                          "--baseline", str(tmp_path / "o2" / "candidate_rows.json")]) == 0
    d = json.loads((tmp_path / "o21" / "diff_vs_baseline.json").read_text(encoding="utf-8"))
    assert [x["ward_code"] for x in d["added"]] == ["S2", "U2"] and d["removed"] == [] and d["changed"] == []
