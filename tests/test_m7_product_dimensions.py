"""CA Directive 340 §1.1 — Product dimensions (length/width/height cm): parse (pure), RBAC gate (pure endpoint),
persist + audit (DB). `_opt_pos_int` = huu han DUONG; sua kich thuoc BAT BUOC quyen catalog.manage."""
import asyncio
import os

import pytest
from fastapi import HTTPException

from app.api.dashboard import (
    _opt_pos_int,
    create_product_endpoint,
    update_product_endpoint,
)

DB = os.environ.get("M6_TEST_DB") == "1"


# ---- pure parse ----
def test_opt_pos_int_blank_to_none():
    assert _opt_pos_int(None, "length_cm") is None
    assert _opt_pos_int("", "length_cm") is None


def test_opt_pos_int_valid():
    assert _opt_pos_int("10", "length_cm") == 10
    assert _opt_pos_int(25, "width_cm") == 25


def test_opt_pos_int_rejects_nonpositive_and_nonint():
    for bad in ("abc", "12.5", "0", 0, "-1", -3):
        with pytest.raises(HTTPException) as ei:
            _opt_pos_int(bad, "height_cm")
        assert ei.value.status_code == 422


# ---- endpoint RBAC (pure: 403/422 xay ra TRUOC khi cham DB) ----
_STAFF_NOPERM = {"rbac_provisioned": True, "permissions": set(), "id": 9, "username": "noperm"}


def test_create_dims_without_permission_403():
    body = {"sku": "X", "name": "x", "price_vnd": 1, "stock": 1, "length_cm": 10}
    with pytest.raises(HTTPException) as ei:
        asyncio.run(create_product_endpoint(body, _STAFF_NOPERM))
    assert ei.value.status_code == 403 and "catalog.manage" in ei.value.detail


def test_update_dims_without_permission_403():
    body = {"name": "x", "price_vnd": 1, "stock": 1, "width_cm": 10}
    with pytest.raises(HTTPException) as ei:
        asyncio.run(update_product_endpoint(1, body, _STAFF_NOPERM))
    assert ei.value.status_code == 403


def test_update_invalid_dim_422_before_permission():
    body = {"name": "x", "price_vnd": 1, "stock": 1, "length_cm": "abc"}
    with pytest.raises(HTTPException) as ei:
        asyncio.run(update_product_endpoint(1, body, _STAFF_NOPERM))
    assert ei.value.status_code == 422


# ---- DB persist + audit ----
@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_create_update_dims_persist_and_audit():
    # products service tu mo pool + COMMIT -> cleanup bang delete_product trong finally (khong dung tx rollback).
    import time

    from app.db_pool import get_pool
    from app.services import products as P
    actor = {"id": 1, "username": "po"}
    sku = f"DIM-{int(time.time()*1000)}"
    pool = await get_pool()
    pid = None
    try:
        created = await P.create_product(sku=sku, name="d", description="", price_vnd=1000, stock=1,
                                          length_cm=10, width_cm=20, height_cm=30, actor=actor)
        pid = created["id"]
        assert (created["length_cm"], created["width_cm"], created["height_cm"]) == (10, 20, 30)
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT length_cm, width_cm, height_cm FROM products WHERE id=$1", pid)
        assert (row["length_cm"], row["width_cm"], row["height_cm"]) == (10, 20, 30)
        # OMITTED dims giu nguyen; explicit thay doi -> audit
        upd = await P.update_product(pid, name="d2", description="", price_vnd=1000, stock=1,
                                     height_cm=35, actor=actor)
        assert upd["length_cm"] == 10 and upd["height_cm"] == 35   # length giu, height doi
        async with pool.acquire() as conn:
            n_audit = await conn.fetchval(
                "SELECT count(*) FROM audit_log WHERE entity_type='product' AND entity_id=$1 "
                "AND action LIKE 'product.dimensions.%'", str(pid))
        assert n_audit >= 2   # set (create) + update
    finally:
        if pid is not None:
            try:
                await P.delete_product(pid)
            except Exception:
                pass
