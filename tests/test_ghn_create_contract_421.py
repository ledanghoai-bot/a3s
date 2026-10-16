"""CA Directive 421 B1 — sua adapter GHN create theo hop dong QUAN SAT tren staging (probe 16/10/2026, read-only/preview).

Pure (CI-safe): lookup = GET + query string (khong body); not_found CHI khi dung tin hieu GHN that (HTTP 400/code 400/
data null + code_message ORDER_NOT_FOUND hoac doan cuoi message == 'Đơn hàng không tồn tại', GIU DAU, NFC) — cac chuoi
gan giong (khong dau, tieng Anh, 'Route not found', 404) -> unknown; code_message GHN vao error_class da loc ky tu;
payload van theo MA (to_district_id/to_ward_code — staging chap nhan, ban theo ten bi TO_ADDRESS_CONFLICT).
DB (skipif not M6_TEST_DB): items_missing / cod_over_provider_max la blocker (policy v2).
"""
import asyncio
import json
import unicodedata

import pytest

from app.services.fulfillment import ghn_shipment_create as G
from app.services.providers import ghn_create as P
from tests import test_ghn_shipment_create_393 as T

REAL_NOT_FOUND = "Lỗi gọi API: corev2_tenant_order_detail_by_client_order_code - Đơn hàng không tồn tại"


def _run(coro):
    return asyncio.run(coro)


def test_lookup_is_get_with_query_string_no_body():
    send = T._send(400, {"code": 400, "code_message": None, "message": REAL_NOT_FOUND, "data": None})
    r = _run(P.GhnCreateProvider({}, send=send).lookup("A3S-7-1"))
    assert r.outcome == "not_found"
    path, body, kw = send.calls[0]
    assert path == P.DETAIL_BY_CLIENT_CODE_PATH and body is None
    assert kw == {"method": "GET", "params": {"client_order_code": "A3S-7-1"}}


def test_create_still_post_json_body():
    send = T._send(200, {"code": 200, "data": {"order_code": "G1"}})
    _run(P.GhnCreateProvider({}, send=send).create(T.SNAP, "A3S-7-1"))
    path, body, kw = send.calls[0]
    assert path == P.CREATE_PATH and body["client_order_code"] == "A3S-7-1" and kw == {}


@pytest.mark.parametrize("status,js,expected", [
    (400, {"code": 400, "code_message": None, "message": REAL_NOT_FOUND, "data": None}, True),       # staging that
    (400, {"code": 400, "message": unicodedata.normalize("NFD", REAL_NOT_FOUND)}, True),             # NFD -> NFC
    (400, {"code": 400, "code_message": "ORDER_NOT_FOUND", "message": "x"}, True),                   # theo docs
    (400, {"code": 400, "message": "Lỗi gọi API: x - Don hang khong ton tai"}, False),               # bo dau: KHONG
    (400, {"code": 400, "message": "Order not found"}, False),
    (400, {"code": 400, "message": "Route not found"}, False),
    (400, {"code": 400, "message": "x - Đơn hàng không tồn tại trong ca"}, False),                   # khong substring
    (400, {"code": 400, "code_message": "CLIENT_NOT_OWNER_OF_SHOP", "message": "Không có quyền thao tác"}, False),
    (404, {"code": 404, "message": REAL_NOT_FOUND}, False),
    (200, {"code": 400, "message": REAL_NOT_FOUND}, False),
    (400, {"code": 400, "message": REAL_NOT_FOUND, "data": {"order_code": "G1"}}, False),
    (400, None, False),
])
def test_not_found_only_on_verified_signal(status, js, expected):
    assert P.is_lookup_not_found(status, js) is expected
    r = _run(P.GhnCreateProvider({}, send=T._send(status, js)).lookup("c"))
    if expected:
        assert r.outcome == "not_found"
    else:
        assert r.outcome == "unknown"


