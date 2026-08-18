"""I-B M4 H2-B — test OFFLINE cho luong external-account (WIF X.509).

AUTHORITY: CA-Docs/PHASE1B-M4-H2B-WIF-X509-TRUST-SOURCE-PO-DECISION-VI.md.

Toan bo chay bang credential GIA: khong google-auth that, khong mang, khong credential that
(directive Correction 2 cam tao credential/CA/chung chi that). Nhung chung di qua DUNG logic
cache/refresh cua production, nen chung minh duoc dieu can chung minh: nap mot lan, tai su dung
token con han, refresh khi gan het han, va N luong dong thoi chi refresh MOT lan.
"""
from __future__ import annotations

import datetime as dt
import threading

import pytest

from app.services.pii.google_credentials import GoogleWifTokenProvider
from app.services.pii.signing_backend import (
    SigningBackendDenied,
    SigningBackendMisconfigured,
    SigningBackendUnavailable,
)

_CONFIG = "/run/m4-wif/credential-config.json"
_TOKEN = "ya29.TOKEN-KHONG-DUOC-LO"
_SUBJECT = "SUBJECT-TOKEN-KHONG-DUOC-LO"


class _CredsGia:
    """Bat chuoc be mat cua google-auth credentials: `.token`, `.expiry`, `.refresh()`."""

    def __init__(self, *, han_sau: dt.timedelta | None = dt.timedelta(hours=1),
                 loi=None, token: str = _TOKEN) -> None:
        self.token: str | None = None
        self.expiry: dt.datetime | None = None
        self._han_sau = han_sau
        self._loi = loi
        self._token = token
        self.so_lan_refresh = 0

    def refresh(self, _yeu_cau) -> None:
        self.so_lan_refresh += 1
        if self._loi is not None:
            raise self._loi
        self.token = self._token
        # naive UTC, dung nhu google-auth dat `expiry`
        self.expiry = ((dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + self._han_sau)
                       if self._han_sau else None)


def _provider(creds: _CredsGia, **kw) -> GoogleWifTokenProvider:
    return GoogleWifTokenProvider(_CONFIG, nap=lambda _p: creds,
                                  tao_yeu_cau=lambda: object(), **kw)


# ---------------------------------------------------------------------------
# Nap mot lan, cache, refresh dung luc
# ---------------------------------------------------------------------------
def test_lan_dau_refresh_va_tra_token() -> None:
    creds = _CredsGia()
    p = _provider(creds)
    assert p() == _TOKEN
    assert creds.so_lan_refresh == 1


def test_token_con_han_thi_TAI_SU_DUNG_khong_refresh_lai() -> None:
    """Truoc correction, moi lan ky deu nap + refresh — ton quota va tang do tre."""
    creds = _CredsGia()
    p = _provider(creds)
    for _ in range(10):
        assert p() == _TOKEN
    assert creds.so_lan_refresh == 1, "chi duoc refresh dung mot lan"


def test_gan_het_han_thi_refresh_som() -> None:
    """Token con 1 phut phai duoc lam moi TRUOC: het han giua fenced unit lam ca unit that bai."""
    creds = _CredsGia(han_sau=dt.timedelta(minutes=1))
    p = _provider(creds)
    p()
    assert creds.so_lan_refresh == 1
    p()
    assert creds.so_lan_refresh == 2


def test_khong_biet_han_va_khong_valid_thi_coi_nhu_het_han() -> None:
    """Fail-closed: tha refresh thua con hon ky bang mot token da chet."""
    creds = _CredsGia(han_sau=None)
    p = _provider(creds)
    p()
    p()
    assert creds.so_lan_refresh == 2


def test_nhieu_luong_dong_thoi_chi_refresh_MOT_lan() -> None:
    """Signer co concurrency: N luong cung thay token thieu se tao N vong STS neu khong co lock."""
    cham = threading.Event()

    class _CredsCham(_CredsGia):
        def refresh(self, yeu_cau) -> None:
            cham.wait(0.2)  # gia lap do tre mang cua vong STS
            super().refresh(yeu_cau)

    creds = _CredsCham()
    p = _provider(creds)
    ket_qua: list[str] = []

    luong = [threading.Thread(target=lambda: ket_qua.append(p())) for _ in range(8)]
    for t in luong:
        t.start()
    cham.set()
    for t in luong:
        t.join(timeout=5)

    assert ket_qua == [_TOKEN] * 8
    assert creds.so_lan_refresh == 1, f"refresh {creds.so_lan_refresh} lan thay vi 1"
    assert p.so_lan_refresh == 1


# ---------------------------------------------------------------------------
# Phan loai loi an toan
# ---------------------------------------------------------------------------
def test_thieu_cau_hinh_la_loi_CAU_HINH() -> None:
    with pytest.raises(SigningBackendMisconfigured):
        GoogleWifTokenProvider("")


def test_loi_ha_tang_thanh_unavailable() -> None:
    ga = pytest.importorskip("google.auth.exceptions")
    p = _provider(_CredsGia(loi=ga.TransportError("mat mang")))
    with pytest.raises(SigningBackendUnavailable) as e:
        p()
    assert e.value.MA == "backend_unavailable"


