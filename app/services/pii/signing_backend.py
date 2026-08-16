"""I-B M4 H2-A — SigningBackend: truu tuong hoa cho KY BAT DOI XUNG (Ed25519).

Boi canh (CA PRE-PUBLIC-HARDENING H2, PO decision record 17/8/2026):
`crypto.py:sign_capture()` hien ky transcript bang HMAC-SHA256 voi khoa DOI XUNG nam trong
`m4_stage0p_transcript_signing_keys.hmac_key` (DB) va trong file plaintext
`/run/m4-signing-secrets/transcript_hmac_key`. Chinh docstring `crypto.py` da ghi gioi han:
khoa do KHONG co non-repudiation — DBA, nguoi giu backup DB, hoac ai doc duoc runtime deu gia
mao duoc transcript ma khong de lai dau vet.

PO da chot phuong an DUAL-TAG:
  - HMAC cu GIU NGUYEN, nhung CHI con y nghia "integrity/capability gate cua DB" (ham
    `m4_stage0p_record_sample` tu verify truoc khi tieu thu capability). No KHONG duoc goi la
    chu ky co quy trach nhiem nua.
  - THEM chu ky Ed25519 tao qua KMS/HSM/Vault: private material KHONG BAO GIO nam trong image,
    `.env`, file plaintext hay bien moi truong cua application. Verify bang PUBLIC key, THUC HIEN
    NGOAI DB — nen nguoi verify khong can giu bat ky bi mat nao.

Module nay CHI dinh nghia ranh gioi (protocol + 2 hien thuc + factory fail-closed). No KHONG tu
noi vao `sign_capture()`; viec noi day la buoc rieng trong cung PR H2-A.

CAC HIEN THUC
  - `LocalDevBackend`   : sinh khoa Ed25519 TRONG RAM. CHI cho sandbox/CI. Co guard fail-closed
                          (xem `_assert_localdev_allowed`) de khong the vo tinh chay o production.
  - `KmsSigningBackend` : goi ra backend ngoai qua `KmsTransport`. Bản thân module nay KHONG
                          hien thuc client cho mot nha cung cap cu the — PO chua chot backend, va
                          directive H2-A CAM provision KMS that. Transport la ranh gioi de:
                            (a) test protocol Ed25519 E2E bang fake transport,
                            (b) test KMS outage -> fail-closed,
                            (c) sau nay cam adapter that vao ma khong sua logic ky.

FAIL-CLOSED LA MAC DINH
Moi loi cua backend deu nang thanh `SigningBackendUnavailable`/`SigningBackendDenied` va KHONG
co duong lui "tam ky bang HMAC". Duong lui do se xoa sach gia tri cua H2 (xem design proposal
§5.4) nen co tinh KHONG ton tai trong code nay.

KHONG BAO GIO LOG KEY MATERIAL
Moi nhanh loi chi log ten class/ma loi. Khong log message duoc ky, khong log signature, khong
log private material (dinh nghia: `LocalDevBackend` la noi duy nhat co private key, va no khong
expose ra ngoai qua bat ky phuong thuc public nao).
"""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

SIGNATURE_ALGORITHM = "Ed25519"
_ED25519_PUBLIC_KEY_BYTES = 32
_ED25519_SIGNATURE_BYTES = 64

# Bien moi truong bat buoc de duoc phep dung LocalDevBackend. Hai bien RIENG BIET, phai dung ca
# hai: mot cai chon backend, mot cai la xac nhan tuong minh "toi biet day la khoa trong RAM".
_ENV_BACKEND = "M4_SIGNING_BACKEND"
_ENV_ALLOW_LOCALDEV = "M4_ALLOW_LOCALDEV_SIGNING"
# Gia tri `app_env` bi coi la production — LocalDevBackend bi tu choi ke ca khi 2 bien tren dung.
_PRODUCTION_APP_ENVS = frozenset({"production", "prod", "staging"})


class SigningBackendError(Exception):
    """Goc cua moi loi backend. Caller chi can bat class nay de fail-closed."""


class SigningBackendUnavailable(SigningBackendError):
    """Backend khong tra loi duoc (timeout, mat mang, KMS down). PHAI dan den KHONG ghi sample."""


class SigningBackendDenied(SigningBackendError):
    """Backend tu choi thao tac (policy/quyen). Vd: co export private key -> phai bi tu choi."""


