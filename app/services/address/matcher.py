"""M5 Phase 2 — Address matcher (logic THUAN, khong cham DB). CA Directive 108.

Nhan dataset (units + aliases) da nap san + input dia chi (ten cac cap) + as_of -> tra ve resolution dict:
status/method/confidence/codes/candidates/rules. Test bang fixture current/legacy/ambiguous/conflict/as_of.

Nguyen tac (Directive 108 + PO Decision #4):
- Normalize tieng Viet NHAT QUAN hai phia (bai hoc du an: bo dau ca hai phia).
- Auto (auto_verified) CHI khi: method='current', mot-mot moi cap cung cap, hierarchy hop le, effective range
  phu hop, confidence >= 0.95.
- 0.80–<0.95 -> needs_customer_confirmation; <0.80 -> needs_staff_review.
- Hard rules LUON chan auto bat ke diem: one-to-many, abnormal many-to-one, missing parent, conflict.
- Canonical name khong bi alias override (uu tien canonical khi trung normalized).
- Fail-closed khi thieu candidate mot cap bat buoc / khong hop effective range / input thieu province.
"""
from __future__ import annotations

import re

from app.services.address.acceptance_gate import normalize

# base score theo kind match
_KIND_SCORE = {"canonical": 1.00, "accentless": 0.97, "legacy": 0.90, "abbrev": 0.85, "other": 0.80}
_LEGACY_KINDS = {"legacy", "abbrev", "other"}
_LEVEL_ORDER = ("province", "district", "ward")

# --- M5 upgrade (Directive 214 §6.A + Memo 213 §4): khop nhan-biet TIEN TO hanh chinh + VIET TAT ---
# Bug F1 (PROVEN): dataset luu ten CO tien to ("Tinh Dak Lak", "Phuong Ea Kao") va matcher khop
# NGUYEN CHUOI da normalize. Nen input tran "Dak Lak" (thieu "Tinh") hay viet tat "P. Ea Kao"
# KHONG khop, du cung don vi hanh chinh. Fix: sinh KEY khop uu tien [dang-day-du, dang-tran] + mo
# rong viet tat token hanh chinh dau cum. KHONG fuzzy tu che — chi chuan hoa xac dinh; alias cu/moi
# van chi qua admin_unit_alias versioned.
# Token viet tat (da normalize, khong dau cham) -> tien to day du.
_ADMIN_ABBREV = {
    "tp": "thanh pho", "t": "tinh", "p": "phuong", "q": "quan",
    "h": "huyen", "x": "xa", "tt": "thi tran", "tx": "thi xa",
}
# Tien to hanh chinh (da normalize) de tao dang TRAN. Cum nhieu tu dat TRUOC de strip dung.
_ADMIN_PREFIXES = ("thanh pho", "thi tran", "thi xa", "tinh", "phuong", "quan", "huyen", "xa")
_ABBREV_RE = re.compile(r"^([a-z]{1,2})\.?\s+(.+)$")

# CA 232 §5 (B1): regression-alias cho bien the chinh ta tester phat hien (vd phu-am-cuoi k/c). BOUNDED —
# map TUONG MINH (khong fuzzy dai tra: KHONG tu doi k<->c moi noi). Ap dong nhat 2 phia qua _match_keys ->
# input bien the sinh THEM key canonical -> khop dataset. Ambiguous van clarify (khong ep chon nham phuong).
_REGRESSION_VARIANTS = {
    "ea knuek": "ea knuec",  # tester 07/09: "Xa Ea Knuek" -> canonical "Xa Ea Knuếc" (24505, Dak Lak)
}


