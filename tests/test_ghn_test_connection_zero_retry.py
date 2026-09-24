"""CA Directive 365 — GHN test_connection phai ton trong max_retries=0 (truoc day `or 1` bien 0 thanh 1).

Pure (CI): FakeConn du cho 3 pha cua test_connection + _decrypt_secret/_audit gia; transport THAT ghn._post voi
httpx.AsyncClient.post bi thay bang ham dem attempt (khong network). DB (M6_TEST_DB=1): end-to-end record that.
Khong credential that, khong goi GHN.
"""
import asyncio
import json
import os

import httpx
import pytest

from app.services.providers import ghn
from app.services.settings import integrations as S

DB = os.environ.get("M6_TEST_DB") == "1"


def _cp(**over):
    cp = {"base_url": ghn.PROD_BASE, "shop_id": "999999", "from_district_id": 1552, "from_ward_code": "400105",
          "timeout_seconds": 5, "max_retries": 0, "light_max_g": 20000, "address_map_version": 1}
    cp.update(over)
    return {k: v for k, v in cp.items() if v is not _ABSENT}


_ABSENT = object()


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeConn:
    """Du cho test_connection: SELECT * integrations, version secret, FOR UPDATE, UPDATE last_test."""
    def __init__(self, cp):
        self.row = {"id": 3, "provider": "ghn", "mode": "production", "config_public": json.dumps(cp),
                    "config_revision": 7}
        self.updates = []

    def transaction(self):
        return _Tx()

    async def fetchrow(self, sql, *a):
        return self.row if "FOR UPDATE" not in sql else {"config_revision": self.row["config_revision"]}

    async def fetchval(self, sql, *a):
        return 1                                     # secret version

    async def execute(self, sql, *a):
        self.updates.append(a)


def _patch_helpers(monkeypatch):
    async def dec(conn, iid, provider, key):
        return "TOK-FAKE-365"
    audits = []

    async def aud(conn, action, actor, iid, after):
        audits.append((action, after))
    monkeypatch.setattr(S, "_decrypt_secret", dec)
    monkeypatch.setattr(S, "_audit", aud)
    return audits


def _count_http(monkeypatch, status=503):
    """httpx.AsyncClient.post -> tra response gia `status`, dem attempt. Khong network. Bo sleep backoff."""
    attempts = []

    async def fake_post(self, url, *a, **k):
        attempts.append(str(url))
        return httpx.Response(status, json={"code": status}, request=httpx.Request("POST", str(url)))

    async def no_sleep(*a, **k):
        return None
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(ghn.asyncio, "sleep", no_sleep)
    return attempts


def _spy(calls):
    """Transport spy: ghi retries nhan duoc roi chuyen cho ghn._post THAT (de dem attempt thuc)."""
    async def p(cfg, path, body, *, retries):
        calls.append({"path": path, "retries": retries, "cfg_retries": cfg["retries"]})
        return await ghn._post(cfg, path, body, retries=retries)
    return p


# ============================================================== PURE (CI)
def test_zero_retry_passes_zero_and_single_attempt_on_retryable_error(monkeypatch):
    """max_retries=0 + transport tra 503 (retryable) -> retries=0 toi transport, DUNG 1 attempt, ket qua fail."""
    _patch_helpers(monkeypatch)
    attempts = _count_http(monkeypatch, status=503)
    calls = []
    res = asyncio.run(S.test_connection(FakeConn(_cp(max_retries=0)), 3, actor="t", post=_spy(calls)))
    assert calls == [{"path": "/master-data/province", "retries": 0, "cfg_retries": 0}]
    assert len(attempts) == 1                                   # KHONG co HTTP thu hai
    assert res["ok"] is False and res["error_class"] == "http_503"


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_zero_retry_every_retryable_status_single_attempt(monkeypatch, status):
    _patch_helpers(monkeypatch)
    attempts = _count_http(monkeypatch, status=status)
    asyncio.run(S.test_connection(FakeConn(_cp(max_retries=0)), 3, actor="t", post=_spy([])))
    assert len(attempts) == 1, status


def test_zero_retry_timeout_single_attempt(monkeypatch):
    _patch_helpers(monkeypatch)
    attempts = []

    async def boom(self, url, *a, **k):
        attempts.append(1)
        raise httpx.ReadTimeout("t")

    async def no_sleep(*a, **k):
        return None
    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    monkeypatch.setattr(ghn.asyncio, "sleep", no_sleep)
    res = asyncio.run(S.test_connection(FakeConn(_cp(max_retries=0)), 3, actor="t", post=_spy([])))
    assert len(attempts) == 1 and res["error_class"] == "timeout"


