"""CA Directive 404 §2B/§2C — nhan zone nghiep vu + tra vet quote theo command_key.

Pure (CI-safe): zone_label/fee_label (GHN ngoai tinh KHONG hien 'unknown'; khong doi du lieu).
DB (skipif not M6_TEST_DB, moi test trong transaction ROLLBACK): route-quote GHN qua route_operation -> provider_quote_log
co trace_key=command_key + route_operation_id + endpoint + response_class; replay cung command_key KHONG them provider
call; quote_trace noi du chuoi order -> snapshot -> route decision -> quote log -> route op; self-delivery = 0 provider
call; luong bot (m7_routing:<order>) truy duoc; khong lo token/PII.
"""
import json
import os
import time

import pytest

from app.services.fulfillment import shipment_service as ship


def test_zone_label_business_not_unknown_for_ghn():
    assert ship.zone_label("GHN", "unknown") == "GHN ngoài khu vực tự giao"
    assert ship.zone_label("GHN", "province") == "GHN trong tỉnh (ngoài khu vực tự giao)"
    assert ship.zone_label("SELF_DELIVERY", "bmt_inner") == "Tự giao nội thành BMT"
    assert ship.zone_label("MANUAL_REVIEW", "unknown") == "Cần kiểm tra địa chỉ"
    assert ship.zone_label(None, "province") == "Trong tỉnh (bảng phí nội bộ)"
    assert ship.zone_label(None, "unknown") == "Chưa xác định khu vực"
    assert "unknown" not in ship.zone_label("GHN", "unknown")
    assert ship.fee_label("quoted") == "đã báo phí" and ship.fee_label(None) == "chưa xác định phí"


DB = os.environ.get("M6_TEST_DB") == "1"
dbonly = pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
_SEQ = [0]
MAPV = 404


async def _seed(conn, *, province, ward, weight=2500):
    _SEQ[0] += 1
    tag = f"q404-{_SEQ[0]}-{int(time.time()*1000)}"
    await conn.execute("INSERT INTO delivery_routing_versions(version, effective_from, effective_to, dataset_version, "
                       "created_by) VALUES (9404, now() - interval '1 day', NULL, 'VN-TEST', 't') "
                       "ON CONFLICT (version) DO UPDATE SET effective_to=NULL")
    await conn.execute("INSERT INTO delivery_self_wards(routing_version, province_code, ward_code, ward_name) "
                       "VALUES (9404, '66', '24169', 'Test') ON CONFLICT DO NOTHING")
    await conn.execute("UPDATE shipping_settings SET packing_overhead_percent=10 WHERE id=1")
    cid = await conn.fetchval("INSERT INTO customers (psid, channel, external_chat_id, name, phone) VALUES ($1, "
                              "'telegram_customer', $1, 'T', '0912345678') RETURNING id", f"tg:{tag}")
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,length_cm,width_cm,"
                              "height_cm) VALUES($1,'CF',100000,999,$2,10,10,10) RETURNING id", f"SKU-{tag}", weight)
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',"
                              "100000,'telegram_customer') RETURNING id", cid)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,1,100000)",
                       oid, pid)
    rid = await conn.fetchval("INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,"
                              "ward_code,method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,$1,$2,"
                              "'current',1.0) RETURNING id", province, ward)
    await conn.execute("INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,dataset_version,"
                       "verification_method,bound_by,street_text) VALUES($1,$2,$3,$4,'VN-TEST','test','t','1 Lê Lợi')",
                       oid, rid, province, ward)
    await conn.execute("INSERT INTO carrier_address_map (provider, mode, map_version, province_code, ward_code, "
                       "carrier_province_id, carrier_district_id, carrier_ward_code, status, method) VALUES "
                       "('ghn','staging',$1,$2,$3,202,1442,'20108','matched','staff') ON CONFLICT DO NOTHING",
                       MAPV, province, ward)
    return oid


def _provider():
    from app.services.providers import ghn
    calls = []

    async def post(cfg, path, body, *, retries):
        calls.append(path)
        if path.endswith("/fee"):
            return 200, {"code": 200, "data": {"total": 33000, "service_fee": 33000}}, "", 12
        return 200, {"code": 200, "data": {"leadtime": int(time.time()) + 2 * 86400}}, "", 5
    cfg = {"enabled": True, "base": "https://dev-online-gateway.ghn.vn/shiip/public-api", "token": "SECRET-TOKEN-404",
           "shop_id": "123456", "from_district_id": 1552, "from_ward_code": "400105", "timeout": 1, "retries": 0,
           "light_max_g": 20000, "map_version": MAPV, "mode": "staging"}
    return ghn.GhnQuoteProvider(cfg, post=post), calls


async def _tx():
    from app.db_pool import get_pool
    pool = await get_pool()
    conn = await pool.acquire()
    tr = conn.transaction()
    await tr.start()
    return pool, conn, tr


