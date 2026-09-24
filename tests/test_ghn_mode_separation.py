"""CA Directive 357 §4 — tach TUYET DOI GHN staging/production.

Pure (CI) + DB (M6_TEST_DB=1). Khong credential that, khong goi GHN (transport mock/controlled).
Bao phu: tach mode (token/ShopId/pickup/endpoint/snapshot/map), endpoint allowlist + fail-closed, token write-only +
audit redacted, contract G1 khong hoi quy o ca 2 mode, guard >20 kg trong production, tool mode/cap/dry-run/compare.
"""
import asyncio
import base64
import importlib.util
import json
import os
import pathlib
import uuid

import pytest

from app.config import settings
from app.services.providers import ghn
from app.services.providers import ghn_master_data as md
from app.services.providers.base import QUOTE_OK, QuoteRequest
from app.services.settings import integrations as S

DB = os.environ.get("M6_TEST_DB") == "1"
ROOT = pathlib.Path(__file__).resolve().parents[1]
TOK = {"staging": "TOK-STG-357", "production": "TOK-PRD-357"}
SHOP = {"staging": "111111", "production": "999999"}      # gia tri GIA — khong dung ShopId that trong fixture


def _cfg(mode, **over):
    return {"enabled": True, "base": ghn.BASE_BY_MODE[mode], "token": TOK[mode], "shop_id": SHOP[mode],
            "from_district_id": 1552, "from_ward_code": "400105", "timeout": 1.0, "retries": 0,
            "light_max_g": 20000, "map_version": 1, "mode": mode, **over}


class _Conn:
    """FakeConn: ghi lai tham so address_lookup + cac lenh ghi."""
    def __init__(self, map_rows=None):
        self.lookups, self.execs = [], []
        self.map_rows = map_rows or {}      # (mode, province, ward) -> dict|None

    async def fetchrow(self, sql, *a):
        if "carrier_address_map" in sql:
            provider, mode, mv, pc, wc = a
            self.lookups.append({"mode": mode, "map_version": mv, "pc": pc, "wc": wc})
            return self.map_rows.get((mode, pc, wc))
        return None

    async def execute(self, sql, *a):
        self.execs.append(sql)


MATCH = {"carrier_province_id": 210, "carrier_district_id": 1954, "carrier_ward_code": "400701",
         "status": "matched", "method": "staff", "confidence": None}


def _post(calls, fee=42900):
    async def p(cfg, path, body, *, retries):
        calls.append({"path": path, "base": cfg["base"], "token": cfg["token"], "shop": cfg["shop_id"],
                      "body": dict(body)})
        if path.endswith("/fee"):
            return 200, {"code": 200, "data": {"total": fee}}, "", 3
        return 200, {"code": 200, "data": {"leadtime": 0}}, "", 2
    return p


def _req(w=400, pc="66", wc="24490"):
    return QuoteRequest(order_id=1, province_code=pc, ward_code=wc, weight_g=w, length_cm=10, width_cm=10,
                        height_cm=11)


def _patch_loader(monkeypatch, by_mode: dict):
    seen = []

    async def fake(conn, provider, mode):
        seen.append(mode)
        lc = by_mode.get(mode)
        if lc is None:
            return {"source": "none", "enabled": False, "config": {}, "secrets": {}}
        return lc
    monkeypatch.setattr(S, "load_active_config", fake)
    return seen


def _db_cfg(mode, base=None):
    return {"source": "database", "enabled": True, "secrets": {"token": TOK[mode]},
            "config": {"base_url": base or ghn.BASE_BY_MODE[mode], "shop_id": SHOP[mode], "from_district_id": 1552,
                       "from_ward_code": "400105", "timeout_seconds": 8, "max_retries": 1, "light_max_g": 20000,
                       "address_map_version": 1}}


def _env(monkeypatch, mode):
    monkeypatch.setattr(settings, "m7_ghn_quote", True)
    monkeypatch.setattr(settings, "settings_integrations_enabled", True)
    monkeypatch.setattr(settings, "ghn_active_mode", mode)
    monkeypatch.setattr(settings, "ghn_token", "")
    monkeypatch.setattr(settings, "ghn_shop_id", "")


