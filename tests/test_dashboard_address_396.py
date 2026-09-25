"""CA Directive 396 F2 — Dashboard address (co cau truc) -> snapshot -> quote (evidence don #255: free-text, khong
snapshot, "Tinh phi theo dia chi" tra 200 zone=unknown).

Thuan (CI-safe): validate input, fingerprint, chon provider theo gate (OFF -> stub KHONG HTTP).
DB (skipif not M6_TEST_DB): catalog loc theo dataset active + tinh; tao don Dashboard (legacy + command bus) resolve+bind
snapshot CUNG tx; mo ho -> 409 candidates, KHONG tao don; staff_confirm (ly do) -> staff_confirmed + audit; don cu
xac minh thu cong; quote 409 address_not_verified; co snapshot -> pipeline chung (route_operation), gate OFF zero GHN
HTTP; Idempotency-Key gate ON/OFF; RBAC staff_confirm.
"""
import os
import random
import uuid

import pytest
from fastapi import HTTPException, Response

from app.services.address import dashboard_address as DA


def _addr(**kw):
    b = {"province_code": "66", "ward_code": "24169", "street_text": "99 Lê Thánh Tôn"}
    b.update(kw)
    return b


def test_parse_input_requires_structured_fields():
    assert DA.parse_input(_addr())["staff_confirm"] is None
    for bad in (_addr(province_code=""), _addr(ward_code=None), _addr(street_text="  "), _addr(street_text="x" * 301)):
        with pytest.raises(DA.DashboardAddressError) as e:
            DA.parse_input(bad)
        assert e.value.code == "invalid_address"
    with pytest.raises(DA.DashboardAddressError) as e:
        DA.parse_input(_addr(staff_confirm={"reason": "abc"}))           # ly do < 5 ky tu
    assert e.value.code == "invalid_confirmation"
    assert DA.parse_input(_addr(staff_confirm={"reason": "Khach xac nhan qua dien thoai"}))["staff_confirm"]


def test_fingerprint_deterministic_and_sensitive():
    a = DA.parse_input(_addr())
    assert DA.fingerprint(a) == DA.fingerprint(DA.parse_input(_addr()))
    assert DA.fingerprint(a) != DA.fingerprint(DA.parse_input(_addr(street_text="100 Lê Thánh Tôn")))
    assert DA.fingerprint(a) != DA.fingerprint(DA.parse_input(_addr(ward_code="24490")))
    assert "Lê Thánh Tôn" not in DA.fingerprint(a)                                   # khong dia chi tho


@pytest.mark.asyncio
async def test_quote_provider_selection_by_gate(monkeypatch):
    """Gate OFF -> _DashboardGateOffProvider (KHONG HTTP); ON -> None (provider that). Khong DB: stub execute."""
    from app.api import m6_fulfillment as M6
    from app.config import settings
    from app.services.fulfillment import route_operation as rops
    seen = {}

    async def fake_execute(conn, order_id, *, actor, command_key, provider=None, **kw):
        seen["provider"], seen["ck"] = provider, command_key
        return {"shipment": {"fee_status": "quote_required", "quote_snapshot": {"x": 1}}, "duplicate": False}

    class FakeConn:
        async def fetchval(self, *a):
            return 1

        def transaction(self):
            class T:
                async def __aenter__(s):
                    return s

                async def __aexit__(s, *a):
                    return False
            return T()

        async def close(self):
            pass

    async def fake_connect(*a, **k):
        return FakeConn()

    async def noguard(*a, **k):
        return None
    monkeypatch.setattr(rops, "execute", fake_execute)
    monkeypatch.setattr(M6.asyncpg, "connect", fake_connect)
    monkeypatch.setattr(M6, "guard_order_active", noguard)
    staff = {"id": 1, "username": "t", "rbac_provisioned": True, "permissions": {"shipment.manage"}}
    monkeypatch.setattr(settings, "dashboard_route_quote_enabled", False)
    r = await M6.shipment_quote(1, {"command_key": "abc"}, staff=staff)
    assert isinstance(seen["provider"], M6._DashboardGateOffProvider) and r["provider_gate"] == "off"
    assert seen["ck"] == "dash:abc" and "quote_snapshot" not in r
    monkeypatch.setattr(settings, "dashboard_route_quote_enabled", True)
    r = await M6.shipment_quote(1, {"command_key": "abc"}, staff=staff)
    assert seen["provider"] is None and r["provider_gate"] == "on"
    with pytest.raises(HTTPException) as e:
        await M6.shipment_quote(1, {}, staff=staff)                    # thieu command_key
    assert e.value.status_code == 422


# =========================================================================== DB
DB = os.environ.get("M6_TEST_DB") == "1"


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


