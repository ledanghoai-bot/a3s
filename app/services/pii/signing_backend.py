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

import base64
import hashlib
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
# H2-A-2 (F-H2A2-02): seed 32 byte (base64) de `LocalDevBackend` sinh khoa XAC DINH thay vi ngau
# nhien. CHI co nghia trong sandbox/CI: no chi duoc doc SAU khi `_assert_localdev_allowed` cho qua,
# nen o production ca LocalDevBackend lan seed deu bi chan boi CUNG mot guard.
#
# Vi sao can: kich ban E2E chay signer nhu MOT TIEN TRINH RIENG that. Khoa cua `LocalDevBackend`
# sinh trong RAM cua tien trinh do, nen ben ngoai KHONG biet duoc public key — trong khi
# `m4_stage0p_record_transcript_signature` (migration 044) doi hang registry public key phai co SAN
# TRUOC khi ghi chu ky. Voi KMS that, buoc do la "doc public key tu API cua KMS roi cong bo vao
# registry"; sandbox khong co KMS nen seed dong dung vai tro ay — de harness BIET TRUOC public key
# ma provision registry, KHONG phai de ky thay signer (moi chu ky trong E2E deu do tien trinh
# signer that tao ra).
_ENV_LOCALDEV_SEED = "M4_LOCALDEV_SIGNING_SEED_B64"
# Gia tri `app_env` bi coi la production — LocalDevBackend bi tu choi ke ca khi 2 bien tren dung.
_PRODUCTION_APP_ENVS = frozenset({"production", "prod", "staging"})


class SigningBackendError(Exception):
    """Goc cua moi loi backend. Caller chi can bat class nay de fail-closed.

    `MA` la MA LOI AN TOAN — thu DUY NHAT duoc phep di ra khoi tien trinh signer (F-H2-KMS-02).
    Thong diep chi tiet cua nha cung cap KHONG BAO GIO duoc chuyen tiep: contract nay trung lap
    nha cung cap, nen khong the lay hanh vi cua MOT provider (vd "Vault khong echo input") lam
    bao dam cho MOI provider/proxy/cau hinh sai trong tuong lai. Chi tiet chan doan thuoc ve kenh
    audit cua chinh KMS, khong phai payload cua giao thuc collector.
    """

    MA = "backend_error"


class SigningBackendUnavailable(SigningBackendError):
    """Backend khong tra loi duoc (timeout, mat mang, KMS down). PHAI dan den KHONG ghi sample."""

    MA = "backend_unavailable"


class SigningBackendDenied(SigningBackendError):
    """Backend tu choi thao tac (policy/quyen). Vd: co export private key -> phai bi tu choi."""

    MA = "backend_denied"


class SigningBackendKeyUnusable(SigningBackendError):
    """Khoa/phien ban ton tai nhung KHONG dung ky duoc (bi vo hieu, het han, sai muc dich).

    Tach rieng khoi `Denied` vi huong xu ly khac han: `Denied` la van de QUYEN (sua policy/token),
    con day la van de VONG DOI KHOA (cong bo phien ban moi, doi key_version). Nguoi van hanh doc
    ma loi phai biet ngay minh can lam gi ma khong can doc text cua provider.
    """

    MA = "backend_key_disabled"


class SigningBackendMisconfigured(SigningBackendError):
    """Cau hinh sai — vd co dung LocalDevBackend o production. Fail o startup, khong fail giua chung."""

    MA = "backend_misconfigured"


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


def assert_khong_phai_production(app_env: str, ten_backend: str) -> None:
    """Guard DUNG CHUNG cho moi backend CHI-DANH-CHO-SANDBOX (F-H2-KMS-01).

    Truoc correction nay, chi `LocalDevBackend` co guard production, con transport Vault thi khong:
    mot deployment cau hinh TUONG MINH `kms + vault` van chay duoc o production/staging, trai voi
    PO delivery path (Vault/VPS la sandbox-only). "Khong co mac dinh" khong ngan duoc cau hinh sai
    tuong minh — nen ranh buoc phai nam trong CODE.

    Dinh nghia "production" nam DUY NHAT o `_PRODUCTION_APP_ENVS`, de them mot backend sandbox moi
    khong the vo tinh dung mot danh sach khac.
    """
    if app_env.strip().lower() in _PRODUCTION_APP_ENVS:
        raise SigningBackendMisconfigured(
            f"{ten_backend} bi tu choi: app_env={app_env!r} la moi truong production. "
            "Backend nay chi duoc dung o sandbox/CI.")