def _match_keys(name: str) -> list[str]:
    """Sinh key khop theo THU TU UU TIEN: [dang-day-du-da-mo-viet-tat, dang-tran-bo-tien-to].

    Vi du: "Tinh Dak Lak" -> ["tinh dak lak", "dak lak"]; "P. Ea Kao" -> ["phuong ea kao", "ea kao"];
    "Dak Lak" -> ["dak lak"]. Uu tien dang day du de GIU tinh dac hieu (input "Phuong Tan Lap" khop
    dung 1 phuong, KHONG roi xuong "tan lap" gay one_to_many voi cac "Xa Tan Lap"). Dung CHUNG ham nay
    ca khi index dataset lan khi match input -> nhat quan hai phia (bai hoc tieng Viet CLAUDE.md).
    """
    n = normalize(name)
    if not n:
        return []
    # Mo rong viet tat token dau ("p. ea kao"/"p ea kao" -> "phuong ea kao"); chi khi token la abbrev
    # hanh chinh da biet (khong dung cham vao ten thuong nhu "Ea Kao").
    m = _ABBREV_RE.match(n)
    if m and m.group(1) in _ADMIN_ABBREV:
        n = f"{_ADMIN_ABBREV[m.group(1)]} {m.group(2)}"
    keys = [n]
    for pre in _ADMIN_PREFIXES:
        if n.startswith(pre + " "):
            bare = n[len(pre) + 1:].strip()
            if bare and bare not in keys:
                keys.append(bare)
            break
    # CA 232 §5 (B1): sinh THEM key canonical cho bien the chinh ta da biet (bounded map, khong fuzzy).
    for k in list(keys):
        canon = _REGRESSION_VARIANTS.get(k)
        if canon and canon not in keys:
            keys.append(canon)
    return keys


def _effective(u: dict, as_of) -> bool:
    """Unit hop le tai as_of (None as_of -> luon hop). effective_from/to co the None (mo)."""
    if as_of is None:
        return True
    ef, et = u.get("effective_from"), u.get("effective_to")
    if ef is not None and as_of < ef:
        return False
    if et is not None and as_of > et:
        return False
    return True


def _index(units: list[dict], aliases: list[dict], level: str, as_of):
    """Tra ve dict normalized_name -> list[(code, kind)] cho 1 cap, uu tien canonical, loc effective."""
    codes_ok = {u["code"] for u in units if u["level"] == level and _effective(u, as_of)}
    idx: dict[str, list[tuple[str, str]]] = {}
    for u in units:
        if u["level"] != level or u["code"] not in codes_ok:
            continue
        # M5 upgrade A: index duoi CA dang day-du VA tran (bo tien to). _match uu tien key day du nen
        # bare chi la fallback khi input tran -> khong lam mat tinh dac hieu.
        for key in _match_keys(u["name"]):
            idx.setdefault(key, []).append((u["code"], "canonical"))
    for a in aliases:
        if a["unit_code"] not in codes_ok:
            continue
        # CA Review 126: alias trung canonical cua unit KHAC = ambiguity hop le -> GIU CA HAI candidate
        # (canonical KHONG am tham thang, khong lam mat candidate legacy). Collision -> one_to_many ->
        # needs_staff_review (hard rule, khong ha xuong customer confirmation).
        kind = a["alias_kind"] if a["alias_kind"] in _KIND_SCORE else "other"
        for key in _match_keys(a["alias_name"]):
            idx.setdefault(key, []).append((a["unit_code"], kind))
    return idx


def _match(idx, name):
    """Match 1 ten -> list[(code, kind)] duy nhat theo code (giu kind diem cao nhat).

    Thu KEY theo THU TU UU TIEN (_match_keys): dang day-du truoc, dang tran sau. Lay candidate tu
    KEY DAU TIEN co ket qua -> input dac hieu ("Phuong Tan Lap") khong bi hoa lan voi cac don vi khac
    cung ten tran ("Xa Tan Lap"). Chi roi xuong dang tran khi input von khong co tien to (vd "Dak Lak").
    """
    if not name:
        return None  # cap khong duoc cung cap
    for key in _match_keys(name):
        cands = idx.get(key)
        if not cands:
            continue
        best: dict[str, str] = {}
        for code, kind in cands:
            if code not in best or _KIND_SCORE[kind] > _KIND_SCORE[best[code]]:
                best[code] = kind
        return [(c, k) for c, k in best.items()]
    return []  # cung cap nhung khong tim thay o bat ky key nao -> fail-closed cap do


