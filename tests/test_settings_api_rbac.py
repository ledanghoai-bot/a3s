"""CA Directive 305 §9.1 — RBAC per-action deny (API level). CI-safe: TestClient + dependency override, no DB
(403 xảy ra TRƯỚC khi chạm DB). Chứng minh backend enforce permission (không phải chỉ UI ẩn nút)."""
import pytest
from fastapi.testclient import TestClient

from app.api.auth import require_staff_session
from app.main import app


def _client(perms):
    async def _fake():
        return {"id": 1, "username": "tester", "rbac_provisioned": True, "permissions": set(perms)}
    app.dependency_overrides[require_staff_session] = _fake
    # raise_server_exceptions=False: endpoint chạm DB khi CHẠY KHÔNG DB (CI) -> trả 5xx thay vì raise (vẫn != 403).
    return TestClient(app, raise_server_exceptions=False)


def _clear():
    app.dependency_overrides.pop(require_staff_session, None)


# (method, path, body, required_permission)
_ENDPOINTS = [
    ("get", "/dashboard/settings/integrations", None, "settings.integration.view"),
    ("get", "/dashboard/settings/integrations/1", None, "settings.integration.view"),
    ("post", "/dashboard/settings/integrations", {"kind": "shipping", "provider": "ghn", "label": "x", "mode": "staging"}, "settings.integration.manage_public"),
    ("patch", "/dashboard/settings/integrations/1", {"expected_version": 1}, "settings.integration.manage_public"),
    ("post", "/dashboard/settings/integrations/1/secret", {"key_name": "token", "value": "v"}, "settings.integration.secret_write"),
    ("delete", "/dashboard/settings/integrations/1/secret/token", None, "settings.integration.secret_write"),
    ("post", "/dashboard/settings/integrations/1/test-connection", None, "settings.integration.test"),
    ("post", "/dashboard/settings/integrations/1/enable", {"expected_version": 1}, "settings.integration.activate"),
    ("post", "/dashboard/settings/integrations/1/disable", None, "settings.integration.activate"),
]


@pytest.mark.parametrize("method,path,body,perm", _ENDPOINTS)
def test_denied_without_permission(method, path, body, perm):
    c = _client([])   # không có quyền nào
    try:
        r = getattr(c, method)(path, json=body) if body is not None else getattr(c, method)(path)
        assert r.status_code == 403, f"{method} {path} nên 403 khi thiếu {perm}, được {r.status_code}"
    finally:
        _clear()


def test_secret_write_empty_value_kept_no_mutation():
    # có quyền secret_write + value rỗng -> giữ nguyên (không chạm DB), trả kept (CA 304-07 blank-keeps).
    c = _client(["settings.integration.secret_write"])
    try:
        r = c.post("/dashboard/settings/integrations/1/secret", json={"key_name": "token", "value": ""})
        assert r.status_code == 200 and r.json().get("kept") is True
    finally:
        _clear()


def test_view_permission_allows_list_route_reached():
    # có view -> KHÔNG 403 (route được vào; có thể lỗi DB nếu không có DB, nhưng không phải 403).
    c = _client(["settings.integration.view"])
    try:
        r = c.get("/dashboard/settings/integrations")
        assert r.status_code != 403
    finally:
        _clear()
