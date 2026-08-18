"""I-B M4 H2-B — `KmsTransport` cho Google Cloud KMS (provider PRODUCTION).

PO decision `H2B-GOOGLE-CLOUD-KMS`: `ASYMMETRIC_SIGN` + `EC_SIGN_ED25519` + protection level
`SOFTWARE`. Day la provider cho duong PRODUCTION, khac han `kms_transport_vault.py` (sandbox-only,
co guard chan production).

KHONG CO GUARD MOI TRUONG O DAY — va do la CO Y: Google KMS chinh la backend duoc phep chay o
production. Nhung cung vi the moi rang buoc con lai phai chat hon:

  * ky bang DUNG CryptoKeyVersion tuong minh, KHONG BAO GIO dung "latest" (PO decision + directive
    muc 1). Mot lan rotate am tham se lam transcript khai sai key_version, va sai lech do chi lo ra
    o tan buoc verify;
  * doi chieu `name` TRA VE voi resource DA YEU CAU — chan nham khoa/nham phien ban;
  * doi chieu `algorithm` cua public key voi `EC_SIGN_ED25519` — chan nham thuat toan/muc dich.

ED25519 LA PureEdDSA: gui RAW BYTES, KHONG hash truoc
Voi cac thuat toan EC/RSA khac, Google KMS nhan truong `digest`. Voi Ed25519 thi nhan truong
`data` — chinh chuoi byte cua transcript. Gui nham sang `digest` se tao ra chu ky tren mot noi dung
KHAC voi thu ta luu, va verifier ngoai DB se bao sai. Vi vay module nay CHI dat `data`, va co test
khang dinh dieu do.

XAC THUC
Transport nhan mot `token_provider` — ham tra ve bearer token. Cach lay token (Workload Identity
Federation theo PO decision) KHONG duoc hien thuc o day vi directive H2-B CAM tao credential/
service-account key, va khong the kiem thu that neu khong co credential that. Tach ra thanh tham so
giup: (a) test bom token gia, (b) buoc provisioning sau nay cam WIF vao ma khong sua logic ky.

KHONG BAO GIO LOG: token, noi dung duoc ky, chu ky, hay body cua provider. Chi ma loi an toan
(`SigningBackendError.MA`) duoc di ra ngoai — xem F-H2-KMS-02.
"""
from __future__ import annotations

import base64
from collections.abc import Callable

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.services.pii.signing_backend import (
    SigningBackendDenied,
    SigningBackendKeyUnusable,
    SigningBackendUnavailable,
)

_ENDPOINT_MAC_DINH = "https://cloudkms.googleapis.com"
_THUAT_TOAN = "EC_SIGN_ED25519"
_DEFAULT_TIMEOUT_SECONDS = 5.0

# `error.status` cua Google API la mot ENUM on dinh — phan loai theo no chac chan hon nhieu so voi
# doc `message` (bai hoc tu adapter Vault: Vault khong co truong nao tuong duong nen phai match text).
_STATUS_KHOA_KHONG_DUNG_DUOC = frozenset({"FAILED_PRECONDITION"})
_STATUS_TU_CHOI = frozenset({
    "PERMISSION_DENIED", "UNAUTHENTICATED", "INVALID_ARGUMENT", "NOT_FOUND", "OUT_OF_RANGE",
})


def _phan_loai(status_code: int, body: dict | None):
    """Chon LOP ngoai le. KHONG tra ve text nao cua provider (F-H2-KMS-02)."""
    trang_thai = ""
    if isinstance(body, dict):
        loi = body.get("error")
        if isinstance(loi, dict):
            trang_thai = str(loi.get("status") or "")
    if trang_thai in _STATUS_KHOA_KHONG_DUNG_DUOC:
        return SigningBackendKeyUnusable
    if trang_thai in _STATUS_TU_CHOI:
        return SigningBackendDenied
    if status_code in (400, 401, 403, 404):
        return SigningBackendDenied
    return SigningBackendUnavailable


