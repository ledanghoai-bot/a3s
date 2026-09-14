"""M7-B GHN adapter — unit voi HTTP gia (inject post) + conn gia. Moi loi -> quote_required (fail-closed), khong raise.
asyncio.run (repo khong dung pytest-asyncio)."""
import asyncio

from app.services.providers import ghn
from app.services.providers.base import QUOTE_OK, QUOTE_REQUIRED, QuoteRequest

CFG = {"enabled": True, "base": "https://dev-online-gateway.ghn.vn/shiip/public-api", "token": "T", "shop_id": "1",
       "from_district_id": 1000, "from_ward_code": "100", "timeout": 1.0, "retries": 1, "light_max_g": 20000,
       "map_version": 1}


class FakeConn:
    def __init__(self, mapped=True):
        self.logs = []
        self.mapped = mapped

    async def fetchrow(self, sql, *a):
        if "carrier_address_map" in sql:
            if not self.mapped:
                return None
            return {"carrier_province_id": 1, "carrier_district_id": 1655, "carrier_ward_code": "590913",
                    "status": "matched", "method": "legacy_alias_exact", "confidence": 1.0}
        return None

    async def execute(self, sql, *a):
        self.logs.append(a)


def _req(w=600):
    return QuoteRequest(order_id=1, province_code="66", ward_code="24316", weight_g=w, length_cm=20, width_cm=15,
                        height_cm=10)


def _post_factory(seq):
    calls = []

    async def post(cfg, path, body, *, retries):
        calls.append((path, body))
        item = seq.pop(0) if seq else (200, {"code": 200, "data": {"total": 0}}, "", 5)
        return item

    post.calls = calls
    return post


def test_service_type_and_dims_contract():
    assert ghn.service_type_for_weight(20000, 20000) == 2 and ghn.service_type_for_weight(20001, 20000) == 5
    assert ghn.default_dims_cm(600) == (20, 15, 10) and ghn.default_dims_cm(4000) == (30, 25, 20)
    assert ghn.default_dims_cm(9000) == (40, 30, 30)


def test_quote_ok_with_leadtime_and_snapshot():
    post = _post_factory([(200, {"code": 200, "message": "Success", "data": {"total": 31000, "service_fee": 30000,
                                                                              "insurance_fee": 1000}}, "", 40),
                          (200, {"code": 200, "data": {"leadtime": 4102444800}}, "", 10)])
    conn = FakeConn()
    res = asyncio.run(ghn.GhnQuoteProvider(CFG, post=post).quote(conn, _req()))
    assert res.status == QUOTE_OK and res.fee_vnd == 31000 and res.breakdown["service_fee"] == 30000
    assert res.leadtime_days and res.leadtime_days >= 1
    assert res.carrier_ids["to_district_id"] == 1655 and res.carrier_ids["to_ward_code"] == "590913"
    assert res.request_fingerprint == _req().fingerprint()
    body = post.calls[0][1]
    assert body["service_type_id"] == 2 and body["weight"] == 600 and body["to_ward_code"] == "590913"
    assert "Token" not in body and "ShopId" not in body
    assert conn.logs and conn.logs[-1][5] == "ok"          # provider_quote_log status
    snap = res.snapshot()
    assert snap["fee_vnd"] == 31000 and "token" not in str(snap).lower()


def test_disabled_or_not_configured_quote_required():
    cfg = dict(CFG, enabled=False)
    res = asyncio.run(ghn.GhnQuoteProvider(cfg, post=_post_factory([])).quote(FakeConn(), _req()))
    assert (res.status, res.reason) == (QUOTE_REQUIRED, "ghn_disabled")
    cfg = dict(CFG, token="")
    res = asyncio.run(ghn.GhnQuoteProvider(cfg, post=_post_factory([])).quote(FakeConn(), _req()))
    assert (res.status, res.reason) == (QUOTE_REQUIRED, "ghn_not_configured")


def test_address_unmapped_fail_closed_no_http():
    post = _post_factory([])
    res = asyncio.run(ghn.GhnQuoteProvider(CFG, post=post).quote(FakeConn(mapped=False), _req()))
    assert (res.status, res.reason) == (QUOTE_REQUIRED, "address_unmapped") and post.calls == []


def test_timeout_http_error_schema_error_all_quote_required():
    for seq, want in (
        ([(None, None, "timeout", 1000)], "ghn_timeout"),
        ([(500, {"code": 500, "message": "err"}, "", 20)], "ghn_http_500_code_500"),
        ([(400, {"code": 400, "message": "bad"}, "", 20)], "ghn_http_400_code_400"),
        ([(200, {"code": 200, "data": {"total": "31000"}}, "", 20)], "ghn_schema_total"),
        ([(200, {"code": 200, "data": {"total": -1}}, "", 20)], "ghn_schema_total"),
        ([(200, {"code": 200, "data": None}, "", 20)], "ghn_http_200_code_200"),
        ([(200, "not-json", "", 20)], "ghn_http_200_code_na"),
    ):
        conn = FakeConn()
        res = asyncio.run(ghn.GhnQuoteProvider(CFG, post=_post_factory(list(seq))).quote(conn, _req()))
        assert res.status == QUOTE_REQUIRED and res.reason == want, (seq, res.reason)
        assert res.fee_vnd is None
        assert conn.logs and conn.logs[-1][5] in ("error", "timeout")


def test_invalid_weight_no_call():
    post = _post_factory([])
    res = asyncio.run(ghn.GhnQuoteProvider(CFG, post=post).quote(FakeConn(), _req(0)))
    assert res.status == QUOTE_REQUIRED and res.reason == "invalid_weight_or_dims" and post.calls == []


def test_leadtime_days_helper():
    import time
    assert ghn._leadtime_days({"leadtime": int(time.time()) + 3 * 86400 + 10}) == 4
    assert ghn._leadtime_days({"leadtime": int(time.time()) - 100}) == 1
    assert ghn._leadtime_days({"leadtime": "x"}) is None and ghn._leadtime_days(None) is None