@dbonly
@pytest.mark.asyncio
async def test_route_quote_trace_links_command_key_to_quote_log_once():
    from app.services.fulfillment import quote_trace as qt
    from app.services.fulfillment import route_operation as ro
    pool, conn, tr = await _tx()
    try:
        oid = await _seed(conn, province="79", ward="26734")
        prov, calls = _provider()
        key = f"k404-{oid}"
        r1 = await ro.execute(conn, oid, actor="t", command_key=key, provider=prov)
        r2 = await ro.execute(conn, oid, actor="t", command_key=key, provider=prov)
        assert r1["duplicate"] is False and r2["duplicate"] is True
        assert calls.count("/v2/shipping-order/fee") == 1                  # 1 provider effect / command
        op_id = await conn.fetchval("SELECT id FROM fulfillment_route_operations WHERE command_key=$1", key)
        logs = await conn.fetch("SELECT trace_key, route_operation_id, endpoint, response_class, status "
                                "FROM provider_quote_log WHERE order_id=$1", oid)
        assert len(logs) == 1
        lg = logs[0]
        assert (lg["trace_key"], lg["route_operation_id"], lg["endpoint"], lg["response_class"], lg["status"]) == \
            (key, op_id, "/v2/shipping-order/fee+leadtime", "ok", "ok")
        t = await qt.trace(conn, key)
        assert t["logical_quote_attempts"] == 1 and len(t["route_operations"]) == 1 and t["route_operations"][0]["id"] == op_id
        o = t["orders"][0]
        assert o["order"]["id"] == oid and o["address_snapshot"]["ward_code"] == "26734"
        assert o["route_decision"]["routing_source"] == "GHN" and o["route_decision"]["fee_status"] == "quoted"
        assert o["route_decision"]["zone_label"] == "GHN ngoài khu vực tự giao"
        assert len(o["quote_logs"]) == 1 and len(o["audit"]) >= 1
        blob = json.dumps(t, default=str, ensure_ascii=False)
        assert "SECRET-TOKEN-404" not in blob and "0912345678" not in blob and "Lê Lợi" not in blob
        assert "123456" not in blob
        assert '"actor_ref"' not in blob and '"dedupe_key"' not in blob and "tg:q404" not in blob
    finally:
        await tr.rollback()
        await pool.release(conn)


@dbonly
@pytest.mark.asyncio
async def test_self_delivery_trace_zero_provider_and_bot_path_trace():
    from app.services.fulfillment import conversation as fc
    from app.services.fulfillment import quote_trace as qt
    from app.services.fulfillment import route_operation as ro
    pool, conn, tr = await _tx()
    try:
        oid = await _seed(conn, province="66", ward="24169")
        prov, calls = _provider()
        key = f"k404-self-{oid}"
        await ro.execute(conn, oid, actor="t", command_key=key, provider=prov)
        t = await qt.trace(conn, key)
        assert calls == [] and t["logical_quote_attempts"] == 0 and t["http_requests"] == 0 and t["quote_log_count"] == 0
        assert t["orders"][0]["route_decision"]["routing_source"] == "SELF_DELIVERY"
        assert t["route_operations"][0]["provider"] == "none"
        # luong bot/worker: trace_key m7_routing:<order>
        oid2 = await _seed(conn, province="79", ward="26735")
        prov2, calls2 = _provider()
        res = await fc.prepare_ghn_quote(conn, oid2, provider=prov2, trace={"trace_key": f"m7_routing:{oid2}"})
        assert res.status == "ok" and calls2.count("/v2/shipping-order/fee") == 1
        t2 = await qt.trace(conn, f"m7_routing:{oid2}")
        assert t2["logical_quote_attempts"] == 1 and t2["orders"][0]["order"]["id"] == oid2
        # mac dinh (khong truyen trace) -> order:<id>
        oid3 = await _seed(conn, province="79", ward="26736")
        prov3, _ = _provider()
        await fc.prepare_ghn_quote(conn, oid3, provider=prov3)
        assert await conn.fetchval("SELECT trace_key FROM provider_quote_log WHERE order_id=$1", oid3) == f"order:{oid3}"
    finally:
        await tr.rollback()
        await pool.release(conn)


@dbonly
@pytest.mark.asyncio
async def test_http_attempts_counts_real_requests_including_retry(monkeypatch):
    """CA Review 406: 1 dong log = 1 quote LOGIC; http_attempts = so HTTP THAT (fee 503 -> retry 200 + leadtime = 3)."""
    import httpx

    from app.services.fulfillment import quote_trace as qt
    from app.services.fulfillment import route_operation as ro
    from app.services.providers import ghn
    seen = {"fee": 0, "leadtime": 0, "auth_headers": set()}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth_headers"].add(request.headers.get("Token"))
        if request.url.path.endswith("/fee"):
            seen["fee"] += 1
            if seen["fee"] == 1:
                return httpx.Response(503, json={"code": 503})
            return httpx.Response(200, json={"code": 200, "data": {"total": 41000}})
        seen["leadtime"] += 1
        return httpx.Response(200, json={"code": 200, "data": {"leadtime": int(time.time()) + 3 * 86400}})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(ghn.httpx, "AsyncClient",
                        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))

    async def no_sleep(*a, **k):
        return None
    monkeypatch.setattr(ghn.asyncio, "sleep", no_sleep)
    pool, conn, tr = await _tx()
    try:
        oid = await _seed(conn, province="79", ward="26737")
        cfg = {"enabled": True, "base": "https://dev-online-gateway.ghn.vn/shiip/public-api",
               "token": "SECRET-TOKEN-404", "shop_id": "123456", "from_district_id": 1552, "from_ward_code": "400105",
               "timeout": 2, "retries": 1, "light_max_g": 20000, "map_version": MAPV, "mode": "staging"}
        key = f"k404-http-{oid}"
        await ro.execute(conn, oid, actor="t", command_key=key, provider=ghn.GhnQuoteProvider(cfg))
        assert (seen["fee"], seen["leadtime"]) == (2, 1)
        row = await conn.fetchrow("SELECT http_attempts, response_class, request::text AS req FROM provider_quote_log "
                                  "WHERE trace_key=$1", key)
        assert row["http_attempts"] == 3 and row["response_class"] == "ok" and "SECRET-TOKEN-404" not in row["req"]
        t = await qt.trace(conn, key)
        assert t["logical_quote_attempts"] == 1 and t["http_requests"] == 3
    finally:
        await tr.rollback()
        await pool.release(conn)