class _Env:
    """Dataset dia chi RIENG (commit, version duy nhat) + tro active tam thoi; khoi phuc sau test."""

    async def up(self, conn):
        from app.services.address import acceptance_gate as ag
        self.dsv = f"VN-ADMIN-2098-09-v{random.randint(10**6, 10**9)}"
        self.prev = await conn.fetchval("SELECT value FROM address_dataset_config WHERE key='active_version'")
        await conn.execute("INSERT INTO admin_unit_dataset (version, status, source_url, source_kind, sha256, license) "
                           "VALUES ($1,'draft','test','cross_reference',$2,'test')", self.dsv, "0" * 64)
        units = [("province", "66", "Tỉnh Đắk Lắk", None), ("province", "79", "Thành phố Hồ Chí Minh", None),
                 ("ward", "24169", "Phường Buôn Ma Thuột", "66"), ("ward", "24490", "Xã Krông Pắc", "66"),
                 ("ward", "26734", "Phường Bến Thành", "79"),
                 # 2 don vi HIEN HANH trung ten trong cung tinh -> matcher mo ho that -> can staff xac nhan
                 ("ward", "90001", "Phường Tân Lập", "66"), ("ward", "90002", "Phường Tân Lập", "66")]
        for lvl, code, name, parent in units:
            await conn.execute("INSERT INTO admin_unit (dataset_version, level, code, name, name_normalized, "
                               "parent_code) VALUES ($1,$2,$3,$4,$5,$6)", self.dsv, lvl, code, name,
                               ag.normalize(name), parent)
        await conn.execute("UPDATE address_dataset_config SET value=$1 WHERE key='active_version'", self.dsv)
        self.staff_id = await conn.fetchval(
            "INSERT INTO staff_users(username,password_hash,password_salt,role_key) VALUES ($1,'x','x','admin') "
            "RETURNING id", f"t396-{uuid.uuid4().hex[:8]}")
        self.sku = f"T396-{uuid.uuid4().hex[:8]}"
        await conn.execute("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
                           "VALUES($1,'CF',170000,50,300,'hũ')", self.sku)
        return self

    async def down(self, conn):
        await conn.execute("UPDATE address_dataset_config SET value=$1 WHERE key='active_version'", self.prev)

    def staff(self, perms=("address.view", "address.bind", "shipment.manage")):
        return {"id": self.staff_id, "username": f"staff:{self.staff_id}", "rbac_provisioned": True,
                "permissions": set(perms)}

    def body(self, addr):
        return {"customer_name": "A Khoa", "phone": "0935333291", "sku": self.sku, "quantity": 1,
                "unit_price_vnd": 170000, "address": addr}


