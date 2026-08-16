"""I-B M4 H2-A — test cho `app/services/pii/signing_backend.py`.

Bo test nay phu cac ca NEGATIVE ma CA liet ke trong H2 Design Review 1 o pham vi TANG BACKEND:
  - khong co capability export o phia signer + chinh sach provider tu choi export (F-H2A-01)
  - signature/key-version mismatch denied
  - KMS outage -> fail-closed (khong tra ve chu ky nao)
  - transcript truoc rotation con verify duoc
  - khong ro ri private material qua interface

Cac ca con lai cua CA (missing/invalid asym signature bi DB tu choi; scan image/env/runtime;
benchmark) thuoc cac buoc khac cua H2-A, khong nam o file nay.

Nguyen tac: moi test phai DO duoc, khong test "code chay khong loi". Vd test rotation phai chung
minh chu ky CU van verify duoc bang public key CU — do moi la dieu CA yeu cau, chu khong phai
"rotate() chay khong throw".
"""
from __future__ import annotations

import pytest

from app.services.pii.signing_backend import (
    SIGNATURE_ALGORITHM,
    KmsSigningBackend,
    LocalDevBackend,
    SigningBackendDenied,
    SigningBackendMisconfigured,
    SigningBackendUnavailable,
    get_signing_backend,
    verify_signature,
)

_MSG = b'{"v":1,"batch_id":"b","canonical_digest":"deadbeef"}'


@pytest.fixture()
def localdev(monkeypatch: pytest.MonkeyPatch) -> LocalDevBackend:
    monkeypatch.setenv("M4_ALLOW_LOCALDEV_SIGNING", "1")
    return LocalDevBackend(app_env="development")


# ---------------------------------------------------------------------------
# Guard fail-closed: LocalDevBackend khong duoc song o production
# ---------------------------------------------------------------------------

def test_localdev_bi_tu_choi_khi_thieu_co_xac_nhan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("M4_ALLOW_LOCALDEV_SIGNING", raising=False)
    with pytest.raises(SigningBackendMisconfigured, match="M4_ALLOW_LOCALDEV_SIGNING"):
        LocalDevBackend(app_env="development")


@pytest.mark.parametrize("app_env", ["production", "PROD", " Production ", "staging"])
def test_localdev_bi_tu_choi_o_moi_truong_production_du_da_bat_co(
        monkeypatch: pytest.MonkeyPatch, app_env: str) -> None:
    """PO decision record §2: dev-mode bi CAM cho production.

    Bat ca khi nguoi van hanh da bat co xac nhan — co do khong duoc phep mo duong vao production.
    """
    monkeypatch.setenv("M4_ALLOW_LOCALDEV_SIGNING", "1")
    with pytest.raises(SigningBackendMisconfigured, match="production"):
        LocalDevBackend(app_env=app_env)


def test_localdev_duoc_phep_o_development_va_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M4_ALLOW_LOCALDEV_SIGNING", "1")
    for env in ("development", "test", "ci"):
        assert LocalDevBackend(app_env=env).key_version().startswith("localdev:v")


# ---------------------------------------------------------------------------
# Ky / verify Ed25519 E2E
# ---------------------------------------------------------------------------

def test_ky_roi_verify_bang_public_key(localdev: LocalDevBackend) -> None:
    sig = localdev.sign(_MSG)
    assert len(sig) == 64
    assert verify_signature(localdev.public_key_raw(), _MSG, sig) is True


def test_thuat_toan_la_ed25519(localdev: LocalDevBackend) -> None:
    assert SIGNATURE_ALGORITHM == "Ed25519"
    assert len(localdev.public_key_raw()) == 32


def test_verify_that_bai_khi_message_bi_sua_mot_bit(localdev: LocalDevBackend) -> None:
    sig = localdev.sign(_MSG)
    tampered = bytearray(_MSG)
    tampered[0] ^= 0x01
    assert verify_signature(localdev.public_key_raw(), bytes(tampered), sig) is False


