"""CA Directive 396 §3 (F2) — Dia chi Dashboard co cau truc -> resolve/bind snapshot TRONG transaction tao don.

Evidence don #255: don Dashboard chi luu free-text -> khong snapshot -> "Tinh phi theo dia chi" tra 200 voi
zone=unknown (loi im lang). Luong moi (duong Dashboard TUONG MINH, origin_channel='dashboard'; KHONG noi M5 bot scope):

  1. Staff chon Tinh + Phuong/Xa tu danh muc dataset ACTIVE (catalog) + nhap so nha/duong tu do.
  2. precheck (matcher THUAN, khong ghi DB): ten chinh thuc cua ma da chon -> auto_verified dung ma do? Neu KHONG
     -> tra candidates cho UI; staff chon candidate + LY DO BAT BUOC (staff_confirm) moi duoc tao.
  3. resolve_and_bind_in_tx (trong tx tao don / xac minh don cu): resolver ghi address_resolution (audit
     address.resolve) -> auto_verified dung ma chon => bind; khong => BAT BUOC staff_confirm -> resolution MOI
     'staff_confirmed' (actor/reason/provenance, audit address.staff_confirm) => bind (audit address.bind).
     Loi bat ky -> raise -> caller rollback CA don (fail-closed, khong don mo coi/snapshot le).

KHONG parse/backfill tu text tu do cu (Directive 396 §1). KHONG sua dataset authoritative.
"""
from __future__ import annotations

import hashlib
import json

from app.services import audit_service
from app.services.address import dataset_registry as reg
from app.services.address import matcher, order_binding, resolver

REASON_MIN, REASON_MAX = 5, 500


class DashboardAddressError(Exception):
    """Fail-closed. code: invalid_address | dataset_unavailable | needs_staff_confirmation | invalid_confirmation."""

    def __init__(self, code: str, message: str, *, candidates: list | None = None):
        super().__init__(message)
        self.code = code
        self.candidates = candidates or []


def parse_input(body: dict | None) -> dict:
    """Validate input co cau truc tu Dashboard. KHONG nhan free-text lam dia chi xac minh."""
    b = body or {}
    pc = str(b.get("province_code") or "").strip()
    wc = str(b.get("ward_code") or "").strip()
    street = str(b.get("street_text") or "").strip()
    if not pc or not wc:
        raise DashboardAddressError("invalid_address", "Thieu Tinh/Phuong-Xa (chon tu danh muc)")
    if not street or len(street) > 300:
        raise DashboardAddressError("invalid_address", "So nha/duong bat buoc (toi da 300 ky tu)")
    out = {"province_code": pc, "ward_code": wc, "street_text": street, "staff_confirm": None}
    sc = b.get("staff_confirm")
    if sc:
        if not isinstance(sc, dict):
            raise DashboardAddressError("invalid_confirmation", "staff_confirm phai la object")
        reason = str(sc.get("reason") or "").strip()
        if not (REASON_MIN <= len(reason) <= REASON_MAX):
            raise DashboardAddressError("invalid_confirmation",
                                        f"Ly do xac nhan dia chi bat buoc ({REASON_MIN}-{REASON_MAX} ky tu)")
        out["staff_confirm"] = {"reason": reason}
    return out


def fingerprint(addr: dict) -> str:
    """Identity TAT DINH cua dia chi co cau truc (vao request_hash lenh order.create; khong PII tho)."""
    h = hashlib.sha256(addr["street_text"].casefold().encode("utf-8")).hexdigest()[:16]
    return f"dash:{addr['province_code']}:{addr['ward_code']}:{h}:{'staff' if addr.get('staff_confirm') else 'auto'}"


# ----------------------------------------------------------------------------- catalog
async def active_version(conn) -> str:
    v = await reg.get_active(conn)
    if not v:
        raise DashboardAddressError("dataset_unavailable", "Chua co dataset dia chi active — khong the xac minh")
    return v


async def catalog_provinces(conn) -> dict:
    v = await active_version(conn)
    rows = await conn.fetch("SELECT code, name FROM admin_unit WHERE dataset_version=$1 AND level='province' "
                            "AND effective_to IS NULL ORDER BY name", v)
    return {"dataset_version": v, "provinces": [dict(r) for r in rows]}


async def catalog_wards(conn, province_code: str) -> dict:
    v = await active_version(conn)
    rows = await conn.fetch("SELECT code, name FROM admin_unit WHERE dataset_version=$1 AND level='ward' "
                            "AND parent_code=$2 AND effective_to IS NULL ORDER BY name", v, str(province_code))
    return {"dataset_version": v, "province_code": str(province_code), "wards": [dict(r) for r in rows]}


async def _chosen_units(conn, v: str, addr: dict) -> tuple[dict, dict]:
    p = await conn.fetchrow("SELECT code, name FROM admin_unit WHERE dataset_version=$1 AND level='province' "
                            "AND code=$2 AND effective_to IS NULL", v, addr["province_code"])
    w = await conn.fetchrow("SELECT code, name, parent_code FROM admin_unit WHERE dataset_version=$1 AND level='ward' "
                            "AND code=$2 AND effective_to IS NULL", v, addr["ward_code"])
    if not p or not w or w["parent_code"] != p["code"]:
        raise DashboardAddressError("invalid_address", "Tinh/Phuong-Xa khong co trong danh muc active (hoac khong "
                                    "thuoc nhau) — tai lai danh muc")
    return dict(p), dict(w)


