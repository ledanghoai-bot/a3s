"""CA Review 316-01 — SePay webhook api_key theo PRECEDENCE loader D305 (DB authoritative khi module ON). DB test.

400 = auth PASS (body rac -> parse fail); 403 = auth REJECT (fail-closed); 404 = connector OFF (truoc auth).
"""
import base64
import os

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.settings import integrations as S

DB = os.environ.get("M6_TEST_DB") == "1"
pytestmark = pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")

ENV_KEY = "ENVKEY_abcdefghijklmnop"
DB_KEY = "DBKEY_zyxwvutsrq0987654321"


def _crypto(mp):
    mp.setattr(settings, "config_enc_keys", f"k1:{base64.b64encode(b'A'*32).decode()}")
    mp.setattr(settings, "config_enc_key_current", "k1")
    mp.setattr(settings, "config_secret_fp_key", base64.b64encode(b'F'*32).decode())
    mp.setattr(settings, "database_url", os.environ["DATABASE_URL"])


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


def _ck():
    return "wh-" + os.urandom(6).hex()


def _post(client, key):
    # body rac -> parse fail (400) khi auth PASS; auth reject -> 403.
    return client.post("/webhooks/sepay", content=b"notjson",
                       headers={"Authorization": f"Apikey {key}"} if key else {})


async def _mk_active_sepay(conn, mp, *, api_key):
    _crypto(mp)
    it = await S.create_integration(conn, kind="payment", provider="sepay", label="SP", mode="test",
                                    config_public={"code_prefix": "3SCF", "allowed_accounts": "0071000123456"},
                                    actor="po", command_key=_ck())
    if api_key is not None:
        await S.write_secret(conn, it["id"], key_name="api_key", plaintext=api_key,
                             expected_version=it["version"] + 0, actor="po", command_key=_ck())
    await conn.execute("UPDATE integrations SET enabled=true WHERE id=$1", it["id"])
    return it["id"]


async def _cleanup(conn, iid):
    async with conn.transaction():
        await conn.execute("DELETE FROM integration_commands WHERE integration_id=$1", iid)
        await conn.execute("DELETE FROM integration_secrets WHERE integration_id=$1", iid)
        await conn.execute("DELETE FROM integrations WHERE id=$1", iid)


@pytest.mark.asyncio
async def test_connector_off_404_before_auth(monkeypatch):
    _crypto(monkeypatch)
    monkeypatch.setattr(settings, "m7_sepay_test_connector", False)
    c = TestClient(app, raise_server_exceptions=False)
    assert _post(c, "anything").status_code == 404


@pytest.mark.asyncio
async def test_module_off_uses_env_baseline(monkeypatch):
    _crypto(monkeypatch)
    monkeypatch.setattr(settings, "m7_sepay_test_connector", True)
    monkeypatch.setattr(settings, "sepay_live_enabled", False)
    monkeypatch.setattr(settings, "settings_integrations_enabled", False)   # module OFF -> env baseline
    monkeypatch.setattr(settings, "sepay_test_api_key", ENV_KEY)
    c = TestClient(app, raise_server_exceptions=False)
    assert _post(c, ENV_KEY).status_code == 400     # env key PASS (body rac -> 400)
    assert _post(c, "wrong").status_code == 403      # sai key reject


@pytest.mark.asyncio
async def test_module_on_db_authoritative_and_rotate(monkeypatch):
    monkeypatch.setattr(settings, "m7_sepay_test_connector", True)
    monkeypatch.setattr(settings, "sepay_live_enabled", False)
    monkeypatch.setattr(settings, "settings_integrations_enabled", True)
    monkeypatch.setattr(settings, "settings_integrations_env_fallback", False)
    monkeypatch.setattr(settings, "sepay_test_api_key", ENV_KEY)   # env STALE
    conn = await _conn()
    iid = None
    try:
        async with conn.transaction():
            iid = await _mk_active_sepay(conn, monkeypatch, api_key=DB_KEY)
        c = TestClient(app, raise_server_exceptions=False)
        assert _post(c, DB_KEY).status_code == 400    # DB key authoritative -> PASS
        assert _post(c, ENV_KEY).status_code == 403    # env stale REJECT
        # rotate DB key
        d = await S.get_integration(conn, iid)
        async with conn.transaction():
            await S.write_secret(conn, iid, key_name="api_key", plaintext="DBKEY_rotated_1122334455",
                                 expected_version=d["version"], actor="po", command_key=_ck())
        assert _post(c, "DBKEY_rotated_1122334455").status_code == 400   # key moi PASS
        assert _post(c, DB_KEY).status_code == 403                        # key cu REJECT
    finally:
        if iid:
            await _cleanup(conn, iid)
        await conn.close()


@pytest.mark.asyncio
async def test_db_active_missing_secret_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "m7_sepay_test_connector", True)
    monkeypatch.setattr(settings, "sepay_live_enabled", False)
    monkeypatch.setattr(settings, "settings_integrations_enabled", True)
    monkeypatch.setattr(settings, "settings_integrations_env_fallback", True)   # du fallback ON van fail-closed vi DB active
    monkeypatch.setattr(settings, "sepay_test_api_key", ENV_KEY)
    conn = await _conn()
    iid = None
    try:
        async with conn.transaction():
            iid = await _mk_active_sepay(conn, monkeypatch, api_key=None)   # active nhung THIEU secret
        c = TestClient(app, raise_server_exceptions=False)
        assert _post(c, ENV_KEY).status_code == 403   # fail-closed, KHONG roi ve env
        assert _post(c, "anything").status_code == 403
    finally:
        if iid:
            await _cleanup(conn, iid)
        await conn.close()


@pytest.mark.asyncio
async def test_module_on_no_db_fallback(monkeypatch):
    _crypto(monkeypatch)
    monkeypatch.setattr(settings, "m7_sepay_test_connector", True)
    monkeypatch.setattr(settings, "sepay_live_enabled", False)
    monkeypatch.setattr(settings, "settings_integrations_enabled", True)
    monkeypatch.setattr(settings, "sepay_test_api_key", ENV_KEY)
    # dam bao khong co active sepay record
    conn = await _conn()
    try:
        await conn.execute("UPDATE integrations SET enabled=false WHERE provider='sepay' AND mode='test'")
    finally:
        await conn.close()
    c = TestClient(app, raise_server_exceptions=False)
    # fallback OFF -> fail-closed
    monkeypatch.setattr(settings, "settings_integrations_env_fallback", False)
    assert _post(c, ENV_KEY).status_code == 403
    # fallback ON -> env
    monkeypatch.setattr(settings, "settings_integrations_env_fallback", True)
    assert _post(c, ENV_KEY).status_code == 400
    assert _post(c, "wrong").status_code == 403
