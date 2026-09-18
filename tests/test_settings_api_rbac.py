"""CA Directive 305 §9.1 + Review 307-01/307-06 — RBAC per-action (API level) + module gate (feature OFF -> 404
zero-effect). CI-safe: TestClient + dependency override, no DB (403/404 xay ra TRUOC khi cham DB). Chung minh backend
enforce permission + module gate (khong phai chi UI an nut)."""
import pytest
from fastapi.testclient import TestClient

from app.api.auth import require_staff_session
from app.config import settings
from app.main import app


def _client(perms, *, module_on=True):
    async def _fake():
        return {"id": 1, "username": "tester", "rbac_provisioned": True, "permissions": set(perms)}
    app.dependency_overrides[require_staff_session] = _fake
    settings.settings_integrations_enabled = module_on   # 307-01: router gate doc flag nay luc request
    # raise_server_exceptions=False: endpoint cham DB khi CHAY KHONG DB (CI) -> tra 5xx thay vi raise (van != 403/404).
    return TestClient(app, raise_server_exceptions=False)


def _clear():
    app.dependency_overrides.pop(require_staff_session, None)
    settings.settings_integrations_enabled = False


# (method, path, body, required_permission)
_ENDPOINTS = [
    ("get", "/dashboard/settings/integrations", None, "settings.integration.view"),
    ("get", "/dashboard/settings/integrations/1", None, "settings.integration.view"),
    ("post", "/dashboard/settings/integrations", {"kind": "shipping", "provider": "ghn", "label": "x", "mode": "staging", "command_key": "k1"}, "settings.integration.manage_public"),
    ("patch", "/dashboard/settings/integrations/1", {"expected_version": 1, "command_key": "k1"}, "settings.integration.manage_public"),
    ("post", "/dashboard/settings/integrations/1/secret", {"key_name": "token", "value": "v", "expected_version": 1, "command_key": "k1"}, "settings.integration.secret_write"),
    ("post", "/dashboard/settings/integrations/1/secret/token/purge", {"expected_version": 1, "command_key": "k1"}, "settings.integration.secret_purge"),
    ("post", "/dashboard/settings/integrations/1/test-connection", None, "settings.integration.test"),
    ("post", "/dashboard/settings/integrations/1/enable", {"expected_version": 1, "command_key": "k1"}, "settings.integration.activate"),
    ("post", "/dashboard/settings/integrations/1/disable", {"expected_version": 1, "command_key": "k1"}, "settings.integration.activate"),
    ("post", "/dashboard/settings/integrations/1/archive", {"expected_version": 1, "command_key": "k1"}, "settings.integration.activate"),
]


@pytest.mark.parametrize("method,path,body,perm", _ENDPOINTS)
def test_denied_without_permission(method, path, body, perm):
    c = _client([])   # khong co quyen nao
    try:
        r = getattr(c, method)(path, json=body) if body is not None else getattr(c, method)(path)
        assert r.status_code == 403, f"{method} {path} nen 403 khi thieu {perm}, duoc {r.status_code}"
    finally:
        _clear()


# 307-06: nguoi CHI co secret_write KHONG duoc purge (purge la quyen rieng secret_purge, PO-only).
def test_secret_write_cannot_purge():
    c = _client(["settings.integration.secret_write"])
    try:
        r = c.post("/dashboard/settings/integrations/1/secret/token/purge",
                   json={"expected_version": 1, "command_key": "k1"})
        assert r.status_code == 403, f"secret_write khong duoc purge, duoc {r.status_code}"
    finally:
        _clear()


# 307-06: purge cho phep khi CO secret_purge (route vao duoc, != 403).
def test_secret_purge_permission_allows_route():
    c = _client(["settings.integration.secret_purge"])
    try:
        r = c.post("/dashboard/settings/integrations/1/secret/token/purge",
                   json={"expected_version": 1, "command_key": "k1"})
        assert r.status_code != 403
    finally:
        _clear()


# 307-01: module OFF -> MOI endpoint 404 (zero-effect) du co day du quyen. Khong 200/403/5xx-cham-DB.
@pytest.mark.parametrize("method,path,body", [(m, p, b) for (m, p, b, _) in _ENDPOINTS])
def test_module_off_returns_404_zero_effect(method, path, body):
    allperm = ["settings.integration.view", "settings.integration.manage_public", "settings.integration.secret_write",
               "settings.integration.secret_purge", "settings.integration.test", "settings.integration.activate"]
    c = _client(allperm, module_on=False)
    try:
        r = getattr(c, method)(path, json=body) if body is not None else getattr(c, method)(path)
        assert r.status_code == 404, f"module OFF: {method} {path} phai 404, duoc {r.status_code}"
    finally:
        _clear()


def test_secret_write_empty_value_kept_no_mutation():
    # co quyen secret_write + value rong -> giu nguyen (khong cham DB), tra kept (CA 304-07 blank-keeps).
    c = _client(["settings.integration.secret_write"])
    try:
        r = c.post("/dashboard/settings/integrations/1/secret", json={"key_name": "token", "value": ""})
        assert r.status_code == 200 and r.json().get("kept") is True
    finally:
        _clear()


def test_view_permission_allows_list_route_reached():
    # co view -> KHONG 403 (route vao duoc; co the loi DB neu khong co DB, nhung khong phai 403/404).
    c = _client(["settings.integration.view"])
    try:
        r = c.get("/dashboard/settings/integrations")
        assert r.status_code not in (403, 404)
    finally:
        _clear()
