"""M5 upgrade (Directive 214 §6.B + Q2 + Memo 213 §4): clarify-before-escalate bounded <=2 luot.

Test THUAN logic dem luot + noi dung clarify (server-owned). Fake Redis async (monkeypatch aioredis.from_url);
chay async qua asyncio.run (repo khong dung pytest-asyncio).
"""
import asyncio

from app.services import orchestrator


class _FakeRedis:
    def __init__(self, store):
        self.store = store

    async def incr(self, k):
        self.store[k] = self.store.get(k, 0) + 1
        return self.store[k]

    async def expire(self, k, t):
        return True

    async def delete(self, k):
        self.store.pop(k, None)

    async def aclose(self):
        return None


def _patch(monkeypatch, store):
    async def _from_url(*a, **k):
        return _FakeRedis(store)
    monkeypatch.setattr(orchestrator.aioredis, "from_url", _from_url)


_VR = {"status": "needs_customer_confirmation",
       "province_name": "Tỉnh Đắk Lắk", "ward_name": "Phường Ea Kao"}


def test_clarify_bounded_two_then_escalate(monkeypatch):
    store = {}
    _patch(monkeypatch, store)
    r1 = asyncio.run(orchestrator._address_clarify("tg:1", _VR, "Dak Lak", "Ea Kao"))
    assert r1 is not None and r1["address_needs_clarification"] is True
    assert "Phường Ea Kao" in r1["predicted_admin"] and "Tỉnh Đắk Lắk" in r1["predicted_admin"]
    r2 = asyncio.run(orchestrator._address_clarify("tg:1", _VR, "Dak Lak", "Ea Kao"))
    assert r2 is not None  # luot 2 van hoi
    r3 = asyncio.run(orchestrator._address_clarify("tg:1", _VR, "Dak Lak", "Ea Kao"))
    assert r3 is None  # het <=2 luot -> caller escalate


def test_clarify_reset_restarts_counter(monkeypatch):
    store = {}
    _patch(monkeypatch, store)
    asyncio.run(orchestrator._address_clarify("tg:2", _VR, "Dak Lak", "Ea Kao"))
    asyncio.run(orchestrator._address_clarify("tg:2", _VR, "Dak Lak", "Ea Kao"))
    asyncio.run(orchestrator._address_clarify_reset("tg:2"))
    r = asyncio.run(orchestrator._address_clarify("tg:2", _VR, "Dak Lak", "Ea Kao"))
    assert r is not None  # sau reset -> dem lai tu dau, van hoi


def test_clarify_no_prediction_asks_province_ward(monkeypatch):
    store = {}
    _patch(monkeypatch, store)
    vr = {"status": "failed", "province_name": None, "ward_name": None}
    r = asyncio.run(orchestrator._address_clarify("tg:3", vr, None, None))
    assert r is not None and r["predicted_admin"] is None
    assert "TINH" in r["instruction"] and "PHUONG" in r["instruction"]
