"""CA Directive 345 §2B — GHN master-data snapshot CO PHAM VI + carrier_address_map builder (tooling G1).

KHONG thuoc runtime bot/worker/request path — chi goi tu scripts/ghn_g1_prep.py bang lenh tuong minh.
- Network: CHI 3 endpoint danh muc (ALLOWED_PATHS); hard cap request (mac dinh 10, dem ca loi); cham cap -> dung,
  khong retry/loop. KHONG fee/leadtime/available-services/shipment/production.
- Snapshot luu carrier_master_data (+snapshot_version) + header carrier_master_snapshot (moi lan chay, ke ca aborted).
- Map ghi append theo map_version moi (khong sua version cu); moi version co audit. Staff/manual import cung validation.
Ten dia danh: GIU DAU, NFC + casefold + bo tien to don vi hanh chinh, ap dung NHAT QUAN ca hai phia (bai hoc du an:
bo dau gay dong am gia)."""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

PROVIDER = "ghn"
ALLOWED_PATHS = frozenset({"/master-data/province", "/master-data/district", "/master-data/ward"})
DEFAULT_CAP = 10
MAP_STATUSES = ("matched", "ambiguous", "manual", "unmatched")

_PREFIXES = ("thành phố ", "tỉnh ", "quận ", "huyện ", "thị xã ", "thị trấn ", "phường ", "xã ", "tp. ", "tp ")


class SnapshotAbort(Exception):
    """Dung snapshot (khong persist master-data)."""


class CapReached(SnapshotAbort):
    pass


class PathNotAllowed(SnapshotAbort):
    pass


class MapValidationError(ValueError):
    pass


# ------------------------------------------------------------------ ten dia danh
def norm_name(s: Any) -> str:
    if not s:
        return ""
    t = re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(s)).casefold().strip())
    changed = True
    while changed:
        changed = False
        for p in _PREFIXES:
            if t.startswith(p):
                t = t[len(p):].strip()
                changed = True
    return t


def names_of(name: Any, extensions: Any = None) -> set[str]:
    out = {norm_name(name)}
    for e in (extensions or []):
        out.add(norm_name(e))
    out.discard("")
    return out


# ------------------------------------------------------------------ network (cap + allowlist)
class CappedPost:
    """Boc ham post GHN: endpoint allowlist + hard cap. Dem request TRUOC khi goi (ke ca loi/exception).
    Luon goi voi retries=0 -> moi request dem = dung 1 HTTP."""

    def __init__(self, post, cap: int = DEFAULT_CAP):
        if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
            raise ValueError("cap phai la so nguyen duong")
        self._post = post
        self.cap = cap
        self.calls: list[dict] = []

    async def __call__(self, cfg: dict, path: str, body: dict, *, retries: int = 0):
        if path not in ALLOWED_PATHS:
            raise PathNotAllowed(f"endpoint khong nam trong allowlist: {path}")
        if len(self.calls) >= self.cap:
            raise CapReached(f"cham cap {self.cap} request — dung, khong goi tiep")
        rec: dict = {"path": path, "http_status": None, "error": None}
        self.calls.append(rec)
        try:
            st, js, err, dur = await self._post(cfg, path, body, retries=0)
        except Exception as e:  # noqa: BLE001
            rec["error"] = type(e).__name__
            raise SnapshotAbort(f"loi goi {path}: {type(e).__name__}") from e
        rec["http_status"] = st
        rec["error"] = err or None
        return st, js, err, dur


def parse_targets(specs: list[str]) -> list[dict]:
    """'Tinh=Quan1|Quan2' -> [{province, districts}]."""
    out = []
    for s in specs or []:
        if "=" not in s:
            raise ValueError(f"target sai dinh dang (Tinh=Quan|Quan): {s!r}")
        p, ds = s.split("=", 1)
        dl = [d.strip() for d in ds.split("|") if d.strip()]
        if not p.strip() or not dl:
            raise ValueError(f"target thieu tinh/quan: {s!r}")
        out.append({"province": p.strip(), "districts": dl})
    if not out:
        raise ValueError("can it nhat 1 target")
    return out


def planned_requests(targets: list[dict]) -> int:
    return 1 + len(targets) + sum(len(t["districts"]) for t in targets)


def _ok(st, js) -> bool:
    return st == 200 and isinstance(js, dict) and js.get("code") == 200 and isinstance(js.get("data"), list)


def _aborted(reason: str, calls: list, report: list) -> dict:
    return {"status": "aborted", "reason": reason, "calls": calls, "provinces": [], "districts": [], "wards": [],
            "report": report}