# ================================================================== PURE — mode selection & endpoint pin
def test_base_pinned_per_mode():
    assert ghn.BASE_BY_MODE["staging"].startswith("https://dev-online-gateway.ghn.vn")
    assert ghn.BASE_BY_MODE["production"].startswith("https://online-gateway.ghn.vn")
    assert S.ghn_base_for_mode("production") == ghn.BASE_BY_MODE["production"]
    for bad in ("prod", "", "Production", None):
        with pytest.raises(S.SettingsError):
            S.ghn_base_for_mode(bad)


def test_validate_public_pins_base_and_rejects_arbitrary_url():
    for mode in ("staging", "production"):
        out = S._validate_public("ghn", {"base_url": "https://evil.example", "shop_id": "1"}, mode)
        assert out["base_url"] == ghn.BASE_BY_MODE[mode]      # URL tuy y bi ghi de bang base ghim
    with pytest.raises(S.SettingsError):
        S._validate_public("ghn", {"shop_id": "1"}, "prod-typo")


@pytest.mark.parametrize("mode", ["staging", "production"])
def test_resolve_cfg_picks_active_mode_only(monkeypatch, mode):
    _env(monkeypatch, mode)
    other = "production" if mode == "staging" else "staging"
    seen = _patch_loader(monkeypatch, {"staging": _db_cfg("staging"), "production": _db_cfg("production")})
    c = asyncio.run(ghn.resolve_quote_cfg(None))
    assert seen == [mode] and c["mode"] == mode and c["source"] == "database"
    assert c["token"] == TOK[mode] and c["shop_id"] == SHOP[mode] and c["base"] == ghn.BASE_BY_MODE[mode]
    assert c["token"] != TOK[other] and c["shop_id"] != SHOP[other]        # KHONG tron cheo


def test_resolve_cfg_mode_invalid_fail_closed(monkeypatch):
    for bad in ("", "prod", "PRODUCTION", "  "):
        _env(monkeypatch, bad)
        seen = _patch_loader(monkeypatch, {"staging": _db_cfg("staging")})
        c = asyncio.run(ghn.resolve_quote_cfg(None))
        assert c["source"] == "mode_invalid" and c["token"] == "" and seen == []    # khong doc DB/secret


def test_resolve_cfg_base_mode_mismatch_fail_closed(monkeypatch):
    _env(monkeypatch, "production")
    # config production nhung base_url lai la staging (vd copy nham) -> fail-closed
    _patch_loader(monkeypatch, {"production": _db_cfg("production", base=ghn.BASE_BY_MODE["staging"])})
    c = asyncio.run(ghn.resolve_quote_cfg(None))
    assert c["source"] == "base_mode_mismatch" and c["token"] == "" and c["shop_id"] == ""


def test_resolve_cfg_missing_config_or_decrypt_error_fail_closed(monkeypatch):
    _env(monkeypatch, "production")
    _patch_loader(monkeypatch, {"staging": _db_cfg("staging")})        # khong co record production
    assert asyncio.run(ghn.resolve_quote_cfg(None))["source"] == "none"

    async def boom(conn, provider, mode):
        raise RuntimeError("decrypt failed")
    monkeypatch.setattr(S, "load_active_config", boom)
    c = asyncio.run(ghn.resolve_quote_cfg(None))
    assert c["source"] == "db_error" and c["token"] == ""


# ============================================= PURE — R359-01: env legacy KHONG duoc dung cho production
def _env_cfg_legacy(monkeypatch):
    """Gia lap .env legacy (khong mang mode): token/ShopId/pickup/base cua STAGING nam san trong settings."""
    monkeypatch.setattr(settings, "ghn_base_url", ghn.STAGING_BASE)
    monkeypatch.setattr(settings, "ghn_token", "TOK-ENV-LEGACY")
    monkeypatch.setattr(settings, "ghn_shop_id", SHOP["staging"])
    monkeypatch.setattr(settings, "ghn_from_district_id", 1552)
    monkeypatch.setattr(settings, "ghn_from_ward_code", "400105")


