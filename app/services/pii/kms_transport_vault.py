"""I-B M4 H2 — `KmsTransport` cho HashiCorp Vault Transit (SANDBOX).

VAI TRO CUA MODULE NAY TRONG LO TRINH (PO decision `H2-KMS-DELIVERY-PATH`, 18/8/2026)
PO chot lo trinh HAI giai doan:
  1. BAY GIO — sandbox: hoan thien adapter, test fail-closed, runbook. Vault tren VPS/may dev CHI
     la sandbox, khoa la khoa THU.
  2. TRUOC khi cham du lieu khach — managed cloud KMS ho tro Ed25519, khoa rieng khong roi backend.

Nghia la module nay KHONG phai dich den. No ton tai de:
  * chung minh contract `KmsTransport` chay duoc voi mot backend ky TU XA THAT (HTTP, token,
    timeout, ma loi) — thu ma mot fake transport khong chung minh noi;
  * lam cho ba kich ban fail-closed CA doi (backend chet / khong co quyen / khoa bi vo hieu) tro
    thanh phep thu VAT LY: tat container, doi token, disable khoa.
Sang giai doan 2 chi thay DUNG file nay bang adapter cua provider; contract, DB, verifier va E2E
giu nguyen (directive H2-KMS-SANDBOX-ADAPTER muc 5).

CAM (directive muc Cam): KHONG duoc dat backend nay lam mac dinh production, va KHONG duoc dung
lam duong lui khi managed KMS loi. Vi vay module nay khong tu dang ky o dau ca — no chi duoc dung
khi `M4_KMS_TRANSPORT=vault` duoc dat TUONG MINH (xem `kms_transport.py`).

VI SAO CHI CO `sign` VA `public_key`
Do la toan bo `KmsTransport` (CA F-H2A-01). Khong co export/backup/wrap: "khong the goi thu khong
ton tai". Vault con chan o lop thu hai — khoa tao voi `exportable=false` nen NGAY CA root token
cung khong export duoc (do duoc trong evidence V0 muc 5d).

KHONG BAO GIO LOG: token, noi dung duoc ky, chu ky. Moi nhanh loi chi mang ten class/ma trang thai.
"""
from __future__ import annotations

import base64

import httpx

from app.services.pii.signing_backend import (
    SigningBackendDenied,
    SigningBackendKeyUnusable,
    SigningBackendUnavailable,
    assert_khong_phai_production,
)

# Vault tra chu ky dang "vault:v<n>:<base64>" — tien to nay la mot phan giao thuc, khong phai rac.
_SIG_PREFIX = "vault"
_DEFAULT_TIMEOUT_SECONDS = 5.0


# Dau hieu RIENG CUA VAULT dung de PHAN LOAI trong noi bo adapter. Chung KHONG BAO GIO roi khoi
# file nay: thu duy nhat di ra ngoai la mot lop ngoai le mang MA LOI AN TOAN.
#
# Vi sao phai doc text: Vault tra HTTP 500 cho ca truong hop CAU HINH (ky bang phien ban khoa da bi
# vo hieu) lan truong hop ha tang. Neu khong phan loai, nguoi van hanh se di sua HA TANG trong khi
# nguyen nhan nam o VONG DOI KHOA. Viec doc text la kien thuc RIENG cua adapter — dung cho mot
# adapter phai lam — va no duoc gioi han trong dung mot ham.
_DAU_HIEU_KHOA_KHONG_DUNG_DUOC = (
    "minimum encryption key version",
    "key version disabled",
    "is disabled",
)


def _phan_loai_loi(resp) -> type[SigningBackendUnavailable] | type[SigningBackendDenied] | type[SigningBackendKeyUnusable]:
    """Chon LOP ngoai le tu phan hoi loi cua Vault. KHONG tra ve text nao.

    Quy tac:
      * 403/404 -> `Denied` (quyen/khong ton tai);
      * 400 -> `Denied`, tru khi noi dung cho thay khoa khong dung duoc;
      * 5xx -> `Unavailable`, tru khi noi dung cho thay khoa khong dung duoc -> `KeyUnusable`.
    """
    try:
        loi = (resp.json() or {}).get("errors") or []
        gop = " ".join(str(x) for x in loi).lower()
    except Exception:  # noqa: BLE001 - body khong phai JSON thi khong phan loai sau duoc
        gop = ""
    if any(d in gop for d in _DAU_HIEU_KHOA_KHONG_DUNG_DUOC):
        return SigningBackendKeyUnusable
    if resp.status_code in (400, 403, 404):
        return SigningBackendDenied
    return SigningBackendUnavailable


