"""CA Directive 305 — settings integrations service DB test (m5lab, M6_TEST_DB=1). Skip khong DB.

Bao phu: create/update CAS, secret write-only + no-plaintext readback + replay idempotent, test-connection (mock GHN
read-only) bind version, enable-gate (test pass + version match), disable kill-switch, loader precedence fail-closed.
"""
import base64
import os

import pytest

from app.config import settings
from app.services.settings import integrations as S

DB = os.environ.get("M6_TEST_DB") == "1"
pytestmark = pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")


def _crypto_env(monkeypatch):
    monkeypatch.setattr(settings, "config_enc_keys", f"k1:{base64.b64encode(b'A'*32).decode()}")
    monkeypatch.setattr(settings, "config_enc_key_current", "k1")
    monkeypatch.setattr(settings, "config_secret_fp_key", base64.b64encode(b'F'*32).decode())


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


async def _ok_post(cfg, path, body, *, retries):
    return 200, {"code": 200, "data": [{"ProvinceID": 1}, {"ProvinceID": 2}]}, "", 12


async def _fail_post(cfg, path, body, *, retries):
    return 401, {"code": 401, "message": "Token invalid"}, "", 9


@pytest.mark.asyncio
async def test_ghn_config_lifecycle(monkeypatch):
    _crypto_env(monkeypatch)
    conn = await _conn()
    try:
        async with conn.transaction():
            it = await S.create_integration(conn, kind="shipping", provider="ghn", label="GHN staging",
                                            mode="staging", config_public={"shop_id": "12345", "from_district_id": 1454,
                                            "from_ward_code": "21211", "base_url": "https://evil.example"}, actor="po")
        iid = it["id"]
        # base_url bị pin về staging (không nhận arbitrary host — 305-08)
        assert it["config_public"]["base_url"].endswith("ghn.vn/shiip/public-api")

        # enable trước khi có secret + test -> reject
        with pytest.raises(S.SettingsError):
            async with conn.transaction():
                await S.enable(conn, iid, expected_version=it["version"], actor="po")

        # write secret token (write-only)
        async with conn.transaction():
            w = await S.write_secret(conn, iid, key_name="token", plaintext="GHN-TOKEN-xyz", actor="po")
        assert w["version"] == 1
        # readback KHÔNG lộ plaintext/ciphertext
        d = await S.get_integration(conn, iid)
        assert d["secrets"]["token"]["present"] is True and d["secrets"]["token"].get("last4") is None
        assert "value" not in d["secrets"]["token"] and "ciphertext" not in str(d)

        # replay cùng secret -> không bump version
        async with conn.transaction():
            w2 = await S.write_secret(conn, iid, key_name="token", plaintext="GHN-TOKEN-xyz", actor="po")
        assert w2.get("replay") is True and w2["version"] == 1

        # enable trước test-pass -> reject
        d = await S.get_integration(conn, iid)
        with pytest.raises(S.SettingsError):
            async with conn.transaction():
                await S.enable(conn, iid, expected_version=d["version"], actor="po")

        # test-connection FAIL (mock 401) -> last_test=fail, enable vẫn reject
        async with conn.transaction():
            r = await S.test_connection(conn, iid, actor="po", post=_fail_post)
        assert r["ok"] is False and r["error_class"] == "http_401"
        d = await S.get_integration(conn, iid)
        with pytest.raises(S.SettingsError):
            async with conn.transaction():
                await S.enable(conn, iid, expected_version=d["version"], actor="po")

        # test-connection PASS (mock) -> enable OK
        async with conn.transaction():
            r = await S.test_connection(conn, iid, actor="po", post=_ok_post)
        assert r["ok"] is True and r["province_count"] == 2
        d = await S.get_integration(conn, iid)
        async with conn.transaction():
            en = await S.enable(conn, iid, expected_version=d["version"], actor="po")
        assert en["enabled"] is True

        # loader: module ON -> đọc từ DB (decrypt token server-side)
        monkeypatch.setattr(settings, "settings_integrations_enabled", True)
        load = await S.load_active_config(conn, "ghn", "staging")
        assert load["source"] == "database" and load["enabled"] is True
        assert load["secrets"]["token"] == "GHN-TOKEN-xyz" and load["config"]["shop_id"] == "12345"

        # đổi config sau khi enable -> test cũ hết hiệu lực (last_test cleared) + version bump
        async with conn.transaction():
            up = await S.update_public(conn, iid, label="GHN v2", config_public={"shop_id": "999"},
                                       expected_version=en["version"], actor="po")
        assert up["last_test"]["status"] is None

        # disable -> kill-switch, loader không còn active record -> fail-closed none (no env fallback)
        async with conn.transaction():
            await S.disable(conn, iid, actor="po")
        monkeypatch.setattr(settings, "settings_integrations_env_fallback", False)
        load2 = await S.load_active_config(conn, "ghn", "staging")
        assert load2["source"] == "none" and load2["enabled"] is False

        # cleanup (test order, không để rác giữa các lần chạy)
        async with conn.transaction():
            await conn.execute("DELETE FROM integration_secrets WHERE integration_id=$1", iid)
            await conn.execute("DELETE FROM integrations WHERE id=$1", iid)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_cas_conflict(monkeypatch):
    _crypto_env(monkeypatch)
    conn = await _conn()
    try:
        async with conn.transaction():
            it = await S.create_integration(conn, kind="shipping", provider="ghn", label="G", mode="staging",
                                            config_public={"shop_id": "1"}, actor="po")
        iid = it["id"]
        async with conn.transaction():
            await S.update_public(conn, iid, label="A", config_public=None, expected_version=it["version"], actor="po")
        # dùng lại expected_version cũ -> conflict
        with pytest.raises(S.SettingsError):
            async with conn.transaction():
                await S.update_public(conn, iid, label="B", config_public=None, expected_version=it["version"],
                                      actor="po")
        async with conn.transaction():
            await conn.execute("DELETE FROM integrations WHERE id=$1", iid)
    finally:
        await conn.close()
