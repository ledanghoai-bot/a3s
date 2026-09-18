"""CA Directive 305 (+ Review 307 V02) — settings integrations service DB test (m5lab, M6_TEST_DB=1). Skip khong DB.

Bao phu: create/update CAS + command_key idempotency, secret write-only + no-plaintext readback + no-op idempotent,
provider schema validation (307-03), test-connection HAI PHA bind config_revision (307-04/05), enable-gate current sau
enable (307-05), purge tach secret_write, concurrency 2-connection (create/enable effective-once), loader fail-closed.
"""
import asyncio
import base64
import os
import uuid

import pytest

from app.config import settings
from app.services.settings import integrations as S

DB = os.environ.get("M6_TEST_DB") == "1"
pytestmark = pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")


def _ck():
    return "t-" + uuid.uuid4().hex


def _crypto_env(monkeypatch):
    monkeypatch.setattr(settings, "config_enc_keys", f"k1:{base64.b64encode(b'A'*32).decode()}")
    monkeypatch.setattr(settings, "config_enc_key_current", "k1")
    monkeypatch.setattr(settings, "config_secret_fp_key", base64.b64encode(b'F'*32).decode())


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


def _full_cfg(**over):
    base = {"shop_id": "12345", "from_district_id": 1454, "from_ward_code": "21211", "timeout_seconds": 8,
            "max_retries": 2, "light_max_g": 20000, "address_map_version": 1}
    base.update(over)
    return base


async def _ok_post(cfg, path, body, *, retries):
    return 200, {"code": 200, "data": [{"ProvinceID": 1}, {"ProvinceID": 2}]}, "", 12


async def _fail_post(cfg, path, body, *, retries):
    return 401, {"code": 401, "message": "Token invalid"}, "", 9


async def _cleanup(conn, iid):
    async with conn.transaction():
        await conn.execute("DELETE FROM integration_commands WHERE integration_id=$1", iid)
        await conn.execute("DELETE FROM integration_secrets WHERE integration_id=$1", iid)
        await conn.execute("DELETE FROM integrations WHERE id=$1", iid)


