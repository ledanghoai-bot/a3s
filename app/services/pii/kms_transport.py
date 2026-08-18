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
from collections.abc import Callable

from app.services.pii.signing_backend import (
    KmsTransport,
    SigningBackendDenied,
    SigningBackendMisconfigured,
)

_ENV_TRANSPORT = "M4_KMS_TRANSPORT"
_ENV_KEY_ID = "M4_KMS_KEY_ID"
_ENV_KEY_VERSION = "M4_KMS_KEY_VERSION"

# Google Cloud KMS (provider production, PO decision H2B)
_ENV_GOOGLE_ENDPOINT = "M4_GOOGLE_KMS_ENDPOINT"
# Duong dan file CAU HINH credential external-account (WIF). File nay KHONG phai bi mat: no chi
# TRO toi nguon subject-token. Ban than nguon do (chung chi/OIDC assertion) moi la thu can bao ve.
_ENV_GOOGLE_CRED_CONFIG = "M4_GOOGLE_CREDENTIAL_CONFIG"
_GOOGLE_ENDPOINT_MAC_DINH = "https://cloudkms.googleapis.com"

# Vault (sandbox-only, xem docstring kms_transport_vault.py)
_ENV_VAULT_ADDR = "M4_VAULT_ADDR"
_ENV_VAULT_TOKEN = "M4_VAULT_TOKEN"
_ENV_VAULT_NAMESPACE = "M4_VAULT_NAMESPACE"


def _token_provider_google() -> Callable[[], str]:
    """Nguon bearer token cho Google KMS — BAT BUOC di qua Workload Identity Federation.

    F-H2B-01: ban truoc doc thang `M4_GOOGLE_ACCESS_TOKEN`. CA bac dung: do la TIEM TOKEN, khong
    phai WIF, va no tao ra mot duong van hanh production ma PO chua duyet. Bien do da bi bo han.

    WIF KHONG tu tao danh tinh cho VPS. No doi mot credential co san tu mot external IdP (OIDC/
    SAML/X.509/AWS/Azure...) roi doi qua STS lay short-lived Google token. VPS cua du an la mot VM
    thuong, KHONG co ambient credential nao — nen nguon tin cay do phai duoc CHON truoc, bang mot
    PO decision. Bang so sanh phuong an: docs/M4-H2B-WIF-TRUST-SOURCE-OPTIONS-VI.md.

    Vi chua co quyet dinh do, ham nay CHUA the hien thuc duoc, va no fail-closed thay vi doan:
    thieu cau hinh credential -> `SigningBackendMisconfigured`. Viet mot duong xac thuc khong the
    kiem thu la cach chac chan nhat de no sai am tham.
    """
    duong_dan = os.environ.get(_ENV_GOOGLE_CRED_CONFIG, "").strip()
    if not duong_dan:
        raise SigningBackendMisconfigured(
            f"chua cau hinh nguon credential WIF cho Google KMS ({_ENV_GOOGLE_CRED_CONFIG} trong). "
            "Nguon tin cay (OIDC hay X.509) can PO chot — xem "
            "docs/M4-H2B-WIF-TRUST-SOURCE-OPTIONS-VI.md.")

    def _lay() -> str:
        # Import MUON: `google-auth` chi can khi that su dung Google KMS, va viec them dependency
        # nay thuoc buoc provisioning (CA F-H2B-01 muc 3).
        try:
            from google.auth import (
                load_credentials_from_file,  # type: ignore[import-not-found]
            )
            from google.auth.transport.requests import (
                Request,  # type: ignore[import-not-found]
            )
        except ImportError as exc:
            raise SigningBackendMisconfigured(
                f"thieu thu vien google-auth cho luong external-account: {type(exc).__name__}"
            ) from None
        try:
            creds, _ = load_credentials_from_file(
                duong_dan, scopes=["https://www.googleapis.com/auth/cloud-platform"])
            creds.refresh(Request())
        except Exception as exc:  # noqa: BLE001 - khong dua chi tiet credential vao thong diep
            raise SigningBackendDenied(
                f"khong doi duoc credential WIF sang token: {type(exc).__name__}") from None
        token = getattr(creds, "token", None)
        if not token:
            raise SigningBackendDenied("luong WIF khong tra ve access token")
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
                app_env=app_env,
                endpoint=os.environ.get(_ENV_GOOGLE_ENDPOINT) or _GOOGLE_ENDPOINT_MAC_DINH,
            ),
            key_id,
            key_version,
        )

    raise SigningBackendMisconfigured(
        f"{_ENV_TRANSPORT} chua duoc dat hoac khong duoc ho tro: {ten!r}. "
        "Khong co mac dinh va khong co duong lui — moi provider phai duoc chon tuong minh.")