async def _candidate_view(conn, v: str, cands: list, chosen_ward: dict) -> list[dict]:
    codes = sorted({c["code"] for c in cands if c.get("level") == "ward"} | {chosen_ward["code"]})
    rows = await conn.fetch("SELECT code, name, parent_code FROM admin_unit WHERE dataset_version=$1 "
                            "AND code = ANY($2::text[])", v, codes)
    return [{"ward_code": r["code"], "name": r["name"], "province_code": r["parent_code"],
             "chosen": r["code"] == chosen_ward["code"]} for r in rows]


# ----------------------------------------------------------------------------- precheck (thuan, khong ghi)
async def precheck(conn, addr: dict) -> dict:
    """{'auto': bool, 'dataset_version', 'candidates'}. Chi DOC (units/aliases + matcher thuan)."""
    v = await active_version(conn)
    p, w = await _chosen_units(conn, v, addr)
    units = [dict(r) for r in await conn.fetch(
        "SELECT level,code,name,parent_code,effective_from,effective_to FROM admin_unit WHERE dataset_version=$1", v)]
    aliases = [dict(r) for r in await conn.fetch(
        "SELECT unit_code,alias_name,alias_kind FROM admin_unit_alias WHERE dataset_version=$1", v)]
    aliases += [dict(r) for r in await conn.fetch(
        "SELECT unit_code,alias_name,alias_kind FROM admin_unit_alias_augment WHERE dataset_version=$1", v)]
    res = matcher.resolve(units, aliases, province=p["name"], district=None, ward=w["name"])
    auto = res["status"] == "auto_verified" and res.get("ward_code") == w["code"] \
        and res.get("province_code") == p["code"]
    return {"auto": auto, "dataset_version": v,
            "candidates": [] if auto else await _candidate_view(conn, v, res.get("candidates") or [], w)}


# ----------------------------------------------------------------------------- resolve + bind (trong tx caller)
async def _staff_confirmed_resolution(conn, orig: dict, *, p: dict, w: dict, street: str, actor: str,
                                      reason: str) -> str:
    """Resolution MOI 'staff_confirmed' cho DUNG ma staff chon (khong copy ma matcher). Append-only + audit."""
    note = {"via": "dashboard_staff_confirm", "confirmed_province": p["code"], "confirmed_ward": w["code"],
            "from_resolution": str(orig["id"]), "matcher_status": orig["status"]}
    row = await conn.fetchrow(
        "INSERT INTO address_resolution (subject_type,subject_id,raw_province,raw_district,raw_ward,street_text,"
        "province_code,district_code,ward_code,dataset_version,as_of,status,method,confidence,candidates,"
        "rules_applied,resolved_by,reason) VALUES ($1,$2,$3,NULL,$4,$5,$6,NULL,$7,$8,NULL,'staff_confirmed','manual',"
        "1.0,$9::jsonb,$10::jsonb,$11,$12) RETURNING id",
        orig["subject_type"], orig["subject_id"], p["name"], w["name"], street, p["code"], w["code"],
        orig["dataset_version"], json.dumps([note], ensure_ascii=False),
        json.dumps(["dashboard_staff_confirm"], ensure_ascii=False), actor, reason)
    await audit_service.record(conn, actor_type="cli", action="address.staff_confirm", actor_ref=actor,
                               entity_type="address_resolution", entity_id=str(row["id"]), before=None,
                               after={"subject_type": orig["subject_type"], "subject_id": orig["subject_id"],
                                      "dataset_version": orig["dataset_version"], "from_resolution": str(orig["id"]),
                                      "matcher_status": orig["status"], "via": "dashboard"},
                               reason=reason)
    return str(row["id"])


async def resolve_and_bind_in_tx(conn, *, order_id: int, addr: dict, actor: str, ticket: str) -> dict:
    """Goi TRONG transaction dang mo cua caller. Tra {'snapshot', 'resolution_id', 'verification'}.
    Raise DashboardAddressError / order_binding.BindingError / resolver.ResolveError -> caller rollback."""
    v = await active_version(conn)
    p, w = await _chosen_units(conn, v, addr)
    res = await resolver.resolve(conn, subject_type="order", subject_id=str(order_id), province=p["name"],
                                 ward=w["name"], street_text=addr["street_text"], actor=actor,
                                 reason="dashboard-structured-address", ticket=ticket)
    auto = res["status"] == "auto_verified" and res.get("ward_code") == w["code"] \
        and res.get("province_code") == p["code"]
    if auto:
        rid, how = res["id"], "auto_verified"
    else:
        sc = addr.get("staff_confirm")
        if not sc:
            raise DashboardAddressError(
                "needs_staff_confirmation", "Dia chi chua tu xac minh duoc — can nhan vien chon va xac nhan (ly do)",
                candidates=await _candidate_view(conn, v, res.get("candidates") or [], w))
        rid = await _staff_confirmed_resolution(conn, res, p=p, w=w, street=addr["street_text"], actor=actor,
                                                reason=sc["reason"])
        how = "staff_confirmed"
    snap = await order_binding.bind_in_order_tx(conn, order_id=order_id, resolution_id=rid, actor=actor,
                                                reason=f"dashboard-address:{how}", ticket=ticket)
    return {"snapshot": snap, "resolution_id": str(rid), "verification": how}


def compose_address_text(addr: dict, province_name: str, ward_name: str) -> str:
    return f"{addr['street_text']}, {ward_name}, {province_name}"


async def display_text(conn, addr: dict) -> str:
    """Chuoi hien thi tuong thich cu (orders.shipping_address) ghep tu 3 phan co cau truc."""
    v = await active_version(conn)
    p, w = await _chosen_units(conn, v, addr)
    return compose_address_text(addr, p["name"], w["name"])
