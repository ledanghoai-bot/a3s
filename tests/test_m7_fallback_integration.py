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
    cid = await conn.fetchval("INSERT INTO customers (psid, channel, external_chat_id, name,phone) VALUES ($1, 'telegram_customer', $1, 'T','0900000000') RETURNING id",
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
            for k in ("chargeable_weight_kg", "provider_volumetric_weight_kg", "raw_volume_cm3", "packing_overhead_percent",
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
            assert snap["fee"]["reason"] == "packing_input_missing"
            assert snap["fee"]["packing_reason"] == "dimension_missing"   # 341-01: khong goi GHN, khong fallback
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
            assert snap["fee"]["reason"] == "packing_input_missing"
            assert snap["fee"]["packing_reason"] == "packing_overhead_invalid"
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


# ============================ CA Review 341-01: API request dung packed dims (cung contract fallback) ============
class _FakeProv:
    """Provider gia: ghi lai request, tra ket qua theo result_fn. Dem so lan goi (= provider effect)."""
    def __init__(self, result_fn):
        self.calls = []
        self.result_fn = result_fn

    async def quote(self, conn, req):
        self.calls.append(req)
        return self.result_fn(req)


def _ok(fee):
    from app.services.providers.base import QuoteResult
    return lambda req: QuoteResult(status="ok", provider="ghn", fee_vnd=fee, eta_text="2-3 ngay",
                                   request_fingerprint=req.fingerprint())


def _fail(reason):
    from app.services.providers.base import QuoteResult
    return lambda req: QuoteResult(status="quote_required", provider="ghn", reason=reason,
                                   request_fingerprint=req.fingerprint())


def _snap(out):
    import json
    s = out["quote_snapshot"]
    return json.loads(s) if isinstance(s, str) else s


@pytest.mark.asyncio
async def test_prepare_ghn_quote_packed_dims_and_no_call_on_missing_input():
    from app.db_pool import get_pool
    from app.services.fulfillment import conversation as fc
    pool = await get_pool()
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _seed_routing(conn)
            await _set_packing(conn, 10)
            prov = _FakeProv(_ok(33000))
            # hop le: 2 x cube10, x=10 -> packed 2200 -> hop 14^3; weight thuc 2500*2
            oid = await _mk_order(conn, province="79", ward="26734", weight=2500, qty=2, dims=(10, 10, 10))
            res = await fc.prepare_ghn_quote(conn, oid, provider=prov)
            assert res is not None and len(prov.calls) == 1
            req = prov.calls[0]
            assert (req.length_cm, req.width_cm, req.height_cm) == (14, 14, 14)   # KHONG phai default (30,25,20)
            assert req.weight_g == 5000
            # thieu dims -> KHONG goi provider
            oid2 = await _mk_order(conn, province="79", ward="26734", weight=2500, dims=None)
            assert await fc.prepare_ghn_quote(conn, oid2, provider=prov) is None and len(prov.calls) == 1
            # x chua cau hinh -> KHONG goi provider
            await conn.execute("UPDATE shipping_settings SET packing_overhead_percent=NULL WHERE id=1")
            assert await fc.prepare_ghn_quote(conn, oid, provider=prov) is None and len(prov.calls) == 1
            await _set_packing(conn, 10)
            # SELF_DELIVERY (noi thanh) -> KHONG goi provider
            oid3 = await _mk_order(conn, province="66", ward="24169", weight=600)
            assert await fc.prepare_ghn_quote(conn, oid3, provider=prov) is None and len(prov.calls) == 1
        finally:
            await tr.rollback()


@pytest.mark.asyncio
async def test_api_quote_ok_used_no_fallback_and_request_snapshot(monkeypatch):
    from app.config import settings
    from app.db_pool import get_pool
    from app.services.fulfillment import conversation as fc
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
            prov = _FakeProv(_ok(33000))
            res = await fc.prepare_ghn_quote(conn, oid, provider=prov)
            out = await ship.route_and_quote(conn, oid, actor="t", ghn_result=res)
            assert int(out["delivery_fee_vnd"]) == 33000 and out["quote_source"] == "auto_route"   # API uu tien
            s = _snap(out)
            assert s["request"]["dims_source"] == "packed_volume_box"
            assert s["request"]["request_dims_cm"] == [14, 14, 14]
            assert s["request"]["request_fingerprint"] == s["fee"]["request_fingerprint"] == prov.calls[0].fingerprint()
        finally:
            await tr.rollback()


@pytest.mark.asyncio
async def test_api_fail_fallback_uses_same_chargeable_inputs(monkeypatch):
    from app.config import settings
    from app.db_pool import get_pool
    from app.services.fulfillment import conversation as fc
    from app.services.fulfillment import shipment_service as ship
    monkeypatch.setattr(settings, "ghn_fallback_enabled", True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _seed_routing(conn)
            await _set_packing(conn, 25)
            # volumetric > actual: 3 x cube20 = 24000; x=25 -> packed 30000 -> hop gui GHN 32^3=32768 -> 6.5536kg;
            # actual 300*3=0.9kg. 342-01: W = 32768/5000 (KHONG phai packed 30000/5000=6.0)
            oid = await _mk_order(conn, province="79", ward="26734", weight=300, qty=3, dims=(20, 20, 20))
            for reason in ("ghn_timeout", "ghn_http_429_code_na", "ghn_http_500_code_500", "ghn_schema_total"):
                prov = _FakeProv(_fail(reason))
                res = await fc.prepare_ghn_quote(conn, oid, provider=prov)
                out = await ship.route_and_quote(conn, oid, actor="t", ghn_result=res)
                s = _snap(out)
                assert out["quote_source"] == "fallback_policy", reason
                req = prov.calls[0]
                sent_box = req.length_cm * req.width_cm * req.height_cm
                assert sent_box == 32768 and s["request"]["provider_box_volume_cm3"] == sent_box
                assert s["request"]["chargeable_weight_kg"] == s["fee"]["chargeable_weight_kg"] == sent_box / 5000
                assert s["fee"]["weight_basis"] == "provider_volumetric" and s["fee"]["api_error_reason"] == reason
                assert int(out["delivery_fee_vnd"]) == 40000 + 2 * 7000      # lien >5kg: ceil(6.5536-5)=2
        finally:
            await tr.rollback()


@pytest.mark.asyncio
async def test_route_operation_replay_single_provider_effect_and_no_call_missing_dims():
    from app.db_pool import get_pool
    from app.services.fulfillment import route_operation as ro
    pool = await get_pool()
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _seed_routing(conn)
            await _set_packing(conn, 10)
            oid = await _mk_order(conn, province="79", ward="26734", weight=2500, qty=2, dims=(10, 10, 10))
            prov = _FakeProv(_ok(33000))
            r1 = await ro.execute(conn, oid, actor="t", command_key="k341-a", provider=prov)
            r2 = await ro.execute(conn, oid, actor="t", command_key="k341-a", provider=prov)
            assert len(prov.calls) == 1                       # 1 provider effect / logical command
            assert r1["duplicate"] is False and r2["duplicate"] is True
            tag = await conn.fetchval("SELECT provider FROM fulfillment_route_operations WHERE order_id=$1 "
                                      "AND command_key='k341-a'", oid)
            assert tag == "ghn"
            # thieu dims -> KHONG goi provider, tag 'none' (khong phai ambiguous)
            oid2 = await _mk_order(conn, province="79", ward="26734", weight=2500, dims=None)
            prov2 = _FakeProv(_ok(33000))
            await ro.execute(conn, oid2, actor="t", command_key="k341-b", provider=prov2)
            assert len(prov2.calls) == 0
            tag2 = await conn.fetchval("SELECT provider FROM fulfillment_route_operations WHERE order_id=$1 "
                                       "AND command_key='k341-b'", oid2)
            assert tag2 == "none"
        finally:
            await tr.rollback()


@pytest.mark.asyncio
async def test_342_api_fail_fallback_w_from_sent_box_threshold(monkeypatch):
    """Vi du CA 342: 2 x cube10, x=10 -> packed 2200 nhung hop gui GHN 14^3=2744 -> W 0.5488kg -> bac 1kg (27000),
    KHONG phai 0.44kg (25000). API OK va API loi deu ghi cung W tu hop da gui."""
    from app.config import settings
    from app.db_pool import get_pool
    from app.services.fulfillment import conversation as fc
    from app.services.fulfillment import shipment_service as ship
    monkeypatch.setattr(settings, "ghn_fallback_enabled", True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _seed_routing(conn)
            await _set_packing(conn, 10)
            oid = await _mk_order(conn, province="79", ward="26734", weight=100, qty=2, dims=(10, 10, 10))  # actual 0.2kg
            prov = _FakeProv(_fail("ghn_timeout"))
            res = await fc.prepare_ghn_quote(conn, oid, provider=prov)
            out = await ship.route_and_quote(conn, oid, actor="t", ghn_result=res)
            req = prov.calls[0]
            sent = req.length_cm * req.width_cm * req.height_cm
            s = _snap(out)
            assert sent == 2744 and s["fee"]["packed_volume_cm3"] == 2200.0
            assert s["fee"]["chargeable_weight_kg"] == s["request"]["chargeable_weight_kg"] == sent / 5000
            assert out["quote_source"] == "fallback_policy" and int(out["delivery_fee_vnd"]) == 27000
            # API OK: snapshot request cung W tu hop da gui
            prov_ok = _FakeProv(_ok(31000))
            res2 = await fc.prepare_ghn_quote(conn, oid, provider=prov_ok)
            out2 = await ship.route_and_quote(conn, oid, actor="t", ghn_result=res2)
            s2 = _snap(out2)
            assert int(out2["delivery_fee_vnd"]) == 31000 and out2["quote_source"] == "auto_route"
            assert s2["request"]["chargeable_weight_kg"] == sent / 5000
            assert s2["request"]["provider_box_volume_cm3"] == prov_ok.calls[0].length_cm ** 3 == 2744
        finally:
            await tr.rollback()
