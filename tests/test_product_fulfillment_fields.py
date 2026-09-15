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
async def test_create_update_persist_fields():
    """create_product luu shipping_weight_g + sales_unit; update_product doi duoc; de trong -> NULL."""
    import time

    from app.db_pool import get_pool
    from app.services import products as P

    sku = f"TESTUNIT-{int(time.time())}"
    created = await P.create_product(sku=sku, name="Test unit", description="d", price_vnd=100000, stock=10,
                                     shipping_weight_g=400, sales_unit="hũ")
    pid = created["id"]
    assert created["shipping_weight_g"] == 400 and created["sales_unit"] == "hũ"
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT shipping_weight_g, sales_unit FROM products WHERE id=$1", pid)
        assert row["shipping_weight_g"] == 400 and row["sales_unit"] == "hũ"
        # update: doi weight, xoa unit (rong -> NULL)
        await P.update_product(product_id=pid, name="Test unit", description="d", price_vnd=100000, stock=10,
                               shipping_weight_g=550, sales_unit="  ")
        row2 = await conn.fetchrow("SELECT shipping_weight_g, sales_unit FROM products WHERE id=$1", pid)
        assert row2["shipping_weight_g"] == 550 and row2["sales_unit"] is None
        # create khong truyen (mac dinh None) -> NULL
        c2 = await P.create_product(sku=sku + "-B", name="No unit", description="d", price_vnd=100000, stock=5)
        row3 = await conn.fetchrow("SELECT shipping_weight_g, sales_unit FROM products WHERE id=$1", c2["id"])
        assert row3["shipping_weight_g"] is None and row3["sales_unit"] is None
        # cleanup
        for x in (pid, c2["id"]):
            await conn.execute("DELETE FROM knowledge_chunks WHERE product_id=$1", x)
            await conn.execute("DELETE FROM products WHERE id=$1", x)