class GoogleKmsTransport:
    """Ky qua Google Cloud KMS REST. Dong bo (khop protocol `KmsTransport`).

    `key_id` la resource path DAY DU cua CryptoKey:
        projects/<project>/locations/<loc>/keyRings/<ring>/cryptoKeys/<key>
    `key_version` la so thu tu phien ban ("1", "2", ...).

    Vi sao dung resource path day du lam `key_id`: gia tri nay di thang vao registry
    (`m4_stage0p_transcript_public_keys`) va vao tung hang chu ky. Dung ten ngan se khien mot chu ky
    khong tu mo ta duoc no thuoc project/keyring nao — nguoi verify sau nay (co the la nguoi khong
    con quyen truy cap he thong) phai doan. Path day du lam bang chung tu dung vung.
    """

    def __init__(self, *, key_id: str, token_provider: Callable[[], str],
                 endpoint: str = _ENDPOINT_MAC_DINH,
                 timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        if not key_id or key_id.count("/") != 7 or not key_id.startswith("projects/"):
            raise SigningBackendDenied(
                "key_id phai la resource path day du cua CryptoKey "
                "(projects/../locations/../keyRings/../cryptoKeys/..)")
        self._key_id = key_id
        self._token_provider = token_provider
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout

    # -- ha tang ------------------------------------------------------------
    def _ten_phien_ban(self, key_version: str) -> str:
        if not str(key_version).isdigit():
            raise SigningBackendDenied(
                f"key_version cua Google KMS phai la so nguyen, nhan {key_version!r}")
        return f"{self._key_id}/cryptoKeyVersions/{key_version}"

    def _goi(self, method: str, duong_dan: str, payload: dict | None = None) -> dict:
        try:
            token = self._token_provider()
        except Exception as exc:  # noqa: BLE001 - khong dua chi tiet credential vao thong diep
            # Federation/credential hong la van de QUYEN, khong phai ha tang: thu lai khong giup.
            raise SigningBackendDenied(
                f"khong lay duoc credential: {type(exc).__name__}") from None
        if not token:
            raise SigningBackendDenied("credential provider tra ve token rong")

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.request(
                    method, f"{self._endpoint}/v1/{duong_dan}",
                    headers={"Authorization": f"Bearer {token}"}, json=payload)
        except Exception as exc:  # noqa: BLE001 - khong dua URL/token vao thong diep
            raise SigningBackendUnavailable(
                f"khong goi duoc Google KMS: {type(exc).__name__}") from None

        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = None
        if resp.status_code >= 400:
            lop = _phan_loai(resp.status_code, body)
            # Thong diep TINH do chinh ta viet — body cua provider khong bao gio di kem.
            raise lop(f"Google KMS tu choi hoac khong dung duoc (HTTP {resp.status_code})")
        if not isinstance(body, dict):
            raise SigningBackendUnavailable("Google KMS tra ve body khong phai JSON")
        return body

    # -- KmsTransport -------------------------------------------------------
    def sign(self, key_id: str, key_version: str, message: bytes) -> bytes:
        if key_id != self._key_id:
            # Chan nham khoa: transport nay duoc cau hinh cho DUNG mot CryptoKey.
            raise SigningBackendDenied("key_id khong khop khoa da cau hinh cho transport nay")
        ten = self._ten_phien_ban(key_version)
        # Ed25519 la PureEdDSA: gui `data` (raw transcript bytes). TUYET DOI khong dung `digest` —
        # lam vay se ky tren mot noi dung khac voi thu duoc luu va verifier se bao sai.
        body = self._goi("POST", f"{ten}:asymmetricSign",
                         {"data": base64.b64encode(message).decode("ascii")})

        # Doi chieu phien ban TRA VE voi phien ban DA YEU CAU: chan truong hop backend/proxy tra ve
        # ket qua cua mot phien ban khac (vd cau hinh "latest" o dau do trong duong goi).
        ten_tra_ve = body.get("name")
        if ten_tra_ve and ten_tra_ve != ten:
            raise SigningBackendDenied(
                "Google KMS ky bang phien ban khac voi phien ban da yeu cau")

        chu_ky_b64 = body.get("signature")
        if not isinstance(chu_ky_b64, str):
            raise SigningBackendUnavailable("Google KMS khong tra ve truong signature")
        try:
            return base64.b64decode(chu_ky_b64, validate=True)
        except Exception:  # noqa: BLE001
            raise SigningBackendUnavailable(
                "chu ky cua Google KMS khong phai base64 hop le") from None

    def public_key(self, key_id: str, key_version: str) -> bytes:
        if key_id != self._key_id:
            raise SigningBackendDenied("key_id khong khop khoa da cau hinh cho transport nay")
        ten = self._ten_phien_ban(key_version)
        body = self._goi("GET", f"{ten}/publicKey")

        # Chan nham thuat toan/muc dich: mot khoa RSA/ECDSA van tra ve PEM hop le, nhung chu ky se
        # khong phai Ed25519 va migration 044 se tu choi ghi. Bat o day de hong SOM va ro rang.
        thuat_toan = body.get("algorithm")
        if thuat_toan != _THUAT_TOAN:
            raise SigningBackendDenied(
                f"khoa khong phai {_THUAT_TOAN} (nhan {thuat_toan!r})")

        pem = body.get("pem")
        if not isinstance(pem, str) or not pem:
            raise SigningBackendUnavailable("Google KMS khong tra ve truong pem")
        try:
            khoa = serialization.load_pem_public_key(pem.encode("ascii"))
        except Exception:  # noqa: BLE001 - khong dua noi dung PEM vao thong diep
            raise SigningBackendUnavailable("PEM cua Google KMS khong doc duoc") from None
        if not isinstance(khoa, Ed25519PublicKey):
            raise SigningBackendDenied("PEM khong phai khoa Ed25519")
        # Registry (migration 044) doi DUNG 32 byte raw, khong phai PEM/DER.
        return khoa.public_bytes(encoding=serialization.Encoding.Raw,
                                 format=serialization.PublicFormat.Raw)