def test_code_message_in_error_class_sanitized():
    r = _run(P.GhnCreateProvider({}, send=T._send(400, {"code": 400, "code_message": "TO_ADDRESS_CONFLICT",
                                                         "message": "To address conflict"})).create(T.SNAP, "c"))
    assert r.outcome == "rejected" and r.error_class == "rejected_http_400_code_400_TO_ADDRESS_CONFLICT"
    r = _run(P.GhnCreateProvider({}, send=T._send(400, {"code": 400, "code_message": "x 0912345678 <b>; drop"}))
             .create(T.SNAP, "c"))
    assert r.error_class.startswith("rejected_http_400_code_400_") and " " not in r.error_class
    assert "<" not in r.error_class and ";" not in r.error_class
    r = _run(P.GhnCreateProvider({}, send=T._send(400, {"code": 400, "message": "invalid"})).create(T.SNAP, "c"))
    assert r.error_class == "rejected_http_400_code_400"
    lk = _run(P.GhnCreateProvider({}, send=T._send(401, {"code": 401, "code_message": "UNAUTHORIZED"})).lookup("c"))
    assert lk.outcome == "unknown" and lk.error_class == "lookup_http_401_UNAUTHORIZED"


def test_payload_stays_code_based_per_staging_probe():
    b = P.build_create_payload(T.SNAP, "A3S-7-1")
    assert {"to_district_id", "to_ward_code", "from_district_id", "from_ward_code"} <= set(b)
    assert not {"to_ward_name", "to_province_name", "is_new_to_address"} & set(b)
    assert b["items"] and "Token" not in json.dumps(b)


def test_policy_v2():
    assert G.POLICY_VERSION == "ghn_create_policy_v2" and P.COD_MAX_VND == 50_000_000


@T.dbonly
@pytest.mark.asyncio
async def test_items_missing_and_cod_cap_are_blockers():
    conn = await T._conn()
    iid, mapv = await T._env(conn)
    try:
        ok = await T._seed(conn, mapv)
        ev = await G.evaluate(conn, ok["oid"], source="dashboard")
        assert ev["eligible"] and ev["snapshot"]["policy_version"] == "ghn_create_policy_v2", ev["blockers"]
        s = await T._seed(conn, mapv)
        await conn.execute("DELETE FROM order_items WHERE order_id=$1", s["oid"])
        ev = await G.evaluate(conn, s["oid"], source="dashboard")
        assert not ev["eligible"] and ev["snapshot"] is None          # don rong: da chan som (weight_missing)
        s = await T._seed(conn, mapv)
        await conn.execute("UPDATE products SET name='  ' WHERE id=(SELECT product_id FROM order_items "
                           "WHERE order_id=$1)", s["oid"])
        ev = await G.evaluate(conn, s["oid"], source="dashboard")
        assert not ev["eligible"] and ev["blockers"] == ["items_missing"] and ev["snapshot"] is None
        s = await T._seed(conn, mapv)
        await conn.execute("UPDATE payments SET amount_due_vnd=50000001 WHERE order_id=$1", s["oid"])
        ev = await G.evaluate(conn, s["oid"], source="dashboard")
        assert not ev["eligible"] and ev["blockers"] == ["cod_over_provider_max"]
        s = await T._seed(conn, mapv)
        await conn.execute("UPDATE payments SET amount_due_vnd=50000000 WHERE order_id=$1", s["oid"])
        ev = await G.evaluate(conn, s["oid"], source="dashboard")
        assert ev["eligible"] and "cod_amount_high" in ev["warnings"]
    finally:
        await T._cleanup_env(conn, iid)
        await conn.close()


# ============================================================ CA 422 §B1.2/§B1.3 bo sung
from tests.test_ghn_shipment_create_393 import gate_on  # noqa: E402,F401 — fixture


def test_20kg_boundary_service5_guard_unchanged():
    from app.services.fulfillment import shipping_policy as sp
    from app.services.providers import ghn
    assert ghn.service_type_for_weight(19999, 20000) == 2 and ghn.service_type_for_weight(20000, 20000) == 5
    assert sp.is_heavy(20000) is False and sp.is_heavy(20001) is True      # guard PO: CHI tren 20 kg -> staff


