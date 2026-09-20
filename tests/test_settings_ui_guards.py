"""CA Review 309 (Erratum 310) residual — guard tinh cho UI Settings (source-level, CI-safe, khong can browser).

309-01: link hang doi dia chi tro /address-review (route THAT), KHONG /fulfillment.
309-02: action gate theo permission readback (can(perm)); nut purge CHI hien khi co settings.integration.secret_purge.
Backend RBAC van la nguon enforce; test nay chan REGRESSION cua lop UI rendering.
"""
import pathlib

import pytest

PAGE = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "app" / "settings" / "page.js"
SRC = PAGE.read_text(encoding="utf-8")


def test_page_exists():
    assert PAGE.is_file(), "dashboard/app/settings/page.js phai ton tai"


# 309-01 — link queue dia chi
def test_address_queue_links_to_address_review_not_fulfillment():
    assert 'href="/address-review"' in SRC, "queue dia chi phai link /address-review (309-01)"
    # khong con link queue tro thang /fulfillment (card 'Dia chi chua khop')
    assert 'href="/fulfillment"' not in SRC, "khong duoc link queue dia chi sang /fulfillment (309-01)"


# 309-02 — permission readback + gate
def test_reads_permissions_from_auth_me():
    assert '/dashboard/auth/me' in SRC, "phai doc quyen tu /dashboard/auth/me (309-02)"
    assert 'const can =' in SRC and 'perms === null' in SRC, "phai co helper can() fail-open khi chua biet quyen"


@pytest.mark.parametrize("perm", [
    "settings.integration.manage_public",
    "settings.integration.secret_write",
    "settings.integration.secret_purge",
    "settings.integration.test",
    "settings.integration.activate",
])
def test_actions_gated_by_permission(perm):
    assert f'c("{perm}")' in SRC or f'can("{perm}")' in SRC, f"action phai gate theo quyen {perm} (309-02)"


def test_purge_button_gated_by_secret_purge():
    # nut purge (endpoint .../secret/token/purge) phai nam trong nhanh gate secret_purge.
    idx = SRC.find("/secret/token/purge")
    assert idx != -1, "phai co nut purge token"
    window = SRC[max(0, idx - 400):idx]
    assert 'secret_purge' in window, "nut purge phai duoc bao boi c(secret_purge) (309-02 PO-only)"