async def fetch_scoped(cfg: dict, targets: list[dict], *, post, cap: int = DEFAULT_CAP) -> dict:
    """Pha NETWORK (khong DB). 1 province + moi tinh 1 district + moi quan 1 ward. Vuot cap du kien -> tu choi truoc,
    khong goi. Loi province list / cham cap / exception -> aborted (du lieu KHONG persist)."""
    need = planned_requests(targets)
    if need > cap:
        return _aborted(f"du kien {need} request > cap {cap} — khong goi", [], [])
    cp = CappedPost(post, cap)
    provinces, districts, wards, report = [], [], [], []
    try:
        st, js, _, _ = await cp(cfg, "/master-data/province", {})
        if not _ok(st, js):
            return _aborted(f"province list loi (http={st})", cp.calls, report)
        provs = js["data"]
        for t in targets:
            want = norm_name(t["province"])
            hits = [p for p in provs if want in names_of(p.get("ProvinceName"), p.get("NameExtension"))]
            if len(hits) != 1:
                report.append({"province": t["province"], "result": f"province_match_{len(hits)}"})
                continue
            p = hits[0]
            provinces.append(p)
            st, js, _, _ = await cp(cfg, "/master-data/district", {"province_id": p.get("ProvinceID")})
            if not _ok(st, js):
                report.append({"province": t["province"], "result": f"district_list_error_http_{st}"})
                continue
            dists = js["data"]
            districts.extend({**d, "_province_id": p.get("ProvinceID")} for d in dists)
            for dn in t["districts"]:
                w = norm_name(dn)
                dh = [d for d in dists if w in names_of(d.get("DistrictName"), d.get("NameExtension"))]
                if len(dh) != 1:
                    report.append({"province": t["province"], "district": dn, "result": f"district_match_{len(dh)}"})
                    continue
                d = dh[0]
                st, js, _, _ = await cp(cfg, "/master-data/ward", {"district_id": d.get("DistrictID")})
                if not _ok(st, js):
                    report.append({"province": t["province"], "district": dn, "result": f"ward_list_error_http_{st}"})
                    continue
                wards.extend({**wd, "_district_id": d.get("DistrictID")} for wd in js["data"])
                report.append({"province": t["province"], "district": dn, "result": "ok",
                               "district_id": d.get("DistrictID"), "ward_count": len(js["data"])})
    except SnapshotAbort as e:
        return _aborted(str(e), cp.calls, report)
    return {"status": "completed", "reason": None, "calls": cp.calls, "provinces": provinces,
            "districts": districts, "wards": wards, "report": report}


# ------------------------------------------------------------------ persist snapshot (DB, transaction caller)
async def _upsert_md(conn, kind: str, key: str, parent: str | None, name: str, payload: dict, ver: str) -> None:
    await conn.execute(
        "INSERT INTO carrier_master_data (provider, kind, key, parent_key, name, payload, fetched_at, snapshot_version) "
        "VALUES ($1,$2,$3,$4,$5,$6::jsonb,now(),$7) ON CONFLICT (provider, kind, key) DO UPDATE SET "
        "parent_key=EXCLUDED.parent_key, name=EXCLUDED.name, payload=EXCLUDED.payload, fetched_at=now(), "
        "snapshot_version=EXCLUDED.snapshot_version", PROVIDER, kind, key, parent, name, json.dumps(payload), ver)