def test_settle_window_invariant():
    assert G.POLICY["backoff_s"][0] >= G.LOOKUP_SETTLE_S > 0 and G.PARCEL_MAX_SIDE_CM == 200


@T.dbonly
@pytest.mark.asyncio
async def test_20000g_eligible_with_service5_and_dims_guard():
    conn = await T._conn()
    iid, mapv = await T._env(conn)
    try:
        s = await T._seed(conn, mapv, weight=20000)
        ev = await G.evaluate(conn, s["oid"], source="dashboard")
        assert ev["eligible"], ev["blockers"]
        assert ev["snapshot"]["parcel"]["service_type_id"] == 5 and ev["snapshot"]["parcel"]["weight_g"] == 20000
        s = await T._seed(conn, mapv)
        await conn.execute("UPDATE products SET length_cm=201 WHERE id=(SELECT product_id FROM order_items "
                           "WHERE order_id=$1)", s["oid"])
        ev = await G.evaluate(conn, s["oid"], source="dashboard")
        assert not ev["eligible"] and "parcel_over_provider_max" in ev["blockers"], ev["blockers"]
    finally:
        await T._cleanup_env(conn, iid)
        await conn.close()


async def _attn(conn, oid, why):
    return await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND reason='shipment_create' "
                               "AND status='open' AND detail->>'why'=$2", oid, why)


@T.dbonly
@pytest.mark.asyncio
async def test_fee_mismatch_opens_attention_shipment_kept(gate_on):
    conn = await T._conn()
    iid, mapv = await T._env(conn)
    try:
        st = await T._staff(conn)
        for billed, expect in ((45000, 1), (30000, 0)):
            s = await T._seed(conn, mapv)
            op_id = (await T._prepare(conn, s["oid"], st))["operation"]["id"]
            prov = T.FakeProv(creates=[P.ProviderOutcome("created", http_status=200, order_code=f"GF{billed}",
                                                         result={"order_code": f"GF{billed}", "total_fee": billed})])
            await G.run_dispatch_once(provider_factory=T._fac(prov), op_ids=[op_id])
            assert (await T._op(conn, op_id))["state"] == "succeeded"
            assert await _attn(conn, s["oid"], "provider_fee_mismatch") == expect
            assert await conn.fetchval("SELECT count(*) FROM audit_log WHERE action='shipment.ghn_create.fee_mismatch' "
                                       "AND entity_id=$1", str(op_id)) == expect
    finally:
        await T._cleanup_env(conn, iid)
        await conn.close()


@T.dbonly
@pytest.mark.asyncio
async def test_reconcile_not_found_within_settle_window_stays_unknown(gate_on, monkeypatch):
    conn = await T._conn()
    iid, mapv = await T._env(conn)
    try:
        st = await T._staff(conn)
        s = await T._seed(conn, mapv)
        op_id = (await T._prepare(conn, s["oid"], st))["operation"]["id"]
        await G.run_dispatch_once(provider_factory=T._fac(T.FakeProv(
            creates=[P.ProviderOutcome("unknown", error_class="timeout_read")])), op_ids=[op_id])
        assert (await T._op(conn, op_id))["state"] == "unknown_reconciliation_required"
        nf = P.ProviderOutcome("not_found", http_status=400)
        out = await G.reconcile(conn, op_id, staff_id=st, actor="t", provider_factory=T._fac(T.FakeProv(lookups=[nf])))
        assert out["lookup"] == "not_found_unsettled" and out["changed"] is False
        assert (await T._op(conn, op_id))["state"] == "unknown_reconciliation_required"     # KHONG mo lai create
        assert await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND status='open' "
                                   "AND reason='shipment_create'", s["oid"]) == 1
        assert await conn.fetchval("SELECT error_class FROM ghn_shipment_create_attempts WHERE operation_id=$1 "
                                   "AND kind='reconcile'", op_id) == "not_found_unsettled"
        monkeypatch.setattr(G, "LOOKUP_SETTLE_S", 0)          # het cua so (attempts append-only: khong sua thoi gian)
        # CA 425 §2: SAU 60s van KHONG mo lai create — GHN tra not_found ca cho don DA HUY (probe staging L8RD3U)
        prov = T.FakeProv(lookups=[nf])
        out = await G.reconcile(conn, op_id, staff_id=st, actor="t", provider_factory=T._fac(prov))
        assert out["lookup"] == "not_found_unverified" and out["changed"] is False and prov.calls == ["lookup"]
        assert (await T._op(conn, op_id))["state"] == "unknown_reconciliation_required"
        assert await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND status='open' "
                                   "AND reason='shipment_create'", s["oid"]) == 1
        w = T.FakeProv()
        again = await G.run_dispatch_once(provider_factory=T._fac(w), op_ids=[op_id])
        assert again["picked"] == 0 and again["http_calls"] == 0 and w.calls == []     # zero create HTTP moi
        assert await conn.fetchval("SELECT count(*) FROM ghn_shipment_create_attempts WHERE operation_id=$1 "
                                   "AND kind='create'", op_id) == 1
    finally:
        await T._cleanup_env(conn, iid)
        await conn.close()