class SigningBackendMisconfigured(SigningBackendError):
    """Cau hinh sai — vd co dung LocalDevBackend o production. Fail o startup, khong fail giua chung."""


@runtime_checkable
class SigningBackend(Protocol):
    """Ranh gioi duy nhat ma tang ky duoc phep goi.

    Chu y KHONG co phuong thuc nao tra ve private material. Do la co y: mot backend dung chuan
    thi KHONG THE bi hoi private key qua interface nay, nen code goi khong the vo tinh lam ro ri.
    """

    def key_id(self) -> str:
        """Dinh danh khoa on dinh qua cac lan xoay vong. Vd 'm4-transcript-ed25519'."""

    def key_version(self) -> str:
        """Phien ban khoa hien dang KY. Ghi vao transcript de verify duoc sau khi xoay vong."""

    def public_key_raw(self, key_version: str | None = None) -> bytes:
        """32 byte raw public key cua `key_version` (mac dinh: phien ban dang ky).

        Nhan `key_version` de verifier lay lai public key cua transcript CU sau khi xoay vong.
        """

    def sign(self, message: bytes) -> bytes:
        """64 byte chu ky Ed25519 tren DUNG `message` (khong hash truoc — Ed25519 tu lam)."""


def verify_signature(public_key_raw: bytes, message: bytes, signature: bytes) -> bool:
    """Verify Ed25519 — dung duoc BOI BAT KY AI co public key, khong can bi mat nao.

    Day chinh la diem cot loi cua H2: hom nay chi DB verify duoc (bang khoa doi xung DB tu giu,
    ma DB cung la ben gia mao duoc); sau H2 nguoi verify khong con can giu bi mat.

    Tra `False` thay vi raise cho moi truong hop chu ky sai/kich thuoc sai — de caller xu ly
    dong nhat. Loi KHONG chua `message` hay `signature` (T11-03: khong log raw content).
    """
    if len(public_key_raw) != _ED25519_PUBLIC_KEY_BYTES:
        return False
    if len(signature) != _ED25519_SIGNATURE_BYTES:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(public_key_raw).verify(signature, message)
    except (InvalidSignature, ValueError):
        return False
    return True


def _assert_localdev_allowed(app_env: str) -> None:
    """Guard fail-closed: LocalDevBackend chi song duoc trong sandbox/CI.

    PO decision record §2 ghi ro 'dev-mode bi cam cho production'. Guard nay lam dieu do thanh
    rang buoc cua CODE, khong phai cua tai lieu — vi tai lieu khong ngan duoc mot lan deploy nham.
    """
    if os.environ.get(_ENV_ALLOW_LOCALDEV) != "1":
        raise SigningBackendMisconfigured(
            f"LocalDevBackend bi tu choi: thieu {_ENV_ALLOW_LOCALDEV}=1 (khoa nam trong RAM, "
            "chi duoc dung o sandbox/CI)")
    if app_env.strip().lower() in _PRODUCTION_APP_ENVS:
        raise SigningBackendMisconfigured(
            f"LocalDevBackend bi tu choi: app_env={app_env!r} la moi truong production. "
            "PO decision record §2: dev-mode bi cam cho production.")


class LocalDevBackend:
    """Ed25519 sinh TRONG RAM — sandbox/CI only.

    Ho tro `rotate()` de test duoc dieu CA yeu cau: 'transcript truoc rotation con verify duoc'.
    Public key cua MOI phien ban deu duoc giu lai; private key cua phien ban cu bi bo di ngay khi
    xoay (khong con ky duoc bang khoa cu — dung ngu nghia thu hoi).
    """

    def __init__(self, *, key_id: str = "m4-transcript-ed25519-localdev",
                 app_env: str | None = None) -> None:
        _assert_localdev_allowed(app_env if app_env is not None
                                 else os.environ.get("APP_ENV", "development"))
        self._key_id = key_id
        self._version_counter = 0
        # key_version -> public bytes. Chi PUBLIC duoc giu lich su.
        self._public_history: dict[str, bytes] = {}
        self._private: Ed25519PrivateKey | None = None
        self._key_version = ""
        self.rotate()

    def rotate(self) -> str:
        """Sinh phien ban khoa moi, tra ve `key_version` moi. Public key cu VAN tra cuu duoc."""
        self._version_counter += 1
        self._key_version = f"localdev:v{self._version_counter}"
        self._private = Ed25519PrivateKey.generate()
        self._public_history[self._key_version] = self._private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        return self._key_version

    def key_id(self) -> str:
        return self._key_id

    def key_version(self) -> str:
        return self._key_version

    def public_key_raw(self, key_version: str | None = None) -> bytes:
        version = key_version or self._key_version
        try:
            return self._public_history[version]
        except KeyError:
            raise SigningBackendDenied(
                f"khong co public key cho key_version={version!r}") from None

    def sign(self, message: bytes) -> bytes:
        if self._private is None:  # pragma: no cover — bat trang thai khong the xay ra
            raise SigningBackendUnavailable("LocalDevBackend chua co khoa")
        return self._private.sign(message)