@pytest.mark.parametrize("nhan", [
    "issuer khong khop", "audience khong khop", "subject khong khop",
    "chung chi het han", "chung chi da bi thu hoi",
])
def test_credential_khong_hop_le_thanh_denied(nhan: str) -> None:
    """Issuer/audience/subject/certificate sai hay bi thu hoi deu la van de QUYEN, khong phai ha tang."""
    ga = pytest.importorskip("google.auth.exceptions")
    p = _provider(_CredsGia(loi=ga.RefreshError(f"{nhan}: {_SUBJECT}")))
    with pytest.raises(SigningBackendDenied) as e:
        p()
    assert e.value.MA == "backend_denied"


def test_refresh_xong_ma_khong_co_token_thi_tu_choi() -> None:
    p = _provider(_CredsGia(token=""))
    with pytest.raises(SigningBackendDenied):
        p()


# ---------------------------------------------------------------------------
# Khong ro ri
# ---------------------------------------------------------------------------
def test_khong_ro_ri_token_subject_hay_duong_dan_credential() -> None:
    ga = pytest.importorskip("google.auth.exceptions")
    p = _provider(_CredsGia(loi=ga.RefreshError(
        f"chi tiet noi bo: subject={_SUBJECT} token={_TOKEN} file={_CONFIG}")))
    with pytest.raises(SigningBackendDenied) as e:
        p()
    thong_diep = str(e.value)
    assert _SUBJECT not in thong_diep
    assert _TOKEN not in thong_diep
    assert _CONFIG not in thong_diep


def test_loi_khong_ro_loai_van_fail_closed() -> None:
    p = _provider(_CredsGia(loi=RuntimeError("khong ro")))
    with pytest.raises((SigningBackendDenied, SigningBackendUnavailable)):
        p()


# ---------------------------------------------------------------------------
# F-H2B-06 — cau hinh X.509 phai di qua PARSER THAT cua phien ban da pin
# ---------------------------------------------------------------------------
def _cau_hinh_x509(thu_muc, **ghi_de) -> str:
    """Cau hinh external-account X.509 hop le. KHONG chua credential that.

    `cert_path`/`key_path` tro toi file KHONG ton tai — co y: buoc NAP chi duoc parse, moi I/O
    (doc chung chi, goi STS) phai xay ra o `refresh()`. Neu mot ban google-auth tuong lai doc chung
    chi ngay luc nap, test nay se do va bao cho ta biet.
    """
    import json as _json

    cert_cfg = thu_muc / "certificate_config.json"
    cert_cfg.write_text(_json.dumps({"cert_configs": {"workload": {
        "cert_path": str(thu_muc / "client.pem"),
        "key_path": str(thu_muc / "client.key")}}}), encoding="utf-8")

    thong_tin = {
        "type": "external_account",
        "audience": ("//iam.googleapis.com/projects/000000000000/locations/global/"
                     "workloadIdentityPools/alpha3s-vps/providers/vps-x509"),
        "subject_token_type": "urn:ietf:params:oauth:token-type:mtls",
        "token_url": "https://sts.googleapis.com/v1/token",
        "credential_source": {"certificate": {"certificate_config_location": str(cert_cfg)}},
    }
    thong_tin.update(ghi_de)
    cfg = thu_muc / "wif-credential-config.json"
    cfg.write_text(_json.dumps(thong_tin), encoding="utf-8")
    return str(cfg)


def test_phien_ban_google_auth_ho_tro_X509(tmp_path) -> None:
    """F-H2B-06: pin >= 2.39.0 va cau hinh X.509 phai parse duoc bang loader THAT."""
    ga = pytest.importorskip("google.auth")
    phien_ban = tuple(int(x) for x in ga.__version__.split(".")[:2])
    assert phien_ban >= (2, 39), f"google-auth {ga.__version__} khong ho tro X.509 WIF"

    p = GoogleWifTokenProvider(_cau_hinh_x509(tmp_path))
    creds = p._nap(p._duong_dan)  # noqa: SLF001 - co y goi duong nap that
    from google.auth import identity_pool  # type: ignore[import-not-found]

    assert isinstance(creds, identity_pool.Credentials)


def test_nap_KHONG_cham_mang_va_khong_doc_chung_chi(tmp_path) -> None:
    """Nap chi duoc PARSE. File chung chi khong ton tai ma van nap duoc = khong co I/O nao."""
    pytest.importorskip("google.auth")
    duong_dan = _cau_hinh_x509(tmp_path)
    assert not (tmp_path / "client.pem").exists()
    GoogleWifTokenProvider(duong_dan)._nap(duong_dan)  # noqa: SLF001


def test_credential_source_khong_phai_X509_bi_tu_choi(tmp_path) -> None:
    """PO decision chot X.509; mot cau hinh 'file'/'url' van chay duoc nhung sai mo hinh da duyet."""
    pytest.importorskip("google.auth")
    duong_dan = _cau_hinh_x509(tmp_path, credential_source={"file": "/tmp/subject-token"})
    with pytest.raises(SigningBackendMisconfigured, match="certificate"):
        GoogleWifTokenProvider(duong_dan)._nap(duong_dan)  # noqa: SLF001


def test_cau_hinh_sai_loai_hoac_thieu_file_la_loi_CAU_HINH(tmp_path) -> None:
    pytest.importorskip("google.auth")
    p = GoogleWifTokenProvider(str(tmp_path / "khong-ton-tai.json"))
    with pytest.raises(SigningBackendMisconfigured):
        p()

    sai = tmp_path / "sai.json"
    sai.write_text('{"type": "service_account"}', encoding="utf-8")
    with pytest.raises(SigningBackendMisconfigured, match="external_account"):
        GoogleWifTokenProvider(str(sai))._nap(str(sai))  # noqa: SLF001
