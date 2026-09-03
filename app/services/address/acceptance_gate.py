"""M5 Phase 1 — Acceptance gate (8 kiem tra da khoa, CA Directive 104).

Logic THUAN (khong cham DB) de test bang fixture cu the. Nhan cau truc dataset da staging + provenance +
sha256 mong doi + regression fixture -> tra ve report {passed: bool, checks: [...]}. Dataset mac dinh KHONG
duoc activate cho toi khi passed=True (enforce o control layer).

8 kiem tra (theo directive + PO Decision #1):
 1. schema           — version format, level enum, cot bat buoc, alias_kind hop le.
 2. code_range       — code duy nhat trong effective range (khong trung code chong lap thoi gian).
 3. parent_child     — moi ward co parent district hop le; moi district co parent province hop le.
 4. coverage         — so luong moi cap khop provenance.expected_counts (nguon authoritative).
 5. duplicate        — khong trung (code); alias khong override canonical name cua unit KHAC.
 6. mapping_regress  — regression fixture (legacy_norm -> expected_code) van resolve dung.
 7. checksum         — sha256 tinh lai tren canonical serialization khop sha256 khai bao.
 8. provenance       — provenance du truong bat buoc + rollback target (first_version hoac prev active).
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata

_VERSION_RE = re.compile(r"^VN-ADMIN-\d{4}-\d{2}-v\d+$")
_LEVELS = ("province", "district", "ward")
_ALIAS_KINDS = ("legacy", "accentless", "abbrev", "other")
_PROV_REQUIRED = ("source_url", "source_kind", "downloaded_at", "license", "expected_counts")


def normalize(s: str) -> str:
    """Bo dau + lower + gom khoang trang. Dung NHAT QUAN ca hai phia khi so khop (bai hoc tieng Viet:
    chi bo dau khi bo o CA HAI phia)."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "d")  # đ/Đ
    return re.sub(r"\s+", " ", s).strip().lower()


