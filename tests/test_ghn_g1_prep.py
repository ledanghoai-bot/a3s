"""CA Directive 345 — GHN G1 prep: runtime config theo loader D305 + master-data tooling (offline, KHONG network).

Pure (chay CI): norm_name giu dau; CappedPost allowlist/cap/dem loi/retries=0; fetch_scoped tren fixture; quy tac map;
resolve_quote_cfg precedence + fail-closed + khong lo token; script dry-run khong doc token/khong goi mang.
DB (M6_TEST_DB=1): load_saved_ghn_config (khong enable), test-connection tren integration chua enable, resolve_quote_cfg
that, persist snapshot + build map + version + audit, import thu cong (phuong an B). Moi test DB rollback/cleanup."""
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

DB = os.environ.get("M6_TEST_DB") == "1"
ROOT = pathlib.Path(__file__).resolve().parents[1]
TOKEN = "TOK-SECRET-345-do-not-leak"

# ------------------------------------------------------------------ fixture danh muc GHN gia (khong network)
PROVS = [{"ProvinceID": 205, "ProvinceName": "Gia Lai", "NameExtension": ["Tỉnh Gia Lai", "Gia Lai"]},
         {"ProvinceID": 210, "ProvinceName": "Đắk Lắk", "NameExtension": ["Tỉnh Đắk Lắk", "Dak Lak"]},
         {"ProvinceID": 202, "ProvinceName": "Hồ Chí Minh", "NameExtension": ["TP.HCM"]}]
DISTS = {205: [{"DistrictID": 1660, "DistrictName": "Thành phố Pleiku", "NameExtension": ["Pleiku", "TP Pleiku"]},
               {"DistrictID": 1661, "DistrictName": "Huyện Chư Păh", "NameExtension": []}],
         210: [{"DistrictID": 1780, "DistrictName": "Huyện Krông Pắc", "NameExtension": ["Krông Pắc"]},
               {"DistrictID": 1781, "DistrictName": "Thành phố Buôn Ma Thuột", "NameExtension": []}]}
WARDS = {1660: [{"WardCode": "400101", "WardName": "Phường Hoa Lư"}, {"WardCode": "400102", "WardName": "Phường Hội Thương"},
                {"WardCode": "400103", "WardName": "Phường Phù Đổng"}, {"WardCode": "400104", "WardName": "Phường Tây Sơn"},
                {"WardCode": "400105", "WardName": "Xã Trà Đa"}],
         1780: [{"WardCode": "470201", "WardName": "Thị trấn Phước An"}, {"WardCode": "470202", "WardName": "Xã Ea Yông"},
                {"WardCode": "470203", "WardName": "Xã Hòa An"}, {"WardCode": "470204", "WardName": "Xã Hòa Tiến"},
                {"WardCode": "470205", "WardName": "Xã Ea Kênh"}, {"WardCode": "470206", "WardName": "Xã Ea Knuếc"},
                {"WardCode": "470207", "WardName": "Xã Hòa Đông"}]}
TARGETS = [{"province": "Gia Lai", "districts": ["Pleiku"]}, {"province": "Đắk Lắk", "districts": ["Krông Pắc"]}]


def _fake_post(calls=None, status=200, fail_on=None):
    calls = [] if calls is None else calls

    async def post(cfg, path, body, *, retries):
        calls.append((path, dict(body), retries, cfg.get("token")))
        if fail_on and path == fail_on:
            return 500, {"code": 500}, "", 3
        if path == "/master-data/province":
            data = PROVS
        elif path == "/master-data/district":
            data = DISTS.get(body["province_id"], [])
        else:
            data = WARDS.get(body["district_id"], [])
        return status, {"code": status, "data": data}, "", 4
    post.calls = calls
    return post


# ================================================================== PURE
def test_norm_name_keeps_accents_and_strips_prefix_consistently():
    assert md.norm_name("Tỉnh Gia Lai") == md.norm_name("Gia Lai") == "gia lai"
    assert md.norm_name("Thị trấn  Phước An") == md.norm_name("Thị Trấn Phước An")
    assert md.norm_name("Huyện Krông Pắc") == md.norm_name("Krông Pắc")
    assert md.norm_name("Xã Hòa An") != md.norm_name("Xã Hoa An")          # KHONG bo dau (dong am gia)
    assert md.norm_name("Huyện Tĩnh Gia") == "tĩnh gia"                     # 'tĩnh' != tien to 'tỉnh'


