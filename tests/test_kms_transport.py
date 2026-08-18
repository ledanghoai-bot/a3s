"""I-B M4 H2 — test cho `KmsTransport` va factory trung lap nha cung cap.

Bang chung HANH VI (Vault that, ba che do hong, rotation) nam o
`scripts/m4_h2_kms_e2e_sandbox.py` vi no can mot backend that. Cac test o day chay duoc trong CI
khong co Vault, va chan dung hai thu de bi lam hong ma khong ai thay:

  * mot MAC DINH am tham duoc them lai (chon provider ho caller),
  * mot DUONG LUI khi provider loi (directive H2-KMS cam tuyet doi).
"""
from __future__ import annotations

import base64

import httpx
import pytest

from app.services.pii.kms_transport import get_kms_transport
from app.services.pii.kms_transport_vault import VaultTransitTransport
from app.services.pii.signing_backend import (
    SigningBackendDenied,
    SigningBackendMisconfigured,
    SigningBackendUnavailable,
)

_KEY = "m4-transcript"


@pytest.fixture()
def moi_truong_sach(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for bien in ("M4_KMS_TRANSPORT", "M4_KMS_KEY_ID", "M4_KMS_KEY_VERSION",
                 "M4_VAULT_ADDR", "M4_VAULT_TOKEN", "M4_VAULT_NAMESPACE"):
        monkeypatch.delenv(bien, raising=False)
    return monkeypatch


class _PhanHoiGia:
    def __init__(self, status: int, body: dict | None) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> dict:
        if self._body is None:
            raise ValueError("khong phai JSON")
        return self._body


def _cam_client_gia(monkeypatch: pytest.MonkeyPatch, phan_hoi) -> list[dict]:
    """Thay `httpx.Client` bang ban gia. Tra list ghi lai cac request de assert."""
    da_goi: list[dict] = []

    class _ClientGia:
        def __init__(self, *a, **kw) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a) -> None:
            return None

        def request(self, method, url, headers=None, json=None):
            da_goi.append({"method": method, "url": url, "headers": headers or {},
                           "json": json or {}})
            return phan_hoi(da_goi[-1]) if callable(phan_hoi) else phan_hoi

    monkeypatch.setattr(httpx, "Client", _ClientGia)
    return da_goi


# ---------------------------------------------------------------------------
# Factory: khong mac dinh, khong duong lui
# ---------------------------------------------------------------------------
def test_factory_khong_co_mac_dinh(moi_truong_sach) -> None:
    """Thieu `M4_KMS_TRANSPORT` la LOI CAU HINH, khong phai co so de tu chon provider."""
    moi_truong_sach.setenv("M4_KMS_KEY_ID", _KEY)
    moi_truong_sach.setenv("M4_KMS_KEY_VERSION", "1")
    with pytest.raises(SigningBackendMisconfigured, match="M4_KMS_TRANSPORT"):
        get_kms_transport()


def test_factory_tu_choi_provider_la(moi_truong_sach) -> None:
    moi_truong_sach.setenv("M4_KMS_KEY_ID", _KEY)
    moi_truong_sach.setenv("M4_KMS_KEY_VERSION", "1")
    moi_truong_sach.setenv("M4_KMS_TRANSPORT", "localdev")  # KHONG duoc coi la duong lui hop le
    with pytest.raises(SigningBackendMisconfigured):
        get_kms_transport()


@pytest.mark.parametrize("thieu", ["M4_KMS_KEY_ID", "M4_KMS_KEY_VERSION"])
def test_factory_doi_key_id_va_version_tuong_minh(moi_truong_sach, thieu: str) -> None:
    """Hai gia tri nay di THANG vao hang chu ky va la thu verifier tra registry — khong duoc doan."""
    moi_truong_sach.setenv("M4_KMS_TRANSPORT", "vault")
    moi_truong_sach.setenv("M4_KMS_KEY_ID", _KEY)
    moi_truong_sach.setenv("M4_KMS_KEY_VERSION", "1")
    moi_truong_sach.setenv("M4_VAULT_ADDR", "http://vault.invalid:8200")
    moi_truong_sach.setenv("M4_VAULT_TOKEN", "tok")
    moi_truong_sach.delenv(thieu)
    with pytest.raises(SigningBackendMisconfigured, match="bat buoc"):
        get_kms_transport()


def test_factory_khong_co_duong_lui_trong_source() -> None:
    """Directive H2-KMS cam dung backend khac lam fallback khi provider loi."""
    import inspect

    from app.services.pii import kms_transport as mod

    src = inspect.getsource(mod.get_kms_transport)
    assert "except" not in src, "khong duoc bat loi provider roi chuyen sang provider khac"


# ---------------------------------------------------------------------------
# Transport Vault: anh xa loi va rang buoc phien ban
# ---------------------------------------------------------------------------
def _transport() -> VaultTransitTransport:
    return VaultTransitTransport(base_url="http://vault.invalid:8200", token="tok", timeout=1.0)