def canonical_checksum(units: list[dict], aliases: list[dict]) -> str:
    """sha256 tren serialization on dinh (sort theo code / (unit_code,alias)). Doc lap thu tu input."""
    u = sorted(
        ([x["code"], x["level"], x["name"], x.get("parent_code"),
          x.get("effective_from"), x.get("effective_to")] for x in units),
        key=lambda r: r[0],
    )
    a = sorted(
        ([x["unit_code"], x["alias_name"], x["alias_kind"]] for x in aliases),
        key=lambda r: (r[0], r[1]),
    )
    payload = json.dumps({"units": u, "aliases": a}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _c(name: str, ok: bool, detail: str = "") -> dict:
    return {"check": name, "ok": bool(ok), "detail": detail}


def run(
    *,
    version: str,
    units: list[dict],
    aliases: list[dict],
    provenance: dict,
    declared_sha256: str,
    regression: list[dict] | None = None,
    has_rollback_target: bool = False,
) -> dict:
    """Chay 8 kiem tra. Tra ve {"passed": bool, "checks": [...], "computed_sha256": str}."""
    checks: list[dict] = []
    regression = regression or []

    # 1. schema
    bad = []
    if not _VERSION_RE.match(version or ""):
        bad.append(f"version format: {version!r}")
    for x in units:
        if x.get("level") not in _LEVELS:
            bad.append(f"level: {x.get('code')}={x.get('level')!r}")
        if not x.get("code") or not x.get("name"):
            bad.append(f"thieu code/name: {x!r}")
    for x in aliases:
        if x.get("alias_kind") not in _ALIAS_KINDS:
            bad.append(f"alias_kind: {x.get('unit_code')}={x.get('alias_kind')!r}")
        if not x.get("unit_code") or not x.get("alias_name"):
            bad.append(f"alias thieu unit_code/alias_name: {x!r}")
    checks.append(_c("schema", not bad, "; ".join(bad[:8])))

    # 2. code_range — khong trung code voi effective range chong lap
    by_code: dict[str, list[dict]] = {}
    for x in units:
        by_code.setdefault(x["code"], []).append(x)
    overlaps = []
    for code, rows in by_code.items():
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                if _ranges_overlap(rows[i], rows[j]):
                    overlaps.append(code)
    checks.append(_c("code_range", not overlaps, "code trung/chong effective: " + ",".join(sorted(set(overlaps))[:8])))

    # 3. parent_child — TOPOLOGY-AWARE (CA Review 122): 2-tier (province->ward) HOAC 3-tier
    #    (province->district->ward). Topology xac dinh o cap TOAN DATASET (co district hay khong).
    #    Hybrid/mixed (co district nhung mot phan ward tro province) -> FAIL-CLOSED (khong "uu tien").
    codes_by_level = {lv: {x["code"] for x in units if x["level"] == lv} for lv in _LEVELS}
    provinces, districts = codes_by_level["province"], codes_by_level["district"]
    has_district = len(districts) > 0
    orphans = []
    mixed = False
    for x in units:
        if x["level"] == "district" and x.get("parent_code") not in provinces:
            orphans.append(f"district {x['code']}->{x.get('parent_code')} (parent phai province)")
        if x["level"] == "ward":
            p = x.get("parent_code")
            if has_district:
                if p not in districts:
                    orphans.append(f"ward {x['code']}->{p} (3-tier: parent phai district)")
                    if p in provinces:
                        mixed = True   # ward bo qua district trong dataset 3-tier -> hybrid
            elif p not in provinces:
                orphans.append(f"ward {x['code']}->{p} (2-tier: parent phai province)")
    topology = "mixed" if mixed else ("3-tier" if has_district else "2-tier")
    checks.append(_c("parent_child", not orphans and not mixed, f"topology={topology}; " + "; ".join(orphans[:8])))

    # 4. coverage vs authoritative expected_counts
    exp = (provenance or {}).get("expected_counts") or {}
    actual = {lv: sum(1 for x in units if x["level"] == lv) for lv in _LEVELS}
    mism = [f"{lv}: {actual[lv]}!={exp.get(lv)}" for lv in _LEVELS if lv in exp and actual[lv] != exp[lv]]
    checks.append(_c("coverage", bool(exp) and not mism,
                     ("thieu expected_counts" if not exp else "; ".join(mism))))

    # 5. duplicate + alias khong override canonical cua unit khac
    dup_codes = [c for c, rows in by_code.items() if len(rows) > 1 and c not in overlaps]
    canon_by_norm: dict[str, str] = {normalize(x["name"]): x["code"] for x in units}
    alias_override = []
    for a in aliases:
        n = normalize(a["alias_name"])
        owner = canon_by_norm.get(n)
        if owner is not None and owner != a["unit_code"]:
            alias_override.append(f"{a['unit_code']}:{a['alias_name']}->canonical cua {owner}")
    dup_detail = []
    if dup_codes:
        dup_detail.append("code trung: " + ",".join(sorted(set(dup_codes))[:8]))
    if alias_override:
        dup_detail.append("alias override canonical: " + "; ".join(alias_override[:8]))
    checks.append(_c("duplicate", not dup_codes and not alias_override, " | ".join(dup_detail)))

    # 6. mapping regression — legacy_norm -> expected_code van resolve
    alias_index: dict[str, set[str]] = {}
    for a in aliases:
        alias_index.setdefault(normalize(a["alias_name"]), set()).add(a["unit_code"])
    for x in units:
        alias_index.setdefault(normalize(x["name"]), set()).add(x["code"])
    reg_fail = []
    for r in regression:
        key = normalize(r.get("legacy") or r.get("legacy_norm") or "")
        want = r.get("expected_code")
        got = alias_index.get(key, set())
        if got != {want}:  # phai resolve DUY NHAT ve dung code (khong ambiguous)
            reg_fail.append(f"{r.get('legacy')}->{want} (got {sorted(got)})")
    checks.append(_c("mapping_regress", not reg_fail, "; ".join(reg_fail[:8])))

    # 7. checksum
    computed = canonical_checksum(units, aliases)
    checks.append(_c("checksum", computed == (declared_sha256 or "").lower(),
                     f"computed={computed[:12]}… declared={(declared_sha256 or '')[:12]}…"))

    # 8. provenance + rollback target
    miss = [k for k in _PROV_REQUIRED if k not in (provenance or {})]
    is_first = bool((provenance or {}).get("first_version"))
    rb_ok = is_first or has_rollback_target
    detail8 = []
    if miss:
        detail8.append("thieu provenance: " + ",".join(miss))
    if not rb_ok:
        detail8.append("khong co rollback target (va khong phai first_version)")
    checks.append(_c("provenance", not miss and rb_ok, "; ".join(detail8)))

    passed = all(c["ok"] for c in checks)
    return {"passed": passed, "checks": checks, "computed_sha256": computed, "topology": topology}


def _ranges_overlap(a: dict, b: dict) -> bool:
    """Hai effective range [from,to] (to=None = mo) co chong nhau khong. None from = -inf."""
    af, at = a.get("effective_from"), a.get("effective_to")
    bf, bt = b.get("effective_from"), b.get("effective_to")
    lo = max(x for x in (af, bf) if x is not None) if (af or bf) else None
    hi_candidates = [x for x in (at, bt) if x is not None]
    hi = min(hi_candidates) if hi_candidates else None
    if lo is None or hi is None:
        return True  # it nhat mot dau mo -> coi nhu chong (fail-closed)
    return lo <= hi