class VaultTransitTransport:
    """Goi Transit qua HTTP. Dong bo (khop protocol `KmsTransport`), caller tu day sang thread.

    `timeout` mac dinh ngan: signer nam trong fenced unit co deadline, mot backend treo phai thanh
    "khong ky duoc" NHANH de fenced unit that bai va KHONG commit sample — cho lau khong lam ket
    qua tot hon, chi giu lock DB lau hon.
    """

    def __init__(self, *, base_url: str, token: str, app_env: str,
                 timeout: float = _DEFAULT_TIMEOUT_SECONDS,
                 verify: bool | str = True, namespace: str | None = None) -> None:
        if not base_url:
            raise SigningBackendDenied("thieu dia chi Vault")
        if not token:
            raise SigningBackendDenied("thieu token Vault")
        # F-H2-KMS-01: Vault la SANDBOX-ONLY theo PO delivery path. Guard dat trong ham khoi tao —
        # diem khong the bo qua — nen khong the co duong nao tao ra transport nay o production, ke
        # ca khi ai do cau hinh tuong minh `M4_KMS_TRANSPORT=vault`. Nem TRUOC moi request HTTP.
        assert_khong_phai_production(app_env, "VaultTransitTransport")
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._verify = verify
        self._headers = {"X-Vault-Token": token}
        if namespace:
            self._headers["X-Vault-Namespace"] = namespace

    def _goi(self, method: str, duong_dan: str, payload: dict | None = None) -> dict:
        """Tra JSON body. Moi loi deu duoc nang thanh loi cua signing backend, KHONG ro ri chi tiet.

        Phan loai co y:
          * 400/403/404 -> `SigningBackendDenied`: backend TRA LOI va tu choi (sai quyen, khoa
            khong ton tai/bi vo hieu). Day la cau tra loi dut khoat, thu lai khong giup gi.
          * moi thu khac (timeout, mat mang, 5xx, JSON hong) -> `SigningBackendUnavailable`.
        Ca hai deu dan den KHONG ghi sample; phan biet chi de nguoi van hanh doc log biet nen sua
        cau hinh hay sua ha tang.
        """
        url = f"{self._base}/v1/{duong_dan}"
        try:
            with httpx.Client(timeout=self._timeout, verify=self._verify) as client:
                resp = client.request(method, url, headers=self._headers, json=payload)
        except Exception as exc:  # noqa: BLE001 - khong dua URL/token vao thong diep
            raise SigningBackendUnavailable(
                f"khong goi duoc Vault: {type(exc).__name__}") from None
        if resp.status_code >= 400:
            lop = _phan_loai_loi(resp)
            # Thong diep TINH, do chinh ta viet: khong co manh nao cua phan hoi provider di kem.
            raise lop(f"backend tu choi hoac khong dung duoc (HTTP {resp.status_code})")
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            raise SigningBackendUnavailable("Vault tra ve body khong phai JSON") from None

    def sign(self, key_id: str, key_version: str, message: bytes) -> bytes:
        payload = {"input": base64.b64encode(message).decode("ascii")}
        # Ghim DUNG phien ban khoa: neu khong ghim, Vault ky bang phien ban MOI NHAT, va sau mot lan
        # rotate thi transcript se mang key_version khac voi thuc te da ky -> verifier bao sai o tan
        # cuoi duong, xa noi gay loi.
        try:
            payload["key_version"] = int(key_version)
        except (TypeError, ValueError):
            raise SigningBackendDenied(
                f"key_version cua Vault phai la so nguyen, nhan {key_version!r}") from None

        data = self._goi("POST", f"transit/sign/{key_id}", payload).get("data") or {}
        raw = data.get("signature")
        if not isinstance(raw, str):
            raise SigningBackendUnavailable("Vault khong tra ve truong signature")

        phan = raw.split(":")
        if len(phan) != 3 or phan[0] != _SIG_PREFIX:
            raise SigningBackendUnavailable("dinh dang chu ky cua Vault khong nhu mong doi")
        # Doi chieu phien ban TRA VE voi phien ban DA YEU CAU. Neu backend am tham ky bang phien
        # ban khac, ta phai hong ngay tai day chu khong ghi mot hang chu ky khai sai key_version.
        if phan[1] != f"v{payload['key_version']}":
            raise SigningBackendDenied(
                f"Vault ky bang phien ban {phan[1]} nhung da yeu cau v{payload['key_version']}")
        try:
            return base64.b64decode(phan[2], validate=True)
        except Exception:  # noqa: BLE001
            raise SigningBackendUnavailable("chu ky Vault khong phai base64 hop le") from None

    def public_key(self, key_id: str, key_version: str) -> bytes:
        data = self._goi("GET", f"transit/keys/{key_id}").get("data") or {}
        keys = data.get("keys") or {}
        muc = keys.get(str(key_version))
        if not isinstance(muc, dict) or not muc.get("public_key"):
            raise SigningBackendDenied(
                f"khong co public key cho phien ban {key_version!r} cua khoa {key_id!r}")
        try:
            return base64.b64decode(muc["public_key"], validate=True)
        except Exception:  # noqa: BLE001
            raise SigningBackendUnavailable(
                "public key cua Vault khong phai base64 hop le") from None

    def latest_key_version(self, key_id: str) -> str:
        """NGOAI protocol `KmsTransport` — chi dung cho buoc VAN HANH cong bo public key.

        Signer KHONG duoc goi ham nay: no phai ky bang dung phien ban da cau hinh, khong phai
        "phien ban moi nhat tai thoi diem chay". Neu signer tu bam theo phien ban moi nhat thi mot
        lan rotate se lam no am tham doi khoa giua chung, trong khi public key moi CHUA duoc cong
        bo vao registry -> ham 044 tu choi ghi, va ca fenced unit that bai.
        """
        data = self._goi("GET", f"transit/keys/{key_id}").get("data") or {}
        ver = data.get("latest_version")
        if not isinstance(ver, int):
            raise SigningBackendUnavailable("Vault khong tra ve latest_version")
        return str(ver)