def test_r359_production_module_off_fail_closed(monkeypatch):
    """active=production + module OFF -> production_env_disallowed: khong token/ShopId/pickup, khong doc DB/secret."""
    _env(monkeypatch, "production")
    _env_cfg_legacy(monkeypatch)
    monkeypatch.setattr(settings, "settings_integrations_enabled", False)
    seen = _patch_loader(monkeypatch, {"production": _db_cfg("production")})
    c = asyncio.run(ghn.resolve_quote_cfg(None))
    assert c["source"] == "production_env_disallowed" and c["mode"] == "production"
    assert c["token"] == "" and c["shop_id"] == "" and c["from_district_id"] is None and c["from_ward_code"] == ""
    assert seen == []                                    # KHONG cham loader/secret
    # quote() voi cfg nay -> quote_required, KHONG HTTP
    calls = []
    conn = _Conn({("production", "66", "24490"): MATCH})
    res = asyncio.run(ghn.GhnQuoteProvider(c, post=_post(calls)).quote(conn, _req()))
    assert res.status == "quote_required" and res.reason == "ghn_not_configured" and calls == []


def test_r359_production_env_fallback_fail_closed(monkeypatch):
    """active=production + module ON + env_fallback nhung khong co record DB production -> fail-closed, 0 HTTP."""
    _env(monkeypatch, "production")
    _env_cfg_legacy(monkeypatch)
    monkeypatch.setattr(settings, "settings_integrations_env_fallback", True, raising=False)
    _patch_loader(monkeypatch, {"production": {"source": "env", "enabled": True, "config": {}, "secrets": {}}})
    c = asyncio.run(ghn.resolve_quote_cfg(None))
    assert c["source"] == "production_env_disallowed"
    assert c["token"] == "" and c["shop_id"] == "" and c["from_district_id"] is None
    calls = []
    conn = _Conn({("production", "66", "24490"): MATCH})
    res = asyncio.run(ghn.GhnQuoteProvider(c, post=_post(calls)).quote(conn, _req()))
    assert res.status == "quote_required" and calls == []


@pytest.mark.parametrize("module_on", [False, True])
def test_r359_staging_env_baseline_khong_doi(monkeypatch, module_on):
    """Backward compat D305: staging VAN duoc dung env khi module OFF hoac loader tra source='env'."""
    _env(monkeypatch, "staging")
    _env_cfg_legacy(monkeypatch)
    monkeypatch.setattr(settings, "settings_integrations_enabled", module_on)
    if module_on:
        _patch_loader(monkeypatch, {"staging": {"source": "env", "enabled": True, "config": {}, "secrets": {}}})
    c = asyncio.run(ghn.resolve_quote_cfg(None))
    assert c["source"] == "env" and c["mode"] == "staging"
    assert c["token"] == "TOK-ENV-LEGACY" and c["shop_id"] == SHOP["staging"]      # baseline giu nguyen


def test_r359_production_record_db_van_quote_duoc(monkeypatch):
    """Duong DUY NHAT cho production: record Dashboard dung mode -> quote chay binh thuong (transport mock)."""
    _env(monkeypatch, "production")
    _env_cfg_legacy(monkeypatch)
    _patch_loader(monkeypatch, {"production": _db_cfg("production")})
    c = asyncio.run(ghn.resolve_quote_cfg(None))
    assert c["source"] == "database" and c["token"] == TOK["production"] and c["shop_id"] == SHOP["production"]
    assert c["token"] != "TOK-ENV-LEGACY"                  # KHONG lay tu env
    calls = []
    conn = _Conn({("production", "66", "24490"): MATCH})
    res = asyncio.run(ghn.GhnQuoteProvider(c, post=_post(calls)).quote(conn, _req()))
    assert res.status == QUOTE_OK and all(x["base"] == ghn.PROD_BASE for x in calls)


# ================================================================== PURE — quote contract theo mode
@pytest.mark.parametrize("mode", ["staging", "production"])
def test_quote_uses_mode_map_and_mode_endpoint(mode):
    calls = []
    conn = _Conn({(mode, "66", "24490"): MATCH})
    res = asyncio.run(ghn.GhnQuoteProvider(_cfg(mode), post=_post(calls)).quote(conn, _req()))
    assert res.status == QUOTE_OK and res.fee_vnd == 42900
    assert conn.lookups and conn.lookups[0]["mode"] == mode              # tra map DUNG mode
    assert all(c["base"] == ghn.BASE_BY_MODE[mode] for c in calls)       # endpoint DUNG mode
    assert all(c["token"] == TOK[mode] and c["shop"] == SHOP[mode] for c in calls)


