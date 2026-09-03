"""M5 Gate A — Transform 2 file authoritative GSO -> dataset JSON 2-tier (CA Guidance 121 + Review 122).

Input (E:/alpha3s/geo-data, do PO/Ops cung cap tu nguon authoritative):
  - "Danh sách cấp tỉnh __03_09_2026.xls" (BIFF): 34 tinh — Ma | Ten | ... | Cap | Nghi dinh.
  - "BangChuyendoi_DVHC_moi_cu_final.xlsx" sheet "Tổng hợp_không merge ":
    Tinh/TP | Ten Xa moi | Ma Xa moi | Ten Xa cu | Ma Xa cu | Ghi chu | Quan/huyen(cu) | Tinh cu.

Output: dataset JSON 2-tier (province -> ward, KHONG district):
  - units: 34 province (parent=None) + wards moi (parent=province code).
  - aliases: Ten Xa cu -> unit_code = Ma Xa moi, kind='legacy' (giu Ma Xa cu lam provenance/context).
  - provenance: source authoritative + expected_counts + first_version.

KHONG bia du lieu — chi doc & transform file that. Chay acceptance gate offline (topology-aware) de xem truoc.
"""
import argparse
import json
import re

import openpyxl
import xlrd

from app.services.address import acceptance_gate as gate

_CODE_RE = re.compile(r"\((\d+)\)\s*$")


def read_provinces(path):
    wb = xlrd.open_workbook(path)
    sh = wb.sheet_default = wb.sheets()[0]
    prov = {}
    for r in range(1, sh.nrows):
        ma = str(sh.cell_value(r, 0)).strip()
        ten = str(sh.cell_value(r, 1)).strip()
        if ma and ten and ma.lower() != "mã":
            prov[ma.zfill(2)] = ten
    return prov


def read_conversion(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["Tổng hợp_không merge "]
    wards = {}          # ma_xa_moi -> (ten, province_code)
    aliases = []        # {unit_code, alias_name, alias_kind, source(ma cu)}
    seen = set()        # dedup theo (unit_code, alias_normalized): dong "Nhap toan bo/mot phan" tach doi
    for i, row in enumerate(ws.iter_rows(min_row=3, values_only=True)):
        tinh, ten_moi, ma_moi, ten_cu, ma_cu = row[0], row[1], row[2], row[3], row[4]
        if not ma_moi:
            continue
        ma_moi = str(ma_moi).strip()
        pcode = None
        if tinh:
            m = _CODE_RE.search(str(tinh))
            if m:
                pcode = m.group(1).zfill(2)
        if ma_moi not in wards and ten_moi:
            wards[ma_moi] = (str(ten_moi).strip(), pcode)
        if ten_cu:
            an = str(ten_cu).strip()
            key = (ma_moi, gate.normalize(an))   # khop PK admin_unit_alias (unit_code, alias_normalized)
            if key in seen:
                continue                          # bo alias trung (cung xa cu -> cung xa moi, tach 2 dong)
            seen.add(key)
            aliases.append({"unit_code": ma_moi, "alias_name": an, "alias_kind": "legacy",
                            "source": (str(ma_cu).strip() if ma_cu else None)})
    return wards, aliases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geodir", default="/data")
    ap.add_argument("--prov-file", default="Danh sách cấp tỉnh __03_09_2026.xls")
    ap.add_argument("--conv-file", default="BangChuyendoi_DVHC_moi_cu_final.xlsx")
    ap.add_argument("--version", default="VN-ADMIN-2025-07-v1")
    ap.add_argument("--out", default="/data/dataset_VN-ADMIN-2025-07-v1.json")
    a = ap.parse_args()

    prov = read_provinces(f"{a.geodir}/{a.prov_file}")
    wards, aliases = read_conversion(f"{a.geodir}/{a.conv_file}")

    units = [{"level": "province", "code": c, "name": n, "parent_code": None} for c, n in prov.items()]
    orphan_wards = 0
    for ma, (ten, pcode) in wards.items():
        if pcode not in prov:
            orphan_wards += 1
        units.append({"level": "ward", "code": ma, "name": ten, "parent_code": pcode})

    prov_n = sum(1 for u in units if u["level"] == "province")
    ward_n = sum(1 for u in units if u["level"] == "ward")
    provenance = {
        "source_url": "https://danhmuchanhchinh.nso.gov.vn/", "source_kind": "authoritative",
        "downloaded_at": "2026-09-03", "license": "(PO xác nhận)", "first_version": True,
        "legal_ref": "Nghị quyết 202/2025/QH15 (12/06/2025)",
        "expected_counts": {"province": prov_n, "ward": ward_n},
    }
    sha = gate.canonical_checksum(units, aliases)
    dataset = {"version": a.version, "source_url": provenance["source_url"], "source_kind": "authoritative",
               "license": provenance["license"], "sha256": sha, "provenance": provenance,
               "units": units, "aliases": aliases}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False)

    print(f"provinces      : {prov_n}")
    print(f"wards (new)    : {ward_n}")
    print(f"aliases (legacy): {len(aliases)}")
    print(f"orphan wards (province code không khớp): {orphan_wards}")
    print(f"sha256         : {sha}")
    print(f"output         : {a.out}")

    rep = gate.run(version=a.version, units=units, aliases=aliases, provenance=provenance,
                   declared_sha256=sha, has_rollback_target=True)
    print("\n== acceptance gate (offline, topology-aware) ==")
    for c in rep["checks"]:
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['check']}  {c['detail'][:70]}")
    print(f"  topology={rep['topology']}  passed={rep['passed']}")


if __name__ == "__main__":
    main()