def test_capped_post_allowlist_blocks_fee_leadtime_services_shipment():
    cp = md.CappedPost(_fake_post(), cap=10)
    for bad in ("/v2/shipping-order/fee", "/v2/shipping-order/leadtime", "/v2/shipping-order/available-services",
                "/v2/shipping-order/create", "/v2/switch-status/cancel", "/v2/shipping-order/update"):
        with pytest.raises(md.PathNotAllowed):
            asyncio.run(cp({}, bad, {}))
    assert cp.calls == []                     # bi chan TRUOC khi dem/goi


def test_capped_post_cap_counts_errors_and_no_retry():
    raw = []
    cp = md.CappedPost(_fake_post(raw, status=500), cap=3)
    for _ in range(3):
        asyncio.run(cp({}, "/master-data/province", {}, retries=5))
    assert len(cp.calls) == 3 and all(c["http_status"] == 500 for c in cp.calls)   # loi van dem
    assert all(r[2] == 0 for r in raw)                                              # luon retries=0
    with pytest.raises(md.CapReached):
        asyncio.run(cp({}, "/master-data/province", {}))
    assert len(raw) == 3                                                            # khong goi lan 4


def test_capped_post_exception_counted_and_aborts():
    async def boom(cfg, path, body, *, retries):
        raise ConnectionError("x")
    cp = md.CappedPost(boom, cap=2)
    with pytest.raises(md.SnapshotAbort):
        asyncio.run(cp({}, "/master-data/province", {}))
    assert len(cp.calls) == 1 and cp.calls[0]["error"] == "ConnectionError"
    with pytest.raises(ValueError):
        md.CappedPost(boom, cap=0)


def test_parse_targets_and_plan_refuses_over_cap_without_call():
    t = md.parse_targets(["Gia Lai=Pleiku", "Đắk Lắk=Krông Pắc|Buôn Ma Thuột"])
    assert md.planned_requests(t) == 1 + 2 + 3
    for bad in ("GiaLai", "=Pleiku", "Gia Lai="):
        with pytest.raises(ValueError):
            md.parse_targets([bad])
    post = _fake_post()
    r = asyncio.run(md.fetch_scoped({}, t, post=post, cap=5))
    assert r["status"] == "aborted" and "cap" in r["reason"] and post.calls == []


def test_fetch_scoped_fixture_completed_within_cap():
    post = _fake_post()
    r = asyncio.run(md.fetch_scoped({"token": TOKEN}, TARGETS, post=post, cap=10))
    assert r["status"] == "completed" and len(r["calls"]) == 5 == len(post.calls)
    assert [c["path"] for c in r["calls"]] == ["/master-data/province", "/master-data/district", "/master-data/ward",
                                               "/master-data/district", "/master-data/ward"]
    assert {x["result"] for x in r["report"]} == {"ok"} and len(r["wards"]) == 12
    assert TOKEN not in json.dumps(r["calls"]) and TOKEN not in json.dumps(r["report"])


def test_fetch_scoped_unmatched_province_and_district_error_reported():
    post = _fake_post(fail_on="/master-data/district")
    r = asyncio.run(md.fetch_scoped({}, [{"province": "Hà Nội", "districts": ["Ba Đình"]}] + TARGETS, post=post,
                                    cap=10))
    res = [x["result"] for x in r["report"]]
    assert "province_match_0" in res and res.count("district_list_error_http_500") == 2


def test_fetch_scoped_cap_mid_run_aborts_and_drops_data():
    r = asyncio.run(md.fetch_scoped({}, TARGETS, post=_fake_post(), cap=5))
    assert r["status"] == "completed"
    # them 1 quan -> du kien 6 > cap 5 -> tu choi truoc
    t2 = [{"province": "Gia Lai", "districts": ["Pleiku", "Chư Păh"]}, TARGETS[1]]
    r2 = asyncio.run(md.fetch_scoped({}, t2, post=_fake_post(), cap=5))
    assert r2["status"] == "aborted" and r2["wards"] == [] and r2["calls"] == []


def _gw(district_id, ward):
    return {"district_id": district_id, "ward_code": ward["WardCode"], "names": md.names_of(ward["WardName"])}


GW_KP = [_gw(1780, w) for w in WARDS[1780]]
GW_PK = [_gw(1660, w) for w in WARDS[1660]]


