"""I-B M4 H2-B — contract test cho adapter Google Cloud KMS (client GIA, khong cham cloud).

Directive H2-B cam dung credential that va cam tao resource. Nen bang chung o day la contract test
voi client gia: chung minh adapter GUI DUNG thu can gui va TU CHOI dung thu can tu choi.

Gioi han da khai bao: hinh dang phan hoi duoc dung theo tai lieu Google KMS, CHUA doi chieu voi API
that (khong co credential). Buoc provisioning phai co mot phep goi that de xac nhan — xem
docs/M4-H2B-GOOGLE-KMS-IAM-VA-PROVISIONING-VI.md.
"""
from __future__ import annotations

import base64

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.pii.kms_transport_google import GoogleKmsTransport
from app.services.pii.signing_backend import (
    SigningBackendDenied,
    SigningBackendKeyUnusable,
    SigningBackendUnavailable,
    verify_signature,
)

_KEY = ("projects/a3s-m4-signing/locations/asia-southeast1/keyRings/m4-transcript/"
        "cryptoKeys/transcript-ed25519")
_VER = "3"
_TEN_PHIEN_BAN = f"{_KEY}/cryptoKeyVersions/{_VER}"
_TRANSCRIPT = b'{"sample_id":"11111111-1111-1111-1111-111111111111","v":1}'
_TOKEN = "ya29.TOKEN-GIA-KHONG-DUOC-LO"
_MARKER = "MARKER-KHONG-DUOC-XUAT-HIEN"


@pytest.fixture()
def khoa() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def _pem(k: Ed25519PrivateKey) -> str:
    return k.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


class _PhanHoi:
    def __init__(self, status: int, body) -> None:
        self.status_code = status
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("khong phai JSON")
        return self._body


def _cam_client(monkeypatch, phan_hoi) -> list[dict]:
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


def _transport(**kw) -> GoogleKmsTransport:
    kw.setdefault("key_id", _KEY)
    kw.setdefault("token_provider", lambda: _TOKEN)
    return GoogleKmsTransport(**kw)


# ---------------------------------------------------------------------------
# Duong thanh cong: gui dung, doi dung
# ---------------------------------------------------------------------------
def test_ky_gui_raw_bytes_qua_truong_data_khong_phai_digest(monkeypatch, khoa) -> None:
    """Ed25519 la PureEdDSA. Gui nham sang `digest` se ky tren noi dung KHAC voi thu duoc luu."""
    def tra_loi(req):
        sig = khoa.sign(base64.b64decode(req["json"]["data"]))
        return _PhanHoi(200, {"name": _TEN_PHIEN_BAN,
                              "signature": base64.b64encode(sig).decode()})

    da_goi = _cam_client(monkeypatch, tra_loi)
    sig = _transport().sign(_KEY, _VER, _TRANSCRIPT)

    assert "data" in da_goi[0]["json"] and "digest" not in da_goi[0]["json"]
    assert base64.b64decode(da_goi[0]["json"]["data"]) == _TRANSCRIPT
    assert len(sig) == 64
    pub = khoa.public_key().public_bytes(serialization.Encoding.Raw,
                                         serialization.PublicFormat.Raw)
    assert verify_signature(pub, _TRANSCRIPT, sig) is True


def test_ky_dung_CryptoKeyVersion_tuong_minh_khong_dung_latest(monkeypatch, khoa) -> None:
    da_goi = _cam_client(monkeypatch, _PhanHoi(200, {
        "name": _TEN_PHIEN_BAN,
        "signature": base64.b64encode(khoa.sign(_TRANSCRIPT)).decode()}))
    _transport().sign(_KEY, _VER, _TRANSCRIPT)
    url = da_goi[0]["url"]
    assert url.endswith(f"cryptoKeyVersions/{_VER}:asymmetricSign")
    assert "latest" not in url.lower()


def test_public_key_doi_PEM_sang_raw_32_byte(monkeypatch, khoa) -> None:
    _cam_client(monkeypatch, _PhanHoi(200, {"pem": _pem(khoa), "algorithm": "EC_SIGN_ED25519",
                                            "name": _TEN_PHIEN_BAN}))
    raw = _transport().public_key(_KEY, _VER)
    assert len(raw) == 32
    assert raw == khoa.public_key().public_bytes(serialization.Encoding.Raw,
                                                 serialization.PublicFormat.Raw)