async def persist_snapshot(conn, result: dict, *, snapshot_version: str, targets: list[dict], actor: str,
                           cap: int) -> dict:
    """Header luon ghi (completed/aborted); master-data CHI khi completed. Audit. Tra counts."""
    from app.services import audit_service
    counts = {"province": 0, "district": 0, "ward": 0}
    if result["status"] == "completed":
        for p in result["provinces"]:
            await _upsert_md(conn, "province", str(p.get("ProvinceID")), None, str(p.get("ProvinceName") or ""),
                             {"ProvinceName": p.get("ProvinceName"), "Code": p.get("Code"),
                              "NameExtension": p.get("NameExtension")}, snapshot_version)
            counts["province"] += 1
        for d in result["districts"]:
            await _upsert_md(conn, "district", str(d.get("DistrictID")), str(d.get("_province_id")),
                             str(d.get("DistrictName") or ""),
                             {"DistrictName": d.get("DistrictName"), "Code": d.get("Code"),
                              "NameExtension": d.get("NameExtension")}, snapshot_version)
            counts["district"] += 1
        for w in result["wards"]:
            await _upsert_md(conn, "ward", f"{w.get('_district_id')}:{w.get('WardCode')}", str(w.get("_district_id")),
                             str(w.get("WardName") or ""),
                             {"WardCode": w.get("WardCode"), "WardName": w.get("WardName"),
                              "NameExtension": w.get("NameExtension")}, snapshot_version)
            counts["ward"] += 1
    await conn.execute(
        "INSERT INTO carrier_master_snapshot (provider, snapshot_version, status, request_count, request_cap, requests, "
        "scope, report, created_by) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb,$9)",
        PROVIDER, snapshot_version, result["status"], len(result["calls"]), cap, json.dumps(result["calls"]),
        json.dumps(targets), json.dumps({"reason": result.get("reason"), "report": result["report"], "counts": counts}),
        actor)
    if await audit_service.audit_exists(conn):
        await audit_service.record(conn, "staff", "carrier_master.snapshot", actor_ref=actor,
                                   entity_type="carrier_master_snapshot", entity_id=snapshot_version,
                                   after={"status": result["status"], "request_count": len(result["calls"]),
                                          "cap": cap, "counts": counts})
    return counts


# ------------------------------------------------------------------ mapping rule (pure)
def decide_mapping(new_name: str, aliases: list[str], ghn_wards: list[dict]) -> dict:
    """ghn_wards: [{district_id, ward_code, names:set}] trong pham vi tinh da snapshot.
    (1) alias TRUNG ten don vi hien hanh (lien tuc ten) va dung 1 phuong GHN -> matched;
    (2) tong ung vien dung 1 -> matched; (3) >1 -> ambiguous (khong dung); (4) 0 -> unmatched (khong dung)."""
    nn = norm_name(new_name)
    alias_norms = {norm_name(a) for a in aliases or []} - {""}

    def cands(names: set) -> dict:
        return {(w["district_id"], w["ward_code"]): w for w in ghn_wards if w["names"] & names}

    cont = cands({nn}) if nn and nn in alias_norms else {}
    allc = cands(alias_norms | ({nn} if nn else set()))
    cand_list = sorted(f"{k[0]}:{k[1]}" for k in allc)
    if len(cont) == 1:
        (did, wc), basis = next(iter(cont)), "name_continuity"
    elif len(allc) == 1:
        (did, wc), basis = next(iter(allc)), "single_candidate"
    else:
        return {"status": "ambiguous" if allc else "unmatched", "method": "legacy_alias_candidates",
                "confidence": None, "carrier_district_id": None, "carrier_ward_code": None,
                "basis": "multiple_candidates" if allc else "no_candidate", "candidates": cand_list}
    return {"status": "matched", "method": "legacy_alias_exact", "confidence": 1.0, "carrier_district_id": int(did),
            "carrier_ward_code": str(wc), "basis": basis, "candidates": cand_list}


# ------------------------------------------------------------------ DB helpers cho builder
async def _active_dataset(conn) -> str | None:
    return await conn.fetchval("SELECT version FROM admin_unit_dataset WHERE status='active' ORDER BY version DESC "
                               "LIMIT 1")


async def _is_self_zone(conn, province_code: str, ward_code: str) -> bool:
    from app.services.fulfillment import routing as _r
    ver = await _r.active_version(conn)
    allow = await _r.load_allowlist(conn, ver) if ver is not None else set()
    return _r.resolve(province_code, ward_code, allow=allow, version=ver).source == _r.SELF_DELIVERY


async def _admin_ward(conn, dataset: str, province_code: str, ward_code: str) -> dict | None:
    w = await conn.fetchrow("SELECT name, parent_code FROM admin_unit WHERE dataset_version=$1 AND code=$2 "
                            "AND level='ward'", dataset, ward_code)
    if not w or w["parent_code"] != province_code:
        return None
    p = await conn.fetchval("SELECT name FROM admin_unit WHERE dataset_version=$1 AND code=$2 AND level='province'",
                            dataset, province_code)
    aliases = [r["alias_name"] for r in await conn.fetch(
        "SELECT alias_name FROM admin_unit_alias WHERE dataset_version=$1 AND unit_code=$2 AND alias_kind='legacy'",
        dataset, ward_code)]
    return {"ward_name": w["name"], "province_name": p, "aliases": aliases}


