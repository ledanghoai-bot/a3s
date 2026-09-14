"""M7 delivery routing (CA Directive 272 §3.2 / PO 271 §4.1). TAT DINH, cau hinh co version/effective date.

SELF_DELIVERY : verified ward_code nam trong allowlist cua version dang hieu luc.
GHN           : dia chi hop le (co province+ward) nam NGOAI allowlist.
MANUAL_REVIEW : thieu snapshot / thieu ma / khong co version hieu luc (fail-closed — KHONG doan noi thanh, KHONG 0d).

Ham thuan `resolve()` + loader DB. Ket qua duoc SNAPSHOT vao shipments (routing_source/version/ward/reason) o
shipment_service.route_and_quote -> doi allowlist sau KHONG doi quote da gui.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

SELF_DELIVERY = "SELF_DELIVERY"
GHN = "GHN"
MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass(frozen=True)
class RouteResult:
    source: str
    reason: str
    version: int | None
    province_code: str | None
    ward_code: str | None


def resolve(province_code: str | None, ward_code: str | None, *, allow: set[tuple[str, str]],
            version: int | None) -> RouteResult:
    """Thuan. `allow` = {(province_code, ward_code)} cua version hieu luc; version None = khong co config -> manual."""
    pc = (province_code or "").strip() or None
    wc = (ward_code or "").strip() or None
    if version is None:
        return RouteResult(MANUAL_REVIEW, "no_active_routing_version", None, pc, wc)
    if not pc or not wc:
        return RouteResult(MANUAL_REVIEW, "address_missing_codes", version, pc, wc)
    if (pc, wc) in allow:
        return RouteResult(SELF_DELIVERY, "ward_in_allowlist", version, pc, wc)
    return RouteResult(GHN, "ward_outside_allowlist", version, pc, wc)


async def active_version(conn, at: datetime | None = None) -> int | None:
    """Version hieu luc tai `at` (mac dinh now()): effective_from <= at < effective_to (hoac NULL). Nhieu version
    trung nhau -> lay version lon nhat (moi nhat)."""
    if at is None:
        return await conn.fetchval(
            "SELECT max(version) FROM delivery_routing_versions "
            "WHERE effective_from <= now() AND (effective_to IS NULL OR effective_to > now())")
    return await conn.fetchval(
        "SELECT max(version) FROM delivery_routing_versions "
        "WHERE effective_from <= $1 AND (effective_to IS NULL OR effective_to > $1)", at)


async def load_allowlist(conn, version: int) -> set[tuple[str, str]]:
    rows = await conn.fetch(
        "SELECT province_code, ward_code FROM delivery_self_wards WHERE routing_version=$1", version)
    return {(r["province_code"], r["ward_code"]) for r in rows}


async def resolve_for_order(conn, order_id: int, at: datetime | None = None) -> RouteResult:
    """Doc order_address_snapshot (bat bien) + allowlist hieu luc -> RouteResult (chua ghi gi)."""
    snap = await conn.fetchrow(
        "SELECT province_code, ward_code FROM order_address_snapshot WHERE order_id=$1", order_id)
    ver = await active_version(conn, at)
    allow = await load_allowlist(conn, ver) if ver is not None else set()
    if snap is None:
        return RouteResult(MANUAL_REVIEW, "no_address_snapshot", ver, None, None)
    return resolve(snap["province_code"], snap["ward_code"], allow=allow, version=ver)
