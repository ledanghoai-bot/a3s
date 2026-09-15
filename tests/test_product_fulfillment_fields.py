"""Product catalog: shipping_weight_g + sales_unit (M6/M7 fields exposed via dashboard product CRUD).

- `_opt_int` (endpoint parse) la logic thuan -> test truc tiep (khong DB).
- create/update persist 2 field: test DB (chay khi co M6_TEST_DB=1 + pool). Skip khi khong co DB.
"""
import os

import pytest
from fastapi import HTTPException

from app.api.dashboard import _opt_int


def test_opt_int_blank_to_none():
    assert _opt_int(None) is None
    assert _opt_int("") is None


def test_opt_int_valid():
    assert _opt_int("400") == 400
    assert _opt_int(400) == 400
    assert _opt_int(0) == 0


def test_opt_int_invalid_raises_422():
    for bad in ("abc", "12.5", "-1"):
        with pytest.raises(HTTPException) as ei:
            _opt_int(bad)
        assert ei.value.status_code == 422


DB = os.environ.get("M6_TEST_DB") == "1"


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_create_update_persist_and_omitted_preserve():
    """CA 283-01: create luu 2 field; update OMITTED giu nguyen; EXPLICIT null/blank clear; weight-only/unit-only."""
    import time

    from app.db_pool import get_pool
    from app.services import products as P

    sku = f"TESTUNIT-{int(time.time())}"
    created = await P.create_product(sku=sku, name="Test unit", description="d", price_vnd=100000, stock=10,
                                     shipping_weight_g=400, sales_unit="hũ")
    pid = created["id"]
    assert created["shipping_weight_g"] == 400 and created["sales_unit"] == "hũ"
    pool = await get_pool()

    async def _rd(oid):
        # KHONG giu conn qua loi goi update_product (update_product tu acquire conn + embed) -> tranh pool pressure.
        async with pool.acquire() as conn:
            return await conn.fetchrow("SELECT shipping_weight_g, sales_unit FROM products WHERE id=$1", oid)

    r = await _rd(pid)
    assert r["shipping_weight_g"] == 400 and r["sales_unit"] == "hũ"

    # (1) LEGACY body: KHONG truyen 2 field -> GIU NGUYEN (khong bi NULL)
    out = await P.update_product(product_id=pid, name="Renamed", description="d2", price_vnd=110000, stock=9)
    r = await _rd(pid)
    assert r["shipping_weight_g"] == 400 and r["sales_unit"] == "hũ", "omitted phai giu nguyen"
    assert out["shipping_weight_g"] == 400 and out["sales_unit"] == "hũ", "response = state cuoi thuc te"

    # (2) weight-only -> doi weight, GIU unit
    await P.update_product(product_id=pid, name="Renamed", description="d2", price_vnd=110000, stock=9,
                           shipping_weight_g=550)
    r = await _rd(pid)
    assert r["shipping_weight_g"] == 550 and r["sales_unit"] == "hũ"

    # (3) unit-only -> doi unit, GIU weight
    await P.update_product(product_id=pid, name="Renamed", description="d2", price_vnd=110000, stock=9,
                           sales_unit="lon")
    r = await _rd(pid)
    assert r["shipping_weight_g"] == 550 and r["sales_unit"] == "lon"

    # (4) EXPLICIT null/blank -> clear ve NULL (chi field duoc chi dinh)
    await P.update_product(product_id=pid, name="Renamed", description="d2", price_vnd=110000, stock=9,
                           shipping_weight_g=None, sales_unit="  ")
    r = await _rd(pid)
    assert r["shipping_weight_g"] is None and r["sales_unit"] is None

    # create khong truyen -> NULL (san pham moi khong co gia tri cu de giu)
    c2 = await P.create_product(sku=sku + "-B", name="No unit", description="d", price_vnd=100000, stock=5)
    r3 = await _rd(c2["id"])
    assert r3["shipping_weight_g"] is None and r3["sales_unit"] is None
    # cleanup
    async with pool.acquire() as conn:
        for x in (pid, c2["id"]):
            await conn.execute("DELETE FROM knowledge_chunks WHERE product_id=$1", x)
            await conn.execute("DELETE FROM products WHERE id=$1", x)


def test_endpoint_patch_forwards_only_present_fields(monkeypatch):
    """CA 283-01 (endpoint logic, pure): PATCH chi forward field khi body CO key -> omitted khong forward
    (service giu nguyen qua _UNSET); gui ro null/blank -> forward (service clear). SYNC + asyncio.run de chay
    duoc trong CI KHONG co pytest-asyncio (mock update_product de tach DB/embed)."""
    import asyncio

    from app.api import dashboard as D

    captured = {}

    async def _fake_update(**kwargs):
        captured.clear()
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(D.products_service, "update_product", _fake_update)

    # legacy body (chi name/price/stock) -> KHONG forward 2 field -> service giu nguyen
    asyncio.run(D.update_product_endpoint(1, {"name": "x", "price_vnd": 1, "stock": 1}))
    assert "shipping_weight_g" not in captured and "sales_unit" not in captured

    # weight-only present -> forward weight, KHONG forward unit
    asyncio.run(D.update_product_endpoint(1, {"name": "x", "price_vnd": 1, "stock": 1, "shipping_weight_g": 500}))
    assert captured.get("shipping_weight_g") == 500 and "sales_unit" not in captured

    # explicit null/blank -> forward (service clear)
    asyncio.run(D.update_product_endpoint(1, {"name": "x", "price_vnd": 1, "stock": 1,
                                              "shipping_weight_g": None, "sales_unit": ""}))
    assert captured["shipping_weight_g"] is None and captured["sales_unit"] == ""

    # invalid weight -> 422 truoc khi goi service (record khong doi)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(D.update_product_endpoint(1, {"name": "x", "price_vnd": 1, "stock": 1, "shipping_weight_g": "abc"}))
    assert ei.value.status_code == 422
