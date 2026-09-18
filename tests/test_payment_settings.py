"""CA Directive 306 — Payment Settings + SePay S0. VietQR self-test (sync CI-safe), SePay readiness (DB), RBAC deny."""
import base64
import os

import pytest
from fastapi.testclient import TestClient

from app.api.auth import require_staff_session
from app.config import settings
from app.main import app
from app.services.settings import integrations as S


def test_vietqr_self_test_ok_and_fail():
    r = S.vietqr_self_test(bin_code="970415", account_number="0071000123456", amount_vnd=10000, add_info="3SCF 42")
    assert r["ok"] is True and r["crc_valid"] is True and r["account_last4"] == "3456"
    bad = S.vietqr_self_test(bin_code="", account_number="x", amount_vnd=-1, add_info="")
    assert bad["ok"] is False and "error_class" in bad


# --- RBAC deny (CI-safe TestClient, no DB) ---
def _client(perms):
    async def _fake():
        return {"id": 1, "username": "t", "rbac_provisioned": True, "permissions": set(perms)}
    app.dependency_overrides[require_staff_session] = _fake
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("method,path,body,perm", [
    ("get", "/dashboard/settings/payments", None, "settings.integration.view"),
    ("post", "/dashboard/settings/payments/bank", {"bank": "b", "account_number": "1", "holder_name": "h"}, "settings.integration.secret_write"),
    ("post", "/dashboard/settings/payments/vietqr-self-test", {}, "settings.integration.test"),
])
def test_payment_endpoints_deny_without_perm(method, path, body, perm):
    c = _client([])
    try:
        r = getattr(c, method)(path, json=body) if body is not None else getattr(c, method)(path)
        assert r.status_code == 403, f"{path} nên 403 khi thiếu {perm}"
    finally:
        app.dependency_overrides.pop(require_staff_session, None)


# --- SePay readiness (DB) ---
DB = os.environ.get("M6_TEST_DB") == "1"


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_sepay_readiness_and_enable_gate(monkeypatch):
    import asyncpg
    monkeypatch.setattr(settings, "config_enc_keys", f"k1:{base64.b64encode(b'A'*32).decode()}")
    monkeypatch.setattr(settings, "config_enc_key_current", "k1")
    monkeypatch.setattr(settings, "config_secret_fp_key", base64.b64encode(b'F'*32).decode())
    conn = await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    try:
        async with conn.transaction():
            it = await S.create_integration(conn, kind="payment", provider="sepay", label="SePay Test", mode="test",
                                            config_public={"code_prefix": "3SCF"}, actor="po")
        iid = it["id"]
        # readiness khi chưa có key -> not_configured
        async with conn.transaction():
            r0 = await S.sepay_readiness(conn, iid, actor="po")
        assert r0["ok"] is False and r0["error_class"] == "not_configured"
        # nhập api_key -> readiness pass -> enable OK
        async with conn.transaction():
            await S.write_secret(conn, iid, key_name="api_key", plaintext="SEPAY-TEST-KEY-123", actor="po")
        async with conn.transaction():
            r1 = await S.sepay_readiness(conn, iid, actor="po")
        assert r1["ok"] is True
        d = await S.get_integration(conn, iid)
        assert d["secrets"]["api_key"]["present"] is True and "value" not in d["secrets"]["api_key"]
        async with conn.transaction():
            en = await S.enable(conn, iid, expected_version=d["version"], actor="po")
        assert en["enabled"] is True
        async with conn.transaction():
            await conn.execute("DELETE FROM integration_secrets WHERE integration_id=$1", iid)
            await conn.execute("DELETE FROM integrations WHERE id=$1", iid)
    finally:
        await conn.close()
