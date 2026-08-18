"""I-B M4 H2 — test cho `KmsTransport`, factory, va HAI guard do CA yeu cau.

Bang chung HANH VI (Vault that, ba che do hong, rotation) nam o
`scripts/m4_h2_kms_e2e_sandbox.py`. Cac test o day chay duoc trong CI khong co Vault va chan bon
thu de bi lam hong ma khong ai thay:

  * mot MAC DINH am tham duoc them lai (chon provider ho caller);
  * mot DUONG LUI khi provider loi;
  * F-H2-KMS-01: backend SANDBOX chay duoc o production vi ai do cau hinh tuong minh;
  * F-H2-KMS-02: chi tiet chan doan cua provider ro ri qua giao thuc collector.
"""
from __future__ import annotations

import base64

import httpx
import pytest

from app.services.pii.kms_transport import get_kms_transport
from app.services.pii.kms_transport_vault import VaultTransitTransport
from app.services.pii.signing_backend import (
    SigningBackendDenied,
    SigningBackendKeyUnusable,
    SigningBackendMisconfigured,
    SigningBackendUnavailable,
)

_KEY = "m4-transcript"
_ENV_SANDBOX = "sandbox"
_ENV_CAM = ["production", "prod", "staging"]


@pytest.fixture()
def moi_truong_sach(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for bien in ("M4_KMS_TRANSPORT", "M4_KMS_KEY_ID", "M4_KMS_KEY_VERSION",
                 "M4_VAULT_ADDR", "M4_VAULT_TOKEN", "M4_VAULT_NAMESPACE"):
        monkeypatch.delenv(bien, raising=False)
    return monkeypatch


def _cau_hinh_vault(mp: pytest.MonkeyPatch) -> None:
    mp.setenv("M4_KMS_TRANSPORT", "vault")
    mp.setenv("M4_KMS_KEY_ID", _KEY)
    mp.setenv("M4_KMS_KEY_VERSION", "1")
    mp.setenv("M4_VAULT_ADDR", "http://vault.invalid:8200")
    mp.setenv("M4_VAULT_TOKEN", "tok")


class _PhanHoiGia:
    def __init__(self, status: int, body: dict | None) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> dict:
        if self._body is None:
            raise ValueError("khong phai JSON")
        return self._body


def _cam_client_gia(monkeypatch: pytest.MonkeyPatch, phan_hoi) -> list[dict]:
    """Thay `httpx.Client` bang ban gia; tra list ghi lai request de assert (ke ca 'khong he goi')."""
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
            return phan_hoi

    monkeypatch.setattr(httpx, "Client", _ClientGia)
    return da_goi


def _transport(app_env: str = _ENV_SANDBOX) -> VaultTransitTransport:
    return VaultTransitTransport(base_url="http://vault.invalid:8200", token="tok",
                                 app_env=app_env, timeout=1.0)


# ---------------------------------------------------------------------------
# Factory: khong mac dinh, khong duong lui
# ---------------------------------------------------------------------------
def test_factory_khong_co_mac_dinh(moi_truong_sach) -> None:
    moi_truong_sach.setenv("M4_KMS_KEY_ID", _KEY)
    moi_truong_sach.setenv("M4_KMS_KEY_VERSION", "1")
    with pytest.raises(SigningBackendMisconfigured, match="M4_KMS_TRANSPORT"):
        get_kms_transport(_ENV_SANDBOX)


def test_factory_tu_choi_provider_la(moi_truong_sach) -> None:
    moi_truong_sach.setenv("M4_KMS_KEY_ID", _KEY)
    moi_truong_sach.setenv("M4_KMS_KEY_VERSION", "1")
    moi_truong_sach.setenv("M4_KMS_TRANSPORT", "localdev")
    with pytest.raises(SigningBackendMisconfigured):
        get_kms_transport(_ENV_SANDBOX)


@pytest.mark.parametrize("thieu", ["M4_KMS_KEY_ID", "M4_KMS_KEY_VERSION"])
def test_factory_doi_key_id_va_version_tuong_minh(moi_truong_sach, thieu: str) -> None:
    _cau_hinh_vault(moi_truong_sach)
    moi_truong_sach.delenv(thieu)
    with pytest.raises(SigningBackendMisconfigured, match="bat buoc"):
        get_kms_transport(_ENV_SANDBOX)


def test_factory_khong_co_duong_lui_trong_source() -> None:
    import inspect

    from app.services.pii import kms_transport as mod

    src = inspect.getsource(mod.get_kms_transport)
    assert "except" not in src, "khong duoc bat loi provider roi chuyen sang provider khac"


# ---------------------------------------------------------------------------
# F-H2-KMS-01 — backend sandbox KHONG duoc song o production/staging
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("app_env", _ENV_CAM)
def test_vault_bi_tu_choi_o_production_du_cau_hinh_tuong_minh(moi_truong_sach, monkeypatch,
                                                              app_env: str) -> None:
    """Cau hinh tuong minh `kms + vault` VAN phai hong o production — va hong TRUOC moi HTTP."""
    _cau_hinh_vault(moi_truong_sach)
    da_goi = _cam_client_gia(monkeypatch, _PhanHoiGia(200, {"data": {}}))
    with pytest.raises(SigningBackendMisconfigured, match="production"):
        get_kms_transport(app_env)
    assert da_goi == [], "KHONG duoc phat sinh request HTTP nao truoc khi guard chan"


@pytest.mark.parametrize("app_env", _ENV_CAM)
def test_khoi_tao_truc_tiep_cung_bi_chan(monkeypatch, app_env: str) -> None:
    """Guard nam trong ham khoi tao, nen khong the di vong bang cach bo qua factory."""
    da_goi = _cam_client_gia(monkeypatch, _PhanHoiGia(200, {"data": {}}))
    with pytest.raises(SigningBackendMisconfigured, match="production"):
        _transport(app_env)
    assert da_goi == []


@pytest.mark.parametrize("app_env", ["sandbox", "development", "test", "ci"])
def test_moi_truong_khong_phai_production_van_dung_duoc(moi_truong_sach, app_env: str) -> None:
    _cau_hinh_vault(moi_truong_sach)
    transport, key_id, key_version = get_kms_transport(app_env)
    assert isinstance(transport, VaultTransitTransport)
    assert (key_id, key_version) == (_KEY, "1")


# ---------------------------------------------------------------------------
# F-H2-KMS-02 — chi MA LOI AN TOAN duoc di ra ngoai
# ---------------------------------------------------------------------------
# Chuoi doc do provider "tra ve": chua base64 cua transcript, mot token gia va marker rieng.
# Mot provider/proxy/cau hinh sai trong tuong lai HOAN TOAN co the phan chieu nhung thu nay.
_TRANSCRIPT = b'{"sample_id":"11111111-1111-1111-1111-111111111111","v":1}'
_TOKEN_GIA = "hvs.TOKEN-RAT-BI-MAT-KHONG-DUOC-LO"
_MARKER = "MARKER-KHONG-DUOC-XUAT-HIEN-O-DAU"
_BODY_DOC = {"errors": [
    f"loi gia lap: input={base64.b64encode(_TRANSCRIPT).decode()} "
    f"token={_TOKEN_GIA} {_MARKER}"]}


def _khong_ro_ri(chuoi: str) -> None:
    assert _MARKER not in chuoi
    assert _TOKEN_GIA not in chuoi
    assert base64.b64encode(_TRANSCRIPT).decode() not in chuoi
    assert _TRANSCRIPT.decode() not in chuoi


@pytest.mark.parametrize(("status", "lop", "ma"), [
    (403, SigningBackendDenied, "backend_denied"),
    (400, SigningBackendDenied, "backend_denied"),
    (404, SigningBackendDenied, "backend_denied"),
    (503, SigningBackendUnavailable, "backend_unavailable"),
])
def test_ma_loi_an_toan_va_khong_ro_ri_chi_tiet_provider(monkeypatch, status, lop, ma) -> None:
    _cam_client_gia(monkeypatch, _PhanHoiGia(status, _BODY_DOC))
    with pytest.raises(lop) as e:
        _transport().sign(_KEY, "1", _TRANSCRIPT)
    assert e.value.MA == ma, "nguoi van hanh phai nhan dung ma loi de biet sua o dau"
    _khong_ro_ri(str(e.value))


def test_khoa_bi_vo_hieu_co_ma_rieng_khong_can_doc_text_o_ngoai(monkeypatch) -> None:
    """CA yeu cau ma AN TOAN rieng cho key-disabled, thay vi suy luan tu text cua provider."""
    body = {"errors": ["1 error occurred: * requested version for signing is less than the "
                       f"minimum encryption key version {_MARKER}"]}
    _cam_client_gia(monkeypatch, _PhanHoiGia(500, body))
    with pytest.raises(SigningBackendKeyUnusable) as e:
        _transport().sign(_KEY, "1", _TRANSCRIPT)
    assert e.value.MA == "backend_key_disabled"
    _khong_ro_ri(str(e.value))


def test_phan_hoi_dung_nhung_di_dang_cung_khong_ro_ri(monkeypatch) -> None:
    _cam_client_gia(monkeypatch, _PhanHoiGia(200, {"data": {"signature": _MARKER}}))
    with pytest.raises(SigningBackendUnavailable) as e:
        _transport().sign(_KEY, "1", _TRANSCRIPT)
    _khong_ro_ri(str(e.value))


def test_signer_chi_dua_MA_ra_socket() -> None:
    """Kiem cau truc: nhanh xu ly `SigningBackendError` chi duoc dat `e.MA` vao response.

    Bang chung HANH VI (ma di het duong socket -> collector -> evidence) nam o kich ban
    `m4_h2_kms_e2e_sandbox.py`; o day chan viec ai do doi lai thanh `str(e)`.
    """
    import inspect

    from app.services.pii import stage0p_signing_service as svc

    src = inspect.getsource(svc._handle_conn_authorized)
    assert 'resp = {"ok": False, "error": e.MA}' in src
    assert 'f"{type(e).__name__}: {e}"' not in src


# ---------------------------------------------------------------------------
# Rang buoc phien ban / dinh dang (giu tu ban truoc)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("thieu", ["addr", "token"])
def test_thieu_dia_chi_hoac_token_bi_tu_choi_ngay(thieu: str) -> None:
    kw = {"base_url": "http://vault.invalid:8200", "token": "tok", "app_env": _ENV_SANDBOX}
    kw["base_url" if thieu == "addr" else "token"] = ""
    with pytest.raises(SigningBackendDenied):
        VaultTransitTransport(**kw)


def test_key_version_khong_phai_so_bi_tu_choi_truoc_khi_goi_mang() -> None:
    with pytest.raises(SigningBackendDenied, match="so nguyen"):
        _transport().sign(_KEY, "localdev:v1", b"noi dung")


def test_ghim_dung_phien_ban_khi_yeu_cau_ky(monkeypatch) -> None:
    da_goi = _cam_client_gia(monkeypatch, _PhanHoiGia(
        200, {"data": {"signature": "vault:v3:" + base64.b64encode(b"s" * 64).decode()}}))
    _transport().sign(_KEY, "3", b"noi dung")
    assert da_goi[0]["json"]["key_version"] == 3


def test_backend_ky_bang_phien_ban_khac_bi_tu_choi(monkeypatch) -> None:
    _cam_client_gia(monkeypatch, _PhanHoiGia(
        200, {"data": {"signature": "vault:v9:" + base64.b64encode(b"s" * 64).decode()}}))
    with pytest.raises(SigningBackendDenied, match="phien ban"):
        _transport().sign(_KEY, "1", b"noi dung")


def test_public_key_thieu_phien_ban_bi_tu_choi(monkeypatch) -> None:
    _cam_client_gia(monkeypatch, _PhanHoiGia(
        200, {"data": {"keys": {"1": {"public_key": base64.b64encode(b"p" * 32).decode()}}}}))
    t = _transport()
    assert len(t.public_key(_KEY, "1")) == 32
    with pytest.raises(SigningBackendDenied, match="phien ban"):
        t.public_key(_KEY, "2")
