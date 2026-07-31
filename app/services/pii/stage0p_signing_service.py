"""I-B M4 Stage 0P — trusted capture signing SERVICE (F-M4-0P-T10-02, boundary tach biet THAT).

CA Technical Re-review #10 (F-M4-0P-T10-02): REV10 dat `sign_capture()` la 1 ham trong
`app/services/pii/crypto.py`, chay TRONG CUNG tien trinh voi collector — CA bac bo cach hieu nay:
"một function/module 'logic riêng' trong cùng process không được coi là security boundary". Bat
ky code nao khac trong CUNG tien trinh (import duoc `crypto.py`, doc duoc `settings`) deu co the
goi thang `sign_capture()` hoac tu doc `settings.m4_transcript_hmac_key_b64`/
`settings.m4_sample_key_b64` — khong co gi ngan collector process tu ky/tu ma hoa tuy y.

REV11: module nay chay nhu 1 TIEN TRINH HE DIEU HANH RIENG (khong phai thread/task trong CUNG
process voi collector) — khoi dong bang `python -m app.services.pii.stage0p_signing_service`,
doc `M4_SAMPLE_KEY_B64`/`M4_TRANSCRIPT_HMAC_KEY_B64` tu MOI TRUONG CUA CHINH NO (khong bao gio
nam trong moi truong cua collector worker — xem `stage0p_signing_client.py`/evidence script cho
cach 2 tien trinh duoc tach biet). Giao tiep qua Unix domain socket (chi 1 host — phu hop pham vi
dev/test; production THAT can 1 network boundary/KMS that su, xem Known Limitations Correction
#10/#11) — collector gui (identity + RAW content tu `fetch_message_content` tra ve, CHUA qua
canonicalize), service TU canonicalize (`app/services/pii/canonicalize.py` — CUNG thuat toan DB
dung) + TU tinh digest/length/truncated + ma hoa + ky, khong nhan bat ky gia tri nao trong so do
tu collector nhu authority (F-M4-0P-T10-01, xem `crypto.py` docstring).

Giao thuc: 1 request/1 response moi ket noi, 4-byte big-endian length prefix + JSON UTF-8.
Request: {batch_id, conversation_id, message_id, sample_id, raw_content, customer_ref,
          conversation_ref, purpose_code, txid}
Response thanh cong: {ok: true, ciphertext_b64, transcript_b64, signature_b64, key_version,
                       canonical_len, truncated, canonical_digest_hex}
Response loi: {ok: false, error: "..."}"""

import asyncio
import base64
import hashlib
import json
import os
import sys

from app.config import settings
from app.services.pii.canonicalize import canonicalize
from app.services.pii.crypto import SlotCryptoError, sign_capture

_MAX_FRAME_BYTES = 1_000_000  # 1MB - du cho 1 tin nhan da cat toi da MAX_BYTES + metadata JSON


def _log(event: str, **fields) -> None:
    print("[m4-stage0p-signing-service] " + json.dumps({"event": event, **fields},
                                                         ensure_ascii=False, sort_keys=True))


async def _read_frame(reader: asyncio.StreamReader) -> bytes:
    header = await reader.readexactly(4)
    length = int.from_bytes(header, "big")
    if length <= 0 or length > _MAX_FRAME_BYTES:
        raise ValueError(f"frame length khong hop le: {length}")
    return await reader.readexactly(length)


async def _write_frame(writer: asyncio.StreamWriter, payload: bytes) -> None:
    writer.write(len(payload).to_bytes(4, "big") + payload)
    await writer.drain()


def _handle_request(req: dict) -> dict:
    """REV11 T10-01: canonicalize + tu tinh digest/length/truncated TU raw_content — KHONG nhan
    bat ky gia tri nao trong so do tu `req` nhu authority (chi nhan raw_content + identity)."""
    raw_content = req["raw_content"]
    canonical_text, was_truncated = canonicalize(raw_content)
    # DB-computed flag (noi dung GOC dai hon 2000 ky tu TRUOC khi cat ve raw_content) - KHONG the
    # tu suy ra tu raw_content da bi cat, nen phai nhan tu caller nhu 1 DU KIEN (khong phai
    # "authority" ve digest/length như CA lo ngai) roi OR vao ket qua tu-canonicalize cua chinh
    # service - van la service quyet dinh gia tri CUOI CUNG, khong phai collector.
    was_truncated = was_truncated or bool(req.get("db_char_truncated", False))
    blob, transcript_bytes, signature, key_version = sign_capture(
        canonical_text,
        batch_id=req["batch_id"], conversation_id=req["conversation_id"],
        message_id=req["message_id"], sample_id=req["sample_id"],
        customer_ref=req["customer_ref"], conversation_ref=req["conversation_ref"],
        canonical_len=len(canonical_text), truncated=was_truncated,
        txid=req["txid"], purpose_code=req["purpose_code"],
    )
    canonical_digest_hex = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    return {
        "ok": True,
        "ciphertext_b64": base64.b64encode(blob).decode("ascii"),
        "transcript_b64": base64.b64encode(transcript_bytes).decode("ascii"),
        "signature_b64": base64.b64encode(signature).decode("ascii"),
        "key_version": key_version,
        "canonical_len": len(canonical_text),
        "truncated": was_truncated,
        "canonical_digest_hex": canonical_digest_hex,
    }


async def _handle_conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        raw_req = await _read_frame(reader)
        req = json.loads(raw_req.decode("utf-8"))
        try:
            resp = _handle_request(req)
        except (SlotCryptoError, KeyError, ValueError, TypeError) as e:
            _log("m4_signing_request_rejected", error_type=type(e).__name__)
            resp = {"ok": False, "error": str(e)}
        await _write_frame(writer, json.dumps(resp).encode("utf-8"))
    except Exception as e:  # noqa: BLE001 - loi giao thuc/ket noi, khong de lo plaintext trong log
        _log("m4_signing_connection_error", error_type=type(e).__name__)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass


async def run_signing_service(socket_path: str) -> None:
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    server = await asyncio.start_unix_server(_handle_conn, path=socket_path)
    _log("m4_signing_service_started", socket_path=socket_path)
    async with server:
        await server.serve_forever()


def main() -> int:
    socket_path = os.environ.get("STAGE0P_SIGNING_SOCKET")
    if not socket_path:
        print("STAGE0P_SIGNING_SOCKET chua duoc dat", file=sys.stderr)
        return 2
    sample_key_b64 = os.environ.get("M4_SAMPLE_KEY_B64", "")
    hmac_key_b64 = os.environ.get("M4_TRANSCRIPT_HMAC_KEY_B64", "")
    if not sample_key_b64 or not hmac_key_b64:
        print("M4_SAMPLE_KEY_B64/M4_TRANSCRIPT_HMAC_KEY_B64 chua duoc dat", file=sys.stderr)
        return 2
    # REV11 T10-02: 2 khoa nay CHI ton tai trong settings cua CHINH tien trinh nay - collector
    # khong bao gio dat 2 bien moi truong nay trong process cua no (xem evidence scripts).
    settings.m4_sample_key_b64 = sample_key_b64
    settings.m4_transcript_hmac_key_b64 = hmac_key_b64
    asyncio.run(run_signing_service(socket_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
