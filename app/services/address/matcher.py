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

from app.services.address.acceptance_gate import normalize

# base score theo kind match
_KIND_SCORE = {"canonical": 1.00, "accentless": 0.97, "legacy": 0.90, "abbrev": 0.85, "other": 0.80}
_LEGACY_KINDS = {"legacy", "abbrev", "other"}
_LEVEL_ORDER = ("province", "district", "ward")


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
        idx.setdefault(normalize(u["name"]), []).append((u["code"], "canonical"))
    for a in aliases:
        if a["unit_code"] not in codes_ok:
            continue
        n = normalize(a["alias_name"])
        # alias KHONG override canonical: neu normalized da la canonical cua unit khac -> bo qua alias do
        existing = idx.get(n, [])
        if any(k == "canonical" and c != a["unit_code"] for c, k in existing):
            continue
        kind = a["alias_kind"] if a["alias_kind"] in _KIND_SCORE else "other"
        idx.setdefault(n, []).append((a["unit_code"], kind))
    return idx


def _match(idx, name):
    """Match 1 ten -> list[(code, kind)] duy nhat theo code (giu kind diem cao nhat)."""
    if not name:
        return None  # cap khong duoc cung cap
    cands = idx.get(normalize(name))
    if not cands:
        return []  # cung cap nhung khong tim thay -> fail-closed cap do
    best: dict[str, str] = {}
    for code, kind in cands:
        if code not in best or _KIND_SCORE[kind] > _KIND_SCORE[best[code]]:
            best[code] = kind
    return [(c, k) for c, k in best.items()]


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
            rules.append(f"one_to_many:{level}")
            prev_codes = {c for c, _ in m}
            # one-to-many chan auto -> staff review
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
