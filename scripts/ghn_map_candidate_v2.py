#!/usr/bin/env python3
"""CA Directive 379 — CANDIDATE production map v2 (OFFLINE, khong DB, khong network, KHONG import).

Input (checksum trong summary): ket qua builder D377 (results.jsonl), snapshot GHN production D377, admin export D377,
lineage vn_province_lineage_2025_v1 (PO chap nhan), production map v1 (Record 367).

State tung phuong Alpha3s (RULE_VERSION):
  self_delivery            5 phuong self-zone: KHONG row map (self-delivery, 0 GHN call)
  mapped_existing_v1       3 quyet dinh PO Record 367 — giu NGUYEN, khong remap
  mapped_matched_v1        builder D377 `matched` (name_continuity | single_candidate)
  mapped_same_district     D377 `same_district`: xac nhan lai MOI candidate cung DistrictID tu snapshot; chon WardCode
                           so NHO NHAT (int tang dan). WardCode khong parse duoc so / lech district -> exception (staff)
  mapped_spelling          10 unmatched co chan doan khong dau: chuan hoa spelling DA AUDIT o D377 (strip dau + d/đ, NFC,
                           ca hai phia, trong scope lineage). CHI map khi DUY NHAT 1 candidate; >1 -> exception (staff)
  staff_required           656 cross_district + 6 unmatched khong candidate: KHONG row map (quote_required/staff)
  exception                khong thoa dieu kien tren -> staff, liet ke ly do
Output: candidate_rows.json (dang carrier_address_map, CHUA import), states.jsonl (trace), cac danh sach CSV, summary.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.providers.ghn_master_data import names_of, norm_name  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ghn_map_builder import (
    strip_accents,  # noqa: E402  (CUNG ham chan doan da audit o D377)
)

RULE_VERSION = ("ghn_map_candidate_v2(v1_matched + po_same_district_lowest_ward_id + po_spelling_normalized_match_unique"
                " + po_record_367_overrides; lineage=vn_province_lineage_2025_v1)")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def build(results, snap_dir, v1_rows):
    dists = {d["DistrictID"]: d for d in load(os.path.join(snap_dir, "districts.json"))}
    wards = load(os.path.join(snap_dir, "wards.json"))
    wkey = {f"{w['DistrictID']}:{w['WardCode']}": w for w in wards}
    v1 = {(r["province_code"], r["ward_code"]): r for r in v1_rows}
    by_prov = {}
    for w in wards:
        by_prov.setdefault(dists[w["DistrictID"]]["ProvinceID"], []).append(w)

    def row(r, did, wc, reason, extra=None):
        pid = dists[did]["ProvinceID"]
        return {"province_code": r["province_code"], "ward_code": r["ward_code"], "carrier_province_id": pid,
                "carrier_district_id": did, "carrier_ward_code": str(wc), "status": "matched", "method": "staff",
                "confidence": None,
                "note": json.dumps({"reason": reason, "rule_version": RULE_VERSION, **(extra or {})},
                                   ensure_ascii=False, sort_keys=True)}

    states, rows = [], []
    for r in results:
        key = (r["province_code"], r["ward_code"])
        st = {"province_code": r["province_code"], "ward_code": r["ward_code"], "ward_name": r["ward_name"],
              "province_name": r["province_name"], "d377": r["classification"], "d377_ambiguity": r.get("ambiguity"),
              "candidates": [c["key"] for c in r.get("candidates") or []]}
        if r["self_zone"]:
            st.update(state="self_delivery", reason="self_zone_zero_ghn_call")
        elif key in v1:
            v = v1[key]
            k = f"{v['carrier_district_id']}:{v['carrier_ward_code']}"
            if k not in wkey or k not in st["candidates"]:
                st.update(state="exception", reason=f"v1_decision_not_in_snapshot_or_candidates:{k}")
            else:
                note = {}
                if r.get("ambiguity") == "same_district":
                    low = min(st["candidates"], key=lambda x: int(x.split(":")[1]))
                    note = {"same_district_rule_would_pick": low, "kept_po_decision": k}
                st.update(state="mapped_existing_v1", reason="po_record_367_kept", selected=k, **note)
                rows.append(row(r, v["carrier_district_id"], v["carrier_ward_code"], "po_record_367_kept", note))
        elif r["classification"] == "matched":
            k = f"{r['carrier_district_id']}:{r['carrier_ward_code']}"
            if k not in wkey:
                st.update(state="exception", reason="matched_key_not_in_snapshot")
            else:
                st.update(state="mapped_matched_v1", reason=f"d377_{r['basis']}", selected=k)
                rows.append(row(r, r["carrier_district_id"], r["carrier_ward_code"], f"d377_{r['basis']}"))
        elif r.get("ambiguity") == "same_district":
            cands = r["candidates"]
            dset = {wkey[c["key"]]["DistrictID"] for c in cands if c["key"] in wkey}
            missing = [c["key"] for c in cands if c["key"] not in wkey]
            nonnum = [c["key"] for c in cands if not str(c["key"].split(":")[1]).isdigit()]
            if missing or len(dset) != 1 or not cands:
                st.update(state="exception", reason=f"same_district_recheck_failed:missing={missing},districts={sorted(dset)}")
            elif nonnum:
                st.update(state="exception", reason="ward_code_not_numeric_po_rule_undefined", nonnumeric=nonnum)
            else:
                pick = sorted(cands, key=lambda c: int(c["key"].split(":")[1]))[0]
                did, wc = pick["key"].split(":")
                ex = {"candidates_sorted": [c["key"] for c in sorted(cands, key=lambda c: int(c["key"].split(":")[1]))],
                      "district_id": int(did)}
                st.update(state="mapped_same_district", reason="po_same_district_lowest_ward_id", selected=pick["key"],
                          **ex)
                rows.append(row(r, int(did), wc, "po_same_district_lowest_ward_id", ex))
        elif r["classification"] == "unmatched" and r.get("diagnostic_accent_insensitive_candidates"):
            # tinh LAI doc lap bang dung rule D377 va doi chieu voi chan doan D377
            want = {strip_accents(norm_name(x)) for x in (r.get("aliases") or []) + [r["ward_name"]] if x}
            scope = [w for pid in r.get("scope_ghn_provinces") or [] for w in by_prov.get(pid, [])]
            found = sorted(f"{w['DistrictID']}:{w['WardCode']}" for w in scope
                           if {strip_accents(n) for n in names_of(w.get("WardName"), w.get("NameExtension"))} & want)
            same_as_d377 = found == sorted(r["diagnostic_accent_insensitive_candidates"])
            ex = {"canonical_alpha3s_name": r["ward_name"], "normalized_candidates": found, "matches_d377_diag": same_as_d377}
            if not same_as_d377:
                st.update(state="exception", reason="spelling_recompute_differs_from_d377", **ex)
            elif len(found) == 1:
                did, wc = found[0].split(":")
                st.update(state="mapped_spelling", reason="po_spelling_normalized_match", selected=found[0], **ex)
                rows.append(row(r, int(did), wc, "po_spelling_normalized_match", ex))
            else:
                st.update(state="exception", reason="spelling_not_unique_keep_staff", **ex)
        elif r["classification"] == "unmatched":
            st.update(state="staff_required", reason="unmatched_no_candidate")
        elif r.get("ambiguity") == "cross_district":
            st.update(state="staff_required", reason="po_cross_district_no_map")
        else:
            st.update(state="exception", reason="khong_thuoc_nhom_nao")
        states.append(st)
    return states, rows


def verify(states, rows, snap_dir, v1_rows):
    """Tu kiem cac bat bien Directive 379 — tra danh sach loi (rong = dat)."""
    errs = []
    dists = {d["DistrictID"]: d for d in load(os.path.join(snap_dir, "districts.json"))}
    wset = {f"{w['DistrictID']}:{w['WardCode']}" for w in load(os.path.join(snap_dir, "wards.json"))}
    keys = [(x["province_code"], x["ward_code"]) for x in rows]
    if len(keys) != len(set(keys)):
        errs.append("row trung dia chi")
    for x in rows:
        if f"{x['carrier_district_id']}:{x['carrier_ward_code']}" not in wset:
            errs.append(f"row {x['ward_code']} tro toi ward khong co trong snapshot")
        if dists[x["carrier_district_id"]]["ProvinceID"] != x["carrier_province_id"]:
            errs.append(f"row {x['ward_code']} province lech")
    by = {(s["province_code"], s["ward_code"]): s for s in states}
    for s in states:
        if s["state"] in ("staff_required", "self_delivery", "exception") and (s["province_code"], s["ward_code"]) in set(keys):
            errs.append(f"{s['ward_code']} {s['state']} nhung co row map")
        if s["state"] == "mapped_same_district":
            ds = {int(c.split(":")[0]) for c in s["candidates"]}
            if len(ds) != 1 or s["selected"] != s["candidates_sorted"][0]:
                errs.append(f"{s['ward_code']} same_district vi pham")
    for v in v1_rows:
        s = by[(v["province_code"], v["ward_code"])]
        if s.get("selected") != f"{v['carrier_district_id']}:{v['carrier_ward_code']}":
            errs.append(f"v1 {v['ward_code']} bi doi")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser()
    for a in ("--results", "--snapshot", "--v1", "--admin", "--lineage", "--out"):
        ap.add_argument(a, required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    results = [json.loads(x) for x in open(a.results, encoding="utf-8")]
    v1_rows = load(a.v1)
    states, rows = build(results, a.snapshot, v1_rows)
    errs = verify(states, rows, a.snapshot, v1_rows)
    cnt = Counter(s["state"] for s in states)
    exc = Counter(s["reason"] for s in states if s["state"] == "exception")
    summary = {"rule_version": RULE_VERSION, "wards_total": len(states), "states": dict(cnt), "exception_reasons": dict(exc),
               "candidate_rows": len(rows), "rows_by_reason": dict(Counter(json.loads(x["note"])["reason"] for x in rows)),
               "verify_errors": errs,
               "inputs_sha256": {"d377_results": sha(a.results), "v1_map": sha(a.v1), "admin_export": sha(a.admin),
                                 "lineage": sha(a.lineage),
                                 **{f"snapshot/{n}": sha(os.path.join(a.snapshot, n))
                                    for n in ("provinces.json", "districts.json", "wards.json")}}}
    with open(os.path.join(a.out, "candidate_rows.json"), "w", encoding="utf-8") as fh:
        json.dump(sorted(rows, key=lambda x: (x["province_code"], x["ward_code"])), fh, ensure_ascii=False, indent=0)
    with open(os.path.join(a.out, "states.jsonl"), "w", encoding="utf-8") as fh:
        for s in states:
            fh.write(json.dumps(s, ensure_ascii=False, sort_keys=True) + "\n")
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1, sort_keys=True)
    cols = ["province_code", "province_name", "ward_code", "ward_name", "state", "reason", "selected", "candidates"]
    for name, pred in (("same_district_683.csv", lambda s: s["d377_ambiguity"] == "same_district"),
                       ("cross_district_656.csv", lambda s: s["d377_ambiguity"] == "cross_district"),
                       ("unmatched_16.csv", lambda s: s["d377"] == "unmatched"),
                       ("exceptions.csv", lambda s: s["state"] == "exception")):
        with open(os.path.join(a.out, name), "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for s in states:
                if pred(s):
                    w.writerow({**s, "candidates": " | ".join(s["candidates"])})
    print(json.dumps({k: summary[k] for k in ("states", "exception_reasons", "candidate_rows", "rows_by_reason",
                                               "verify_errors")}, ensure_ascii=False))
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
