"""I-B M4 H2 — factory TRUNG LAP NHA CUNG CAP cho `KmsTransport`.

Directive `H2-KMS-SANDBOX-ADAPTER-PREPARATION` doi hai thu tuong nhau nhung khac nhau:

  * deliverable 1: contract phai TRUNG LAP nha cung cap;
  * muc Cam: KHONG duoc dat local/Vault backend lam mac dinh production, cung KHONG duoc dung lam
    duong lui khi managed KMS loi.

Module nay la cho hai dieu do gap nhau. No la diem DUY NHAT biet ten cac nha cung cap, va no:
  * KHONG co gia tri mac dinh — thieu `M4_KMS_TRANSPORT` la loi cau hinh, khong phai "tu chon ho";
  * KHONG co fallback — mot provider loi thi hong, khong am tham chuyen sang provider khac;
  * import provider module MUON (ben trong nhanh dieu kien), nen `signing_backend.py` — module loi
    cua tang ky — khong bao gio phu thuoc vao thu vien cua bat ky nha cung cap nao.

Them mot provider (vd cloud KMS o giai doan 2) = them MOT nhanh o day + mot module adapter. Khong
sua signer, khong sua `signing_backend.py`, khong sua DB/verifier.
"""
from __future__ import annotations

import os

from app.services.pii.signing_backend import (
    KmsTransport,
    SigningBackendMisconfigured,
)

_ENV_TRANSPORT = "M4_KMS_TRANSPORT"
_ENV_KEY_ID = "M4_KMS_KEY_ID"
_ENV_KEY_VERSION = "M4_KMS_KEY_VERSION"

# Google Cloud KMS (provider production, PO decision H2B)
_ENV_GOOGLE_ENDPOINT = "M4_GOOGLE_KMS_ENDPOINT"
_ENV_GOOGLE_TOKEN = "M4_GOOGLE_ACCESS_TOKEN"
_GOOGLE_ENDPOINT_MAC_DINH = "https://cloudkms.googleapis.com"

# Vault (sandbox-only, xem docstring kms_transport_vault.py)
_ENV_VAULT_ADDR = "M4_VAULT_ADDR"
_ENV_VAULT_TOKEN = "M4_VAULT_TOKEN"
_ENV_VAULT_NAMESPACE = "M4_VAULT_NAMESPACE"


def _token_provider_google():
    """Tra ve ham lay bearer token cho Google KMS.

    Directive H2-B CAM tao credential/service-account key, va PO decision chot dung Workload
    Identity Federation. Nen o buoc CHUAN BI nay chua the hien thuc duong WIF that: khong co
    credential de kiem thu, va viet mot duong xac thuc khong the chay thu la cach chac chan nhat de
    no sai am tham.

    Hien tai ho tro mot nguon token TUONG MINH (`M4_GOOGLE_ACCESS_TOKEN`) danh cho contract test va
    cho buoc preflight sau nay. Khi PO mo Provisioning Gate, cam adapter WIF vao DUNG cho nay —
    phan con lai cua tang ky khong phai sua mot dong.
    """
    def _lay() -> str:
        token = os.environ.get(_ENV_GOOGLE_TOKEN, "").strip()
        if not token:
            raise SigningBackendMisconfigured(
                f"chua co nguon credential cho Google KMS ({_ENV_GOOGLE_TOKEN} trong). "
                "Duong Workload Identity Federation duoc cam vao o buoc provisioning.")
        return token

    return _lay


def get_kms_transport(app_env: str) -> tuple[KmsTransport, str, str]:
    """Tra (transport, key_id, key_version) theo cau hinh moi truong. Fail-closed moi nhanh.

    `key_id`/`key_version` la BAT BUOC va TUONG MINH: chung di thang vao hang chu ky
    (`m4_stage0p_transcript_signatures`) va la thu verifier dung de tra public key trong registry.
    De backend tu chon "phien ban moi nhat" se tao ra chu ky ma khong ai cong bo public key tuong
    ung — sai lech chi lo ra o tan buoc verify.
    """
    # F-H2-KMS-01: `app_env` la THAM SO BAT BUOC, khong doc tu moi truong o day. Caller (signer)
    # phai truyen `settings.app_env` — cung nguon su that ma phan con lai cua ung dung dung — nen
    # khong the co tinh huong "guard doc mot bien khac voi bien ung dung dang chay".
    ten = os.environ.get(_ENV_TRANSPORT, "").strip().lower()
    key_id = os.environ.get(_ENV_KEY_ID, "").strip()
    key_version = os.environ.get(_ENV_KEY_VERSION, "").strip()
    if not key_id or not key_version:
        raise SigningBackendMisconfigured(
            f"{_ENV_KEY_ID} va {_ENV_KEY_VERSION} deu bat buoc khi dung backend kms")

    if ten == "vault":
        # Import MUON: giu `signing_backend.py` sach khoi thu vien cua nha cung cap.
        from app.services.pii.kms_transport_vault import VaultTransitTransport

        return (
            # Guard production nam trong chinh ham khoi tao cua transport (diem khong the bo qua),
            # va nem TRUOC khi co bat ky request HTTP nao.
            VaultTransitTransport(
                base_url=os.environ.get(_ENV_VAULT_ADDR, ""),
                token=os.environ.get(_ENV_VAULT_TOKEN, ""),
                app_env=app_env,
                namespace=os.environ.get(_ENV_VAULT_NAMESPACE) or None,
            ),
            key_id,
            key_version,
        )

    if ten == "google":
        # Provider PRODUCTION (PO decision H2B). Nhanh RIENG, tuong minh — khong phai fallback cua
        # nhanh vault va cung khong nhan duoc dinh huong tu no.
        from app.services.pii.kms_transport_google import GoogleKmsTransport

        return (
            GoogleKmsTransport(
                key_id=key_id,
                token_provider=_token_provider_google(),
                endpoint=os.environ.get(_ENV_GOOGLE_ENDPOINT) or _GOOGLE_ENDPOINT_MAC_DINH,
            ),
            key_id,
            key_version,
        )

    raise SigningBackendMisconfigured(
        f"{_ENV_TRANSPORT} chua duoc dat hoac khong duoc ho tro: {ten!r}. "
        "Khong co mac dinh va khong co duong lui — moi provider phai duoc chon tuong minh.")
