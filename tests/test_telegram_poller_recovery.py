"""Telegram customer poller auto-recovery (CA Review 292-03) — CI-safe (asyncio.run + fakes, KHONG DB/pytest-asyncio).

Bao phu: backoff bounded+jitter, poller_status readiness, reconnect sau loi lien tiep (fresh client), reset backoff +
heartbeat khi poll OK, message-handler error isolation (khong vo loop), CancelledError (shutdown) propagate.
"""
import asyncio

import pytest

import app.workers.telegram_customer_listener as L


def test_backoff_bounded_and_grows():
    # n=1 quanh base; tang theo n; luon trong [raw*(1-jitter), cap*(1+jitter)]; khong bao gio vuot cap*(1+jitter).
    d1 = [L._backoff_delay(1) for _ in range(50)]
    assert all(L._BACKOFF_BASE * 0.75 <= d <= L._BACKOFF_BASE * 1.25 for d in d1)
    big = [L._backoff_delay(30) for _ in range(50)]
    assert all(d <= L._BACKOFF_CAP * (1 + L._JITTER) for d in big)
    assert max(big) > max(d1)          # backoff tang theo so loi
    assert L._backoff_delay(0) > 0     # guard n>=1


def test_poller_status_healthy_vs_stale():
    L._poll_started_at = None
    L._last_poll_ok_at = None
    assert L.poller_status(now=1000.0)["started"] is False
    assert L.poller_status(now=1000.0)["healthy"] is False
    L._poll_started_at = 500.0
    L._last_poll_ok_at = 990.0
    st = L.poller_status(now=1000.0, max_age_s=90)   # 10s tuoi -> healthy
    assert st["started"] and st["healthy"] and st["last_ok_age_s"] == pytest.approx(10.0)
    L._last_poll_ok_at = 800.0
    assert L.poller_status(now=1000.0, max_age_s=90)["healthy"] is False   # 200s > 90 -> stale


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakeClient:
    """get_script: list moi phan tu la Exception (raise) hoac dict (json getUpdates)."""
    def __init__(self, get_script):
        self.get_script = list(get_script)
        self.get_calls = 0

    async def post(self, url, **kw):
        return _Resp({"ok": True})

    async def get(self, url, params=None):
        self.get_calls += 1
        if not self.get_script:
            raise asyncio.CancelledError()
        item = self.get_script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return _Resp(item)


def _no_sleep(monkeypatch):
    async def _s(*_a, **_k):
        return None
    monkeypatch.setattr(L.asyncio, "sleep", _s)


def _reset():
    L._last_poll_ok_at = None
    L._poll_started_at = None


def test_next_reconnect_count_resets_after_success():
    # CA 298-01: had_success -> reset ve 1 (base); khong -> tang dan.
    assert L._next_reconnect_count(5, True) == 1
    assert L._next_reconnect_count(5, False) == 6
    assert L._next_reconnect_count(0, False) == 1
    # backoff cua reconnect sau outage-co-success = muc base (thap), khong bi lich su lam cham.
    assert L._backoff_delay(L._next_reconnect_count(9, True)) <= L._BACKOFF_BASE * (1 + L._JITTER)


def test_reconnect_raises_and_inner_does_not_own_delay(monkeypatch):
    # CA 298-02: inner KHONG sleep khi RAISE reconnect (chi sleep cho retry TRONG phien). Sleep count = threshold-1.
    _reset()
    slept = []

    async def _cnt(d=0):
        slept.append(d)
    monkeypatch.setattr(L.asyncio, "sleep", _cnt)
    monkeypatch.setattr(L.settings, "telegram_customer_bot_token", "T")
    import httpx
    client = _FakeClient([httpx.ConnectError("dns")] * L._RECONNECT_AFTER_CONSEC_ERRORS)
    with pytest.raises(L._ReconnectSession) as ei:
        asyncio.run(L._run_session(client, {"offset": None}))
    assert ei.value.had_success is False          # khong poll OK -> outer tang backoff
    assert client.get_calls == L._RECONNECT_AFTER_CONSEC_ERRORS
    assert len(slept) == L._RECONNECT_AFTER_CONSEC_ERRORS - 1   # KHONG sleep o lan raise (single-delay ownership)


def test_reconnect_after_success_marks_had_success(monkeypatch):
    # phien poll OK vai lan roi loi lien tiep -> _ReconnectSession(had_success=True) -> outer se reset backoff.
    _reset()
    _no_sleep(monkeypatch)
    monkeypatch.setattr(L.settings, "telegram_customer_bot_token", "T")
    import httpx
    ok = {"result": []}
    client = _FakeClient([ok, ok] + [httpx.ConnectError("x")] * L._RECONNECT_AFTER_CONSEC_ERRORS)
    with pytest.raises(L._ReconnectSession) as ei:
        asyncio.run(L._run_session(client, {"offset": None}))
    assert ei.value.had_success is True and L._last_poll_ok_at is not None


def test_time_based_heartbeat(monkeypatch, capsys):
    # CA 298-03: heartbeat theo THOI GIAN (~60s), khong theo so poll. Jump time -> co dong heartbeat.
    _reset()
    _no_sleep(monkeypatch)
    monkeypatch.setattr(L.settings, "telegram_customer_bot_token", "T")
    t = {"v": 1000.0}
    monkeypatch.setattr(L.time, "monotonic", lambda: t["v"])

    ok = {"result": []}
    calls = {"n": 0}
    orig_get = _FakeClient.get

    async def _get(self, url, params=None):
        calls["n"] += 1
        t["v"] += 40      # moi poll +40s -> poll 2 vuot 60s ke tu last_hb
        return await orig_get(self, url, params)
    monkeypatch.setattr(_FakeClient, "get", _get)
    client = _FakeClient([ok, ok])   # 2 poll OK roi CancelledError
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(L._run_session(client, {"offset": None}))
    out = capsys.readouterr().out
    assert "heartbeat: dang poll" in out


def test_success_updates_heartbeat_and_message_error_isolated(monkeypatch):
    _reset()
    _no_sleep(monkeypatch)
    monkeypatch.setattr(L.settings, "telegram_customer_bot_token", "T")

    calls = {"n": 0}

    async def _boom(*_a, **_k):
        calls["n"] += 1
        raise ValueError("handler boom")     # loi xu ly 1 message
    monkeypatch.setattr(L, "_handle_customer_message", _boom)

    upd = {"result": [{"update_id": 41, "message": {"chat": {"id": 5}, "text": "hi", "message_id": 9}}]}
    client = _FakeClient([upd])              # 1 poll OK co update, roi CancelledError (het script) de dung
    state = {"offset": None}
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(L._run_session(client, state))
    assert L._last_poll_ok_at is not None      # heartbeat cap nhat khi getUpdates OK
    assert state["offset"] == 42               # offset tien du handler loi (khong lap vo han)
    assert calls["n"] == 1                     # handler duoc goi, loi bi co lap (loop khong vo)


def test_cancelled_propagates_immediately(monkeypatch):
    _reset()
    _no_sleep(monkeypatch)
    monkeypatch.setattr(L.settings, "telegram_customer_bot_token", "T")
    client = _FakeClient([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(L._run_session(client, {"offset": None}))