def resolve(units, aliases, *, province, district, ward, as_of=None) -> dict:
    parent_of = {u["code"]: u.get("parent_code") for u in units}
    rules: list[str] = []
    candidates: list[dict] = []
    chosen: dict[str, str] = {}     # level -> code
    scores: list[float] = []
    kinds: list[str] = []

    prev_codes: set[str] | None = None
    for level, name in (("province", province), ("district", district), ("ward", ward)):
        if name is None:
            prev_codes = None if level == "province" else prev_codes
            continue
        idx = _index(units, aliases, level, as_of)
        m = _match(idx, name)
        if m is None:
            continue
        if m == []:
            rules.append(f"no_candidate:{level}")
            return _fail("failed", rules, candidates, chosen)
        # loc theo parent (hierarchy) neu co cap cha da chon
        if prev_codes is not None:
            filtered = [(c, k) for c, k in m if parent_of.get(c) in prev_codes]
            if not filtered:
                rules.append(f"hierarchy_conflict:{level}")
                for c, k in m:
                    candidates.append({"level": level, "code": c, "kind": k})
                return _fail("needs_staff_review", rules, candidates, chosen)
            m = filtered
        for c, k in m:
            candidates.append({"level": level, "code": c, "kind": k})
        if len(m) > 1:
            # CA Directive 251 §3.A: TEN HIEN HANH (canonical) thang mot trung-ten LEGACY-alias.
            # Vd "Tan Lap" trong Dak Lak khop 24121 (canonical "Phuong Tan Lap") + 24316 (legacy alias
            # "Xa Tan Lap" cua "Xa Pong Drang" — ten CU da sap nhap). Khach go TEN HIEN HANH => y chi
            # don vi hien hanh. Sau khi loc theo scope, neu con DUNG MOT candidate kind hien hanh
            # (canonical/accentless) => chon no (khong con mo ho that). Neu >=2 hien hanh => mo ho THAT
            # -> clarify. KHONG tang confidence gia, KHONG auto chon giua nhieu don vi hien hanh.
            current = [(c, k) for c, k in m if k not in _LEGACY_KINDS]
            if len(current) == 1:
                rules.append(f"current_over_legacy:{level}")
                m = current
            else:
                rules.append(f"one_to_many:{level}")
                prev_codes = {c for c, _ in m}
                # one-to-many that (>=2 hien hanh, hoac chi toan legacy) -> staff/clarify
                return _fail("needs_staff_review", rules, candidates, chosen)
        code, kind = m[0]
        chosen[level] = code
        scores.append(_KIND_SCORE[kind])
        kinds.append(kind)
        prev_codes = {code}

    if not chosen or "province" not in chosen:
        rules.append("missing_province")
        return _fail("failed", rules, candidates, chosen)

    confidence = round(min(scores), 3) if scores else 0.0
    method = "legacy_mapping" if any(k in _LEGACY_KINDS for k in kinds) else "current"
    if method == "current" and confidence >= 0.95:
        status = "auto_verified"
    elif confidence >= 0.80:
        status = "needs_customer_confirmation"
    else:
        status = "needs_staff_review"
    return {
        "status": status, "method": method, "confidence": confidence,
        "province_code": chosen.get("province"), "district_code": chosen.get("district"),
        "ward_code": chosen.get("ward"), "candidates": candidates, "rules_applied": rules,
    }


def _fail(status, rules, candidates, chosen) -> dict:
    return {
        "status": status, "method": None, "confidence": 0.0,
        "province_code": chosen.get("province"), "district_code": chosen.get("district"),
        "ward_code": chosen.get("ward"), "candidates": candidates, "rules_applied": rules,
    }
