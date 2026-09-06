"""M5 — API auth/session binding cho dataset deactivate endpoint (CA Review 139/141 §3).

Chung minh: 401 (khong session) · 403 (sai permission) · actor lay tu SESSION khong phai body (body-spoof
resistance). Dung FastAPI TestClient KHONG lifespan (khong cham DB startup); no-spoof monkeypatch get_pool +
reg.deactivate de khong can DB that. Chay trong CI (full deps).
"""
from fastapi.testclient import TestClient

import app.api.m5_address_dataset as mod
from app.api.auth import require_staff_session
from app.main import app

client = TestClient(app)
URL = "/dashboard/address-dataset/VN-ADMIN-2025-07-v2/deactivate"


def _staff(username, perms):
    return {"username": username, "id": 1, "name": username, "token": "x",
            "rbac_provisioned": True, "permissions": set(perms), "must_change_password": False}


def test_deactivate_401_no_session():
    r = client.post(URL, json={})
    assert r.status_code == 401, r.text


def test_deactivate_403_wrong_permission():
    # co session nhung thieu address.dataset.manage (chi co review) -> 403
    app.dependency_overrides[require_staff_session] = lambda: _staff("staff-1", {"address.dataset.review"})
    try:
        r = client.post(URL, json={"reason": "r", "ticket": "t", "apply": True})
        assert r.status_code == 403, r.text
    finally:
        app.dependency_overrides.clear()


def test_deactivate_actor_from_session_not_body(monkeypatch):
    captured = {}

    class _Conn:
        pass

    class _Acq:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *a):
            return False

    class _Pool:
        def acquire(self):
            return _Acq()

    async def _fake_pool():
        return _Pool()

    async def _fake_deactivate(conn, *, version, actor, reason, ticket, apply=False):
        captured["actor"] = actor
        captured["version"] = version
        return {"action": "deactivate", "version": version, "actor": actor, "applied": bool(apply)}

    monkeypatch.setattr(mod, "get_pool", _fake_pool)
    monkeypatch.setattr(mod.reg, "deactivate", _fake_deactivate)
    app.dependency_overrides[require_staff_session] = lambda: _staff("po-hoai", {"address.dataset.manage"})
    try:
        r = client.post(URL, json={"actor": "attacker", "reason": "r", "ticket": "t", "apply": True})
        assert r.status_code == 200, r.text
        # actor PHAI la 'po-hoai' (tu session), KHONG phai 'attacker' (body) -> body-spoof resistance
        assert captured["actor"] == "po-hoai"
        assert captured["version"] == "VN-ADMIN-2025-07-v2"
    finally:
        app.dependency_overrides.clear()
