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


@dataclass(frozen=True)
class SigningResult:
    ciphertext: bytes
    transcript: bytes
    signature: bytes
    key_version: str
    canonical_len: int
    truncated: bool
    canonical_digest: bytes


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
                            db_char_truncated: bool = False,
                            timeout: float = 5.0) -> SigningResult:
    """Goi signing service qua Unix domain socket, tra ve `SigningResult` da san sang truyen cho
    `m4_stage0p_record_sample`. Nem `SigningServiceError` neu service tu choi/loi ket noi.

    `db_char_truncated`: co DB-computed tu `fetch_message_content` (True neu noi dung GOC dai hon
    2000 ky tu TRUOC khi bi cat ve `raw_content` — thong tin nay KHONG THE tu suy ra tu chinh
    `raw_content` da bi cat) — service se OR voi ket qua tu-canonicalize cua chinh no de ra
    `truncated` cuoi cung, KHONG phai collector tu tinh gop (giu dung "signer tu derive TOAN BO
    truong", T10-01)."""
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
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
    resp = json.loads(raw_resp.decode("utf-8"))
    if not resp.get("ok"):
        raise SigningServiceError(f"signing service tu choi: {resp.get('error', 'khong ro loi')}")
    return SigningResult(
        ciphertext=base64.b64decode(resp["ciphertext_b64"]),
        transcript=base64.b64decode(resp["transcript_b64"]),
        signature=base64.b64decode(resp["signature_b64"]),
        key_version=resp["key_version"],
        canonical_len=resp["canonical_len"],
        truncated=resp["truncated"],
        canonical_digest=bytes.fromhex(resp["canonical_digest_hex"]),
    )
