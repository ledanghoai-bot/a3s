"""I-B M4 Stage 0P — client mong cho trusted capture signing service (F-M4-0P-T10-02).

Collector (`stage0p_sampling.py`) goi `request_signature()` thay vi import
`app.services.pii.crypto`/`app.config.settings` truc tiep cho phan ky/ma hoa — module nay KHONG
doc `m4_sample_key_b64`/`m4_transcript_hmac_key_b64` (2 khoa CHI ton tai trong tien trinh
`stage0p_signing_service.py`, xem module do), CHI gui identity + raw content qua Unix domain
socket roi nhan lai ket qua da ky."""

import asyncio
import base64
import json
from dataclasses import dataclass

_MAX_FRAME_BYTES = 1_000_000


class SigningServiceError(Exception):
    """Signing service tu choi (canonicalize/encrypt/sign that bai) hoac loi giao thuc/ket noi."""


class SigningRateLimitedError(SigningServiceError):
    """F-A12-01: signing service tu choi vi VUOT NGAN SACH ADMISSION (fixed-window), KHONG phai
    loi noi dung/chu ky/ha tang.

    Tach rieng khoi `SigningServiceError` vi cach xu ly khac han: day la tin hieu "cham lai roi thu
    lai", co `retry_after_seconds` XAC DINH tu server — caller nen `sleep` dung khoang do roi thu
    lai chinh candidate do, thay vi coi la that bai/retry mu.

    Truoc correction nay, server dong ket noi cam khi vuot han nen client chi thay
    `ConnectionResetError` (loi transport mu, khong phan biet duoc voi signer crash) — Amendment 12
    da gap dung 5 lan nhu vay."""

    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"signing service tu choi: rate_limited (thu lai sau {retry_after_seconds:.3f}s)")


@dataclass(frozen=True)
class SigningResult:
    ciphertext: bytes
    transcript: bytes
    # `signature` la the HMAC — sau H2-A no CHI con y nghia "integrity/capability gate cua DB"
    # (`m4_stage0p_record_sample` tu verify). No KHONG con duoc goi la chu ky co quy trach nhiem.
    signature: bytes
    key_version: str
    canonical_len: int
    truncated: bool
    canonical_digest: bytes
    # --- H2-A-2: the BAT DOI XUNG (Ed25519) ---
    # Ky tren DUNG `transcript` o tren, nen hai the luon noi ve cung mot noi dung.
    # Day moi la bang chung co quy trach nhiem: verify bang PUBLIC key, NGOAI DB.
    signature_asym: bytes
    sig_alg: str
    sig_key_id: str
    sig_key_ver: str


async def _read_frame(reader: asyncio.StreamReader) -> bytes:
    header = await reader.readexactly(4)
    length = int.from_bytes(header, "big")
    if length <= 0 or length > _MAX_FRAME_BYTES:
        raise SigningServiceError(f"frame length khong hop le tu signing service: {length}")
    return await reader.readexactly(length)


async def _write_frame(writer: asyncio.StreamWriter, payload: bytes) -> None:
    writer.write(len(payload).to_bytes(4, "big") + payload)
    await writer.drain()


async def request_signature(socket_path: str, *, batch_id, conversation_id: int, message_id: int,
                            sample_id: str, raw_content: str, customer_ref: str,
                            conversation_ref: str, purpose_code: str, txid: int,
                            signing_authorization: str,
                            db_char_truncated: bool = False,
                            timeout: float = 5.0) -> SigningResult:
    """Goi signing service qua Unix domain socket, tra ve `SigningResult` da san sang truyen cho
    `m4_stage0p_record_sample`. Nem `SigningServiceError` neu service tu choi/loi ket noi.

    `db_char_truncated`: co DB-computed tu `fetch_message_content` (True neu noi dung GOC dai hon
    2000 ky tu TRUOC khi bi cat ve `raw_content` — thong tin nay KHONG THE tu suy ra tu chinh
    `raw_content` da bi cat) — service se OR voi ket qua tu-canonicalize cua chinh no de ra
    `truncated` cuoi cung, KHONG phai collector tu tinh gop (giu dung "signer tu derive TOAN BO
    truong", T10-01).

    `signing_authorization`: chuoi opaque DB da ky trong CUNG transaction voi
    `fetch_message_content()` (T12-02, REV13) — collector CHI relay nguyen ven, KHONG tu tao/hieu/
    sua duoc (khong giu khoa verify). Signing service tu xac minh chu ky nay TRUOC KHI dong y ky/
    ma hoa bat ky noi dung nao."""
    req = {
        "batch_id": str(batch_id),
        "conversation_id": conversation_id,
        "message_id": message_id,
        "sample_id": sample_id,
        "raw_content": raw_content,
        "customer_ref": customer_ref,
        "conversation_ref": conversation_ref,
        "purpose_code": purpose_code,
        "txid": txid,
        "signing_authorization": signing_authorization,
        "db_char_truncated": db_char_truncated,
    }
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(path=socket_path), timeout=timeout)
    except (OSError, asyncio.TimeoutError) as e:
        raise SigningServiceError(f"khong ket noi duoc signing service: {e}") from e
    try:
        await asyncio.wait_for(
            _write_frame(writer, json.dumps(req).encode("utf-8")), timeout=timeout)
        raw_resp = await asyncio.wait_for(_read_frame(reader), timeout=timeout)
    except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError) as e:
        # F-A12-01: bao boc MOI loi transport/giao thuc thanh SigningServiceError. Truoc day chi
        # buoc `open_unix_connection` duoc bao boc, nen `ConnectionResetError` luc write/read lot
        # nguyen ven len tren - caller thay 1 exception la, khong ro tu dau (chinh la trieu chung
        # Amendment 12).
        raise SigningServiceError(
            f"loi giao thuc/ket noi voi signing service: {type(e).__name__}: {e}") from e
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
    resp = json.loads(raw_resp.decode("utf-8"))
    if not resp.get("ok"):
        if resp.get("error") == "rate_limited":
            # F-A12-01: tin hieu backoff XAC DINH tu server - khong phai that bai.
            raw_retry = resp.get("retry_after_seconds")
            try:
                retry_after = float(raw_retry)
            except (TypeError, ValueError):
                # Server luon gui truong nay, nhung neu thieu/hong thi lay ca cua so lam can tren
                # AN TOAN (cho lau hon la thu lai qua som roi bi tu choi tiep).
                retry_after = 10.0
            raise SigningRateLimitedError(max(retry_after, 0.001))
        raise SigningServiceError(f"signing service tu choi: {resp.get('error', 'khong ro loi')}")
    return SigningResult(
        ciphertext=base64.b64decode(resp["ciphertext_b64"]),
        transcript=base64.b64decode(resp["transcript_b64"]),
        signature=base64.b64decode(resp["signature_b64"]),
        key_version=resp["key_version"],
        canonical_len=resp["canonical_len"],
        truncated=resp["truncated"],
        canonical_digest=bytes.fromhex(resp["canonical_digest_hex"]),
        # H2-A-2: bon truong nay la BAT BUOC trong response. Dung `resp[...]` (KeyError neu thieu)
        # chu KHONG dung `.get(...)` — mot signer cu khong tra the asym PHAI lam collector hong ngay,
        # khong duoc am tham ghi sample thieu bang chung quy trach nhiem.
        signature_asym=base64.b64decode(resp["signature_asym_b64"]),
        sig_alg=resp["sig_alg"],
        sig_key_id=resp["sig_key_id"],
        sig_key_ver=resp["sig_key_ver"],
    )