def test_decide_mapping_rules():
    d = md.decide_mapping("Xã Ea Knuếc", ["Xã Ea Kênh", "Xã Ea Knuếc", "Xã Hòa Đông"], GW_KP)
    assert d["status"] == "matched" and d["basis"] == "name_continuity" and d["carrier_ward_code"] == "470206"
    d = md.decide_mapping("Xã Krông Pắc", ["Thị trấn Phước An", "Xã Ea Yông", "Xã Hòa An", "Xã Hòa Tiến"], GW_KP)
    assert d["status"] == "ambiguous" and len(d["candidates"]) == 4 and d["carrier_ward_code"] is None
    d = md.decide_mapping("Phường Mới", ["Phường Hội Thương"], GW_PK)
    assert d["status"] == "matched" and d["basis"] == "single_candidate" and d["carrier_district_id"] == 1660
    d = md.decide_mapping("Phường X", ["Phường Không Có"], GW_PK)
    assert d["status"] == "unmatched" and d["candidates"] == []
    d = md.decide_mapping("Xã Y", ["Xa Hoa An"], GW_KP)                       # khong dau != 'Hòa An'
    assert d["status"] == "unmatched"


# ---- runtime config (loader D305) ----
def _base_env(monkeypatch, *, quote=True, module=True):
    monkeypatch.setattr(settings, "ghn_active_mode", "staging")     # D357: mode active tuong minh
    monkeypatch.setattr(settings, "m7_ghn_quote", quote)
    monkeypatch.setattr(settings, "settings_integrations_enabled", module)
    monkeypatch.setattr(settings, "ghn_token", "")
    monkeypatch.setattr(settings, "ghn_shop_id", "")


def _patch_loader(monkeypatch, result=None, exc=None):
    from app.services.settings import integrations as S
    called = []

    async def fake(conn, provider, mode):
        called.append((provider, mode))
        if exc:
            raise exc
        return result
    monkeypatch.setattr(S, "load_active_config", fake)
    return called


_DB_CFG = {"source": "database", "enabled": True, "secrets": {"token": TOKEN},
           "config": {"base_url": ghn.STAGING_BASE, "shop_id": "1234567", "from_district_id": 1442,
                      "from_ward_code": "20308", "timeout_seconds": 8, "max_retries": 1, "light_max_g": 20000,
                      "address_map_version": 1}}


def test_resolve_cfg_quote_off_does_not_touch_db(monkeypatch):
    _base_env(monkeypatch, quote=False)
    called = _patch_loader(monkeypatch, _DB_CFG)
    c = asyncio.run(ghn.resolve_quote_cfg(None))
    assert c["source"] == "disabled" and c["enabled"] is False and called == []


def test_resolve_cfg_module_off_uses_env(monkeypatch):
    _base_env(monkeypatch, module=False)
    called = _patch_loader(monkeypatch, _DB_CFG)
    c = asyncio.run(ghn.resolve_quote_cfg(None))
    assert c["source"] == "env" and called == []


def test_resolve_cfg_database_authoritative(monkeypatch):
    _base_env(monkeypatch)
    called = _patch_loader(monkeypatch, _DB_CFG)
    c = asyncio.run(ghn.resolve_quote_cfg(None))
    assert called == [("ghn", "staging")] and c["source"] == "database"
    assert c["token"] == TOKEN and c["shop_id"] == "1234567" and c["from_district_id"] == 1442
    assert c["base"] == ghn.STAGING_BASE and c["retries"] == 1 and c["map_version"] == 1


@pytest.mark.parametrize("kind", ["raise", "none", "prod_base"])
def test_resolve_cfg_fail_closed(monkeypatch, kind):
    _base_env(monkeypatch)
    if kind == "raise":
        _patch_loader(monkeypatch, exc=RuntimeError("decrypt failed"))
    elif kind == "none":
        _patch_loader(monkeypatch, {"source": "none", "enabled": False, "config": {}, "secrets": {}})
    else:
        # D357: mode active = staging nhung config mang base production -> base_mode_mismatch (fail-closed)
        bad = {**_DB_CFG, "config": {**_DB_CFG["config"], "base_url": ghn.PROD_BASE}}
        _patch_loader(monkeypatch, bad)
    c = asyncio.run(ghn.resolve_quote_cfg(None))
    assert c["token"] == "" and c["shop_id"] == "" and c["source"] in ("db_error", "none", "base_mode_mismatch")


