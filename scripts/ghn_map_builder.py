#!/usr/bin/env python3
"""CA Directive 377 §4 — MAP BUILDER OFFLINE: dia chi hanh chinh Alpha3s (34 tinh, 2 cap) -> district/ward GHN legacy.

HOAN TOAN OFFLINE: khong DB, khong network, KHONG ghi carrier_address_map hay bang/config nao. Chi doc 3 input co
checksum va ghi bao cao ra thu muc output.

Input (versioned):
  --admin     admin_export.json  (scripts/ghn_map_builder_export_admin.py: tinh/phuong/alias legacy/self-zone)
  --snapshot  thu muc snapshot GHN production (provinces.json, districts.json, wards.json, report.json)
  --lineage   scripts/data/vn_province_lineage_2025_v1.json (tinh moi -> tinh cu, NQ 202/2025/QH15)

Quy tac (RULE_VERSION):
  - Chuan hoa ten = norm_name G1 (NFC, casefold, bo tien to hanh chinh, GIU DAU) — ap dung NHAT QUAN hai phia.
  - Pham vi ung vien cua 1 phuong moi = cac phuong GHN thuoc cac tinh cu trong lineage cua tinh moi.
  - Quyet dinh = decide_mapping G1: (1) ten hien hanh trung 1 alias va dung 1 phuong GHN -> matched/name_continuity;
    (2) tong ung vien dung 1 -> matched/single_candidate; (3) >1 -> ambiguous; (4) 0 -> unmatched.
  - KHONG tu chon trong nhom ambiguous, KHONG tu dat alias/ID. Chan doan "khong dau" chi de PO xu ly, KHONG dung de match.
Phan loai: matched | ambiguous (same_district | cross_district) | unmatched | invalid-source.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import unicodedata
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.providers.ghn_master_data import (  # noqa: E402
    decide_mapping,
    names_of,
    norm_name,
)

RULE_VERSION = "ghn_map_builder_v1(g1_decide_mapping+norm_name_keep_diacritics+lineage_scope)"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def pnorm(s):
    """Ten tinh: norm_name + coi '-' nhu khoang trang (vd 'Bà Rịa - Vũng Tàu')."""
    return " ".join(norm_name(s).replace("-", " ").split())


def strip_accents(s):
    t = unicodedata.normalize("NFD", s)
    return unicodedata.normalize("NFC", "".join(ch for ch in t if unicodedata.category(ch) != "Mn")).replace("đ", "d")


def build(admin, snap_dir, lineage):
    gprov = load(os.path.join(snap_dir, "provinces.json"))
    gdist = load(os.path.join(snap_dir, "districts.json"))
    gward = load(os.path.join(snap_dir, "wards.json"))
    dist_by_id = {d["DistrictID"]: d for d in gdist}

    # ---------- 1. resolve lineage: ten tinh cu -> DUNG 1 ProvinceID GHN
    pnames = {p["ProvinceID"]: {pnorm(x) for x in ({p.get("ProvinceName")} | set(p.get("NameExtension") or []))
                                if x} for p in gprov}
    resolution, lineage_issues, used = {}, [], Counter()
    for ncode, olds in lineage["lineage"].items():
        resolution[ncode] = []
        for old in olds:
            hits = [pid for pid, ns in pnames.items() if pnorm(old) in ns]
            if len(hits) != 1:
                lineage_issues.append({"new_province": ncode, "old_name": old, "ghn_matches": hits})
                continue
            resolution[ncode].append({"old_name": old, "ghn_province_id": hits[0],
                                      "ghn_name": next(p["ProvinceName"] for p in gprov if p["ProvinceID"] == hits[0])})
            used[hits[0]] += 1
    dup_used = [pid for pid, n in used.items() if n > 1]
    unused = [{"ProvinceID": p["ProvinceID"], "ProvinceName": p["ProvinceName"],
               "districts": sum(1 for d in gdist if d["ProvinceID"] == p["ProvinceID"])}
              for p in gprov if p["ProvinceID"] not in used]

    # ---------- 2. index phuong GHN theo tinh
    wards_by_prov = defaultdict(list)
    for w in gward:
        d = dist_by_id.get(w["DistrictID"])
        if not d:
            continue
        wards_by_prov[d["ProvinceID"]].append({
            "district_id": w["DistrictID"], "ward_code": str(w["WardCode"]),
            "names": names_of(w.get("WardName"), w.get("NameExtension")),
            "ward_name": w.get("WardName"), "district_name": d.get("DistrictName")})

    # ---------- 3. empirical lineage: alias (ten phuong cu) cua tinh moi roi vao tinh GHN nao (toan quoc)
    name_to_prov = defaultdict(set)
    for pid, ws in wards_by_prov.items():
        for w in ws:
            for n in w["names"]:
                name_to_prov[n].add(pid)
    prov_new_of_ward = {w["code"]: w["parent_code"] for w in admin["wards"]}
    hits = defaultdict(Counter)                           # ghn_pid -> Counter(new_province)
    for wcode, als in admin["legacy_aliases"].items():
        npc = prov_new_of_ward.get(wcode)
        for a in als:
            ps = name_to_prov.get(norm_name(a["name"]), set())
            if len(ps) == 1:                              # ten cu duy nhat toan quoc -> tin hieu sach
                hits[next(iter(ps))][npc] += 1
    lineage_of_ghn = {r["ghn_province_id"]: ncode for ncode, rs in resolution.items() for r in rs}
    empirical = []
    for p in gprov:
        c = hits.get(p["ProvinceID"], Counter())
        dom, dn = (c.most_common(1)[0] if c else (None, 0))
        tot = sum(c.values())
        empirical.append({"ghn_province_id": p["ProvinceID"], "ghn_name": p["ProvinceName"],
                          "lineage_new": lineage_of_ghn.get(p["ProvinceID"]), "dominant_new": dom,
                          "dominant_share": round(dn / tot, 4) if tot else None, "unique_alias_hits": tot,
                          "agree": (lineage_of_ghn.get(p["ProvinceID"]) == dom) if tot else None})

    # ---------- 4. quyet dinh tung phuong Alpha3s
    self_zone = set(admin.get("self_zone_allowlist") or [])
    pname = {p["code"]: p["name"] for p in admin["provinces"]}
    results = []
    for w in admin["wards"]:
        pc, wc = w["parent_code"], w["code"]
        als = [a["name"] for a in admin["legacy_aliases"].get(wc, [])]
        rec = {"province_code": pc, "ward_code": wc, "province_name": pname.get(pc), "ward_name": w["name"],
               "self_zone": f"{pc}/{wc}" in self_zone, "aliases": als, "rule_version": RULE_VERSION}
        scope_p = [r["ghn_province_id"] for r in resolution.get(pc, [])]
        if pc not in pname or not scope_p or not w.get("name"):
            rec.update(classification="invalid-source",
                       reason="province_khong_trong_lineage" if not scope_p else "thieu_ten_hoac_tinh")
            results.append(rec)
            continue
        scope = [x for pid in scope_p for x in wards_by_prov.get(pid, [])]
        dec = decide_mapping(w["name"], als, scope)
        cmap = {f"{x['district_id']}:{x['ward_code']}": x for x in scope}
        cands = [{"key": k, "district_id": cmap[k]["district_id"], "district_name": cmap[k]["district_name"],
                  "ward_name": cmap[k]["ward_name"]} for k in dec["candidates"] if k in cmap]
        rec.update(scope_ghn_provinces=scope_p, candidates=cands, basis=dec["basis"])
        if dec["status"] == "matched":
            rec.update(classification="matched", carrier_district_id=dec["carrier_district_id"],
                       carrier_ward_code=dec["carrier_ward_code"])
        elif dec["status"] == "ambiguous":
            dists = {c["district_id"] for c in cands}
            rec.update(classification="ambiguous", ambiguity="same_district" if len(dists) == 1 else "cross_district",
                       candidate_districts=sorted(dists))
        else:
            want = {strip_accents(norm_name(x)) for x in als + [w["name"]] if x}
            diag = sorted(f"{x['district_id']}:{x['ward_code']}" for x in scope
                          if {strip_accents(n) for n in x["names"]} & want)
            rec.update(classification="unmatched", diagnostic_accent_insensitive_candidates=diag,
                       diagnostic_note="CHI chan doan cho PO — KHONG dung de match (quy tac giu dau)")
        results.append(rec)

    # ---------- 5. tong hop
    cls = Counter(r["classification"] for r in results)
    amb = Counter(r.get("ambiguity") for r in results if r["classification"] == "ambiguous")
    basis = Counter(r.get("basis") for r in results if r["classification"] == "matched")
    per_prov = defaultdict(Counter)
    for r in results:
        per_prov[r["province_code"]][r["classification"]] += 1
    non_self = [r for r in results if not r["self_zone"]]
    summary = {
        "rule_version": RULE_VERSION, "lineage_version": lineage["version"],
        "admin_dataset_version": admin["dataset_version"],
        "totals": {"wards": len(results), **cls},
        "ambiguous_breakdown": dict(amb), "matched_basis": dict(basis),
        "self_zone_wards": sum(1 for r in results if r["self_zone"]),
        "totals_excluding_self_zone": {"wards": len(non_self), **Counter(r["classification"] for r in non_self)},
        "unmatched_with_accent_insensitive_diag": sum(1 for r in results if r["classification"] == "unmatched"
                                                      and r.get("diagnostic_accent_insensitive_candidates")),
        "per_province": {k: dict(v) for k, v in sorted(per_prov.items())},
        "lineage": {"resolved_old_provinces": sum(len(v) for v in resolution.values()),
                    "issues": lineage_issues, "ghn_province_used_twice": dup_used, "ghn_provinces_not_in_lineage": unused,
                    "empirical_disagreements": [e for e in empirical if e["agree"] is False]},
    }
    return results, summary, resolution, empirical


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--lineage", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    admin, lineage = load(a.admin), load(a.lineage)
    results, summary, resolution, empirical = build(admin, a.snapshot, lineage)
    inputs = {"admin_export": sha256_file(a.admin), "lineage": sha256_file(a.lineage),
              **{f"snapshot/{n}": sha256_file(os.path.join(a.snapshot, n))
                 for n in ("provinces.json", "districts.json", "wards.json")}}
    summary["inputs_sha256"] = inputs
    with open(os.path.join(a.out, "results.jsonl"), "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    for name, obj in (("summary.json", summary), ("lineage_resolution.json", resolution),
                      ("lineage_empirical.json", empirical)):
        with open(os.path.join(a.out, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)
    cols = ["province_code", "province_name", "ward_code", "ward_name", "self_zone", "classification", "ambiguity",
            "basis", "n_candidates", "candidates", "aliases", "diagnostic_accent_insensitive_candidates"]
    for cl, fname in (("ambiguous", "ambiguous_for_PO.csv"), ("unmatched", "unmatched_for_PO.csv"),
                      ("invalid-source", "invalid_source.csv"), ("matched", "matched.csv")):
        with open(os.path.join(a.out, fname), "w", encoding="utf-8-sig", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            wr.writeheader()
            for r in results:
                if r["classification"] != cl:
                    continue
                wr.writerow({**r, "n_candidates": len(r.get("candidates") or []),
                             "candidates": " | ".join(f"{c['key']} {c['ward_name']} ({c['district_name']})"
                                                     for c in r.get("candidates") or []),
                             "aliases": " | ".join(r.get("aliases") or []),
                             "diagnostic_accent_insensitive_candidates":
                                 " ".join(r.get("diagnostic_accent_insensitive_candidates") or [])})
    print(json.dumps({k: summary[k] for k in ("totals", "ambiguous_breakdown", "matched_basis", "self_zone_wards",
                                               "totals_excluding_self_zone", "unmatched_with_accent_insensitive_diag")},
                     ensure_ascii=False))
    print("LINEAGE:", json.dumps({k: (v if k != "ghn_provinces_not_in_lineage" else len(v))
                                  for k, v in summary["lineage"].items()}, ensure_ascii=False)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
