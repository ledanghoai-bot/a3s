"""CA Directive 354 / PO Record 353 — guard hang nang (>20.000 g): quote_required 'heavy_goods_manual', KHONG dung request,
KHONG giai ma credential, KHONG goi GHN, KHONG provider_quote_log, KHONG fallback fee. Bien 20.000 g van quote binh thuong.

Pure (CI) + DB (M6_TEST_DB=1). Test DB rollback; test dong thoi dung du lieu commit va don sach o finally."""
import asyncio
import json
import os
import uuid

import pytest

from app.services.fulfillment import fallback_quote as fb
from app.services.fulfillment import shipping_policy as sp
from app.services.providers import ghn
from app.services.providers.base import QuoteRequest

DB = os.environ.get("M6_TEST_DB") == "1"
POLICY = {"policy_version": "GHN_FALLBACK_PO_V2", "rounding_version": fb.ROUNDING_VERSION,
          "packing_version": fb.PACKING_VERSION, "shop_province_code": "66",
          "spec": {"noi_tinh": {"base_max_kg": 3, "base_fee_vnd": 16500, "per_extra_kg_vnd": 7000},
                   "lien_tinh": {"tiers": [[0.5, 25000], [1, 27000], [2, 29000], [3, 32000], [4, 35000], [5, 40000]],
                                 "per_extra_kg_vnd": 7000, "per_extra_after_kg": 5}}}
ITEM = [{"product_id": 1, "quantity": 1, "length_cm": 10, "width_cm": 10, "height_cm": 11}]
CFG = {"enabled": True, "base": ghn.STAGING_BASE, "token": "T", "shop_id": "1", "from_district_id": 1552,
       "from_ward_code": "400105", "timeout": 1.0, "retries": 0, "light_max_g": 20000, "map_version": 2}


class _Conn:
    def __init__(self):
        self.execs, self.reads = [], []

    async def fetchrow(self, sql, *a):
        self.reads.append(sql)
        if "carrier_address_map" in sql:
            return {"carrier_province_id": 210, "carrier_district_id": 1954, "carrier_ward_code": "400701",
                    "status": "matched", "method": "staff", "confidence": None}
        return None

    async def execute(self, sql, *a):
        self.execs.append(sql)


def _post(calls):
    async def p(cfg, path, body, *, retries):
        calls.append(path)
        if path.endswith("/fee"):
            return 200, {"code": 200, "data": {"total": 99000}}, "", 3
        return 200, {"code": 200, "data": {"leadtime": 0}}, "", 2
    return p


def _req(w):
    return QuoteRequest(order_id=1, province_code="66", ward_code="24490", weight_g=w, length_cm=10, width_cm=10,
                        height_cm=11)


# ================================================================== PURE
def test_policy_boundary_and_version():
    assert sp.is_heavy(20000) is False and sp.is_heavy(20001) is True
    assert sp.is_heavy(None) is False and sp.is_heavy("x") is False
    d = sp.heavy_detail(20001)
    assert d == {"reason": "heavy_goods_manual", "policy_version": "po_record_353_v1", "max_weight_g": 20000,
                 "weight_g": 20001}


def test_fallback_20001_no_fee_20000_normal():
    fee, reason, d = fb.quote_fallback(POLICY, "79", ITEM, 20001, 10)
    assert fee is None and reason == "heavy_goods_manual" and "fee_vnd" not in d
    assert d["heavy_goods"]["policy_version"] == sp.HEAVY_GOODS_POLICY_VERSION
    fee2, reason2, _ = fb.quote_fallback(POLICY, "79", ITEM, 20000, 10)
    assert reason2 == "ok" and fee2 == 40000 + 15 * 7000            # 20 kg lien tinh: 40000 + ceil(20-5)*7000


def test_request_dims_20001_heavy_20000_ok():
    assert fb.ghn_request_dims(ITEM, 20001, 10)[:2] == (None, "heavy_goods_manual")
    dims, reason, _ = fb.ghn_request_dims(ITEM, 20000, 10)
    assert reason == "ok" and dims == (10, 10, 11)


def test_build_request_heavy_before_any_db_access():
    class Route:
        province_code, ward_code = "66", "24490"
    # conn=None: neu guard cham DB se AttributeError -> chung minh khong truy van (khong doc packing/secret)
    req, reason, d = asyncio.run(fb.build_ghn_request(None, 1, Route(), 20001))
    assert req is None and reason == "heavy_goods_manual" and d["heavy_goods"]["weight_g"] == 20001


def test_provider_20001_no_http_no_log_20000_calls():
    calls, conn = [], _Conn()
    res = asyncio.run(ghn.GhnQuoteProvider(CFG, post=_post(calls)).quote(conn, _req(20001)))
    assert res.status == "quote_required" and res.reason == "heavy_goods_manual" and res.fee_vnd is None
    assert calls == [] and conn.execs == [] and conn.reads == []      # 0 HTTP, 0 provider_quote_log, 0 map lookup
    res2 = asyncio.run(ghn.GhnQuoteProvider(CFG, post=_post(calls)).quote(conn, _req(20000)))
    assert res2.status == "ok" and res2.service_type_id == 2 and calls[0].endswith("/fee")


