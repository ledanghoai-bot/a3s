"""CA Directive 340 §1.2 — Shipping Settings packing_overhead_percent: validation (pure) + CAS/version/audit (DB)."""
import os

import pytest

from app.services.fulfillment import shipping_settings as ss

DB = os.environ.get("M6_TEST_DB") == "1"


# ---- pure validation ----
def test_validate_x_rejects_negative_and_nonnumeric():
    for bad in (None, "", "abc", -1, -0.5, float("inf"), float("nan")):
        with pytest.raises(ss.ShippingSettingsError):
            ss._validate_x(bad)


def test_validate_x_accepts_nonnegative():
    assert ss._validate_x(0) == 0.0
    assert ss._validate_x("12.5") == 12.5
    assert ss._validate_x(30) == 30.0


# ---- DB: CAS + version + audit ----
# Luu y: update_packing_overhead/get_settings tu mo pool connection + COMMIT (singleton) -> KHONG rollback duoc bang
# transaction cua test. Vi vay: snapshot gia tri goc -> chay -> RESTORE trong finally (m5lab la disposable).
@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_update_bumps_version_and_cas_conflict():
    from app.db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        orig = await conn.fetchrow("SELECT packing_overhead_percent, version FROM shipping_settings WHERE id=1")
    try:
        cur0 = await ss.get_settings()
        v0 = cur0["version"]
        actor = {"id": 1, "username": "po"}
        r1 = await ss.update_packing_overhead(15, actor=actor, expected_version=v0)
        assert r1["packing_overhead_percent"] == 15.0 and r1["version"] == v0 + 1
        cur = await ss.get_settings()
        assert cur["packing_overhead_percent"] == 15.0 and cur["version"] == v0 + 1
        # stale expected_version -> conflict (khong ghi)
        with pytest.raises(ss.ShippingSettingsError) as ei:
            await ss.update_packing_overhead(20, actor=actor, expected_version=v0)
        assert "version conflict" in str(ei.value)
        # negative rejected (no write)
        with pytest.raises(ss.ShippingSettingsError):
            await ss.update_packing_overhead(-3, actor=actor)
        # conn-based read (fallback path) thay gia tri da commit
        async with pool.acquire() as conn2:
            assert await ss.get_packing_overhead(conn2) == 15.0
    finally:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE shipping_settings SET packing_overhead_percent=$1, version=$2 WHERE id=1",
                               orig["packing_overhead_percent"], orig["version"])