def _assert_localdev_allowed(app_env: str) -> None:
    """Guard fail-closed: LocalDevBackend chi song duoc trong sandbox/CI.

    PO decision record §2 ghi ro 'dev-mode bi cam cho production'. Guard nay lam dieu do thanh
    rang buoc cua CODE, khong phai cua tai lieu — vi tai lieu khong ngan duoc mot lan deploy nham.
    """
    if os.environ.get(_ENV_ALLOW_LOCALDEV) != "1":
        raise SigningBackendMisconfigured(
            f"LocalDevBackend bi tu choi: thieu {_ENV_ALLOW_LOCALDEV}=1 (khoa nam trong RAM, "
            "chi duoc dung o sandbox/CI)")
    # PO decision record §2: dev-mode bi cam cho production. Dung CHUNG guard voi cac backend
    # sandbox khac (vd transport Vault) de chi co MOT dinh nghia ve "production".
    assert_khong_phai_production(app_env, "LocalDevBackend")


class LocalDevBackend:
    """Ed25519 sinh TRONG RAM — sandbox/CI only.

    Ho tro `rotate()` de test duoc dieu CA yeu cau: 'transcript truoc rotation con verify duoc'.
    Public key cua MOI phien ban deu duoc giu lai; private key cua phien ban cu bi bo di ngay khi
    xoay (khong con ky duoc bang khoa cu — dung ngu nghia thu hoi).

    Neu `M4_LOCALDEV_SIGNING_SEED_B64` duoc dat (chi kha thi trong sandbox — xem hang so do), khoa
    duoc DAN XUAT xac dinh tu seed thay vi sinh ngau nhien, de tien trinh khac biet truoc public
    key ma provision registry. Khong dat -> hanh vi cu, khong doi.
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
        # Doc SAU guard o tren — xem `_ENV_LOCALDEV_SEED`. `None` = giu nguyen hanh vi cu
        # (sinh ngau nhien trong RAM), la mac dinh cua moi caller hien co.
        self._seed = self._doc_seed_sandbox()
        self.rotate()

    @staticmethod
    def _doc_seed_sandbox() -> bytes | None:
        """Doc seed sandbox tuy chon. Thieu -> None (ngau nhien nhu cu); co ma SAI -> raise.

        Sai dinh dang bi coi la CAU HINH SAI chu khong am tham quay ve ngau nhien: mot harness
        tuong seed cua minh dang duoc dung, trong khi thuc te signer sinh khoa khac, se lam
        registry provision nham public key va sinh ra that bai KHO HIEU o tan buoc verify.
        """
        raw = os.environ.get(_ENV_LOCALDEV_SEED)
        if not raw:
            return None
        try:
            seed = base64.b64decode(raw, validate=True)
        except Exception:  # noqa: BLE001 — khong dua gia tri seed vao thong diep loi
            raise SigningBackendMisconfigured(
                f"{_ENV_LOCALDEV_SEED} khong phai base64 hop le") from None
        if len(seed) != 32:
            raise SigningBackendMisconfigured(
                f"{_ENV_LOCALDEV_SEED} phai la 32 byte sau khi giai base64, dang la {len(seed)}")
        return seed

    def rotate(self) -> str:
        """Sinh phien ban khoa moi, tra ve `key_version` moi. Public key cu VAN tra cuu duoc."""
        self._version_counter += 1
        self._key_version = f"localdev:v{self._version_counter}"
        if self._seed is None:
            self._private = Ed25519PrivateKey.generate()
        else:
            # Dan xuat theo TUNG phien ban: hai phien ban khac nhau van la hai khoa doc lap, nen
            # kich ban rotation/thu hoi trong sandbox giu nguyen y nghia. Domain tag de seed nay
            # khong the trung voi bat ky dan xuat nao khac dung cung nguon.
            material = hashlib.sha256(
                self._seed + b"|m4-h2a2-localdev|" + self._key_version.encode("ascii")).digest()
            self._private = Ed25519PrivateKey.from_private_bytes(material)
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

    CHI HAI THAO TAC: ky, va doc public key. **Khong co** thao tac export/wrap/backup private
    material, va do la ket luan cua CA F-H2A-01.

    Ban dau Dev co dat `export_private_key()` o day, voi lap luan "de test NEGATIVE goi duoc va
    chung minh no bi tu choi". CA bac bo dung: dat no vao interface bien export thanh mot
    **capability hop le** cho MOI implementation tuong lai — chi can mot adapter viet sai la
    private key co duong di vao application, bat ke fake transport hom nay tu choi the nao.

    Nguyen tac thay the: *khong the goi thu khong ton tai*. Bang chung "application khong export
    duoc" gio nam o HAI cho, ca hai deu KHONG cho signer mot duong export:
      1. Kiem noi suy: signer va transport khong co phuong thuc nao mang nghia export
         (`test_khong_mot_doi_tuong_nao_signer_cham_toi_co_capability_export`).
      2. Chinh sach o PHIA PROVIDER: khoa duoc tao voi `exportable=false` /
         `allow_plaintext_backup=false`, va provider tu choi export ngay ca voi admin. Phep thu do
         chay qua mot fixture ADMIN cua provider, TACH khoi API ma signer nhin thay.
    """

    def sign(self, key_id: str, key_version: str, message: bytes) -> bytes: ...

    def public_key(self, key_id: str, key_version: str) -> bytes: ...


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