def test_guard_independent_of_light_max_g():
    calls = []
    cfg = {**CFG, "light_max_g": 50000}                                # provider config KHONG noi long policy
    res = asyncio.run(ghn.GhnQuoteProvider(cfg, post=_post(calls)).quote(_Conn(), _req(25000)))
    assert res.reason == "heavy_goods_manual" and calls == []


# ================================================================== DB
async def _seed(conn, weight, qty=1, province="79", ward="26734", tag="354"):
    await conn.execute(
        "INSERT INTO delivery_routing_versions(version, effective_from, effective_to, dataset_version, created_by) "
        "VALUES (9354, now() - interval '1 day', NULL, 'VN-TEST', 't') ON CONFLICT DO NOTHING")
    await conn.execute("INSERT INTO delivery_self_wards(routing_version, province_code, ward_code, ward_name) "
                       "VALUES (9354, '66', '24169', 'Noi thanh') ON CONFLICT DO NOTHING")
    await conn.execute("INSERT INTO carrier_address_map (provider, map_version, province_code, ward_code, "
                       "carrier_province_id, carrier_district_id, carrier_ward_code, status, method) "
                       "VALUES ('ghn', 1, $1, $2, 202, 1442, '20108', 'matched', 'staff') ON CONFLICT DO NOTHING",
                       province, ward)
    await conn.execute("UPDATE shipping_settings SET packing_overhead_percent=10 WHERE id=1")
    cid = await conn.fetchval("INSERT INTO customers (psid, channel, external_chat_id, name,phone) VALUES ($1, 'telegram_customer', $1, 'T','0900000000') RETURNING id",
                              f"tg:hg-{tag}-{weight}-{uuid.uuid4().hex[:10]}")
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,length_cm,width_cm,"
                              "height_cm) VALUES($1,'CF',100000,999,$2,10,10,11) RETURNING id",
                              f"HG-{tag}-{weight}-{uuid.uuid4().hex[:10]}", weight)
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                              "VALUES($1,'confirmed',100000,'telegram_customer') RETURNING id", cid)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,$3,100000)",
                       oid, pid, qty)
    rid = await conn.fetchval(
        "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,method,"
        "confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,$1,$2,'current',1.0) RETURNING id",
        province, ward)
    await conn.execute("INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,"
                       "dataset_version,verification_method,bound_by) VALUES($1,$2,$3,$4,'VN-TEST','test','t')",
                       oid, rid, province, ward)
    return {"oid": oid, "cid": cid, "pid": pid, "rid": rid}


class _Prov:
    def __init__(self):
        self.calls = []

    async def quote(self, conn, req):
        from app.services.providers.base import QuoteResult
        self.calls.append(req)
        return QuoteResult(status="ok", provider="ghn", fee_vnd=77000, eta_text="2 ngay",
                           request_fingerprint=req.fingerprint())


