"""CA Directive 340 — GHN fallback integration qua shipment_service.route_and_quote (DB).

Skip khi khong co M6_TEST_DB (CI). Moi test chay trong transaction roi ROLLBACK (khong ban m5lab).
Bao phu 340 §3.5 phan integration: API khong dung duoc + flag ON -> fallback + snapshot + attention;
flag OFF -> quote_required (khong fallback); thieu dims -> manual; SELF_DELIVERY -> KHONG GHN/fallback;
replay -> gia on dinh (deterministic). Fee tiers/volumetric chi tiet o test_m7_fallback_quote.py (pure).
"""
import os

import pytest

DB = os.environ.get("M6_TEST_DB") == "1"
pytestmark = pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")

_SEQ = [0]


async def _seed_routing(conn):
    """1 routing version hieu luc + allowlist self = (66, 24169). Idempotent."""
    await conn.execute(
        "INSERT INTO delivery_routing_versions(version, effective_from, effective_to, dataset_version, created_by) "
        "VALUES (1, now() - interval '1 day', NULL, 'VN-TEST', 'test') ON CONFLICT DO NOTHING")
    await conn.execute(
        "INSERT INTO delivery_self_wards(routing_version, province_code, ward_code, ward_name) "
        "VALUES (1, '66', '24169', 'Test ward') ON CONFLICT DO NOTHING")
    await conn.execute("INSERT INTO delivery_zones(province_code,ward_code,zone) VALUES('66','24169','bmt_inner') "
                       "ON CONFLICT DO NOTHING")


async def _mk_order(conn, *, province, ward, weight, qty=2, dims=(10, 10, 10)):
    _SEQ[0] += 1
    tag = f"fb340-{_SEQ[0]}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'T','0900000000') RETURNING id",
                              f"tg:{tag}")
    length_cm, width_cm, height_cm = (dims if dims else (None, None, None))
    pid = await conn.fetchval(
        "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,length_cm,width_cm,height_cm) "
        "VALUES($1,'CF',100000,999,$2,$3,$4,$5) RETURNING id", f"SKU-{tag}", weight, length_cm, width_cm, height_cm)
    oid = await conn.fetchval(
        "INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',100000,"
        "'telegram_customer') RETURNING id", cid)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,$3,100000)",
                       oid, pid, qty)
    rid = await conn.fetchval(
        "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,"
        "method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,$1,$2,'current',1.0) RETURNING id",
        province, ward)
    await conn.execute(
        "INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,dataset_version,"
        "verification_method,bound_by) VALUES($1,$2,$3,$4,'VN-TEST','test','t')", oid, rid, province, ward)
    return oid


async def _set_packing(conn, x):
    await conn.execute("UPDATE shipping_settings SET packing_overhead_percent=$1, version=version+1 WHERE id=1", x)


