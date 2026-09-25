"""CA Directive 393 — GHN shipment create (Bot + Dashboard), lifecycle chung, gate OFF mac dinh.

Pure (CI-safe): payload tu snapshot, phan loai ket qua adapter (created/rejected/retryable/unknown, 429 Retry-After,
connect vs read-timeout), lookup doi soat, redaction, xac nhan cuoi cua khach, gate mac dinh OFF, route RBAC.
DB (skipif not M6_TEST_DB): eligibility + guard (self/heavy/unmapped/payment/attention/quote/cancelled), prepare
(xac nhan fingerprint, replay, 1 active/order, conflict, dong thoi), snapshot bat bien, gate OFF = 0 HTTP, happy create,
timeout -> unknown (khong blind retry), 429 -> retry sau doi soat, 5xx bounded -> terminal, 4xx terminal, doi soat found,
revalidate truoc dispatch, huy truoc/sau dispatch, luong Bot (offer -> XAC NHAN GIAO -> prepared), khong PII trong audit.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.fulfillment import conversation as C
from app.services.fulfillment import ghn_shipment_create as G
from app.services.providers import ghn_create as P

SNAP = {
    "order": {"id": 7, "status": "confirmed", "total_vnd": 200000},
    "recipient": {"name": "Nguyễn A", "phone": "0912345678", "address_text": "1 Lê Lợi, P. Bến Nghé, TP.HCM"},
    "address": {"carrier_district_id": 1442, "carrier_ward_code": "20108"},
    "pickup": {"from_district_id": 1552, "from_ward_code": "400105"},
    "parcel": {"weight_g": 600, "length_cm": 20, "width_cm": 15, "height_cm": 10, "service_type_id": 2,
               "insurance_value_vnd": 0},
    "payment": {"method": "COD", "cod_amount_vnd": 230000},
    "items": [{"name": "Cà phê", "quantity": 2, "weight_g": 300}],
    "policy": {"payment_type_id": 1, "required_note": "KHONGCHOXEMHANG"},
}


class _Resp:
    def __init__(self, status, headers=None):
        self.status_code, self.headers = status, headers or {}


def _send(status=None, js=None, err="", headers=None):
    calls = []

    async def send(cfg, path, body):
        calls.append((path, body))
        return (_Resp(status, headers) if status is not None else None), js, err, 5
    send.calls = calls
    return send


def _run(coro):
    return asyncio.run(coro)


# ============================================================ pure
def test_payload_from_frozen_snapshot_only():
    b = P.build_create_payload(SNAP, "A3S-7-1")
    assert b["client_order_code"] == "A3S-7-1" and b["cod_amount"] == 230000 and b["to_district_id"] == 1442
    assert b["from_ward_code"] == "400105" and b["service_type_id"] == 2 and b["items"][0]["quantity"] == 2
    assert "Token" not in json.dumps(b) and G.client_order_code(7, 1) == "A3S-7-1"


@pytest.mark.parametrize("status,js,err,headers,outcome,extra", [
    (200, {"code": 200, "data": {"order_code": "GHN123", "total_fee": 30000, "to_phone": "0912345678"}}, "", None,
     "created", "GHN123"),
    (200, {"code": 200, "data": {}}, "", None, "unknown", None),
    (200, {"code": 400, "message": "sai ward"}, "", None, "rejected", None),
    (400, {"code": 400, "message": "invalid"}, "", None, "rejected", None),
    (429, {"code": 429}, "", {"Retry-After": "120"}, "retryable", 120),
    (503, None, "", None, "retryable", None),
    (None, None, "connect", None, "retryable", None),
    (None, None, "timeout_read", None, "unknown", None),
    (None, None, "protocol", None, "unknown", None),
])
def test_create_outcome_classification(status, js, err, headers, outcome, extra):
    prov = P.GhnCreateProvider({"base": "x", "token": "t", "timeout": 1}, send=_send(status, js, err, headers))
    r = _run(prov.create(SNAP, "A3S-7-1"))
    assert r.outcome == outcome
    if outcome == "created":
        assert r.order_code == extra and "to_phone" not in r.result          # redaction: khong PII
    if status == 429:
        assert r.retry_after_s == extra


def test_retry_after_capped_and_lookup():
    prov = P.GhnCreateProvider({}, send=_send(429, {"code": 429}, "", {"Retry-After": "999999"}))
    assert _run(prov.create(SNAP, "c")).retry_after_s == P.RETRY_AFTER_MAX_S
    f = P.GhnCreateProvider({}, send=_send(200, {"code": 200, "data": {"order_code": "G1", "client_order_code": "c"}}))
    assert _run(f.lookup("c")).outcome == "found"
    nf = P.GhnCreateProvider({}, send=_send(400, {"code": 400, "message": "Order not found"}))
    assert _run(nf.lookup("c")).outcome == "not_found"
    uk = P.GhnCreateProvider({}, send=_send(None, None, "timeout_read"))
    assert _run(uk.lookup("c")).outcome == "unknown"
    mm = P.GhnCreateProvider({}, send=_send(200, {"code": 200, "data": {"order_code": "G1", "client_order_code": "z"}}))
    assert _run(mm.lookup("c")).outcome == "unknown"


def test_customer_final_confirmation_phrase():
    for ok in ("XÁC NHẬN GIAO", "xac nhan giao hang", "Đồng ý giao", "xác nhận tạo vận đơn"):
        assert C.is_ship_confirmation(ok), ok
    for no in ("ok", "xác nhận", "không xác nhận giao", "chưa xác nhận giao", "giao đi", ""):
        assert not C.is_ship_confirmation(no), no


def test_gates_default_off_and_route_rbac():
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.ghn_shipment_create_bot_enabled is False and s.ghn_shipment_create_dashboard_enabled is False
    from app.api import ghn_shipment_create as api
    assert api.PERM == "shipment.ghn.create"
    for r in api.router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert any(getattr(d, "__qualname__", "").startswith("require_permission") or
                   "require_permission" in repr(d) for d in deps), r.path


# ============================================================ DB
DB = os.environ.get("M6_TEST_DB") == "1"
dbonly = pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
MAPV = 393
ROUTEV = 9393


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


async def _env(conn):
    """Routing version + integration GHN staging (map v393) + map row. Tra integration id."""
    await conn.execute("INSERT INTO delivery_routing_versions(version, effective_from, effective_to, dataset_version, "
                       "created_by) VALUES ($1, now() - interval '1 day', NULL, 'VN-TEST', 't') "
                       "ON CONFLICT (version) DO UPDATE SET effective_to=NULL", ROUTEV)
    iid = await conn.fetchval("SELECT id FROM integrations WHERE provider='ghn' AND mode='staging' AND enabled "
                              "AND archived_at IS NULL")
    if iid is None:
        iid = await conn.fetchval(
            "INSERT INTO integrations (kind, provider, label, mode, enabled, config_public) VALUES "
            "('shipping','ghn','GHN test 393','staging',true,$1::jsonb) RETURNING id",
            json.dumps({"base_url": "https://dev-online-gateway.ghn.vn/shiip/public-api", "shop_id": "1",
                        "from_district_id": 1552, "from_ward_code": "400105", "address_map_version": MAPV,
                        "light_max_g": 20000}))
    cp = await conn.fetchval("SELECT config_public FROM integrations WHERE id=$1", iid)
    cp = json.loads(cp) if isinstance(cp, str) else cp
    return iid, int(cp.get("address_map_version") or 1)


async def _cleanup_env(conn, iid):
    await conn.execute("UPDATE delivery_routing_versions SET effective_to=now() WHERE version=$1", ROUTEV)
    await conn.execute("UPDATE integrations SET enabled=false, archived_at=now() WHERE id=$1 AND label='GHN test 393'",
                       iid)


async def _seed(conn, mapv, *, weight=600, pay_method="COD", pay_status="awaiting", ward=None, mapped=True,
                quoted=True, channel="telegram_customer"):
    from app.services.fulfillment import fallback_quote as fb
    from app.services.fulfillment import routing as r
    tag = uuid.uuid4().hex[:10]
    ward = ward or f"9{int(tag[:5], 16) % 90000:05d}"
    psid = f"tg:393-{tag}"
    cid = await conn.fetchval("INSERT INTO customers(psid,channel,external_chat_id,name,phone) VALUES ($1,$2,$3,'Chủ',"
                              "'0900000000') RETURNING id", psid, channel, psid[3:])
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,length_cm,width_cm,"
                              "height_cm) VALUES ($1,'Cà phê',100000,99,$2,10,10,11) RETURNING id", f"T393-{tag}", weight)
    staff = await _staff(conn) if channel == "dashboard" else None
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel,shipping_name,"
                              "shipping_phone,shipping_address,created_by_staff_id) VALUES ($1,'confirmed',100000,$2,"
                              "'Người Nhận','0912345678','1 Le Loi',$3) RETURNING id", cid, channel, staff)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES ($1,$2,1,100000)",
                       oid, pid)
    rid = await conn.fetchval("INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,"
                              "ward_code,method,confidence) VALUES ('order','auto_verified','[]'::jsonb,'[]'::jsonb,'79',"
                              "$1,'current',1.0) RETURNING id", ward)
    await conn.execute("INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,dataset_version,"
                       "verification_method,bound_by,street_text,ward_name,province_name) VALUES ($1,$2,'79',$3,'VN-TEST',"
                       "'test','t','1 Lê Lợi','Phường Test','TP.HCM')", oid, rid, ward)
    if mapped:
        await conn.execute("INSERT INTO carrier_address_map (provider, mode, map_version, province_code, ward_code, "
                           "carrier_province_id, carrier_district_id, carrier_ward_code, status, method) VALUES "
                           "('ghn','staging',$1,'79',$2,202,1442,'20108','matched','staff') ON CONFLICT DO NOTHING",
                           mapv, ward)
    route = await r.resolve_for_order(conn, oid)
    req, _, _ = await fb.build_ghn_request(conn, oid, route, weight)
    fee_snap = {"fee": {"status": "ok" if quoted else "quote_required",
                        "request_fingerprint": req.fingerprint() if req else None}}
    await conn.execute(
        "INSERT INTO shipments(order_id,status,zone,fee_status,delivery_fee_vnd,quote_provider,quote_source,quoted_at,"
        "quote_snapshot,weight_g) VALUES ($1,'pending_prep','unknown',$2,$3,'ghn','auto_route',now(),$4::jsonb,$5)",
        oid, "quoted" if quoted else "quote_required", 30000 if quoted else None, json.dumps(fee_snap), weight)
    await conn.execute("INSERT INTO payments(order_id,method,amount_due_vnd,amount_received_vnd,status) "
                       "VALUES ($1,$2,130000,$3,$4)", oid, pay_method,
                       130000 if pay_status in ("confirmed", "reconciled") else 0, pay_status)
    return {"oid": oid, "cid": cid, "psid": psid, "ward": ward}


async def _staff(conn, role="admin"):
    return await conn.fetchval("INSERT INTO staff_users(username,password_hash,password_salt,role_key) "
                               "VALUES ($1,'x','x',$2) RETURNING id", f"t393-{role}-{uuid.uuid4().hex[:8]}", role)


async def _prepare(conn, oid, staff, key=None):
    ev = await G.evaluate(conn, oid, source="dashboard")
    assert ev["eligible"], ev["blockers"]
    async with conn.transaction():
        return await G.prepare(conn, oid, source="dashboard", command_key=key or uuid.uuid4().hex, actor="t",
                               staff_id=staff, confirm_fingerprint=ev["fingerprint"])


class FakeProv:
    def __init__(self, creates=(), lookups=()):
        self.creates, self.lookups, self.calls = list(creates), list(lookups), []

    async def create(self, snapshot, code):
        self.calls.append("create")
        return self.creates.pop(0)

    async def lookup(self, code):
        self.calls.append("lookup")
        return self.lookups.pop(0)


def _fac(prov):
    return lambda cfg: prov


@pytest.fixture
def gate_on(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ghn_shipment_create_dashboard_enabled", True)

    async def fake_cfg(conn, op):
        return {"base": "x", "token": "t", "shop_id": "1", "timeout": 1}, ""
    monkeypatch.setattr(G, "_create_cfg", fake_cfg)
    return settings


async def _op(conn, op_id):
    return dict(await conn.fetchrow("SELECT * FROM ghn_shipment_create_operations WHERE id=$1", op_id))


@dbonly
@pytest.mark.asyncio
async def test_eligibility_guards_and_redacted_preview():
    conn = await _conn()
    iid, mapv = await _env(conn)
    try:
        ok = await _seed(conn, mapv)
        ev = await G.evaluate(conn, ok["oid"], source="dashboard")
        assert ev["eligible"], ev["blockers"]
        pv = G.redacted_preview(ev)
        assert pv["snapshot"]["recipient"]["phone"] == "***678" and "0912345678" not in json.dumps(pv)
        assert pv["snapshot"]["payment"]["cod_amount_vnd"] == 130000
        cases = [
            (dict(weight=25000), "heavy_goods"),
            (dict(mapped=False), "address_unmapped"),
            (dict(pay_method="BANK_TRANSFER", pay_status="awaiting"), "payment_not_confirmed"),
            (dict(quoted=False), "quote_not_ghn_api_ok"),
            (dict(channel="dashboard"), "customer_not_messaging"),
        ]
        for kw, blocker in cases:
            s = await _seed(conn, mapv, **kw)
            ev = await G.evaluate(conn, s["oid"], source="bot")
            assert blocker in ev["blockers"], (kw, ev["blockers"])
        # transfer DA xac nhan -> du dieu kien (khong thu COD)
        t = await _seed(conn, mapv, pay_method="BANK_TRANSFER", pay_status="confirmed")
        evt = await G.evaluate(conn, t["oid"], source="bot")
        assert evt["eligible"] and evt["snapshot"]["payment"]["cod_amount_vnd"] == 0
        # self delivery (ward trong allowlist)
        s = await _seed(conn, mapv)
        await conn.execute("INSERT INTO delivery_self_wards(routing_version,province_code,ward_code,ward_name) "
                           "VALUES ($1,'79',$2,'x')", ROUTEV, s["ward"])
        assert "self_delivery" in (await G.evaluate(conn, s["oid"], source="dashboard"))["blockers"]
        # attention mo / don huy
        s = await _seed(conn, mapv)
        await conn.execute("INSERT INTO staff_attention(order_id,reason,detail,created_by) VALUES ($1,'refund_required',"
                           "'{}'::jsonb,'t')", s["oid"])
        b = (await G.evaluate(conn, s["oid"], source="dashboard"))["blockers"]
        assert "staff_attention_open" in b and "refund_or_exception_pending" in b
        s = await _seed(conn, mapv)
        await conn.execute("UPDATE orders SET status='cancelled' WHERE id=$1", s["oid"])
        assert "order_cancelled" in (await G.evaluate(conn, s["oid"], source="dashboard"))["blockers"]
        # quote qua han
        s = await _seed(conn, mapv)
        await conn.execute("UPDATE shipments SET quoted_at=now() - interval '30 hours' WHERE order_id=$1", s["oid"])
        assert "quote_expired" in (await G.evaluate(conn, s["oid"], source="dashboard"))["blockers"]
    finally:
        await _cleanup_env(conn, iid)
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_prepare_confirmation_replay_one_active_and_freeze():
    conn = await _conn()
    iid, mapv = await _env(conn)
    try:
        st = await _staff(conn)
        s = await _seed(conn, mapv)
        with pytest.raises(G.ShipmentCreateError) as e:
            async with conn.transaction():
                await G.prepare(conn, s["oid"], source="dashboard", command_key="k-bad", actor="t", staff_id=st,
                                confirm_fingerprint="sai")
        assert e.value.code == "confirmation_stale"
        key = uuid.uuid4().hex
        r1 = await _prepare(conn, s["oid"], st, key)
        async with conn.transaction():
            r2 = await G.prepare(conn, s["oid"], source="dashboard", command_key=key, actor="t", staff_id=st,
                                 confirm_fingerprint="bat-ky")   # replay: tra receipt cu, khong danh gia lai
        assert r2["duplicate"] and r2["operation"]["id"] == r1["operation"]["id"]
        assert r1["operation"]["state"] == "prepared" and "client_order_code" not in r1["operation"]
        with pytest.raises(G.ShipmentCreateError) as e2:
            async with conn.transaction():
                await G.prepare(conn, s["oid"], source="dashboard", command_key=uuid.uuid4().hex, actor="t",
                                staff_id=st, confirm_fingerprint="x")
        assert e2.value.code == "not_eligible" and "operation_active" in e2.value.blockers
        other = await _seed(conn, mapv)
        with pytest.raises(G.ShipmentCreateError) as e3:
            async with conn.transaction():
                await G.prepare(conn, other["oid"], source="dashboard", command_key=key, actor="t", staff_id=st,
                                confirm_fingerprint="x")
        assert e3.value.code == "idempotency_conflict"
        import asyncpg
        with pytest.raises(asyncpg.RaiseError):
            await conn.execute("UPDATE ghn_shipment_create_operations SET request_snapshot='{}'::jsonb WHERE id=$1",
                               r1["operation"]["id"])
        # audit prepare khong chua PII
        aud = await conn.fetchval("SELECT after::text FROM audit_log WHERE action='shipment.ghn_create.prepare' "
                                  "AND entity_id=$1", str(r1["operation"]["id"]))
        assert "0912345678" not in aud and "Người Nhận" not in aud
    finally:
        await _cleanup_env(conn, iid)
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_concurrent_prepare_one_wins():
    c1, c2 = await _conn(), await _conn()
    iid, mapv = await _env(c1)
    try:
        st = await _staff(c1)
        s = await _seed(c1, mapv)
        ev = await G.evaluate(c1, s["oid"], source="dashboard")

        async def go(c):
            try:
                async with c.transaction():
                    await G.prepare(c, s["oid"], source="dashboard", command_key=uuid.uuid4().hex, actor="t",
                                    staff_id=st, confirm_fingerprint=ev["fingerprint"])
                return "ok"
            except G.ShipmentCreateError as e:
                return e.code
        res = await asyncio.gather(go(c1), go(c2))
        assert sorted(res) == ["not_eligible", "ok"], res
        assert await c1.fetchval("SELECT count(*) FROM ghn_shipment_create_operations WHERE order_id=$1", s["oid"]) == 1
    finally:
        await _cleanup_env(c1, iid)
        await c1.close()
        await c2.close()


@dbonly
@pytest.mark.asyncio
async def test_gate_off_zero_http_audited_once(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ghn_shipment_create_dashboard_enabled", False)
    conn = await _conn()
    iid, mapv = await _env(conn)
    try:
        st = await _staff(conn)
        s = await _seed(conn, mapv)
        op_id = (await _prepare(conn, s["oid"], st))["operation"]["id"]

        def boom(cfg):
            raise AssertionError("gate OFF khong duoc tao provider")
        for _ in range(2):
            stats = await G.run_dispatch_once(provider_factory=boom, op_ids=[op_id])
            assert stats["http_calls"] == 0 and stats["gate_blocked"] == 1
        op = await _op(conn, op_id)
        assert op["state"] == "prepared" and op["gate_blocked_reason"] == "gate_off" and op["attempt_count"] == 0
        assert await conn.fetchval("SELECT count(*) FROM audit_log WHERE action='shipment.ghn_create.gate_blocked' "
                                   "AND entity_id=$1", str(op_id)) == 1
    finally:
        await _cleanup_env(conn, iid)
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_happy_create_evidence_shipment_and_notify(gate_on):
    conn = await _conn()
    iid, mapv = await _env(conn)
    try:
        st = await _staff(conn)
        s = await _seed(conn, mapv)
        op_id = (await _prepare(conn, s["oid"], st))["operation"]["id"]
        prov = FakeProv(creates=[P.ProviderOutcome("created", http_status=200, order_code="GHNOK1",
                                                   result={"order_code": "GHNOK1", "total_fee": 30000})])
        stats = await G.run_dispatch_once(provider_factory=_fac(prov), op_ids=[op_id])
        assert stats["created"] == 1 and prov.calls == ["create"]
        op = await _op(conn, op_id)
        assert op["state"] == "succeeded" and op["provider_order_code"] == "GHNOK1" and op["attempt_count"] == 1
        sh = await conn.fetchrow("SELECT status, carrier, tracking_text FROM shipments WHERE order_id=$1", s["oid"])
        assert (sh["status"], sh["carrier"], sh["tracking_text"]) == ("pending_prep", "GHN", "GHNOK1")
        assert await conn.fetchval("SELECT count(*) FROM ghn_shipment_create_attempts WHERE operation_id=$1", op_id) == 1
        ob = await conn.fetchrow("SELECT destination, payload::text p FROM outbox_events WHERE dedupe_key=$1",
                                 f"ghn_created:{op_id}")
        assert ob["destination"] == "telegram_customer" and "GHNOK1" in ob["p"]
        # chay lai: khong dispatch lan 2
        again = await G.run_dispatch_once(provider_factory=_fac(FakeProv()), op_ids=[op_id])
        assert again["picked"] == 0
    finally:
        await _cleanup_env(conn, iid)
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_timeout_unknown_no_blind_retry_then_reconcile_found(gate_on):
    conn = await _conn()
    iid, mapv = await _env(conn)
    try:
        st = await _staff(conn)
        s = await _seed(conn, mapv)
        op_id = (await _prepare(conn, s["oid"], st))["operation"]["id"]
        prov = FakeProv(creates=[P.ProviderOutcome("unknown", error_class="timeout_read")])
        await G.run_dispatch_once(provider_factory=_fac(prov), op_ids=[op_id])
        op = await _op(conn, op_id)
        assert op["state"] == "unknown_reconciliation_required"
        assert await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND reason='shipment_create' "
                                   "AND status='open'", s["oid"]) == 1
        again = await G.run_dispatch_once(provider_factory=_fac(FakeProv()), op_ids=[op_id])
        assert again["picked"] == 0 and again["http_calls"] == 0          # KHONG blind retry
        lk = FakeProv(lookups=[P.ProviderOutcome("found", http_status=200, order_code="GHNREC")])
        out = await G.reconcile(conn, op_id, staff_id=st, actor="t", provider_factory=_fac(lk))
        assert out["lookup"] == "found" and (await _op(conn, op_id))["provider_order_code"] == "GHNREC"
        assert lk.calls == ["lookup"]
        assert await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND reason='shipment_create' "
                                   "AND status='open'", s["oid"]) == 0
    finally:
        await _cleanup_env(conn, iid)
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_429_retry_after_then_reconcile_before_create(gate_on):
    conn = await _conn()
    iid, mapv = await _env(conn)
    try:
        st = await _staff(conn)
        s = await _seed(conn, mapv)
        op_id = (await _prepare(conn, s["oid"], st))["operation"]["id"]
        p1 = FakeProv(creates=[P.ProviderOutcome("retryable", http_status=429, error_class="http_429", retry_after_s=600)])
        await G.run_dispatch_once(provider_factory=_fac(p1), op_ids=[op_id])
        op = await _op(conn, op_id)
        assert op["state"] == "failed_retryable"
        assert op["next_attempt_at"] - datetime.now(timezone.utc) > timedelta(seconds=500)   # ton trong Retry-After
        assert (await G.run_dispatch_once(provider_factory=_fac(FakeProv()), op_ids=[op_id]))["picked"] == 0
        await conn.execute("UPDATE ghn_shipment_create_operations SET next_attempt_at=now() WHERE id=$1", op_id)
        p2 = FakeProv(creates=[P.ProviderOutcome("created", http_status=200, order_code="GHN429")],
                      lookups=[P.ProviderOutcome("not_found", http_status=400)])
        await G.run_dispatch_once(provider_factory=_fac(p2), op_ids=[op_id])
        assert p2.calls == ["lookup", "create"] and (await _op(conn, op_id))["state"] == "succeeded"
    finally:
        await _cleanup_env(conn, iid)
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_5xx_bounded_then_terminal_and_4xx_terminal(gate_on):
    conn = await _conn()
    iid, mapv = await _env(conn)
    try:
        st = await _staff(conn)
        s = await _seed(conn, mapv)
        op_id = (await _prepare(conn, s["oid"], st))["operation"]["id"]
        n = G.POLICY["max_attempts"]
        prov = FakeProv(creates=[P.ProviderOutcome("retryable", http_status=503, error_class="http_503")] * n,
                        lookups=[P.ProviderOutcome("not_found", http_status=400)] * n)
        for _ in range(n):
            await conn.execute("UPDATE ghn_shipment_create_operations SET next_attempt_at=now() WHERE id=$1 "
                               "AND state='failed_retryable'", op_id)
            await G.run_dispatch_once(provider_factory=_fac(prov), op_ids=[op_id])
        op = await _op(conn, op_id)
        assert op["state"] == "failed_terminal" and op["terminal_reason"] == "max_attempts"
        assert prov.calls.count("create") == n and prov.calls.count("lookup") == n - 1
        s2 = await _seed(conn, mapv)
        op2 = (await _prepare(conn, s2["oid"], st))["operation"]["id"]
        p4 = FakeProv(creates=[P.ProviderOutcome("rejected", http_status=400, error_class="rejected_http_400_code_400")])
        await G.run_dispatch_once(provider_factory=_fac(p4), op_ids=[op2])
        assert (await _op(conn, op2))["state"] == "failed_terminal"
        assert await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND reason='shipment_create'",
                                   s2["oid"]) == 1
        # terminal -> duoc tao yeu cau moi (khong con active)
        assert (await G.evaluate(conn, s2["oid"], source="dashboard"))["blockers"] == ["staff_attention_open"]
    finally:
        await _cleanup_env(conn, iid)
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_revalidation_before_dispatch_blocks_http(gate_on):
    conn = await _conn()
    iid, mapv = await _env(conn)
    try:
        st = await _staff(conn)
        s = await _seed(conn, mapv)
        op_id = (await _prepare(conn, s["oid"], st))["operation"]["id"]
        await conn.execute("UPDATE shipments SET delivery_fee_vnd=45000, version=version+1 WHERE order_id=$1", s["oid"])
        prov = FakeProv()
        stats = await G.run_dispatch_once(provider_factory=_fac(prov), op_ids=[op_id])
        assert prov.calls == [] and stats["terminal"] == 1
        assert (await _op(conn, op_id))["terminal_reason"] == "snapshot_changed"
    finally:
        await _cleanup_env(conn, iid)
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_cancel_before_and_after_dispatch(gate_on):
    from app.services.command import lifecycle, registry
    from app.services.command.envelope import Actor
    conn = await _conn()
    iid, mapv = await _env(conn)

    async def cancel(oid, sid):
        env = lifecycle.build_lifecycle_envelope(command_type=registry.ORDER_CANCEL,
                                                 payload={"order_id": oid, "reason": "Khách đổi ý 393"},
                                                 actor=Actor("staff", str(sid)), channel="dashboard",
                                                 idempotency_key=uuid.uuid4().hex)
        return await lifecycle.execute_lifecycle(env)
    try:
        admin, sales = await _staff(conn), await _staff(conn, "sales")
        s = await _seed(conn, mapv)
        op_id = (await _prepare(conn, s["oid"], admin))["operation"]["id"]
        r = await cancel(s["oid"], admin)
        assert r.outcome == "succeeded", r
        assert (await _op(conn, op_id))["state"] == "cancelled_before_dispatch"
        s2 = await _seed(conn, mapv)
        op2 = (await _prepare(conn, s2["oid"], admin))["operation"]["id"]
        await G.run_dispatch_once(provider_factory=_fac(FakeProv(creates=[P.ProviderOutcome(
            "created", http_status=200, order_code="GHNC")])), op_ids=[op2])
        r2 = await cancel(s2["oid"], sales)
        assert r2.outcome == "rejected" and r2.error_code == "ghn_shipment_dispatched"
        assert await conn.fetchval("SELECT status FROM orders WHERE id=$1", s2["oid"]) == "confirmed"
        r3 = await cancel(s2["oid"], admin)
        assert r3.outcome == "succeeded", r3
        assert (await _op(conn, op2))["state"] == "succeeded"                      # khong gia vo huy GHN
        assert await conn.fetchval("SELECT status FROM shipments WHERE order_id=$1", s2["oid"]) == "pending_prep"
        assert await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND status='open' "
                                   "AND reason='order_cancel_exception'", s2["oid"]) == 1
    finally:
        await _cleanup_env(conn, iid)
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_bot_offer_confirm_prepares_and_gate_off_unchanged(monkeypatch):
    from app.config import settings
    conn = await _conn()
    iid, mapv = await _env(conn)
    try:
        async def start(s):
            await conn.execute("INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,policy_version)"
                               " VALUES ($1,'telegram_customer',$2,'awaiting_method',1)", s["oid"], s["psid"])

        async def say(s, text):
            async with conn.transaction():
                return await C.handle_customer_text(conn, s["psid"], text, command_key=uuid.uuid4().hex)
        monkeypatch.setattr(settings, "ghn_shipment_create_bot_enabled", False)
        s0 = await _seed(conn, mapv)
        await start(s0)
        r0 = await say(s0, "COD")
        assert "vận đơn" not in r0 and await conn.fetchval(
            "SELECT step FROM fulfillment_conversations WHERE order_id=$1", s0["oid"]) == "cod_handoff"

        monkeypatch.setattr(settings, "ghn_shipment_create_bot_enabled", True)
        s = await _seed(conn, mapv)
        await start(s)
        r1 = await say(s, "COD")
        assert "XÁC NHẬN GIAO" in r1 and await conn.fetchval(
            "SELECT step FROM fulfillment_conversations WHERE order_id=$1", s["oid"]) == "ship_confirm"
        assert await say(s, "cho em hỏi thêm") is None                     # khong phai xac nhan -> khong tao
        r2 = await say(s, "Xác nhận giao")
        assert "đang tạo vận đơn" in r2
        op = await conn.fetchrow("SELECT source, state, initiator_customer_id FROM ghn_shipment_create_operations "
                                 "WHERE order_id=$1", s["oid"])
        assert (op["source"], op["state"], op["initiator_customer_id"]) == ("bot", "prepared", s["cid"])
        assert await conn.fetchval("SELECT step FROM fulfillment_conversations WHERE order_id=$1", s["oid"]) \
            == "cod_handoff"
        # du lieu doi sau khi gui tom tat -> khong tao, chuyen staff
        s3 = await _seed(conn, mapv)
        await start(s3)
        await say(s3, "COD")
        await conn.execute("UPDATE shipments SET delivery_fee_vnd=50000, version=version+1 WHERE order_id=$1", s3["oid"])
        r3 = await say(s3, "xác nhận giao")
        assert "nhân viên" in r3 and await conn.fetchval(
            "SELECT count(*) FROM ghn_shipment_create_operations WHERE order_id=$1", s3["oid"]) == 0
        assert await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND reason='shipment_create'",
                                   s3["oid"]) == 1
    finally:
        await _cleanup_env(conn, iid)
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_lease_expired_dispatching_becomes_unknown_without_http(gate_on):
    conn = await _conn()
    iid, mapv = await _env(conn)
    try:
        st = await _staff(conn)
        s = await _seed(conn, mapv)
        op_id = (await _prepare(conn, s["oid"], st))["operation"]["id"]
        # mo phong worker chet sau khi da chuyen 'dispatching' (request co the da toi GHN)
        await conn.execute("UPDATE ghn_shipment_create_operations SET state='dispatching', attempt_count=1, "
                           "lease_owner='dead', lease_expires_at=now() - interval '1 minute' WHERE id=$1", op_id)
        prov = FakeProv()
        stats = await G.run_dispatch_once(provider_factory=_fac(prov), op_ids=[op_id])
        assert prov.calls == [] and stats["unknown"] == 1
        assert (await _op(conn, op_id))["state"] == "unknown_reconciliation_required"
        assert await conn.fetchval("SELECT outcome FROM ghn_shipment_create_attempts WHERE operation_id=$1",
                                   op_id) == "lease_expired"
    finally:
        await _cleanup_env(conn, iid)
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_staff_reconcile_gate_off_and_abandon(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ghn_shipment_create_dashboard_enabled", False)
    conn = await _conn()
    iid, mapv = await _env(conn)
    try:
        st = await _staff(conn)
        s = await _seed(conn, mapv)
        op_id = (await _prepare(conn, s["oid"], st))["operation"]["id"]
        await conn.execute("UPDATE ghn_shipment_create_operations SET state='unknown_reconciliation_required' "
                           "WHERE id=$1", op_id)

        def boom(cfg):
            raise AssertionError("gate OFF: khong goi provider")
        with pytest.raises(G.ShipmentCreateError) as e:
            await G.reconcile(conn, op_id, staff_id=st, actor="t", provider_factory=boom)
        assert e.value.code == "gate_off"
        with pytest.raises(G.ShipmentCreateError):
            async with conn.transaction():
                await G.abandon(conn, op_id, staff_id=st, actor="t", note="  ")
        async with conn.transaction():
            out = await G.abandon(conn, op_id, staff_id=st, actor="t", note="Đã kiểm tra portal GHN: không có đơn")
        assert out["operation"]["state"] == "failed_terminal"
        import asyncpg
        with pytest.raises(asyncpg.RaiseError):   # terminal khong doi duoc
            await conn.execute("UPDATE ghn_shipment_create_operations SET state='prepared' WHERE id=$1", op_id)
    finally:
        await _cleanup_env(conn, iid)
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_dashboard_api_review_confirm_and_no_secret_pii(gate_on):
    from fastapi import HTTPException

    from app.api import ghn_shipment_create as api
    conn = await _conn()
    iid, mapv = await _env(conn)
    try:
        st = await _staff(conn)
        staff = {"id": st, "username": "t393", "rbac_provisioned": True, "permissions": {"shipment.ghn.create"}}
        s = await _seed(conn, mapv)
        pv = await api.preview(s["oid"], staff=staff)
        assert pv["eligible"] and pv["gates"]["dashboard"] is True and "0912345678" not in json.dumps(pv, default=str)
        with pytest.raises(HTTPException) as e:
            await api.create_request(s["oid"], {"command_key": "k1", "confirm_order_id": "999",
                                                "preview_fingerprint": pv["fingerprint"]}, staff=staff)
        assert e.value.status_code == 422
        rc = await api.create_request(s["oid"], {"command_key": uuid.uuid4().hex, "confirm_order_id": f"#{s['oid']}",
                                                 "preview_fingerprint": pv["fingerprint"], "note": "giao sớm"},
                                      staff=staff)
        op_id = rc["operation"]["id"]
        assert rc["operation"]["state"] == "prepared" and rc["operation"]["initiator_staff_id"] == st
        prov = FakeProv(creates=[P.ProviderOutcome("created", http_status=200, order_code="GHNAPI",
                                                   result=P.redact_result({"order_code": "GHNAPI", "to_phone": "0912345678",
                                                                           "to_name": "Người Nhận"}))])
        await G.run_dispatch_once(provider_factory=_fac(prov), op_ids=[op_id])
        ops = await api.operations(s["oid"], staff=staff)
        blob = json.dumps(ops, default=str)
        assert "GHNAPI" in blob and "0912345678" not in blob and "Người Nhận" not in blob
        assert ops["operations"][0]["client_order_code_masked"] != G.client_order_code(s["oid"], op_id) or \
            len(G.client_order_code(s["oid"], op_id)) <= 6
        rows = await conn.fetch("SELECT after::text a FROM audit_log WHERE entity_type='ghn_shipment_create_operations' "
                                "AND entity_id=$1", str(op_id))
        att = await conn.fetch("SELECT response_redacted::text r FROM ghn_shipment_create_attempts WHERE operation_id=$1",
                               op_id)
        for t in [r["a"] for r in rows] + [r["r"] for r in att]:
            assert "0912345678" not in t and "Người Nhận" not in t and "token" not in t.lower()
    finally:
        await _cleanup_env(conn, iid)
        await conn.close()