def _enable(monkeypatch, fallback=True):
    from app.config import settings
    monkeypatch.setattr(settings, "ghn_fallback_enabled", fallback)
    monkeypatch.setattr(settings, "m7_ghn_quote", True)
    resolve_calls = []
    orig = ghn.resolve_quote_cfg

    async def spy(conn):
        resolve_calls.append(1)
        return await orig(conn)
    monkeypatch.setattr(ghn, "resolve_quote_cfg", spy)
    return resolve_calls


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_heavy_manual_zero_call_zero_decrypt_no_fallback(monkeypatch):
    from app.db_pool import get_pool
    from app.services.fulfillment import conversation as fc
    from app.services.fulfillment import shipment_service as ship
    resolve_calls = _enable(monkeypatch, fallback=True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            s = await _seed(conn, 20001)
            n_log = await conn.fetchval("SELECT count(*) FROM provider_quote_log")
            prov = _Prov()
            assert await fc.prepare_ghn_quote(conn, s["oid"], provider=prov) is None
            assert prov.calls == [] and resolve_calls == []           # khong dung request, khong resolve/giai ma
            out = await ship.route_and_quote(conn, s["oid"], actor="t", ghn_result=None)
            snap = out["quote_snapshot"]
            snap = json.loads(snap) if isinstance(snap, str) else snap
            assert out["routing_source"] == "GHN" and out["fee_status"] == "quote_required"
            assert out["delivery_fee_vnd"] is None and out["quote_source"] == "auto_route"   # KHONG fallback
            assert snap["fee"]["reason"] == "heavy_goods_manual"
            assert snap["fee"]["policy_version"] == "po_record_353_v1" and snap["fee"]["max_weight_g"] == 20000
            assert out["attention_reason"] == "quote"
            att = await conn.fetchrow("SELECT reason, detail FROM staff_attention WHERE order_id=$1 AND status='open'",
                                      s["oid"])
            det = json.loads(att["detail"]) if isinstance(att["detail"], str) else att["detail"]
            assert att["reason"] == "quote" and det["quote_reason"] == "heavy_goods_manual"
            assert await conn.fetchval("SELECT count(*) FROM provider_quote_log") == n_log
        finally:
            await tr.rollback()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_boundary_20000_quotes_normally_api_and_fallback(monkeypatch):
    from app.db_pool import get_pool
    from app.services.fulfillment import conversation as fc
    from app.services.fulfillment import shipment_service as ship
    from app.services.providers.base import QuoteResult
    _enable(monkeypatch, fallback=True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            s = await _seed(conn, 20000)
            prov = _Prov()
            res = await fc.prepare_ghn_quote(conn, s["oid"], provider=prov)
            assert res is not None and len(prov.calls) == 1 and prov.calls[0].weight_g == 20000
            out = await ship.route_and_quote(conn, s["oid"], actor="t", ghn_result=res)
            assert out["fee_status"] == "quoted" and int(out["delivery_fee_vnd"]) == 77000
            # API loi -> fallback van ap dung o bien 20.000 g
            fail = QuoteResult(status="quote_required", provider="ghn", reason="ghn_timeout",
                               request_fingerprint=prov.calls[0].fingerprint())
            out2 = await ship.route_and_quote(conn, s["oid"], actor="t", ghn_result=fail)
            assert out2["quote_source"] == "fallback_policy" and int(out2["delivery_fee_vnd"]) == 40000 + 15 * 7000
        finally:
            await tr.rollback()


async def _cleanup(conn, s):
    """Don phan XOA DUOC. order_address_snapshot la ho so BAT BIEN (trigger cam DELETE, chu dich) -> order/snapshot/
    customer/product test o lai tren m5lab (disposable, tag uuid, status confirmed khong anh huong test khac)."""
    oid = s["oid"]
    for sql in ("DELETE FROM staff_attention WHERE order_id=$1", "DELETE FROM fulfillment_route_operations WHERE order_id=$1",
                "DELETE FROM shipment_delivery_attempts WHERE shipment_id IN (SELECT id FROM shipments WHERE order_id=$1)",
                "DELETE FROM shipments WHERE order_id=$1"):
        await conn.execute(sql, oid)


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_route_operation_heavy_replay_concurrent_zero_calls(monkeypatch):
    import asyncpg

    from app.services.fulfillment import route_operation as ro
    _enable(monkeypatch, fallback=True)
    dsn = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    setup = await asyncpg.connect(dsn)
    s = None
    x_orig = await setup.fetchval("SELECT packing_overhead_percent FROM shipping_settings WHERE id=1")
    try:
        s = await _seed(setup, 20001, tag="ro")          # COMMIT (can cho 2 connection dong thoi)
        prov = _Prov()

        async def ex(key):
            c = await asyncpg.connect(dsn)
            try:
                return await ro.execute(c, s["oid"], actor="t", command_key=key, provider=prov)
            except ro.RouteOpInFlight:
                return {"in_flight": True}
            finally:
                await c.close()
        r1 = await ex("hg-354-a")
        r2 = await ex("hg-354-a")                      # replay
        rc = await asyncio.gather(ex("hg-354-c"), ex("hg-354-c"))   # dong thoi cung key
        assert prov.calls == []                        # tong 0 provider effect
        assert r1["duplicate"] is False and r2["duplicate"] is True
        assert sum(1 for r in rc if isinstance(r, dict) and not r.get("in_flight")) >= 1
        tags = [r["provider"] for r in await setup.fetch(
            "SELECT provider FROM fulfillment_route_operations WHERE order_id=$1", s["oid"])]
        assert tags and all(t == "none" for t in tags)      # khong bi coi la ambiguous
        sh = await setup.fetchrow("SELECT fee_status, delivery_fee_vnd, quote_snapshot FROM shipments WHERE order_id=$1",
                                  s["oid"])
        snap = json.loads(sh["quote_snapshot"]) if isinstance(sh["quote_snapshot"], str) else sh["quote_snapshot"]
        assert sh["fee_status"] == "quote_required" and sh["delivery_fee_vnd"] is None
        assert snap["fee"]["reason"] == "heavy_goods_manual"
    finally:
        if s:
            await _cleanup(setup, s)
        await setup.execute("DELETE FROM carrier_address_map WHERE provider='ghn' AND map_version=1 AND "
                            "province_code='79' AND ward_code='26734' AND carrier_district_id=1442")
        # routing version test 9354 (lon nhat -> se lan cac test khac neu de lai) + khoi phuc x
        await setup.execute("DELETE FROM delivery_self_wards WHERE routing_version=9354")
        await setup.execute("DELETE FROM delivery_routing_versions WHERE version=9354")
        await setup.execute("UPDATE shipping_settings SET packing_overhead_percent=$1 WHERE id=1", x_orig)
        await setup.close()