@pytest.mark.asyncio
async def test_ghn_config_lifecycle(monkeypatch):
    _crypto_env(monkeypatch)
    conn = await _conn()
    iid = None
    try:
        async with conn.transaction():
            it = await S.create_integration(conn, kind="shipping", provider="ghn", label="GHN staging",
                                            mode="staging", config_public=_full_cfg(base_url="https://evil.example"),
                                            actor="po", command_key=_ck())
        iid = it["id"]
        # base_url bi pin ve staging (khong nhan arbitrary host — 305-08)
        assert it["config_public"]["base_url"].endswith("ghn.vn/shiip/public-api")

        # enable truoc khi co secret + test -> reject
        with pytest.raises(S.SettingsError):
            async with conn.transaction():
                await S.enable(conn, iid, expected_version=it["version"], actor="po", command_key=_ck())

        # write secret token (write-only)
        d = await S.get_integration(conn, iid)
        async with conn.transaction():
            w = await S.write_secret(conn, iid, key_name="token", plaintext="GHN-TOKEN-xyz",
                                     expected_version=d["version"], actor="po", command_key=_ck())
        assert w["version"] == 1
        # readback KHONG lo plaintext/ciphertext
        d = await S.get_integration(conn, iid)
        assert d["secrets"]["token"]["present"] is True and d["secrets"]["token"].get("last4") is None
        assert "value" not in d["secrets"]["token"] and "ciphertext" not in str(d)

        # nhap lai DUNG secret cu (command_key khac) -> no-op, khong bump secret version
        async with conn.transaction():
            w2 = await S.write_secret(conn, iid, key_name="token", plaintext="GHN-TOKEN-xyz",
                                      expected_version=d["version"], actor="po", command_key=_ck())
        assert w2.get("unchanged") is True and w2["version"] == 1

        # enable truoc test-pass -> reject
        d = await S.get_integration(conn, iid)
        with pytest.raises(S.SettingsError):
            async with conn.transaction():
                await S.enable(conn, iid, expected_version=d["version"], actor="po", command_key=_ck())

        # test-connection FAIL (mock 401) -> last_test=fail, enable van reject
        r = await S.test_connection(conn, iid, actor="po", post=_fail_post)
        assert r["ok"] is False and r["error_class"] == "http_401"
        d = await S.get_integration(conn, iid)
        with pytest.raises(S.SettingsError):
            async with conn.transaction():
                await S.enable(conn, iid, expected_version=d["version"], actor="po", command_key=_ck())

        # test-connection PASS (mock) -> enable OK
        r = await S.test_connection(conn, iid, actor="po", post=_ok_post)
        assert r["ok"] is True and r["province_count"] == 2
        d = await S.get_integration(conn, iid)
        cfg_rev_before = d["config_revision"]
        async with conn.transaction():
            en = await S.enable(conn, iid, expected_version=d["version"], actor="po", command_key=_ck())
        assert en["enabled"] is True
        # 307-05: enable bump lifecycle version nhung config_revision GIU NGUYEN -> test van current
        assert en["config_revision"] == cfg_rev_before
        d = await S.get_integration(conn, iid)
        assert d["last_test"]["config_version"] == d["config_revision"]

        # loader: module ON -> doc tu DB (decrypt token server-side)
        monkeypatch.setattr(settings, "settings_integrations_enabled", True)
        load = await S.load_active_config(conn, "ghn", "staging")
        assert load["source"] == "database" and load["enabled"] is True
        assert load["secrets"]["token"] == "GHN-TOKEN-xyz" and load["config"]["shop_id"] == "12345"

        # doi config sau khi enable -> test cu het hieu luc (last_test cleared) + config_revision bump
        d = await S.get_integration(conn, iid)
        async with conn.transaction():
            up = await S.update_public(conn, iid, label="GHN v2", config_public=_full_cfg(shop_id="999"),
                                       expected_version=d["version"], actor="po", command_key=_ck())
        assert up["last_test"]["status"] is None and up["config_revision"] == cfg_rev_before + 1

        # disable (CAS) -> kill-switch, loader khong con active record -> fail-closed none
        async with conn.transaction():
            await S.disable(conn, iid, expected_version=up["version"], actor="po", command_key=_ck())
        monkeypatch.setattr(settings, "settings_integrations_env_fallback", False)
        load2 = await S.load_active_config(conn, "ghn", "staging")
        assert load2["source"] == "none" and load2["enabled"] is False
    finally:
        if iid:
            await _cleanup(conn, iid)
        await conn.close()


@pytest.mark.asyncio
async def test_cas_conflict(monkeypatch):
    _crypto_env(monkeypatch)
    conn = await _conn()
    iid = None
    try:
        async with conn.transaction():
            it = await S.create_integration(conn, kind="shipping", provider="ghn", label="G", mode="staging",
                                            config_public={"shop_id": "1"}, actor="po", command_key=_ck())
        iid = it["id"]
        async with conn.transaction():
            await S.update_public(conn, iid, label="A", config_public=None, expected_version=it["version"],
                                  actor="po", command_key=_ck())
        # dung lai expected_version cu -> conflict
        with pytest.raises(S.SettingsConflict):
            async with conn.transaction():
                await S.update_public(conn, iid, label="B", config_public=None, expected_version=it["version"],
                                      actor="po", command_key=_ck())
    finally:
        if iid:
            await _cleanup(conn, iid)
        await conn.close()