def test_quote_map_of_other_mode_not_used():
    calls = []
    conn = _Conn({("staging", "66", "24490"): MATCH})                   # chi co map staging
    res = asyncio.run(ghn.GhnQuoteProvider(_cfg("production"), post=_post(calls)).quote(conn, _req()))
    assert res.status == "quote_required" and res.reason == "address_unmapped" and calls == []


@pytest.mark.parametrize("mode", ["staging", "production"])
def test_failure_paths_fail_closed_both_modes(mode):
    conn = _Conn({(mode, "66", "24490"): MATCH})
    cases = {"timeout": (None, None, "timeout", 9), "http_429": (429, {"code": 429}, "", 9),
             "http_500": (500, {"code": 500}, "", 9), "schema": (200, {"code": 200, "data": {"total": "x"}}, "", 9)}
    for name, ret in cases.items():
        async def inj(cfg, path, body, *, retries, _r=ret):
            return _r
        res = asyncio.run(ghn.GhnQuoteProvider(_cfg(mode), post=inj).quote(conn, _req()))
        assert res.status == "quote_required" and res.fee_vnd is None, (mode, name)


@pytest.mark.parametrize("mode", ["staging", "production"])
def test_heavy_guard_in_both_modes(mode):
    calls = []
    conn = _Conn({(mode, "66", "24490"): MATCH})
    res = asyncio.run(ghn.GhnQuoteProvider(_cfg(mode, light_max_g=50000), post=_post(calls)).quote(conn, _req(20001)))
    assert res.reason == "heavy_goods_manual" and calls == [] and conn.lookups == [] and conn.execs == []
    res2 = asyncio.run(ghn.GhnQuoteProvider(_cfg(mode), post=_post(calls)).quote(conn, _req(20000)))
    assert res2.status == QUOTE_OK                                       # bien 20.000 g khong bi guard


# ================================================================== PURE — RBAC (§4.3): mode KHONG mo duong vong
_PROD_BODY = {"kind": "shipping", "provider": "ghn", "label": "GHN prod", "mode": "production",
              "config_public": {"shop_id": "9999999"}, "command_key": "k357"}


def _rbac_client(perms):
    from fastapi.testclient import TestClient

    from app.api.auth import require_staff_session
    from app.main import app

    async def _fake():
        return {"id": 1, "username": "tester", "rbac_provisioned": True, "permissions": set(perms)}
    app.dependency_overrides[require_staff_session] = _fake
    settings.settings_integrations_enabled = True
    return TestClient(app, raise_server_exceptions=False), app


def _rbac_clear(app):
    from app.api.auth import require_staff_session
    app.dependency_overrides.pop(require_staff_session, None)
    settings.settings_integrations_enabled = False


def test_rbac_production_config_needs_same_granular_permissions():
    """Tao/sua config production va ghi token production KHONG co duong rieng: van qua manage_public/secret_write."""
    c, app = _rbac_client([])          # khong quyen
    try:
        assert c.post("/dashboard/settings/integrations", json=_PROD_BODY).status_code == 403
        assert c.post("/dashboard/settings/integrations/1/secret",
                      json={"key_name": "token", "value": "x", "expected_version": 1,
                            "command_key": "k357"}).status_code == 403
        assert c.post("/dashboard/settings/integrations/1/enable",
                      json={"expected_version": 1, "command_key": "k357"}).status_code == 403
    finally:
        _rbac_clear(app)
    # chi co quyen xem -> van khong duoc tao config production
    c2, app2 = _rbac_client(["settings.integration.view"])
    try:
        assert c2.post("/dashboard/settings/integrations", json=_PROD_BODY).status_code == 403
    finally:
        _rbac_clear(app2)


def test_module_gate_blocks_production_surface():
    """Flag settings_integrations_enabled OFF -> toan bo surface 404, ke ca duong production (zero DB effect)."""
    from fastapi.testclient import TestClient

    from app.api.auth import require_staff_session
    from app.main import app

    async def _fake():
        return {"id": 1, "username": "tester", "rbac_provisioned": True,
                "permissions": {"settings.integration.manage_public"}}
    app.dependency_overrides[require_staff_session] = _fake
    settings.settings_integrations_enabled = False
    try:
        assert TestClient(app, raise_server_exceptions=False).post(
            "/dashboard/settings/integrations", json=_PROD_BODY).status_code == 404
    finally:
        app.dependency_overrides.pop(require_staff_session, None)