@pytest.mark.parametrize("thieu", ["addr", "token"])
def test_thieu_dia_chi_hoac_token_bi_tu_choi_ngay(thieu: str) -> None:
    kw = {"base_url": "http://vault.invalid:8200", "token": "tok"}
    kw["base_url" if thieu == "addr" else "token"] = ""
    with pytest.raises(SigningBackendDenied):
        VaultTransitTransport(**kw)


def test_key_version_khong_phai_so_bi_tu_choi_truoc_khi_goi_mang() -> None:
    """Vault danh so phien ban bang so nguyen. Bat sai dinh dang tai cho, khong de mang bao ho."""
    with pytest.raises(SigningBackendDenied, match="so nguyen"):
        _transport().sign(_KEY, "localdev:v1", b"noi dung")


@pytest.mark.parametrize(("status", "lop"), [
    (403, SigningBackendDenied),      # sai quyen/token
    (400, SigningBackendDenied),      # khoa khong ton tai
    (404, SigningBackendDenied),
    (500, SigningBackendUnavailable),  # vd phien ban khoa bi vo hieu
    (503, SigningBackendUnavailable),  # vd Vault sealed
])
def test_anh_xa_ma_trang_thai_sang_loi_fail_closed(monkeypatch, status: int, lop) -> None:
    _cam_client_gia(monkeypatch, _PhanHoiGia(status, {"errors": ["ly do cua provider"]}))
    with pytest.raises(lop) as e:
        _transport().sign(_KEY, "1", b"noi dung")
    # Thong diep phai mang GOI Y cua provider, neu khong nguoi van hanh khong biet sua o dau.
    assert "ly do cua provider" in str(e.value)


def test_khong_ro_ri_noi_dung_duoc_ky_trong_thong_diep_loi(monkeypatch) -> None:
    """T11-03: khong bao gio dua raw content vao loi/log."""
    bi_mat = b"tin nhan that cua khach hang"
    _cam_client_gia(monkeypatch, _PhanHoiGia(500, {"errors": ["loi"]}))
    with pytest.raises(SigningBackendUnavailable) as e:
        _transport().sign(_KEY, "1", bi_mat)
    assert bi_mat.decode() not in str(e.value)
    assert base64.b64encode(bi_mat).decode() not in str(e.value)


def test_ghim_dung_phien_ban_khi_yeu_cau_ky(monkeypatch) -> None:
    """Neu khong ghim, Vault ky bang phien ban MOI NHAT -> transcript khai sai key_version."""
    da_goi = _cam_client_gia(monkeypatch, _PhanHoiGia(
        200, {"data": {"signature": "vault:v3:" + base64.b64encode(b"s" * 64).decode()}}))
    _transport().sign(_KEY, "3", b"noi dung")
    assert da_goi[0]["json"]["key_version"] == 3


def test_backend_ky_bang_phien_ban_khac_bi_tu_choi(monkeypatch) -> None:
    """Bat truong hop provider am tham dung phien ban khac voi phien ban da yeu cau."""
    _cam_client_gia(monkeypatch, _PhanHoiGia(
        200, {"data": {"signature": "vault:v9:" + base64.b64encode(b"s" * 64).decode()}}))
    with pytest.raises(SigningBackendDenied, match="phien ban"):
        _transport().sign(_KEY, "1", b"noi dung")


@pytest.mark.parametrize("body", [
    {"data": {}},                                         # thieu truong signature
    {"data": {"signature": "khong-dung-dinh-dang"}},      # khong co tien to vault:vN:
    None,                                                 # body khong phai JSON
])
def test_phan_hoi_di_dang_lam_hong_fail_closed(monkeypatch, body) -> None:
    _cam_client_gia(monkeypatch, _PhanHoiGia(200, body))
    with pytest.raises(SigningBackendUnavailable):
        _transport().sign(_KEY, "1", b"noi dung")


def test_public_key_thieu_phien_ban_bi_tu_choi(monkeypatch) -> None:
    _cam_client_gia(monkeypatch, _PhanHoiGia(
        200, {"data": {"keys": {"1": {"public_key": base64.b64encode(b"p" * 32).decode()}}}}))
    t = _transport()
    assert len(t.public_key(_KEY, "1")) == 32
    with pytest.raises(SigningBackendDenied, match="phien ban"):
        t.public_key(_KEY, "2")


def test_token_khong_bao_gio_nam_trong_thong_diep_loi(monkeypatch) -> None:
    _cam_client_gia(monkeypatch, _PhanHoiGia(403, {"errors": ["permission denied"]}))
    t = VaultTransitTransport(base_url="http://vault.invalid:8200",
                              token="token-rat-bi-mat", timeout=1.0)
    with pytest.raises(SigningBackendDenied) as e:
        t.sign(_KEY, "1", b"x")
    assert "token-rat-bi-mat" not in str(e.value)