@T.dbonly
@pytest.mark.asyncio
async def test_worker_never_recreates_after_maybe_reached_create_even_if_lookup_not_found(gate_on):
    """Phong thu chieu sau: op bi dua ve failed_retryable (vd sua tay) sau 1 create unknown -> worker lookup not_found
    (mo phong don GHN da huy) -> KHONG create, ve unknown + attention not_found_unverified."""
    conn = await T._conn()
    iid, mapv = await T._env(conn)
    try:
        st = await T._staff(conn)
        s = await T._seed(conn, mapv)
        op_id = (await T._prepare(conn, s["oid"], st))["operation"]["id"]
        await G.run_dispatch_once(provider_factory=T._fac(T.FakeProv(
            creates=[P.ProviderOutcome("unknown", http_status=503, error_class="http_503_maybe_created")])),
            op_ids=[op_id])
        await conn.execute("UPDATE ghn_shipment_create_operations SET state='failed_retryable', next_attempt_at=now() "
                           "WHERE id=$1", op_id)
        # sua tay ca attention (neu con mo, revalidation da chan som hon — staff_attention_open, 0 HTTP)
        await conn.execute("UPDATE staff_attention SET status='resolved', resolved_at=now(), resolved_by='t', "
                           "resolution_note='t' WHERE order_id=$1 AND status='open'", s["oid"])
        prov = T.FakeProv(lookups=[P.ProviderOutcome("not_found", http_status=400)])
        stats = await G.run_dispatch_once(provider_factory=T._fac(prov), op_ids=[op_id])
        assert prov.calls == ["lookup"] and stats["unknown"] == 1
        op = await T._op(conn, op_id)
        assert op["state"] == "unknown_reconciliation_required" and op["last_error_class"] == "not_found_unverified"
        assert await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND status='open' AND "
                                   "detail->>'why'='not_found_unverified'", s["oid"]) == 1
    finally:
        await T._cleanup_env(conn, iid)
        await conn.close()