@pytest.mark.asyncio
async def test_command_key_replay_and_conflict(monkeypatch):
    """307-02: cung command_key+payload -> replay ket qua cu; cung key+payload khac -> conflict."""
    _crypto_env(monkeypatch)
    conn = await _conn()
    iid = None
    try:
        async with conn.transaction():
            it = await S.create_integration(conn, kind="shipping", provider="ghn", label="G", mode="staging",
                                            config_public={"shop_id": "1"}, actor="po", command_key=_ck())
        iid = it["id"]
        ck = _ck()
        async with conn.transaction():
            a = await S.update_public(conn, iid, label="X", config_public=None, expected_version=it["version"],
                                      actor="po", command_key=ck)
        # replay cung key+payload -> ket qua cu, KHONG bump them
        async with conn.transaction():
            b = await S.update_public(conn, iid, label="X", config_public=None, expected_version=it["version"],
                                      actor="po", command_key=ck)
        assert b.get("_replay") is True and b["version"] == a["version"]
        # cung key + payload khac -> conflict
        with pytest.raises(S.SettingsConflict):
            async with conn.transaction():
                await S.update_public(conn, iid, label="DIFFERENT", config_public=None,
                                      expected_version=it["version"], actor="po", command_key=ck)
    finally:
        if iid:
            await _cleanup(conn, iid)
        await conn.close()


@pytest.mark.asyncio
async def test_provider_validation_rejects_unknown_and_bad(monkeypatch):
    """307-03: unknown field + bound sai bi reject (khong mutation)."""
    _crypto_env(monkeypatch)
    conn = await _conn()
    iid = None
    try:
        # unknown field
        with pytest.raises(S.SettingsError):
            async with conn.transaction():
                await S.create_integration(conn, kind="shipping", provider="ghn", label="G", mode="staging",
                                           config_public={"evil": 1}, actor="po", command_key=_ck())
        # bound sai (timeout > 60)
        with pytest.raises(S.SettingsError):
            async with conn.transaction():
                await S.create_integration(conn, kind="shipping", provider="ghn", label="G", mode="staging",
                                           config_public={"timeout_seconds": 999}, actor="po", command_key=_ck())
        # thieu pickup -> test reject (khong probe)
        async with conn.transaction():
            it = await S.create_integration(conn, kind="shipping", provider="ghn", label="G", mode="staging",
                                            config_public={"shop_id": "1"}, actor="po", command_key=_ck())
        iid = it["id"]
        async with conn.transaction():
            await S.write_secret(conn, iid, key_name="token", plaintext="tok", expected_version=it["version"],
                                 actor="po", command_key=_ck())
        d = await S.get_integration(conn, iid)
        with pytest.raises(S.SettingsError):
            await S.test_connection(conn, iid, actor="po", post=_ok_post)
        # last_test khong duoc ghi (thieu cau hinh -> khong probe)
        d = await S.get_integration(conn, iid)
        assert d["last_test"]["status"] is None
    finally:
        if iid:
            await _cleanup(conn, iid)
        await conn.close()


@pytest.mark.asyncio
async def test_concurrent_create_one_wins(monkeypatch):
    """307-02.4: hai create dong thoi cung (provider,mode) -> dung MOT thanh cong, con lai conflict."""
    _crypto_env(monkeypatch)
    c1 = await _conn()
    c2 = await _conn()
    mode = "staging"
    provider = "ghn"
    # don sach truoc (dam bao khong con record cu)
    async with c1.transaction():
        rows = await c1.fetch("SELECT id FROM integrations WHERE provider=$1 AND mode=$2 AND archived_at IS NULL",
                              provider, mode)
    for r in rows:
        await _cleanup(c1, r["id"])

    async def _mk(c):
        try:
            async with c.transaction():
                return await S.create_integration(c, kind="shipping", provider=provider, label="G", mode=mode,
                                                  config_public={"shop_id": "1"}, actor="po", command_key=_ck())
        except S.SettingsConflict:
            return "conflict"

    created = None
    try:
        r1, r2 = await asyncio.gather(_mk(c1), _mk(c2))
        outcomes = [r1, r2]
        assert outcomes.count("conflict") == 1, f"phai co dung 1 conflict, duoc {outcomes}"
        created = next(x for x in outcomes if x != "conflict")
    finally:
        if created:
            await _cleanup(c1, created["id"])
        await c1.close()
        await c2.close()