# ================================================================== PURE — tooling
def test_tool_requires_valid_mode():
    for bad in ("prod", "", None, "Staging"):
        with pytest.raises(ValueError):
            md.check_mode(bad)
    assert md.check_mode("production") == "production"


def test_cli_requires_mode_and_caps_requests():
    spec = importlib.util.spec_from_file_location("ghn_g1_prep", ROOT / "scripts" / "ghn_g1_prep.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["plan"])                               # thieu --mode
    a = cli._parser().parse_args(["snapshot", "--mode", "production", "--target", "Gia Lai=Pleiku"])
    assert a.mode == "production" and a.cap == md.DEFAULT_CAP and not a.execute
    b = cli._mode_banner(a)
    assert b["mode"] == "production" and b["endpoint_base"] == ghn.BASE_BY_MODE["production"] and b["execute"] is False
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["compare-modes", "--mode", "prod"])    # choices chan mode sai


# ================================================================== DB
def _crypto(monkeypatch):
    monkeypatch.setattr(settings, "config_enc_keys", f"k1:{base64.b64encode(b'A'*32).decode()}")
    monkeypatch.setattr(settings, "config_enc_key_current", "k1")
    monkeypatch.setattr(settings, "config_secret_fp_key", base64.b64encode(b'F'*32).decode())


def _ck():
    return "m357-" + uuid.uuid4().hex


def _pub(mode):
    return {"shop_id": SHOP[mode], "from_district_id": 1552, "from_ward_code": "400105", "timeout_seconds": 8,
            "max_retries": 1, "light_max_g": 20000, "address_map_version": 1}


