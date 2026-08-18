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

from app.services.pii.google_credentials import GoogleWifTokenProvider
from app.services.pii.signing_backend import (
    KmsTransport,
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
    """Nguon bearer token cho Google KMS — Workload Identity Federation voi X.509 client cert.

    AUTHORITY: `CA-Docs/PHASE1B-M4-H2B-WIF-X509-TRUST-SOURCE-PO-DECISION-VI.md` (APPROVED
    2026-08-18T11:10:00Z).

    F-H2B-01: ban dau doc thang `M4_GOOGLE_ACCESS_TOKEN` — do la TIEM TOKEN, khong phai WIF, va da
    bi go han. Gio duong duy nhat la mot file cau hinh external-account do van hanh mount vao
    TRONG cua so ceremony; ban than file do khong phai bi mat (no chi TRO toi nguon subject-token),
    con chung chi/khoa rieng thi song trong tmpfs va bi xoa o buoc cleanup.

    Doi tuong tra ve duoc TAI SU DUNG (nap mot lan, cache token) — xem `GoogleWifTokenProvider`.
    """
    return GoogleWifTokenProvider(os.environ.get(_ENV_GOOGLE_CRED_CONFIG, "").strip())


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