@pytest.mark.asyncio
async def test_ghn_fallback_applies_when_enabled(monkeypatch):
    from app.config import settings
    from app.db_pool import get_pool
    from app.services.fulfillment import shipment_service as ship
    monkeypatch.setattr(settings, "ghn_fallback_enabled", True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _seed_routing(conn)
            await _set_packing(conn, 10)
            # province 79 (lien tinh, ngoai allowlist -> GHN); actual 5kg; dims 10cm x2 -> vol 0.44kg -> chargeable 5kg
            oid = await _mk_order(conn, province="79", ward="26734", weight=2500, qty=2, dims=(10, 10, 10))
            out = await ship.route_and_quote(conn, oid, actor="t", ghn_result=None)
            assert out["routing_source"] == "GHN"
            assert out["quote_source"] == "fallback_policy"
            assert out["policy_version"] == "GHN_FALLBACK_PO_V2"
            assert out["fee_status"] == "quoted" and int(out["delivery_fee_vnd"]) == 40000   # lien tier 5kg
            assert out["attention_reason"] == "quote"
            import json
            snap = out["quote_snapshot"]
            snap = json.loads(snap) if isinstance(snap, str) else snap
            fee = snap["fee"]
            for k in ("chargeable_weight_kg", "volumetric_weight_kg", "raw_volume_cm3", "packing_overhead_percent",
                      "api_error_reason", "quote_source"):
                assert k in fee, k
            assert fee["quote_source"] == "fallback_policy"
        finally:
            await tr.rollback()


@pytest.mark.asyncio
async def test_ghn_fallback_off_quote_required(monkeypatch):
    from app.config import settings
    from app.db_pool import get_pool
    from app.services.fulfillment import shipment_service as ship
    monkeypatch.setattr(settings, "ghn_fallback_enabled", False)
    pool = await get_pool()
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _seed_routing(conn)
            await _set_packing(conn, 10)
            oid = await _mk_order(conn, province="79", ward="26734", weight=5000)
            out = await ship.route_and_quote(conn, oid, actor="t", ghn_result=None)
            assert out["routing_source"] == "GHN"
            assert out["quote_source"] == "auto_route"           # KHONG fallback
            assert out["fee_status"] == "quote_required" and out["delivery_fee_vnd"] is None
        finally:
            await tr.rollback()


@pytest.mark.asyncio
async def test_ghn_fallback_missing_dims_manual(monkeypatch):
    from app.config import settings
    from app.db_pool import get_pool
    from app.services.fulfillment import shipment_service as ship
    monkeypatch.setattr(settings, "ghn_fallback_enabled", True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _seed_routing(conn)
            await _set_packing(conn, 10)
            oid = await _mk_order(conn, province="79", ward="26734", weight=5000, dims=None)  # thieu dims
            out = await ship.route_and_quote(conn, oid, actor="t", ghn_result=None)
            assert out["fee_status"] == "quote_required" and out["delivery_fee_vnd"] is None
            assert out["quote_source"] == "auto_route"
            import json
            snap = out["quote_snapshot"]
            snap = json.loads(snap) if isinstance(snap, str) else snap
            assert snap["fee"].get("fallback_reason") == "dimension_missing"
        finally:
            await tr.rollback()


@pytest.mark.asyncio
async def test_missing_packing_overhead_manual(monkeypatch):
    from app.config import settings
    from app.db_pool import get_pool
    from app.services.fulfillment import shipment_service as ship
    monkeypatch.setattr(settings, "ghn_fallback_enabled", True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _seed_routing(conn)
            await conn.execute("UPDATE shipping_settings SET packing_overhead_percent=NULL WHERE id=1")  # x chua cau hinh
            oid = await _mk_order(conn, province="79", ward="26734", weight=5000, dims=(10, 10, 10))
            out = await ship.route_and_quote(conn, oid, actor="t", ghn_result=None)
            assert out["fee_status"] == "quote_required" and out["delivery_fee_vnd"] is None
            import json
            snap = out["quote_snapshot"]
            snap = json.loads(snap) if isinstance(snap, str) else snap
            assert snap["fee"].get("fallback_reason") == "packing_overhead_invalid"
        finally:
            await tr.rollback()


@pytest.mark.asyncio
async def test_self_delivery_no_ghn_no_fallback(monkeypatch):
    from app.config import settings
    from app.db_pool import get_pool
    from app.services.fulfillment import shipment_service as ship
    monkeypatch.setattr(settings, "ghn_fallback_enabled", True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _seed_routing(conn)
            await _set_packing(conn, 10)
            # ward 24169 in allowlist -> SELF_DELIVERY (bmt_inner); KHONG dung GHN/fallback
            oid = await _mk_order(conn, province="66", ward="24169", weight=600)
            out = await ship.route_and_quote(conn, oid, actor="t", ghn_result=None)
            assert out["routing_source"] == "SELF_DELIVERY"
            assert out["quote_source"] == "auto_route" and out["zone"] == "bmt_inner"
            assert out["quote_provider"] == "self_rule"          # khong phai ghn/fallback
        finally:
            await tr.rollback()


@pytest.mark.asyncio
async def test_replay_deterministic_same_fee(monkeypatch):
    from app.config import settings
    from app.db_pool import get_pool
    from app.services.fulfillment import shipment_service as ship
    monkeypatch.setattr(settings, "ghn_fallback_enabled", True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _seed_routing(conn)
            await _set_packing(conn, 10)
            oid = await _mk_order(conn, province="79", ward="26734", weight=2500, qty=2, dims=(10, 10, 10))
            out1 = await ship.route_and_quote(conn, oid, actor="t", ghn_result=None)
            out2 = await ship.route_and_quote(conn, oid, actor="t", ghn_result=None)
            assert int(out1["delivery_fee_vnd"]) == int(out2["delivery_fee_vnd"]) == 40000
            assert out2["quote_source"] == "fallback_policy"
            # 1 shipment cho order (khong nhan doi)
            n = await conn.fetchval("SELECT count(*) FROM shipments WHERE order_id=$1", oid)
            assert n == 1
        finally:
            await tr.rollback()