def test_verify_that_bai_voi_public_key_cua_khoa_khac(
        localdev: LocalDevBackend, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M4_ALLOW_LOCALDEV_SIGNING", "1")
    khac = LocalDevBackend(app_env="development")
    sig = localdev.sign(_MSG)
    assert verify_signature(khac.public_key_raw(), _MSG, sig) is False


@pytest.mark.parametrize("sig", [b"", b"\x00" * 63, b"\x00" * 65])
def test_verify_that_bai_khi_chu_ky_sai_kich_thuoc(localdev: LocalDevBackend, sig: bytes) -> None:
    assert verify_signature(localdev.public_key_raw(), _MSG, sig) is False


@pytest.mark.parametrize("pub", [b"", b"\x00" * 31, b"\x00" * 33])
def test_verify_that_bai_khi_public_key_sai_kich_thuoc(localdev: LocalDevBackend,
                                                       pub: bytes) -> None:
    assert verify_signature(pub, _MSG, localdev.sign(_MSG)) is False


# ---------------------------------------------------------------------------
# Rotation — CA yeu cau: "transcript truoc rotation con verify duoc"
# ---------------------------------------------------------------------------

def test_transcript_ky_truoc_rotation_van_verify_duoc_sau_rotation(
        localdev: LocalDevBackend) -> None:
    ver_cu = localdev.key_version()
    pub_cu = localdev.public_key_raw()
    sig_cu = localdev.sign(_MSG)

    ver_moi = localdev.rotate()
    assert ver_moi != ver_cu
    assert localdev.key_version() == ver_moi

    # Diem cot loi: tra cuu public key CU theo key_version ghi trong transcript.
    assert localdev.public_key_raw(ver_cu) == pub_cu
    assert verify_signature(localdev.public_key_raw(ver_cu), _MSG, sig_cu) is True


def test_sau_rotation_chu_ky_moi_khong_verify_duoc_bang_public_key_cu(
        localdev: LocalDevBackend) -> None:
    ver_cu = localdev.key_version()
    localdev.rotate()
    sig_moi = localdev.sign(_MSG)
    assert verify_signature(localdev.public_key_raw(ver_cu), _MSG, sig_moi) is False
    assert verify_signature(localdev.public_key_raw(), _MSG, sig_moi) is True


def test_key_id_khong_doi_qua_rotation(localdev: LocalDevBackend) -> None:
    """`key_id` la dinh danh on dinh; chi `key_version` doi. Verifier dua vao ca hai."""
    kid = localdev.key_id()
    localdev.rotate()
    assert localdev.key_id() == kid


def test_hoi_public_key_cua_version_khong_ton_tai_bi_tu_choi(localdev: LocalDevBackend) -> None:
    with pytest.raises(SigningBackendDenied, match="khong-co-that"):
        localdev.public_key_raw("khong-co-that")


# ---------------------------------------------------------------------------
# KMS backend qua fake transport — khong can KMS that (directive H2-A cam provision)
# ---------------------------------------------------------------------------

class _FakeKms:
    """Transport gia lap DUNG CHUAN: CHI ky va tra public key.

    Khong co thao tac export nao — dung theo F-H2A-01: khong the goi thu khong ton tai.
    Giu private key trong chinh doi tuong nay de mo phong "khoa nam ben trong KMS" — code ung
    dung khong cham vao no.
    """

    def __init__(self) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        self._keys = {"v1": Ed25519PrivateKey.generate(), "v2": Ed25519PrivateKey.generate()}
        self._ser = serialization
        self.so_lan_ky = 0

    def sign(self, key_id: str, key_version: str, message: bytes) -> bytes:
        self.so_lan_ky += 1
        return self._keys[key_version].sign(message)

    def public_key(self, key_id: str, key_version: str) -> bytes:
        return self._keys[key_version].public_key().public_bytes(
            encoding=self._ser.Encoding.Raw, format=self._ser.PublicFormat.Raw)


class _KmsChet:
    """KMS down — moi thao tac nem loi transport thuong (khong phai SigningBackendError)."""

    def sign(self, key_id: str, key_version: str, message: bytes) -> bytes:
        raise ConnectionError("connection refused")

    def public_key(self, key_id: str, key_version: str) -> bytes:
        raise TimeoutError("timed out")


def _kms(version: str = "v1") -> tuple[KmsSigningBackend, _FakeKms]:
    t = _FakeKms()
    return KmsSigningBackend(t, key_id="m4-transcript-ed25519", key_version=version), t


def test_kms_ky_va_verify_e2e() -> None:
    be, transport = _kms()
    sig = be.sign(_MSG)
    assert transport.so_lan_ky == 1
    assert verify_signature(be.public_key_raw(), _MSG, sig) is True


def test_kms_rotation_verify_duoc_ca_hai_version() -> None:
    t = _FakeKms()
    be_v1 = KmsSigningBackend(t, key_id="k", key_version="v1")
    be_v2 = KmsSigningBackend(t, key_id="k", key_version="v2")
    sig_v1, sig_v2 = be_v1.sign(_MSG), be_v2.sign(_MSG)
    # Moi chu ky chi verify duoc bang public key DUNG version cua no.
    assert verify_signature(be_v1.public_key_raw("v1"), _MSG, sig_v1) is True
    assert verify_signature(be_v1.public_key_raw("v2"), _MSG, sig_v2) is True
    assert verify_signature(be_v1.public_key_raw("v2"), _MSG, sig_v1) is False


# ---------------------------------------------------------------------------
# F-H2A-01 — "application khong export duoc private key": chung minh o HAI cho, va KHONG cho
# signer mot duong export nao.
#
# Ban dau Dev dat `export_private_key()` vao `KmsTransport` roi test rang no bi tu choi. CA bac
# bo dung: lam vay bien export thanh mot CAPABILITY HOP LE cua interface — chi can mot adapter
# tuong lai hien thuc no "that" la private key co duong vao application, bat ke fake hom nay tu
# choi the nao. Bay gio phuong thuc do KHONG TON TAI o phia signer nua.
# ---------------------------------------------------------------------------

class _FakeKmsProviderAdmin:
    """Mat phang DIEU KHIEN cua provider — TACH khoi API ma signer nhin thay.

    Doi tuong nay KHONG bao gio duoc cam vao `KmsSigningBackend`. No mo phong nguoi quan tri KMS,
    va ton tai chi de kiem mot dieu: CHINH SACH tren khoa tu choi export ngay ca voi admin.
    """

    def __init__(self) -> None:
        self.policy = {"exportable": False, "allow_plaintext_backup": False}

    def doc_policy(self, key_id: str) -> dict:
        return dict(self.policy)

    def admin_export(self, key_id: str) -> bytes:
        if not self.policy["exportable"]:
            raise SigningBackendDenied(
                f"provider tu choi export {key_id}: khoa tao voi exportable=false")
        raise AssertionError("khoa nay dang la exportable — cau hinh sai")


def test_chinh_sach_provider_tu_choi_export_ngay_ca_voi_admin() -> None:
    """Bang chung thu nhat: o PHIA PROVIDER, khoa duoc tao khong the export.

    Chay qua fixture admin, KHONG qua duong signer — nen no khong the vo tinh tro thanh mot
    capability cua application.
    """
    admin = _FakeKmsProviderAdmin()
    assert admin.doc_policy("m4-transcript-ed25519") == {
        "exportable": False, "allow_plaintext_backup": False}
    with pytest.raises(SigningBackendDenied, match="exportable=false"):
        admin.admin_export("m4-transcript-ed25519")


def test_khong_mot_doi_tuong_nao_signer_cham_toi_co_capability_export() -> None:
    """Bang chung thu hai: khong co duong export trong do thi doi tuong ma signer voi toi.

    Kiem ca backend LAN transport, va kiem ca `KmsTransport` protocol — neu ai do them lai mot
    phuong thuc export (du doi ten), test nay do ngay.
    """
    from app.services.pii.signing_backend import KmsTransport

    mau_export = ("export", "private", "secret", "unwrap", "backup", "extract", "reveal")

    def cong_khai(obj) -> set[str]:
        return {ten for ten in dir(obj) if not ten.startswith("_")}

    backend, transport = _kms()
    for doi_tuong, nhan in ((backend, "KmsSigningBackend"), (transport, "transport"),
                            (KmsTransport, "KmsTransport protocol")):
        pham = {ten for ten in cong_khai(doi_tuong)
                if any(m in ten.lower() for m in mau_export)}
        assert pham == set(), f"{nhan} lo capability export: {pham}"

    # Va do thi doi tuong that su chi co dung hai thao tac.
    assert cong_khai(transport) == {"sign", "public_key", "so_lan_ky"}


def test_kms_chet_thi_ky_that_bai_fail_closed() -> None:
    """CA yeu cau: KMS outage -> 0 sample. O tang nay: KHONG tra ve chu ky nao, khong fallback."""
    be = KmsSigningBackend(_KmsChet(), key_id="k", key_version="v1")
    with pytest.raises(SigningBackendUnavailable):
        be.sign(_MSG)


def test_kms_chet_thi_lay_public_key_cung_that_bai() -> None:
    be = KmsSigningBackend(_KmsChet(), key_id="k", key_version="v1")
    with pytest.raises(SigningBackendUnavailable):
        be.public_key_raw()


def test_loi_kms_khong_chua_noi_dung_duoc_ky() -> None:
    """T11-03: khong log/khong tra raw content trong error.

    Chu ky duoc tinh tren transcript, va transcript chua digest/identity — thong diep loi tuyet
    doi khong duoc mang noi dung do ra ngoai.
    """
    be = KmsSigningBackend(_KmsChet(), key_id="k", key_version="v1")
    with pytest.raises(SigningBackendUnavailable) as ei:
        be.sign(_MSG)
    thong_diep = str(ei.value)
    assert "canonical_digest" not in thong_diep
    assert "deadbeef" not in thong_diep
    assert _MSG.decode() not in thong_diep
    assert "ConnectionError" in thong_diep  # chi ten class, dung nhu thiet ke


class _KmsTraSaiKichThuoc:
    def sign(self, key_id: str, key_version: str, message: bytes) -> bytes:
        return b"\x00" * 63

    def public_key(self, key_id: str, key_version: str) -> bytes:
        return b"\x00" * 31


def test_kms_tra_chu_ky_sai_kich_thuoc_bi_tu_choi() -> None:
    be = KmsSigningBackend(_KmsTraSaiKichThuoc(), key_id="k", key_version="v1")
    with pytest.raises(SigningBackendDenied, match="63 byte"):
        be.sign(_MSG)


def test_kms_tra_public_key_sai_kich_thuoc_bi_tu_choi() -> None:
    be = KmsSigningBackend(_KmsTraSaiKichThuoc(), key_id="k", key_version="v1")
    with pytest.raises(SigningBackendDenied, match="31 byte"):
        be.public_key_raw()


# ---------------------------------------------------------------------------
# Factory fail-closed
# ---------------------------------------------------------------------------

def test_factory_thieu_bien_moi_truong_thi_that_bai_ngay(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("M4_SIGNING_BACKEND", raising=False)
    with pytest.raises(SigningBackendMisconfigured, match="M4_SIGNING_BACKEND"):
        get_signing_backend(app_env="development")


def test_factory_gia_tri_la_thi_that_bai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M4_SIGNING_BACKEND", "hmac")
    with pytest.raises(SigningBackendMisconfigured, match="'hmac'"):
        get_signing_backend(app_env="development")


def test_factory_kms_thieu_transport_thi_that_bai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M4_SIGNING_BACKEND", "kms")
    with pytest.raises(SigningBackendMisconfigured, match="KmsTransport"):
        get_signing_backend(app_env="production")


def test_factory_kms_thieu_key_id_hoac_version_thi_that_bai(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M4_SIGNING_BACKEND", "kms")
    with pytest.raises(SigningBackendMisconfigured, match="key_id"):
        get_signing_backend(app_env="production", transport=_FakeKms(), key_version="v1")


def test_factory_localdev_o_production_van_bi_chan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Duong di qua factory KHONG duoc phep long hon duong goi truc tiep."""
    monkeypatch.setenv("M4_SIGNING_BACKEND", "localdev")
    monkeypatch.setenv("M4_ALLOW_LOCALDEV_SIGNING", "1")
    with pytest.raises(SigningBackendMisconfigured, match="production"):
        get_signing_backend(app_env="production")


# ---------------------------------------------------------------------------
# Ranh gioi: interface khong duoc lam ro ri private material
# ---------------------------------------------------------------------------

def test_interface_khong_co_phuong_thuc_nao_tra_private_material(
        localdev: LocalDevBackend) -> None:
    """Kiem tra bang noi suy, khong bang doc code bang mat.

    Neu ai do them mot phuong thuc public kieu `export_key()`/`private_key()` vao backend, test
    nay do ngay. Do la lop bao ve chong hoi quy, khong phai test trang tri.
    """
    cong_khai = {ten for ten in dir(localdev) if not ten.startswith("_")}
    cam = {"private_key", "export_key", "export", "secret", "private_bytes",
           "private_key_raw", "key_material", "backup", "unwrap"}
    assert cong_khai & cam == set(), f"backend lo phuong thuc private material: {cong_khai & cam}"
    assert cong_khai == {"key_id", "key_version", "public_key_raw", "sign", "rotate"}