@pytest.mark.asyncio
async def test_concurrent_enable_effective_once(monkeypatch):
    """307-02: hai enable dong thoi cung expected_version -> dung MOT thanh cong."""
    _crypto_env(monkeypatch)
    setup = await _conn()
    c1 = await _conn()
    c2 = await _conn()
    iid = None
    try:
        async with setup.transaction():
            it = await S.create_integration(setup, kind="shipping", provider="ghn", label="G", mode="staging",
                                            config_public=_full_cfg(), actor="po", command_key=_ck())
        iid = it["id"]
        async with setup.transaction():
            await S.write_secret(setup, iid, key_name="token", plaintext="tok", expected_version=it["version"],
                                 actor="po", command_key=_ck())
        await S.test_connection(setup, iid, actor="po", post=_ok_post)
        d = await S.get_integration(setup, iid)
        ev = d["version"]

        async def _en(c):
            try:
                async with c.transaction():
                    return await S.enable(c, iid, expected_version=ev, actor="po", command_key=_ck())
            except S.SettingsError:
                return "err"

        r1, r2 = await asyncio.gather(_en(c1), _en(c2))
        outcomes = [r1, r2]
        assert outcomes.count("err") == 1, f"phai dung 1 that bai (effective-once), duoc {outcomes}"
    finally:
        if iid:
            await _cleanup(setup, iid)
        await setup.close()
        await c1.close()
        await c2.close()


@pytest.mark.asyncio
async def test_test_connection_stale_when_config_changes_during_probe(monkeypatch):
    """307-04: config/secret doi trong khi probe dang cho -> ket qua stale, KHONG ghi last_test."""
    _crypto_env(monkeypatch)
    conn = await _conn()
    mutator = await _conn()
    iid = None
    try:
        async with conn.transaction():
            it = await S.create_integration(conn, kind="shipping", provider="ghn", label="G", mode="staging",
                                            config_public=_full_cfg(), actor="po", command_key=_ck())
        iid = it["id"]
        async with conn.transaction():
            await S.write_secret(conn, iid, key_name="token", plaintext="tok", expected_version=it["version"],
                                 actor="po", command_key=_ck())

        async def _mutating_post(cfg, path, body, *, retries):
            # gia lap: giua luc probe, config bi doi (bump config_revision) boi request khac.
            await mutator.execute("UPDATE integrations SET config_revision=config_revision+1 WHERE id=$1", iid)
            return 200, {"code": 200, "data": [{"ProvinceID": 1}]}, "", 10

        r = await S.test_connection(conn, iid, actor="po", post=_mutating_post)
        assert r.get("stale") is True
        d = await S.get_integration(conn, iid)
        assert d["last_test"]["status"] is None   # ket qua stale khong duoc ghi
    finally:
        if iid:
            await _cleanup(conn, iid)
        await conn.close()
        await mutator.close()


@pytest.mark.asyncio
async def test_purge_requires_existing_and_disables(monkeypatch):
    _crypto_env(monkeypatch)
    conn = await _conn()
    iid = None
    try:
        async with conn.transaction():
            it = await S.create_integration(conn, kind="shipping", provider="ghn", label="G", mode="staging",
                                            config_public=_full_cfg(), actor="po", command_key=_ck())
        iid = it["id"]
        # purge khi chua co secret -> NotFound
        d = await S.get_integration(conn, iid)
        with pytest.raises(S.SettingsNotFound):
            async with conn.transaction():
                await S.purge_secret(conn, iid, key_name="token", expected_version=d["version"], actor="po",
                                     command_key=_ck())
        # them secret + enable roi purge -> disable + secret bien mat
        async with conn.transaction():
            await S.write_secret(conn, iid, key_name="token", plaintext="tok", expected_version=d["version"],
                                 actor="po", command_key=_ck())
        await S.test_connection(conn, iid, actor="po", post=_ok_post)
        d = await S.get_integration(conn, iid)
        async with conn.transaction():
            await S.enable(conn, iid, expected_version=d["version"], actor="po", command_key=_ck())
        d = await S.get_integration(conn, iid)
        async with conn.transaction():
            await S.purge_secret(conn, iid, key_name="token", expected_version=d["version"], actor="po",
                                 command_key=_ck())
        d = await S.get_integration(conn, iid)
        assert "token" not in d["secrets"] and d["enabled"] is False
    finally:
        if iid:
            await _cleanup(conn, iid)
        await conn.close()
