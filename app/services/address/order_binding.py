"""M5 Phase 4 — Order snapshot binding + quote_shipping contract (CA Directive 116).

Bind verified resolution vao order -> snapshot BAT BIEN (order_address_snapshot). quote_shipping CHI nhan
verified_address_id (tu choi free-text/unverified/expired/ambiguous/wrong-owner/stale/invalid dataset).
Shadow-mode: enforcement production tat mac dinh (settings.enable_address_quote_enforcement=False).

Fail-closed, idempotency (1 snapshot/order), immutable audit (khong ghi dia chi thua). KHONG mutate order
production tu dong (khong wiring vao create_order); chi cung cap contract/service goi tuong minh khi test/bat.
"""
from __future__ import annotations

import json

from app.config import settings
from app.services import audit_service

VERIFIED = ("auto_verified", "customer_confirmed", "staff_confirmed")


class BindingError(Exception):
    """Fail-closed."""


def _require(actor, reason, ticket):
    if not (actor and actor.strip() and reason and reason.strip() and ticket and ticket.strip()):
        raise BindingError("thieu actor/reason/ticket")


async def _assert_audit(conn):
    if not await audit_service.audit_exists(conn):
        raise BindingError("audit_log chua provision — fail-closed")


async def _load_verified_resolution(conn, resolution_id):
    """Load resolution + kiem tra verified/dataset (KHONG xet owner o day). Fail-closed."""
    r = await conn.fetchrow("SELECT * FROM address_resolution WHERE id=$1::uuid", str(resolution_id))
    if not r:
        raise BindingError("resolution khong ton tai")
    r = dict(r)
    if r["status"] not in VERIFIED:
        raise BindingError(f"resolution chua verified (status={r['status']}) — tu choi")
    if not r["dataset_version"]:
        raise BindingError("resolution khong co dataset_version — tu choi")
    ds = await conn.fetchrow("SELECT status FROM admin_unit_dataset WHERE version=$1", r["dataset_version"])
    if not ds:
        raise BindingError("dataset_version khong truy nguyen duoc — tu choi")
    if ds["status"] == "rolled_back":
        raise BindingError("dataset da rolled_back — resolution stale, tu choi")
    return r


async def _assert_owns_order(conn, resolution: dict, order_id: int):
    """OWNERSHIP tu context CO THAM QUYEN (DB), KHONG tin body (CA Review 117): owner = orders.customer_id
    that. Resolution phai thuoc dung order do (subject_type='order') hoac dung customer cua order
    (subject_type='customer'). adhoc khong the bind vao order that."""
    order = await conn.fetchrow("SELECT id, customer_id FROM orders WHERE id=$1", order_id)
    if not order:
        raise BindingError("order khong ton tai — tu choi")
    stype, sid = resolution["subject_type"], str(resolution["subject_id"])
    if stype == "order":
        if sid != str(order_id):
            raise BindingError("resolution khong thuoc dung order (wrong-owner) — tu choi")
    elif stype == "customer":
        if order["customer_id"] is None or sid != str(order["customer_id"]):
            raise BindingError("resolution khong thuoc dung customer cua order (wrong-owner) — tu choi")
    else:
        raise BindingError("resolution adhoc khong the bind vao order (khong xac dinh owner) — tu choi")


