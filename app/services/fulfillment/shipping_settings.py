"""CA Directive 340 §1.2 — Shipping Settings: packing_overhead_percent (x).

Singleton row (id=1). x = phan tram the tich tang them khi dong chung nhieu don vi (N>1), KHONG am.
- Doc: `get_packing_overhead(conn)` (fallback quote) / `get_settings(conn)` (dashboard readback, khong secret).
- Ghi: `update_packing_overhead(conn, x, actor, expected_version)` — validate x>=0, CAS version, audit before/after.
Fail-closed: x chua cau hinh (NULL) -> fallback tra manual (khong bao phi). x KHONG phai secret -> readback ro.
"""
from __future__ import annotations

from app.db_pool import get_pool
from app.services import audit_service


class ShippingSettingsError(Exception):
    """Validation / CAS conflict (map API 400/409)."""


async def get_packing_overhead(conn) -> float | None:
    """Tra x hien hanh (float) hoac None neu chua cau hinh. Conn-based (fallback quote truyen conn cua transaction)."""
    row = await conn.fetchrow("SELECT packing_overhead_percent FROM shipping_settings WHERE id = 1")
    if row is None or row["packing_overhead_percent"] is None:
        return None
    return float(row["packing_overhead_percent"])


def _shape(row) -> dict:
    if row is None:
        return {"packing_overhead_percent": None, "version": 0, "updated_by": None, "updated_at": None}
    x = row["packing_overhead_percent"]
    return {"packing_overhead_percent": (float(x) if x is not None else None),
            "version": int(row["version"]), "updated_by": row["updated_by"],
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None}


async def get_settings() -> dict:
    """Readback cho dashboard (KHONG secret): {packing_overhead_percent, version, updated_by, updated_at}."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT packing_overhead_percent, version, updated_by, updated_at FROM shipping_settings WHERE id = 1")
        return _shape(dict(row) if row else None)


def _validate_x(value) -> float:
    if value is None or value == "":
        raise ShippingSettingsError("packing_overhead_percent bat buoc (so phan tram >= 0)")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ShippingSettingsError("packing_overhead_percent phai la so")
    if x != x or x in (float("inf"), float("-inf")):   # NaN/inf
        raise ShippingSettingsError("packing_overhead_percent phai huu han")
    if x < 0:
        raise ShippingSettingsError("packing_overhead_percent phai >= 0")
    return x


async def update_packing_overhead(value, *, actor: dict, expected_version: int | None = None) -> dict:
    """Cap nhat x (singleton). CAS optional theo expected_version. Bump version. Audit before/after (fail-closed,
    cung transaction). Tra state moi (readback)."""
    x = _validate_x(value)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            cur = await conn.fetchrow(
                "SELECT packing_overhead_percent, version FROM shipping_settings WHERE id = 1 FOR UPDATE")
            if cur is None:
                raise ShippingSettingsError("shipping_settings chua khoi tao (migration 069)")
            if expected_version is not None and int(expected_version) != int(cur["version"]):
                raise ShippingSettingsError(
                    f"version conflict (expected {expected_version}, hien {cur['version']}) — tai lai roi thu lai")
            before_x = float(cur["packing_overhead_percent"]) if cur["packing_overhead_percent"] is not None else None
            new_version = int(cur["version"]) + 1
            await conn.execute(
                "UPDATE shipping_settings SET packing_overhead_percent = $1, version = $2, updated_by = $3, "
                "updated_at = now() WHERE id = 1", x, new_version, actor.get("username"))
            if await audit_service.audit_exists(conn):
                await audit_service.record(
                    conn, "staff", "shipping_settings.packing_overhead.update",
                    actor_staff_id=actor.get("id"), actor_ref=actor.get("username"),
                    entity_type="shipping_settings", entity_id="1",
                    before={"packing_overhead_percent": before_x, "version": int(cur["version"])},
                    after={"packing_overhead_percent": x, "version": new_version})
    return {"packing_overhead_percent": x, "version": new_version, "updated_by": actor.get("username")}