async def _create(env, addr, *, staff=None, key=None):
    from app.api import dashboard as D
    return await D.create_order_manual_standalone(env.body(addr), Response(), staff=staff or env.staff(),
                                                  idempotency_key=key or uuid.uuid4().hex)


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_catalog_active_dataset_filtered():
    from app.api import dashboard_address as API
    conn = await _conn()
    env = await _Env().up(conn)
    try:
        p = await API.provinces()
        assert p["dataset_version"] == env.dsv and {x["code"] for x in p["provinces"]} == {"66", "79"}
        w = await API.wards(province_code="66")
        assert {x["code"] for x in w["wards"]} == {"24169", "24490", "90001", "90002"}
        assert "26734" not in {x["code"] for x in w["wards"]}
    finally:
        await env.down(conn)
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
@pytest.mark.parametrize("reliable", [False, True])
async def test_db_create_dashboard_order_binds_snapshot_same_tx(monkeypatch, reliable):
    from app.config import settings
    monkeypatch.setattr(settings, "m1_reliable_order_command", reliable)
    conn = await _conn()
    env = await _Env().up(conn)
    try:
        r = await _create(env, _addr(ward_code="26734", province_code="79"))
        oid = r["order_id"]
        o = await conn.fetchrow("SELECT origin_channel, verified_address_id, shipping_address FROM orders WHERE id=$1",
                                oid)
        s = await conn.fetchrow("SELECT province_code, ward_code, street_text, dataset_version, verification_method "
                                "FROM order_address_snapshot WHERE order_id=$1", oid)
        assert o["origin_channel"] == "dashboard" and o["verified_address_id"] is not None
        assert o["shipping_address"] == "99 Lê Thánh Tôn, Phường Bến Thành, Thành phố Hồ Chí Minh"
        assert (s["province_code"], s["ward_code"], s["dataset_version"]) == ("79", "26734", env.dsv)
        acts = {a["action"] for a in await conn.fetch(
            "SELECT action FROM audit_log WHERE action LIKE 'address.%' AND (entity_id IN "
            "(SELECT id::text FROM order_address_snapshot WHERE order_id=$1) OR entity_id=$2)",
            oid, str(o["verified_address_id"]))}
        assert {"address.resolve", "address.bind"} <= acts
    finally:
        await env.down(conn)
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
@pytest.mark.parametrize("reliable", [False, True])
async def test_db_ambiguous_needs_staff_confirm_no_order_then_confirmed(monkeypatch, reliable):
    from app.config import settings
    monkeypatch.setattr(settings, "m1_reliable_order_command", reliable)
    conn = await _conn()
    env = await _Env().up(conn)
    try:
        before = await conn.fetchval("SELECT count(*) FROM orders WHERE created_by_staff_id=$1", env.staff_id)
        with pytest.raises(HTTPException) as e:
            await _create(env, _addr(ward_code="90002"))
        assert e.value.status_code == 409 and e.value.detail["error_code"] == "address_needs_staff_confirmation"
        assert {c["ward_code"] for c in e.value.detail["candidates"]} == {"90001", "90002"}
        assert await conn.fetchval("SELECT count(*) FROM orders WHERE created_by_staff_id=$1", env.staff_id) == before
        # staff_confirm KHONG co quyen address.bind -> 403
        with pytest.raises(HTTPException) as e:
            await _create(env, _addr(ward_code="90002", staff_confirm={"reason": "Khach xac nhan qua dien thoai"}),
                          staff=env.staff(perms=("address.view", "shipment.manage")))
        assert e.value.status_code == 403
        r = await _create(env, _addr(ward_code="90002", staff_confirm={"reason": "Khach xac nhan qua dien thoai"}))
        s = await conn.fetchrow("SELECT s.ward_code, ar.status, ar.resolved_by, ar.reason FROM order_address_snapshot s "
                                "JOIN address_resolution ar ON ar.id=s.resolution_id WHERE s.order_id=$1",
                                r["order_id"])
        assert s["ward_code"] == "90002" and s["status"] == "staff_confirmed"
        assert s["resolved_by"] == f"staff:{env.staff_id}" and s["reason"] == "Khach xac nhan qua dien thoai"
        assert await conn.fetchval("SELECT count(*) FROM audit_log WHERE action='address.staff_confirm' "
                                   "AND reason='Khach xac nhan qua dien thoai' AND actor_ref=$1",
                                   f"staff:{env.staff_id}") >= 1
    finally:
        await env.down(conn)
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_invalid_address_and_free_text_rejected():
    conn = await _conn()
    env = await _Env().up(conn)
    try:
        with pytest.raises(HTTPException) as e:
            await _create(env, "99 Le Thanh Ton, P. Ben Thanh, HCM")        # free-text nhu don #255
        assert e.value.status_code == 422
        with pytest.raises(HTTPException) as e:
            await _create(env, _addr(province_code="79", ward_code="24169"))  # phuong khong thuoc tinh
        assert e.value.status_code == 422 and e.value.detail["error_code"] == "address_invalid_address"
    finally:
        await env.down(conn)
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_idempotency_key_required_when_reliable_on(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "m1_reliable_order_command", True)
    conn = await _conn()
    env = await _Env().up(conn)
    try:
        from app.api import dashboard as D
        resp = Response()
        out = await D.create_order_manual_standalone(env.body(_addr()), resp, staff=env.staff(), idempotency_key=None)
        assert resp.status_code == 400 and out["error_code"] == "idempotency_key_required"
        key = uuid.uuid4().hex
        r1 = await _create(env, _addr(), key=key)
        r2 = await _create(env, _addr(), key=key)                     # replay cung key -> cung don
        assert r1["order_id"] == r2["order_id"] and r2["duplicate"] is True
        assert await conn.fetchval("SELECT count(*) FROM order_address_snapshot WHERE order_id=$1", r1["order_id"]) == 1
        resp3 = Response()
        out3 = await D.create_order_manual_standalone(env.body(_addr(street_text="1 Khac")), resp3, staff=env.staff(),
                                                      idempotency_key=key)   # cung key, dia chi khac -> conflict
        assert resp3.status_code == 409 and "conflict" in (out3.get("error_code") or "")
    finally:
        await env.down(conn)
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_quote_requires_snapshot_then_shared_pipeline_zero_http(monkeypatch):
    """Tai hien #255: don Dashboard free-text cu (khong snapshot) -> 409 address_not_verified (KHONG 200 zone=unknown);
    Xac minh dia chi -> snapshot; Tinh phi -> route_operation (routing GHN) voi gate OFF -> KHONG goi GHN."""
    from app.api import m6_fulfillment as M6
    from app.config import settings
    from app.services.orders import create_order_manual
    from app.services.providers import ghn as ghn_mod

    class _Boom:
        def __init__(self, *a, **k):
            raise AssertionError("GhnQuoteProvider KHONG duoc tao khi gate Dashboard OFF")
    monkeypatch.setattr(ghn_mod, "GhnQuoteProvider", _Boom)
    monkeypatch.setattr(settings, "dashboard_route_quote_enabled", False)
    monkeypatch.setattr(settings, "m1_reliable_order_command", False)
    conn = await _conn()
    env = await _Env().up(conn)
    rv = random.randint(900000, 999999)
    try:
        await conn.execute("INSERT INTO delivery_routing_versions(version, effective_from, effective_to, dataset_version,"
                           " created_by) VALUES ($1, now() - interval '1 day', now() + interval '1 hour', $2, 't396')",
                           rv, env.dsv)
        # don cu kieu #255: tao KHONG dia chi co cau truc (duong service legacy, free-text)
        old = await create_order_manual(customer_name="A Khoa", phone="0935333291",
                                        address="99 Le Thanh Ton, P. Bến Thành, TP. Hồ Chí Minh", sku=env.sku,
                                        quantity=1, unit_price_vnd=170000, created_by_staff_id=env.staff_id)
        oid = old["order_id"]
        st = env.staff()
        with pytest.raises(HTTPException) as e:
            await M6.shipment_quote(oid, {"command_key": uuid.uuid4().hex}, staff=st)
        assert e.value.status_code == 409 and e.value.detail["error_code"] == "address_not_verified"
        assert await conn.fetchval("SELECT count(*) FROM shipments WHERE order_id=$1", oid) == 0   # khong ghi gi
        # xac minh thu cong (KHONG suy tu text cu)
        v = await M6.verify_order_address(oid, _addr(province_code="79", ward_code="26734"), staff=st)
        assert v["verification"] == "auto_verified"
        with pytest.raises(HTTPException) as e:                    # snapshot bat bien -> lan 2 409
            await M6.verify_order_address(oid, _addr(province_code="79", ward_code="26734"), staff=st)
        assert e.value.status_code == 409
        r = await M6.shipment_quote(oid, {"command_key": uuid.uuid4().hex}, staff=st)
        assert r["provider_gate"] == "off" and r["routing_source"] == "GHN"
        assert r["fee_status"] in ("quote_required", "unknown", "quoted")
        assert await conn.fetchval("SELECT count(*) FROM provider_quote_log WHERE order_id=$1", oid) == 0
        assert await conn.fetchval("SELECT count(*) FROM fulfillment_route_operations WHERE order_id=$1", oid) == 1
    finally:
        await conn.execute("UPDATE delivery_routing_versions SET effective_to=now() WHERE version=$1", rv)
        await env.down(conn)
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_in_tx_guard_rolls_back_whole_order_both_paths(monkeypatch):
    """Bo qua precheck (goi thang service): dia chi mo ho khong staff_confirm -> loi trong tx -> KHONG don/items/snapshot
    (fail-closed, khong don mo coi) — ca duong legacy lan command bus."""
    from app.config import settings
    from app.services import orders as OS
    from app.services.command import order_gateway as OG
    conn = await _conn()
    env = await _Env().up(conn)
    try:
        amb = DA.parse_input(_addr(ward_code="90002"))
        n0 = await conn.fetchval("SELECT count(*) FROM orders WHERE created_by_staff_id=$1", env.staff_id)
        stock0 = await conn.fetchval("SELECT stock FROM products WHERE sku=$1", env.sku)
        monkeypatch.setattr(settings, "m1_reliable_order_command", False)
        r = await OS.create_order_manual(customer_name="A", phone="0935333291", address="x", sku=env.sku, quantity=1,
                                         unit_price_vnd=170000, created_by_staff_id=env.staff_id,
                                         dashboard_address=amb)
        assert r["error_code"] == "address_needs_staff_confirmation" and len(r["candidates"]) == 2
        monkeypatch.setattr(settings, "m1_reliable_order_command", True)
        st, out, _ = await OG.create_order_http(actor_id=env.staff_id, idempotency_key=uuid.uuid4().hex,
                                                customer_name="A", phone="0935333291", address="x", sku=env.sku,
                                                quantity=1, unit_price_vnd=170000, dashboard_address=amb)
        assert st == 409 and out["error_code"] == "address_needs_staff_confirmation"
        assert await conn.fetchval("SELECT count(*) FROM orders WHERE created_by_staff_id=$1", env.staff_id) == n0
        assert await conn.fetchval("SELECT stock FROM products WHERE sku=$1", env.sku) == stock0
    finally:
        await env.down(conn)
        await conn.close()
