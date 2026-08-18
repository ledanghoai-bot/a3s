"""I-B M4 H2-B — nguon bearer token cho Google Cloud KMS qua Workload Identity Federation.

AUTHORITY: `CA-Docs/PHASE1B-M4-H2B-WIF-X509-TRUST-SOURCE-PO-DECISION-VI.md` (APPROVED
2026-08-18T11:10:00Z) — PO chon WIF voi **X.509 client certificate**. Module nay khong tu dat ra
quyet dinh nao; moi rang buoc duoi day deu truy nguoc duoc ve van ban do.

VI SAO CAN MOT LOP RIENG (F-H2B-01B)
Ban truoc goi `load_credentials_from_file()` + `refresh()` o MOI LAN KY. Signer co concurrency va
fenced deadline, nen cach do sinh ra nhieu vong STS/impersonation DONG THOI: tang do tre, ton quota,
va nhieu luong cung refresh mot credential. Lop nay:
  * NAP credential dung MOT LAN;
  * CACHE token theo `expiry`, chi refresh khi THIEU hoac GAN HET HAN;
  * refresh duoi mot `Lock`, va kiem lai sau khi gianh duoc lock (double-check) de N luong dong
    thoi chi tao dung MOT vong refresh.

KHONG BAO GIO LOG/NEM RA: token, subject-token, duong dan credential, noi dung chung chi. Chi ma loi
an toan (`SigningBackendError.MA`) duoc di ra ngoai — F-H2-KMS-02.

KHONG CO CREDENTIAL NAO TRONG REPOSITORY. Module chi doc mot duong dan do van hanh truyen vao; file
do ton tai TRONG cua so ceremony va bi xoa o buoc cleanup (PO decision, muc "Cleanup va dormant
invariant").
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import threading
from collections.abc import Callable
from typing import Any

from app.services.pii.signing_backend import (
    SigningBackendDenied,
    SigningBackendMisconfigured,
    SigningBackendUnavailable,
)

# Refresh SOM hon han nay: mot token het han giua chung fenced unit se lam ca unit that bai, trong
# khi refresh som chi ton mot vong goi. 5 phut du rong cho do lech dong ho va do tre mang.
_LE_AN_TOAN = _dt.timedelta(minutes=5)


def _lop_ngoai_le(exc: BaseException):
    """Phan loai ngoai le cua google-auth thanh ma loi an toan.

    Dung `isinstance` voi lop that (import muon) chu khong doc chuoi thong diep: `TransportError`
    la van de HA TANG (thu lai co the giup), con `RefreshError` la van de QUYEN/CAU HINH (thu lai
    khong giup). Nham hai thu nay se lam nguoi van hanh di sai huong.
    """
    try:
        from google.auth import exceptions as ga_exc  # type: ignore[import-not-found]
    except ImportError:
        return SigningBackendDenied
    if isinstance(exc, ga_exc.TransportError):
        return SigningBackendUnavailable
    if isinstance(exc, ga_exc.RefreshError):
        return SigningBackendDenied
    if isinstance(exc, ga_exc.DefaultCredentialsError):
        return SigningBackendMisconfigured
    return SigningBackendDenied


def _nap_mac_dinh(duong_dan: str) -> Any:
    """Nap external-account credentials (X.509 identity pool) — KHONG cham mang, KHONG doc chung chi.

    VI SAO KHONG DUNG `load_credentials_from_file` (do duoc bang thuc nghiem):
    ham do goi `get_project_id()` NGAY khi nap, va thao tac do keo theo mot vong refresh that ->
    doc file chung chi va goi STS. Nhu vay "nap" se cham mang ngoai `_lam_moi()`, pha vo dung thiet
    ke ma correction truoc vua dung (nap mot lan, refresh duoi lock). Ta khong can `project_id` cho
    viec gi ca.

    `identity_pool.Credentials.from_info` chi PARSE cau hinh. Moi I/O xay ra o `refresh()`.
    """
    try:
        from google.auth import identity_pool  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SigningBackendMisconfigured(
            f"thieu thu vien google-auth cho luong external-account: {type(exc).__name__}"
        ) from None

    try:
        thong_tin = json.loads(pathlib.Path(duong_dan).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SigningBackendMisconfigured(
            "khong tim thay file cau hinh credential WIF") from None
    except (OSError, ValueError):
        raise SigningBackendMisconfigured(
            "file cau hinh credential WIF khong doc/parse duoc") from None

    if thong_tin.get("type") != "external_account":
        raise SigningBackendMisconfigured(
            f"cau hinh credential phai la external_account, nhan {thong_tin.get('type')!r}")
    # PO decision (WIF-X509-TRUST-SOURCE): nguon danh tinh la CHUNG CHI X.509. Chan som mot cau hinh
    # dung loai khac (file/url/aws...) — no se chay duoc nhung khong dung mo hinh da duoc duyet.
    nguon = thong_tin.get("credential_source") or {}
    if "certificate" not in nguon:
        raise SigningBackendMisconfigured(
            "credential_source phai la 'certificate' (X.509) theo PO decision WIF-X509-TRUST-SOURCE")

    return identity_pool.Credentials.from_info(
        thong_tin, scopes=["https://www.googleapis.com/auth/cloud-platform"])


def _yeu_cau_mac_dinh() -> Any:
    from google.auth.transport.requests import Request  # type: ignore[import-not-found]

    return Request()


class GoogleWifTokenProvider:
    """Cung cap bearer token; nap mot lan, cache theo expiry, refresh thread-safe.

    `nap`/`tao_yeu_cau` duoc tiem vao de test chay OFFLINE hoan toan — khong can google-auth,
    khong cham mang, va van di qua DUNG logic cache/refresh cua production.
    """

    def __init__(self, duong_dan_config: str, *,
                 nap: Callable[[str], Any] | None = None,
                 tao_yeu_cau: Callable[[], Any] | None = None,
                 le_an_toan: _dt.timedelta = _LE_AN_TOAN) -> None:
        if not duong_dan_config:
            raise SigningBackendMisconfigured(
                "chua cau hinh nguon credential WIF cho Google KMS")
        self._duong_dan = duong_dan_config
        self._nap = nap or _nap_mac_dinh
        self._tao_yeu_cau = tao_yeu_cau or _yeu_cau_mac_dinh
        self._le = le_an_toan
        self._creds: Any | None = None
        self._khoa = threading.Lock()
        # Chi de test/van hanh quan sat: dem so lan THAT SU goi refresh.
        self.so_lan_refresh = 0

    # -- noi bo -------------------------------------------------------------
    def _con_dung_duoc(self, creds: Any) -> bool:
        token = getattr(creds, "token", None)
        if not token:
            return False
        han = getattr(creds, "expiry", None)
        if han is None:
            # Khong biet han thi tin `valid` cua thu vien; neu ca hai deu khong co -> coi la het han
            # (fail-closed: tha refresh thua con hon ky bang mot token da chet).
            return bool(getattr(creds, "valid", False))
        # `expiry` cua google-auth la naive UTC; van so sanh dung ca khi thu vien doi sang
        # timezone-aware. Khong dung `utcnow()` (da deprecated tu Python 3.12).
        bay_gio = _dt.datetime.now(_dt.timezone.utc)
        if han.tzinfo is None:
            bay_gio = bay_gio.replace(tzinfo=None)
        return han - self._le > bay_gio

    def _lam_moi(self) -> None:
        creds = self._creds
        if creds is None:
            creds = self._nap(self._duong_dan)
            self._creds = creds
        creds.refresh(self._tao_yeu_cau())
        self.so_lan_refresh += 1

    # -- API ----------------------------------------------------------------
    def __call__(self) -> str:
        # Duong nhanh: token con han thi khong cham lock, khong goi mang.
        creds = self._creds
        if creds is not None and self._con_dung_duoc(creds):
            return creds.token

        with self._khoa:
            # Kiem LAI sau khi gianh duoc lock: N luong cung vao day thi chi luong dau refresh,
            # cac luong sau thay token da moi va di tiep.
            creds = self._creds
            if creds is not None and self._con_dung_duoc(creds):
                return creds.token
            try:
                self._lam_moi()
            except (SigningBackendMisconfigured, SigningBackendDenied,
                    SigningBackendUnavailable):
                raise
            except Exception as exc:  # noqa: BLE001 - khong dua chi tiet credential vao thong diep
                raise _lop_ngoai_le(exc)(
                    f"khong doi duoc credential WIF sang token: {type(exc).__name__}") from None

            creds = self._creds
            token = getattr(creds, "token", None) if creds is not None else None
            if not token:
                raise SigningBackendDenied("luong WIF khong tra ve access token")
            return token