async def _ghn_province_scope(conn, province_name: str) -> tuple[int | None, list[dict], str]:
    """Province GHN (tu snapshot) khop ten tinh -> danh sach phuong GHN cua cac quan da snapshot."""
    provs = await conn.fetch("SELECT key, name, payload FROM carrier_master_data WHERE provider=$1 AND kind='province'",
                             PROVIDER)
    want = norm_name(province_name)
    hits = []
    for p in provs:
        pl = json.loads(p["payload"]) if isinstance(p["payload"], str) else (p["payload"] or {})
        if want in names_of(p["name"], pl.get("NameExtension")):
            hits.append(p)
    if len(hits) != 1:
        return None, [], f"ghn_province_match_{len(hits)}"
    pid = hits[0]["key"]
    rows = await conn.fetch(
        "SELECT w.key, w.parent_key, w.name, w.payload FROM carrier_master_data w JOIN carrier_master_data d "
        "ON d.provider=w.provider AND d.kind='district' AND d.key=w.parent_key "
        "WHERE w.provider=$1 AND w.kind='ward' AND d.parent_key=$2", PROVIDER, pid)
    wards = []
    for r in rows:
        pl = json.loads(r["payload"]) if isinstance(r["payload"], str) else (r["payload"] or {})
        wards.append({"district_id": int(r["parent_key"]), "ward_code": str(pl.get("WardCode")),
                      "names": names_of(r["name"], pl.get("NameExtension"))})
    return int(pid), wards, "ok"


async def build_map_rows(conn, addresses: list[tuple[str, str]], *, dataset_version: str | None = None) -> tuple:
    """Rows cho map_version moi tu snapshot. Bo qua self-zone; dia chi khong hop le -> report (khong row)."""
    ds = dataset_version or await _active_dataset(conn)
    rows, report = [], []
    for pc, wc in addresses:
        if await _is_self_zone(conn, pc, wc):
            report.append({"address": f"{pc}/{wc}", "result": "self_zone_skip"})
            continue
        au = await _admin_ward(conn, ds, pc, wc) if ds else None
        if not au:
            report.append({"address": f"{pc}/{wc}", "result": "address_invalid"})
            continue
        pid, wards, why = await _ghn_province_scope(conn, au["province_name"])
        if pid is None:
            dec = {"status": "unmatched", "method": "legacy_alias_candidates", "confidence": None,
                   "carrier_district_id": None, "carrier_ward_code": None, "basis": why, "candidates": []}
        else:
            dec = decide_mapping(au["ward_name"], au["aliases"], wards)
        rows.append({"province_code": pc, "ward_code": wc,
                     "carrier_province_id": pid if dec["status"] == "matched" else None,
                     "carrier_district_id": dec["carrier_district_id"], "carrier_ward_code": dec["carrier_ward_code"],
                     "status": dec["status"], "method": dec["method"], "confidence": dec["confidence"],
                     "note": json.dumps({"basis": dec["basis"], "candidates": dec["candidates"]}, ensure_ascii=False)})
        report.append({"address": f"{pc}/{wc}", "result": dec["status"], "basis": dec["basis"],
                       "candidates": dec["candidates"]})
    return rows, report


async def latest_map_rows(conn) -> tuple[int | None, list[dict]]:
    ver = await conn.fetchval("SELECT max(map_version) FROM carrier_address_map WHERE provider=$1", PROVIDER)
    if ver is None:
        return None, []
    rows = await conn.fetch(
        "SELECT province_code, ward_code, carrier_province_id, carrier_district_id, carrier_ward_code, status, method, "
        "confidence, note FROM carrier_address_map WHERE provider=$1 AND map_version=$2", PROVIDER, ver)
    return ver, [dict(r) for r in rows]


def apply_overrides(base_rows: list[dict], overrides: list[dict]) -> list[dict]:
    by = {(r["province_code"], r["ward_code"]): dict(r) for r in base_rows}
    for o in overrides:
        by[(o["province_code"], o["ward_code"])] = dict(o)
    return list(by.values())