# ---------------------------------------------------------------------------
# Negative: moi ca deu phai fail-closed voi ma an toan
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("status", "gstatus", "lop", "ma"), [
    (503, "UNAVAILABLE", SigningBackendUnavailable, "backend_unavailable"),
    (500, "INTERNAL", SigningBackendUnavailable, "backend_unavailable"),
    (403, "PERMISSION_DENIED", SigningBackendDenied, "backend_denied"),
    (401, "UNAUTHENTICATED", SigningBackendDenied, "backend_denied"),
    (404, "NOT_FOUND", SigningBackendDenied, "backend_denied"),
    (400, "INVALID_ARGUMENT", SigningBackendDenied, "backend_denied"),
    (400, "FAILED_PRECONDITION", SigningBackendKeyUnusable, "backend_key_disabled"),
])
def test_anh_xa_loi_sang_ma_an_toan(monkeypatch, status, gstatus, lop, ma) -> None:
    """Phan loai theo `error.status` — ENUM on dinh cua Google, chac chan hon doc `message`."""
    _cam_client(monkeypatch, _PhanHoi(status, {"error": {
        "code": status, "status": gstatus,
        "message": f"chi tiet noi bo {_MARKER} token={_TOKEN}"}}))
    with pytest.raises(lop) as e:
        _transport().sign(_KEY, _VER, _TRANSCRIPT)
    assert e.value.MA == ma
    assert _MARKER not in str(e.value)
    assert _TOKEN not in str(e.value)
    assert base64.b64encode(_TRANSCRIPT).decode() not in str(e.value)


def test_khoa_sai_thuat_toan_bi_tu_choi(monkeypatch, khoa) -> None:
    """Khoa RSA/ECDSA van tra PEM hop le — phai chan o day thay vi de migration 044 tu choi."""
    _cam_client(monkeypatch, _PhanHoi(200, {
        "pem": _pem(khoa), "algorithm": "RSA_SIGN_PSS_2048_SHA256", "name": _TEN_PHIEN_BAN}))
    with pytest.raises(SigningBackendDenied, match="EC_SIGN_ED25519"):
        _transport().public_key(_KEY, _VER)


def test_backend_tra_ve_phien_ban_khac_bi_tu_choi(monkeypatch, khoa) -> None:
    _cam_client(monkeypatch, _PhanHoi(200, {
        "name": f"{_KEY}/cryptoKeyVersions/9",
        "signature": base64.b64encode(khoa.sign(_TRANSCRIPT)).decode()}))
    with pytest.raises(SigningBackendDenied, match="phien ban"):
        _transport().sign(_KEY, _VER, _TRANSCRIPT)


@pytest.mark.parametrize("body", [
    {"name": _TEN_PHIEN_BAN},
    {"name": _TEN_PHIEN_BAN, "signature": "!!!"},
    None,
])
def test_phan_hoi_di_dang_fail_closed(monkeypatch, body) -> None:
    _cam_client(monkeypatch, _PhanHoi(200, body))
    with pytest.raises(SigningBackendUnavailable):
        _transport().sign(_KEY, _VER, _TRANSCRIPT)


def test_timeout_mang_thanh_backend_unavailable(monkeypatch) -> None:
    class _ClientTimeout:
        def __init__(self, *a, **kw) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a) -> None:
            return None

        def request(self, *a, **kw):
            raise httpx.ReadTimeout("qua han")

    monkeypatch.setattr(httpx, "Client", _ClientTimeout)
    with pytest.raises(SigningBackendUnavailable) as e:
        _transport().sign(_KEY, _VER, _TRANSCRIPT)
    assert e.value.MA == "backend_unavailable"


def test_credential_hong_thanh_backend_denied(monkeypatch) -> None:
    """Federation/credential hong la van de QUYEN — thu lai khong giup, va khong duoc lo chi tiet."""
    da_goi = _cam_client(monkeypatch, _PhanHoi(200, {}))

    def _hong() -> str:
        raise RuntimeError(f"chi tiet credential {_MARKER}")

    with pytest.raises(SigningBackendDenied) as e:
        _transport(token_provider=_hong).sign(_KEY, _VER, _TRANSCRIPT)
    assert e.value.MA == "backend_denied"
    assert _MARKER not in str(e.value)
    assert da_goi == [], "khong duoc goi mang khi chua co credential"


@pytest.mark.parametrize("sai", [
    "transcript-ed25519",
    "projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1",
])
def test_key_id_phai_la_resource_path_day_du(sai: str) -> None:
    with pytest.raises(SigningBackendDenied, match="resource path"):
        _transport(key_id=sai)


def test_key_version_khong_phai_so_bi_tu_choi() -> None:
    with pytest.raises(SigningBackendDenied, match="so nguyen"):
        _transport().sign(_KEY, "latest", _TRANSCRIPT)


def test_key_id_khac_khoa_da_cau_hinh_bi_tu_choi() -> None:
    with pytest.raises(SigningBackendDenied, match="khong khop"):
        _transport().sign(_KEY.replace("a3s-m4-signing", "project-khac"), _VER, _TRANSCRIPT)