def test_absent_max_retries_uses_default(monkeypatch):
    """Vang mat -> default (1) nhu hanh vi cu. Goi thang (bo qua _require_ghn_complete de voi toi nhanh vang mat)."""
    _patch_helpers(monkeypatch)
    monkeypatch.setattr(S, "_require_ghn_complete", lambda cp: None)
    attempts = _count_http(monkeypatch, status=503)
    calls = []
    asyncio.run(S.test_connection(FakeConn(_cp(max_retries=_ABSENT)), 3, actor="t", post=_spy(calls)))
    assert calls[0]["retries"] == S._TEST_CONNECTION_DEFAULT_RETRIES == 1
    assert len(attempts) == 2                                   # 1 + 1 retry — giu nguyen hanh vi cu


def test_none_max_retries_uses_default(monkeypatch):
    _patch_helpers(monkeypatch)
    monkeypatch.setattr(S, "_require_ghn_complete", lambda cp: None)
    _count_http(monkeypatch, status=503)
    calls = []
    asyncio.run(S.test_connection(FakeConn(_cp(max_retries=None)), 3, actor="t", post=_spy(calls)))
    assert calls[0]["retries"] == 1


@pytest.mark.parametrize("n", [1, 2, 5])
def test_positive_value_preserved(monkeypatch, n):
    """Gia tri duong giu hanh vi hien huu: n retry -> toi da n+1 attempt khi loi retryable."""
    _patch_helpers(monkeypatch)
    attempts = _count_http(monkeypatch, status=503)
    calls = []
    asyncio.run(S.test_connection(FakeConn(_cp(max_retries=n)), 3, actor="t", post=_spy(calls)))
    assert calls[0]["retries"] == n and len(attempts) == n + 1


def test_zero_retry_success_single_call(monkeypatch):
    """Duong thanh cong van 1 call, ket qua ok + ghi last_test pass."""
    _patch_helpers(monkeypatch)
    attempts = []

    async def ok(self, url, *a, **k):
        attempts.append(1)
        return httpx.Response(200, json={"code": 200, "data": [{"ProvinceID": 1}] * 63},
                              request=httpx.Request("POST", str(url)))
    monkeypatch.setattr(httpx.AsyncClient, "post", ok)
    fc = FakeConn(_cp(max_retries=0))
    res = asyncio.run(S.test_connection(fc, 3, actor="t", post=_spy([])))
    assert res["ok"] is True and res["province_count"] == 63 and len(attempts) == 1
    assert fc.updates and fc.updates[0][1] == "pass"


# ============================================================== DB (M6_TEST_DB=1)
@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_zero_retry_end_to_end(monkeypatch):
    import base64
    import uuid

    import asyncpg

    from app.config import settings
    monkeypatch.setattr(settings, "config_enc_keys", f"k1:{base64.b64encode(b'A' * 32).decode()}")
    monkeypatch.setattr(settings, "config_enc_key_current", "k1")
    monkeypatch.setattr(settings, "config_secret_fp_key", base64.b64encode(b'F' * 32).decode())
    conn = await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    tr = conn.transaction()
    await tr.start()
    try:
        for t in ("integration_commands", "integration_secrets"):
            await conn.execute(f"DELETE FROM {t} WHERE integration_id IN (SELECT id FROM integrations "
                               "WHERE provider='ghn')")
        await conn.execute("DELETE FROM integrations WHERE provider='ghn'")
        pub = {k: v for k, v in _cp(max_retries=0).items() if k != "base_url"}
        it = await S.create_integration(conn, kind="shipping", provider="ghn", label="GHN prod 365",
                                        mode="production", config_public=pub, actor="t",
                                        command_key="d365-" + uuid.uuid4().hex)
        await S.write_secret(conn, it["id"], key_name="token", plaintext="TOK-FAKE-365",
                             expected_version=it["version"], actor="t", command_key="d365-" + uuid.uuid4().hex)
        attempts = _count_http(monkeypatch, status=503)
        calls = []
        res = await S.test_connection(conn, it["id"], actor="t", post=_spy(calls))
        assert calls[0]["retries"] == 0 and len(attempts) == 1 and res["ok"] is False
        st = await conn.fetchval("SELECT last_test_status FROM integrations WHERE id=$1", it["id"])
        assert st == "fail"
    finally:
        await tr.rollback()
        await conn.close()