async def validate_manual_rows(conn, items: list[dict], *, source_note: str,
                               dataset_version: str | None = None) -> list[dict]:
    """Staff mapping / import tu PO-portal (phuong an B, KHONG network). Moi item: province_code, ward_code,
    carrier_district_id (int>0), carrier_ward_code (chu so), carrier_province_id (tuy chon). Tu choi self-zone/dia chi
    sai; neu snapshot da co quan do ma khong co phuong -> tu choi (mau thuan)."""
    if not isinstance(source_note, str) or not source_note.strip():
        raise MapValidationError("can source_note (nguon ID: portal/PO)")
    ds = dataset_version or await _active_dataset(conn)
    out, seen = [], set()
    for it in items or []:
        pc, wc = str(it.get("province_code") or ""), str(it.get("ward_code") or "")
        if (pc, wc) in seen:
            raise MapValidationError(f"trung dia chi {pc}/{wc}")
        seen.add((pc, wc))
        did, gwc = it.get("carrier_district_id"), str(it.get("carrier_ward_code") or "").strip()
        if not isinstance(did, int) or isinstance(did, bool) or did <= 0:
            raise MapValidationError(f"{pc}/{wc}: carrier_district_id phai so nguyen duong")
        if not re.fullmatch(r"\d{1,10}", gwc):
            raise MapValidationError(f"{pc}/{wc}: carrier_ward_code phai chu so")
        cpid = it.get("carrier_province_id")
        if cpid is not None and (not isinstance(cpid, int) or isinstance(cpid, bool) or cpid <= 0):
            raise MapValidationError(f"{pc}/{wc}: carrier_province_id sai")
        if await _is_self_zone(conn, pc, wc):
            raise MapValidationError(f"{pc}/{wc}: self-zone — khong map GHN")
        if not ds or not await _admin_ward(conn, ds, pc, wc):
            raise MapValidationError(f"{pc}/{wc}: dia chi khong ton tai trong dataset")
        has_d = await conn.fetchval("SELECT count(*) FROM carrier_master_data WHERE provider=$1 AND kind='ward' "
                                    "AND parent_key=$2", PROVIDER, str(did))
        if has_d:
            ok = await conn.fetchval("SELECT 1 FROM carrier_master_data WHERE provider=$1 AND kind='ward' AND key=$2",
                                     PROVIDER, f"{did}:{gwc}")
            if not ok:
                raise MapValidationError(f"{pc}/{wc}: ward {did}:{gwc} khong co trong snapshot cua quan nay")
            verified = "verified_against_snapshot"
        else:
            verified = "unverified_manual"
        out.append({"province_code": pc, "ward_code": wc, "carrier_province_id": cpid, "carrier_district_id": did,
                    "carrier_ward_code": gwc, "status": "matched", "method": "staff", "confidence": None,
                    "note": json.dumps({"basis": verified, "source": source_note.strip(),
                                        "staff_note": str(it.get("note") or "")[:200]}, ensure_ascii=False)})
    if not out:
        raise MapValidationError("khong co dong nao")
    return out


def _validate_row(r: dict) -> None:
    if r.get("status") not in MAP_STATUSES:
        raise MapValidationError(f"status sai: {r.get('status')}")
    if not r.get("province_code") or not r.get("ward_code"):
        raise MapValidationError("thieu province_code/ward_code")
    if r["status"] == "matched":
        did, wc = r.get("carrier_district_id"), r.get("carrier_ward_code")
        if not isinstance(did, int) or isinstance(did, bool) or did <= 0 or not wc:
            raise MapValidationError(f"{r['province_code']}/{r['ward_code']}: matched can carrier_district_id + ward")


async def write_map_version(conn, rows: list[dict], *, actor: str, source: str) -> int:
    """Ghi map_version MOI (append, khong sua version cu). Transaction caller. Audit. Tra version."""
    from app.services import audit_service
    if not rows:
        raise MapValidationError("khong co dong nao de ghi")
    keys = [(r["province_code"], r["ward_code"]) for r in rows]
    if len(set(keys)) != len(keys):
        raise MapValidationError("trung dia chi trong version")
    for r in rows:
        _validate_row(r)
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext('carrier_address_map:ghn'))")
    ver = int(await conn.fetchval("SELECT coalesce(max(map_version),0)+1 FROM carrier_address_map WHERE provider=$1",
                                  PROVIDER))
    for r in rows:
        await conn.execute(
            "INSERT INTO carrier_address_map (provider, map_version, province_code, ward_code, carrier_province_id, "
            "carrier_district_id, carrier_ward_code, status, method, confidence, note) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
            PROVIDER, ver, r["province_code"], r["ward_code"], r.get("carrier_province_id"),
            r.get("carrier_district_id"), r.get("carrier_ward_code"), r["status"], r.get("method"),
            r.get("confidence"), r.get("note"))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    if await audit_service.audit_exists(conn):
        await audit_service.record(conn, "staff", "carrier_map.version.create", actor_ref=actor,
                                   entity_type="carrier_address_map", entity_id=str(ver),
                                   after={"map_version": ver, "source": source, "counts": counts})
    return ver