async def _mk_both(conn):
    await conn.execute("DELETE FROM integration_commands WHERE integration_id IN (SELECT id FROM integrations WHERE provider='ghn')")
    await conn.execute("DELETE FROM integration_secrets WHERE integration_id IN (SELECT id FROM integrations WHERE provider='ghn')")
    await conn.execute("DELETE FROM integrations WHERE provider='ghn'")
    ids = {}
    for mode in ("staging", "production"):
        it = await S.create_integration(conn, kind="shipping", provider="ghn", label=f"GHN {mode}", mode=mode,
                                        config_public=_pub(mode), actor="po", command_key=_ck())
        it2 = await S.write_secret(conn, it["id"], key_name="token", plaintext=TOK[mode],
                                   expected_version=it["version"], actor="po", command_key=_ck())
        ids[mode] = (it["id"], it2["integration_version"])
    return ids


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_two_modes_isolated_config_and_secret(monkeypatch):
    import asyncpg
    _crypto(monkeypatch)
    conn = await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    tr = conn.transaction()
    await tr.start()
    try:
        ids = await _mk_both(conn)
        for mode in ("staging", "production"):
            saved = await S.load_saved_ghn_config(conn, mode)
            assert saved["mode"] == mode and saved["token"] == TOK[mode]
            assert saved["config"]["shop_id"] == SHOP[mode]
            assert saved["config"]["base_url"] == ghn.BASE_BY_MODE[mode]      # base ghim theo mode
            assert saved["enabled"] is False                                   # khong tu enable
        # readback API KHONG chua secret
        for it in await S.list_integrations(conn, kind="shipping"):
            blob = json.dumps(it, default=str)
            assert TOK["staging"] not in blob and TOK["production"] not in blob
            tok = it["secrets"]["token"]
            # readback chi co metadata: present/version/updated_at; last4 = None (chi account_number moi duoc hien last4)
            assert tok["present"] is True and tok.get("last4") is None and "ciphertext" not in tok
        # audit KHONG chua token
        rows = await conn.fetch("SELECT after FROM audit_log WHERE action LIKE 'settings.integration.%' "
                                "ORDER BY id DESC LIMIT 6")
        for r in rows:
            assert TOK["staging"] not in str(r["after"]) and TOK["production"] not in str(r["after"])
        # mode sai -> fail-closed
        with pytest.raises(S.SettingsError):
            await S.load_saved_ghn_config(conn, "prod")
        assert ids["staging"][0] != ids["production"][0]
    finally:
        await tr.rollback()
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_resolve_uses_active_mode_record(monkeypatch):
    import asyncpg
    _crypto(monkeypatch)
    conn = await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    tr = conn.transaction()
    await tr.start()
    try:
        ids = await _mk_both(conn)

        async def ok_post(cfg, path, body, *, retries):
            return 200, {"code": 200, "data": [{"ProvinceID": 1}]}, "", 3
        for mode in ("staging", "production"):
            iid, _ = ids[mode]
            await S.test_connection(conn, iid, actor="po", post=ok_post)
            d = await S.get_integration(conn, iid)
            await S.enable(conn, iid, expected_version=d["version"], actor="po", command_key=_ck())
        for mode in ("staging", "production"):
            _env(monkeypatch, mode)
            c = await ghn.resolve_quote_cfg(conn)
            assert c["source"] == "database" and c["mode"] == mode and c["token"] == TOK[mode]
            assert c["shop_id"] == SHOP[mode] and c["base"] == ghn.BASE_BY_MODE[mode]
        _env(monkeypatch, "prod")                                    # mode sai -> khong doc gi
        assert (await ghn.resolve_quote_cfg(conn))["source"] == "mode_invalid"
    finally:
        await tr.rollback()
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_master_map_isolated_and_compare_modes():
    import asyncpg
    conn = await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    tr = conn.transaction()
    await tr.start()
    try:
        await conn.execute("DELETE FROM carrier_address_map WHERE province_code='52' AND ward_code='23575'")
        # master-data: staging co ward 1954:400701; production THIEU
        for mode, wards in (("staging", [("1954:400701", "Thị trấn Phước An")]), ("production", [])):
            await conn.execute("INSERT INTO carrier_master_data (provider, mode, kind, key, parent_key, name, payload) "
                               "VALUES ('ghn',$1,'province','210',NULL,'Đắk Lắk','{}'::jsonb) "
                               "ON CONFLICT DO NOTHING", mode)
            await conn.execute("INSERT INTO carrier_master_data (provider, mode, kind, key, parent_key, name, payload) "
                               "VALUES ('ghn',$1,'district','1954','210','Huyện Krông Pắc','{}'::jsonb) "
                               "ON CONFLICT DO NOTHING", mode)
            for k, nm in wards:
                await conn.execute("INSERT INTO carrier_master_data (provider, mode, kind, key, parent_key, name, "
                                   "payload) VALUES ('ghn',$1,'ward',$2,'1954',$3,'{\"WardCode\":\"400701\"}'::jsonb) "
                                   "ON CONFLICT DO NOTHING", mode, k, nm)
        rows = [{"province_code": "52", "ward_code": "23575", "carrier_province_id": 210,
                 "carrier_district_id": 1954, "carrier_ward_code": "400701", "status": "matched", "method": "staff",
                 "confidence": None, "note": "{}"}]
        v_stg = await md.write_map_version(conn, rows, actor="po", source="test", mode="staging")
        # map version doc lap theo mode
        v_prd = await md.write_map_version(conn, rows, actor="po", source="test", mode="production")
        assert v_stg >= 1 and v_prd == 1
        assert await ghn.address_lookup(conn, "52", "23575", map_version=v_stg, mode="staging") is not None
        assert await ghn.address_lookup(conn, "52", "23575", map_version=v_stg + 99, mode="staging") is None
        # compare: production THIEU ward -> reusable False, chi ro entry
        cmp1 = await md.compare_modes(conn, [("52", "23575")], base_mode="staging", target_mode="production")
        assert cmp1["reusable"] is False and cmp1["addresses"][0]["target"] == "MISSING"
        assert cmp1["master"]["ward"]["base"] == 1 and cmp1["master"]["ward"]["target"] == 0
        # them ward vao production -> reusable True
        await conn.execute("INSERT INTO carrier_master_data (provider, mode, kind, key, parent_key, name, payload) "
                           "VALUES ('ghn','production','ward','1954:400701','1954','Thị trấn Phước An',"
                           "'{\"WardCode\":\"400701\"}'::jsonb) ON CONFLICT DO NOTHING")
        cmp2 = await md.compare_modes(conn, [("52", "23575")], base_mode="staging", target_mode="production")
        assert cmp2["reusable"] is True and cmp2["addresses"][0]["target"] == "present"
        with pytest.raises(ValueError):
            await md.compare_modes(conn, [], base_mode="staging", target_mode="prod")
    finally:
        await tr.rollback()
        await conn.close()