class _Conn:
    def __init__(self):
        self.execs = []

    async def fetchrow(self, sql, *a):
        if "carrier_address_map" in sql:
            return {"carrier_province_id": 205, "carrier_district_id": 1660, "carrier_ward_code": "400102",
                    "status": "matched", "method": "staff", "confidence": None}
        return None

    async def execute(self, sql, *a):
        self.execs.append((sql, a))


def _req():
    return QuoteRequest(order_id=1, province_code="52", ward_code="23575", weight_g=400, length_cm=10, width_cm=10,
                        height_cm=11)


def test_unconfigured_cfg_quote_no_http(monkeypatch):
    _base_env(monkeypatch)
    _patch_loader(monkeypatch, exc=RuntimeError("x"))
    cfg = asyncio.run(ghn.resolve_quote_cfg(None))
    post = _fake_post()
    res = asyncio.run(ghn.GhnQuoteProvider(cfg, post=post).quote(_Conn(), _req()))
    assert res.reason == "ghn_not_configured" and post.calls == []


def test_database_cfg_quote_token_not_leaked(monkeypatch):
    _base_env(monkeypatch)
    _patch_loader(monkeypatch, _DB_CFG)
    cfg = asyncio.run(ghn.resolve_quote_cfg(None))
    seen = []

    async def post(c, path, body, *, retries):
        seen.append((path, body, c["token"]))
        if path.endswith("/fee"):
            return 200, {"code": 200, "data": {"total": 31000}}, "", 5
        return 200, {"code": 200, "data": {"leadtime": 0}}, "", 5
    conn = _Conn()
    res = asyncio.run(ghn.GhnQuoteProvider(cfg, post=post).quote(conn, _req()))
    assert res.status == QUOTE_OK and seen and all(t == TOKEN for _, _, t in seen)   # token chi di qua header cfg
    assert all(TOKEN not in json.dumps(b) for _, b, _ in seen)
    assert TOKEN not in json.dumps(res.snapshot()) and TOKEN not in repr(conn.execs)