async def bind_order(conn, *, order_id: int, resolution_id: str, actor: str, reason: str, ticket: str,
                     apply: bool = False) -> dict:
    """Bind verified resolution vao order + snapshot bat bien. Idempotent theo order_id. Ownership derive tu
    orders.customer_id (khong tin body — CA Review 117)."""
    _require(actor, reason, ticket)
    await _assert_audit(conn)
    ex = await conn.fetchrow("SELECT * FROM order_address_snapshot WHERE order_id=$1", order_id)
    if ex:
        ex = dict(ex)
        if str(ex["resolution_id"]) == str(resolution_id):
            return _snap(ex)  # idempotent
        raise BindingError("order da bind resolution KHAC — tu choi (snapshot bat bien)")
    res = await _load_verified_resolution(conn, resolution_id)
    await _assert_owns_order(conn, res, order_id)
    prov = await conn.fetchval("SELECT provenance FROM admin_unit_dataset WHERE version=$1",
                               res["dataset_version"])
    if isinstance(prov, str):
        prov = json.loads(prov or "{}")
    if not apply:
        return {"action": "bind_order", "order_id": order_id, "resolution_id": str(resolution_id),
                "dry_run": True}
    async with conn.transaction():
        row = await conn.fetchrow(
            "INSERT INTO order_address_snapshot (order_id,resolution_id,province_code,district_code,ward_code,"
            "street_text,dataset_version,verified_at,verification_method,provenance_ref,bound_by) "
            "VALUES ($1,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11) RETURNING *",
            order_id, str(resolution_id), res["province_code"], res["district_code"], res["ward_code"],
            res["street_text"], res["dataset_version"], res["created_at"], res["method"],
            json.dumps({"source": (prov or {}).get("source_url"), "dataset_version": res["dataset_version"]},
                       ensure_ascii=False), actor)
        await conn.execute("UPDATE orders SET verified_address_id=$2::uuid, address_dataset_version=$3 "
                           "WHERE id=$1", order_id, str(resolution_id), res["dataset_version"])
        # audit KHONG ghi dia chi thua (chi id/version/order)
        await audit_service.record(conn, actor_type="cli", action="address.bind", actor_ref=actor,
                                   entity_type="order_address_snapshot", entity_id=str(row["id"]), before=None,
                                   after={"order_id": order_id, "resolution_id": str(resolution_id),
                                          "dataset_version": res["dataset_version"], "ticket": ticket},
                                   reason=reason)
    return _snap(row)


async def quote_shipping(conn, *, verified_address_id: str | None, order_id: int | None = None) -> dict:
    """Contract moi: CHI nhan verified_address_id. Tu choi None/free-text/unverified/stale/wrong-owner.
    Neu co order_id -> enforce ownership tu orders.customer_id (khong tin body). Shadow-mode: enforcement OFF
    -> tra ket qua nhung danh dau shadow (khong ep production)."""
    if not verified_address_id:
        raise BindingError("quote_shipping chi nhan verified_address_id — tu choi free-text/unverified")
    res = await _load_verified_resolution(conn, verified_address_id)
    if order_id is not None:
        await _assert_owns_order(conn, res, order_id)
    enforced = bool(settings.enable_address_quote_enforcement)
    return {"ok": True, "verified_address_id": str(verified_address_id),
            "province_code": res["province_code"], "dataset_version": res["dataset_version"],
            "mode": "enforced" if enforced else "shadow", "order_id": order_id}


async def log_address_change(conn, *, customer_ref: str, old_value: str | None, new_value: str | None,
                             actor: str, reason: str, ticket: str) -> str:
    _require(actor, reason, ticket)
    await _assert_audit(conn)
    async with conn.transaction():
        rid = await conn.fetchval(
            "INSERT INTO address_change_log (customer_ref,old_value,new_value,actor,reason,ticket) "
            "VALUES ($1,$2,$3,$4,$5,$6) RETURNING id", customer_ref, old_value, new_value, actor, reason, ticket)
        await audit_service.record(conn, actor_type="cli", action="address.change_log", actor_ref=actor,
                                   entity_type="address_change_log", entity_id=str(rid),
                                   before=None, after={"customer_ref": customer_ref, "ticket": ticket},
                                   reason=reason)
    return str(rid)


async def retention_due(conn, *, days: int = 400) -> int:
    """DSR/retention design (PO policy 400 ngay): DEM snapshot qua han (read-only, KHONG xoa; audit toi
    thieu giu). Anonymization/erasure that la buoc van hanh rieng, khong tu chay o day."""
    return await conn.fetchval(
        "SELECT count(*) FROM order_address_snapshot WHERE created_at < now() - ($1||' days')::interval",
        str(int(days)))


def _snap(r) -> dict:
    d = dict(r)
    for k in ("id", "resolution_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if isinstance(d.get("provenance_ref"), str):
        d["provenance_ref"] = json.loads(d["provenance_ref"] or "{}")
    return d