@runtime_checkable
class KmsTransport(Protocol):
    """Ranh gioi I/O toi KMS that. Test bom fake vao day de khong can KMS that.

    `export_private_key` co mat CO Y: no ton tai de test NEGATIVE goi duoc va chung minh backend
    bi tu choi. Mot transport dung chuan PHAI raise `SigningBackendDenied` — day la cach bien
    'application khong export duoc private key' thanh mot phep thu chay duoc, thay vi mot cau
    tuyen bo trong tai lieu.
    """

    def sign(self, key_id: str, key_version: str, message: bytes) -> bytes: ...

    def public_key(self, key_id: str, key_version: str) -> bytes: ...

    def export_private_key(self, key_id: str, key_version: str) -> bytes: ...


class KmsSigningBackend:
    """Ky qua KMS/HSM/Vault. KHONG giu private material trong tien trinh nay.

    Moi loi transport deu thanh `SigningBackendUnavailable` — KHONG co fallback sang HMAC.
    """

    def __init__(self, transport: KmsTransport, *, key_id: str, key_version: str) -> None:
        self._transport = transport
        self._key_id = key_id
        self._key_version = key_version

    def key_id(self) -> str:
        return self._key_id

    def key_version(self) -> str:
        return self._key_version

    def public_key_raw(self, key_version: str | None = None) -> bytes:
        version = key_version or self._key_version
        try:
            pub = self._transport.public_key(self._key_id, version)
        except SigningBackendError:
            raise
        except Exception as exc:  # noqa: BLE001 — moi loi transport deu la "khong dung duoc"
            raise SigningBackendUnavailable(
                f"KMS khong tra ve public key: {type(exc).__name__}") from None
        if len(pub) != _ED25519_PUBLIC_KEY_BYTES:
            raise SigningBackendDenied(
                f"KMS tra ve public key dai {len(pub)} byte, cho doi {_ED25519_PUBLIC_KEY_BYTES}")
        return pub

    def sign(self, message: bytes) -> bytes:
        try:
            sig = self._transport.sign(self._key_id, self._key_version, message)
        except SigningBackendError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Khong dua `message` vao thong diep loi (T11-03: khong log raw content).
            raise SigningBackendUnavailable(
                f"KMS khong ky duoc: {type(exc).__name__}") from None
        if len(sig) != _ED25519_SIGNATURE_BYTES:
            raise SigningBackendDenied(
                f"KMS tra ve chu ky dai {len(sig)} byte, cho doi {_ED25519_SIGNATURE_BYTES}")
        return sig


def get_signing_backend(*, app_env: str, transport: KmsTransport | None = None,
                        key_id: str | None = None,
                        key_version: str | None = None) -> SigningBackend:
    """Factory fail-closed doc `M4_SIGNING_BACKEND`.

    Khong co gia tri mac dinh 'doan y caller': thieu/khong hop le -> raise ngay o startup. Day la
    co y, vi mot backend chon nham o production la loi im lang nguy hiem nhat cua ca H2.
    """
    choice = os.environ.get(_ENV_BACKEND, "").strip().lower()
    if choice == "localdev":
        return LocalDevBackend(app_env=app_env)
    if choice == "kms":
        if transport is None:
            raise SigningBackendMisconfigured(
                "M4_SIGNING_BACKEND=kms nhung chua cam KmsTransport")
        if not key_id or not key_version:
            raise SigningBackendMisconfigured(
                "M4_SIGNING_BACKEND=kms can ca key_id lan key_version tuong minh")
        return KmsSigningBackend(transport, key_id=key_id, key_version=key_version)
    raise SigningBackendMisconfigured(
        f"{_ENV_BACKEND} phai la 'localdev' hoac 'kms', dang la {choice!r}")