# ---- tool: script dry-run + khong nam trong runtime path ----
def _load_script():
    spec = importlib.util.spec_from_file_location("ghn_g1_prep", ROOT / "scripts" / "ghn_g1_prep.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_snapshot_dry_run_no_token_no_network(monkeypatch, capsys):
    mod = _load_script()
    from app.services.settings import integrations as S

    async def boom(*a, **k):
        raise AssertionError("dry-run KHONG duoc doc token / goi mang")
    monkeypatch.setattr(S, "load_saved_ghn_config", boom)
    monkeypatch.setattr(md, "fetch_scoped", boom)
    args = mod._parser().parse_args(["snapshot", "--mode", "staging", "--target", "Gia Lai=Pleiku",
                                     "--target", "Đắk Lắk=Krông Pắc"])
    rc = asyncio.run(mod.cmd_snapshot(None, args))
    out = capsys.readouterr().out
    assert rc == 0 and "DRY-RUN" in out and '"planned_requests": 5' in out
    args = mod._parser().parse_args(["snapshot", "--mode", "staging", "--target", "A=b|c|d|e|f|g|h|i|j|k",
                                     "--execute", "--actor", "x"])
    assert asyncio.run(mod.cmd_snapshot(None, args)) == 2 and "REFUSED" in capsys.readouterr().out


def test_tooling_not_in_runtime_paths():
    import re
    imp = re.compile(r"^\s*(from\s+\S+\s+import\s+[^\n]*\bghn_master_data\b|import\s+\S*ghn_master_data\b)", re.M)
    for f in (ROOT / "app").rglob("*.py"):
        if f.name == "ghn_master_data.py":
            continue
        assert not imp.search(f.read_text(encoding="utf-8")), f"tooling bi import o runtime: {f}"
    assert "fetch_master_data" not in (ROOT / "app/services/providers/ghn.py").read_text(encoding="utf-8")


# ================================================================== DB
def _crypto_env(monkeypatch):
    monkeypatch.setattr(settings, "config_enc_keys", f"k1:{base64.b64encode(b'A'*32).decode()}")
    monkeypatch.setattr(settings, "config_enc_key_current", "k1")
    monkeypatch.setattr(settings, "config_secret_fp_key", base64.b64encode(b'F'*32).decode())


def _ck():
    return "g1-" + uuid.uuid4().hex


def _full_cfg():
    return {"shop_id": "1234567", "from_district_id": 1442, "from_ward_code": "20308", "timeout_seconds": 8,
            "max_retries": 1, "light_max_g": 20000, "address_map_version": 1}


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


async def _mk_ghn(conn, S, cfg=None, secret=True):
    await conn.execute("DELETE FROM integration_commands WHERE integration_id IN (SELECT id FROM integrations "
                       "WHERE provider='ghn')")
    await conn.execute("DELETE FROM integration_secrets WHERE integration_id IN (SELECT id FROM integrations "
                       "WHERE provider='ghn')")
    await conn.execute("DELETE FROM integrations WHERE provider='ghn'")
    it = await S.create_integration(conn, kind="shipping", provider="ghn", label="G", mode="staging",
                                    config_public=cfg if cfg is not None else _full_cfg(), actor="po",
                                    command_key=_ck())
    if secret:
        it2 = await S.write_secret(conn, it["id"], key_name="token", plaintext=TOKEN, expected_version=it["version"],
                                   actor="po", command_key=_ck())
        return it["id"], it2
    return it["id"], it


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_load_saved_config_disabled_no_enable(monkeypatch):
    from app.services.settings import integrations as S
    _crypto_env(monkeypatch)
    conn = await _conn()
    tr = conn.transaction()
    await tr.start()
    try:
        iid, _ = await _mk_ghn(conn, S)
        s = await S.load_saved_ghn_config(conn, "staging")
        assert s["token"] == TOKEN and s["enabled"] is False and s["config"]["shop_id"] == "1234567"
        assert await conn.fetchval("SELECT enabled FROM integrations WHERE id=$1", iid) is False
        # sai khoa ma hoa -> fail-closed
        monkeypatch.setattr(settings, "config_enc_keys", f"k1:{base64.b64encode(b'B'*32).decode()}")
        with pytest.raises(Exception):
            await S.load_saved_ghn_config(conn, "staging")
    finally:
        await tr.rollback()
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_load_saved_config_incomplete_or_no_secret(monkeypatch):
    from app.services.settings import integrations as S
    _crypto_env(monkeypatch)
    conn = await _conn()
    tr = conn.transaction()
    await tr.start()
    try:
        await _mk_ghn(conn, S, cfg={"shop_id": "1"})
        with pytest.raises(S.SettingsError):
            await S.load_saved_ghn_config(conn, "staging")
        await _mk_ghn(conn, S, secret=False)
        with pytest.raises(S.SettingsError):
            await S.load_saved_ghn_config(conn, "staging")
    finally:
        await tr.rollback()
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_resolve_cfg_disabled_none_then_enabled_database(monkeypatch):
    from app.services.settings import integrations as S
    _crypto_env(monkeypatch)
    _base_env(monkeypatch)
    monkeypatch.setattr(settings, "settings_integrations_env_fallback", False)
    conn = await _conn()
    iid = None
    try:
        async with conn.transaction():
            iid, it = await _mk_ghn(conn, S)
        c = await ghn.resolve_quote_cfg(conn)
        assert c["source"] == "none" and c["token"] == ""              # chua enable -> fail-closed
        # test-connection tren integration CHUA enable: chay duoc, KHONG tu enable (A.3)
        async def ok_post(cfg, path, body, *, retries):
            assert path == "/master-data/province"
            return 200, {"code": 200, "data": [{"ProvinceID": 1}]}, "", 3
        r = await S.test_connection(conn, iid, actor="po", post=ok_post)
        assert r["ok"] and await conn.fetchval("SELECT enabled FROM integrations WHERE id=$1", iid) is False
        d = await S.get_integration(conn, iid)
        async with conn.transaction():
            await S.enable(conn, iid, expected_version=d["version"], actor="po", command_key=_ck())
        c2 = await ghn.resolve_quote_cfg(conn)
        assert c2["source"] == "database" and c2["token"] == TOKEN and c2["shop_id"] == "1234567"
    finally:
        async with conn.transaction():
            await conn.execute("DELETE FROM integration_commands WHERE integration_id=$1", iid)
            await conn.execute("DELETE FROM integration_secrets WHERE integration_id=$1", iid)
            await conn.execute("DELETE FROM integrations WHERE id=$1", iid)
        await conn.close()


DSV = "VN-ADMIN-2099-01-v1"


async def _seed_admin(conn):
    await conn.execute(
        "INSERT INTO admin_unit_dataset (version, status, source_url, source_kind, sha256, license) "
        "VALUES ($1,'draft','test','cross_reference',$2,'test')", DSV, "0" * 64)
    units = [("province", "52", "Tỉnh Gia Lai", None), ("province", "66", "Tỉnh Đắk Lắk", None),
             ("ward", "23575", "Phường Pleiku", "52"), ("ward", "24490", "Xã Krông Pắc", "66"),
             ("ward", "24505", "Xã Ea Knuếc", "66"), ("ward", "24169", "Phường Nội Thành", "66")]
    for lvl, code, name, parent in units:
        await conn.execute("INSERT INTO admin_unit (dataset_version, level, code, name, name_normalized, parent_code) "
                           "VALUES ($1,$2,$3,$4,$5,$6)", DSV, lvl, code, name, md.norm_name(name), parent)
    aliases = {"23575": ["Phường Hoa Lư", "Phường Hội Thương", "Phường Phù Đổng", "Phường Tây Sơn", "Xã Trà Đa"],
               "24490": ["Thị trấn Phước An", "Xã Ea Yông", "Xã Hòa An", "Xã Hòa Tiến"],
               "24505": ["Xã Ea Kênh", "Xã Ea Knuếc", "Xã Hòa Đông"]}
    for code, al in aliases.items():
        for a in al:
            await conn.execute("INSERT INTO admin_unit_alias (dataset_version, unit_code, alias_name, alias_normalized, "
                               "alias_kind) VALUES ($1,$2,$3,$4,'legacy')", DSV, code, a, md.norm_name(a))
    await conn.execute("INSERT INTO delivery_routing_versions(version, effective_from, effective_to, dataset_version, "
                       "created_by) VALUES (9345, now() - interval '1 day', NULL, 'VN-TEST', 't')")
    await conn.execute("INSERT INTO delivery_self_wards(routing_version, province_code, ward_code, ward_name) "
                       "VALUES (9345, '66', '24169', 'Noi thanh')")


ADDRS = [("52", "23575"), ("66", "24490"), ("66", "24505"), ("66", "24169")]


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_snapshot_persist_build_map_version_audit():
    conn = await _conn()
    tr = conn.transaction()
    await tr.start()
    try:
        await _seed_admin(conn)
        res = await md.fetch_scoped({"token": TOKEN}, TARGETS, post=_fake_post(), cap=10)
        counts = await md.persist_snapshot(conn, res, snapshot_version="t-snap-1", targets=TARGETS, actor="po", cap=10,
                                           mode="staging")
        assert counts == {"province": 2, "district": 4, "ward": 12}
        h = await conn.fetchrow("SELECT status, request_count, request_cap, requests FROM carrier_master_snapshot "
                                "WHERE snapshot_version='t-snap-1'")
        assert h["status"] == "completed" and h["request_count"] == 5 and h["request_cap"] == 10
        assert TOKEN not in str(h["requests"])
        assert await conn.fetchval("SELECT count(*) FROM carrier_master_data WHERE snapshot_version='t-snap-1'") == 18
        rows, report = await md.build_map_rows(conn, ADDRS, mode="staging", dataset_version=DSV)
        by = {f"{r['province_code']}/{r['ward_code']}": r for r in rows}
        assert "66/24169" not in by and {"address": "66/24169", "result": "self_zone_skip"} in report
        assert by["66/24505"]["status"] == "matched" and by["66/24505"]["carrier_ward_code"] == "470206"
        assert by["66/24505"]["carrier_district_id"] == 1780 and by["66/24505"]["carrier_province_id"] == 210
        assert by["66/24490"]["status"] == "ambiguous" and by["66/24490"]["carrier_ward_code"] is None
        assert by["52/23575"]["status"] == "ambiguous"
        prev = await conn.fetchval("SELECT coalesce(max(map_version),0) FROM carrier_address_map WHERE provider='ghn'")
        v = await md.write_map_version(conn, rows, actor="po", source="snapshot:t-snap-1", mode="staging")
        assert v == prev + 1
        assert await conn.fetchval("SELECT count(*) FROM carrier_address_map WHERE provider='ghn' AND map_version=$1",
                                   v) == 3
        # D357: audit entity_id = "<mode>:<map_version>"
        assert await conn.fetchval("SELECT count(*) FROM audit_log WHERE action='carrier_map.version.create' "
                                   "AND entity_id=$1", f'staging:{v}') == 1
        # adapter GHN chi nhan 'matched'
        assert await ghn.address_lookup(conn, "66", "24505", map_version=v, mode="staging") is not None
        assert await ghn.address_lookup(conn, "66", "24490", map_version=v, mode="staging") is None
        # staff chon tay cho dia chi ambiguous -> version MOI, version cu giu nguyen
        staff = await md.validate_manual_rows(conn, [{"province_code": "66", "ward_code": "24490",
                                                      "carrier_district_id": 1780, "carrier_ward_code": "470201"}],
                                              source_note="PO chon", mode="staging", dataset_version=DSV)
        assert json.loads(staff[0]["note"])["basis"] == "verified_against_snapshot"
        _, latest = await md.latest_map_rows(conn, "staging")
        v2 = await md.write_map_version(conn, md.apply_overrides(latest, staff), actor="po", source="manual:PO",
                                       mode="staging")
        assert v2 == v + 1
        assert await ghn.address_lookup(conn, "66", "24490", map_version=v2, mode="staging") is not None
        assert await ghn.address_lookup(conn, "66", "24490", map_version=v, mode="staging") is None       # v cu khong doi
        with pytest.raises(md.MapValidationError):                                        # ward khong co trong snapshot
            await md.validate_manual_rows(conn, [{"province_code": "66", "ward_code": "24490",
                                                  "carrier_district_id": 1780, "carrier_ward_code": "999999"}],
                                          source_note="x", mode="staging", dataset_version=DSV)
    finally:
        await tr.rollback()
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_aborted_snapshot_header_only_and_manual_import_option_b():
    conn = await _conn()
    tr = conn.transaction()
    await tr.start()
    try:
        await _seed_admin(conn)
        n0 = await conn.fetchval("SELECT count(*) FROM carrier_master_data")
        bad = await md.fetch_scoped({}, TARGETS, post=_fake_post(status=401), cap=10)
        assert bad["status"] == "aborted"
        c = await md.persist_snapshot(conn, bad, snapshot_version="t-snap-bad", targets=TARGETS, actor="po", cap=10,
                                      mode="staging")
        assert c == {"province": 0, "district": 0, "ward": 0}
        assert await conn.fetchval("SELECT count(*) FROM carrier_master_data") == n0
        assert await conn.fetchval("SELECT status FROM carrier_master_snapshot WHERE snapshot_version='t-snap-bad'") \
            == "aborted"
        # Phuong an B: import thu cong, khong snapshot cho quan 1700 -> unverified_manual, 0 request
        rows = await md.validate_manual_rows(conn, [
            {"province_code": "52", "ward_code": "23575", "carrier_district_id": 1700, "carrier_ward_code": "123456",
             "carrier_province_id": 205, "note": "tra portal"}], source_note="portal GHN staging", mode="staging", dataset_version=DSV)
        assert rows[0]["method"] == "staff" and json.loads(rows[0]["note"])["basis"] == "unverified_manual"
        for bad_item, _why in (({"province_code": "66", "ward_code": "24169", "carrier_district_id": 1,
                                 "carrier_ward_code": "1"}, "self-zone"),
                               ({"province_code": "52", "ward_code": "24490", "carrier_district_id": 1,
                                 "carrier_ward_code": "1"}, "ward khong thuoc tinh"),
                               ({"province_code": "52", "ward_code": "23575", "carrier_district_id": 0,
                                 "carrier_ward_code": "1"}, "district id"),
                               ({"province_code": "52", "ward_code": "23575", "carrier_district_id": 1,
                                 "carrier_ward_code": "ab"}, "ward code")):
            with pytest.raises(md.MapValidationError):
                await md.validate_manual_rows(conn, [bad_item], source_note="x", mode="staging", dataset_version=DSV)
        with pytest.raises(md.MapValidationError):
            await md.validate_manual_rows(conn, rows and [{"province_code": "52", "ward_code": "23575",
                                                            "carrier_district_id": 1, "carrier_ward_code": "1"}],
                                          source_note="  ", mode="staging", dataset_version=DSV)
        with pytest.raises(md.MapValidationError):
            await md.write_map_version(conn, [{"province_code": "52", "ward_code": "23575", "status": "matched",
                                               "carrier_district_id": None, "carrier_ward_code": None}],
                                       actor="po", source="x", mode="staging")
    finally:
        await tr.rollback()
        await conn.close()