@T.dbonly
@pytest.mark.asyncio
async def test_found_succeeds_once_and_safe_retry_path_kept(gate_on):
    conn = await T._conn()
    iid, mapv = await T._env(conn)
    try:
        st = await T._staff(conn)
        # unknown -> found: ghi thanh cong DUNG mot lan; doi soat lai -> state_invalid, khong ghi them
        s = await T._seed(conn, mapv)
        op_id = (await T._prepare(conn, s["oid"], st))["operation"]["id"]
        await G.run_dispatch_once(provider_factory=T._fac(T.FakeProv(
            creates=[P.ProviderOutcome("unknown", error_class="timeout_read")])), op_ids=[op_id])
        fd = P.ProviderOutcome("found", http_status=200, order_code="GFOUND1", result={"order_code": "GFOUND1"})
        out = await G.reconcile(conn, op_id, staff_id=st, actor="t", provider_factory=T._fac(T.FakeProv(lookups=[fd])))
        assert out["lookup"] == "found" and (await T._op(conn, op_id))["state"] == "succeeded"
        with pytest.raises(G.ShipmentCreateError):
            await G.reconcile(conn, op_id, staff_id=st, actor="t", provider_factory=T._fac(T.FakeProv(lookups=[fd])))
        assert await conn.fetchval("SELECT count(*) FROM audit_log WHERE action='shipment.ghn_create.succeeded' "
                                   "AND entity_id=$1", str(op_id)) == 1
        # duong an toan: 429 (chac chan chua xu ly) -> staff doi soat not_found -> failed_retryable -> worker tao
        s2 = await T._seed(conn, mapv)
        op2 = (await T._prepare(conn, s2["oid"], st))["operation"]["id"]
        await G.run_dispatch_once(provider_factory=T._fac(T.FakeProv(
            creates=[P.ProviderOutcome("retryable", http_status=429, error_class="http_429")])), op_ids=[op2])
        out = await G.reconcile(conn, op2, staff_id=st, actor="t", provider_factory=T._fac(T.FakeProv(
            lookups=[P.ProviderOutcome("not_found", http_status=400)])))
        assert out["lookup"] == "not_found" and (await T._op(conn, op2))["state"] == "failed_retryable"
        p = T.FakeProv(lookups=[P.ProviderOutcome("not_found", http_status=400)],
                       creates=[P.ProviderOutcome("created", http_status=200, order_code="GSAFE", result={})])
        await G.run_dispatch_once(provider_factory=T._fac(p), op_ids=[op2])
        assert p.calls == ["lookup", "create"] and (await T._op(conn, op2))["state"] == "succeeded"
    finally:
        await T._cleanup_env(conn, iid)
        await conn.close()


@T.dbonly
@pytest.mark.asyncio
async def test_abandon_unknown_resolves_its_attention_then_new_operation(gate_on):
    conn = await T._conn()
    iid, mapv = await T._env(conn)
    try:
        st = await T._staff(conn)
        s = await T._seed(conn, mapv)
        op_id = (await T._prepare(conn, s["oid"], st))["operation"]["id"]
        await G.run_dispatch_once(provider_factory=T._fac(T.FakeProv(
            creates=[P.ProviderOutcome("unknown", error_class="timeout_read")])), op_ids=[op_id])
        assert "staff_attention_open" in (await G.evaluate(conn, s["oid"], source="dashboard"))["blockers"]
        async with conn.transaction():
            await G.abandon(conn, op_id, staff_id=st, actor="t", note="Da kiem tra cong GHN: khong co van don hieu luc")
        assert (await T._op(conn, op_id))["state"] == "failed_terminal"
        assert await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND status='open'",
                                   s["oid"]) == 0
        new = await T._prepare(conn, s["oid"], st)          # operation MOI, client_order_code moi
        assert new["operation"]["id"] != op_id
    finally:
        await T._cleanup_env(conn, iid)
        await conn.close()


@pytest.mark.parametrize("status", [408, 500, 502, 503, 504])
def test_create_5xx_408_is_unknown_staff_only_not_auto_retry(status):
    """CA 424 §2: 5xx/408 co the da tao don -> unknown (staff doi soat), KHONG retryable (worker se lookup+create lai)."""
    r = _run(P.GhnCreateProvider({}, send=T._send(status, None)).create(T.SNAP, "c"))
    assert r.outcome == "unknown" and r.error_class == f"http_{status}_maybe_created"


@pytest.mark.parametrize("status", [425, 429])
def test_create_429_425_still_retryable(status):
    r = _run(P.GhnCreateProvider({}, send=T._send(status, {"code": status})).create(T.SNAP, "c"))
    assert r.outcome == "retryable"
