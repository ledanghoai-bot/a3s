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
Response loi: {ok: false, error: "..."}

CA Technical Re-review #11 (F-M4-0P-T10-02 PARTIALLY CLOSED / F-M4-0P-T11-02, P1): REV11 tach dung
process (dong) nhung KHONG tach QUYEN TRUY CAP (`start_unix_server(..., path=socket_path)` khong co
private parent directory/mode, khong chmod socket, khong xac minh peer credential, khong gioi han
frame/concurrency/rate/timeout) — BAT KY tien trinh local nao co quyen mo socket path deu dung
duoc service nhu 1 "encryption/signing oracle". F-M4-0P-T11-03 (P2, "co the dong cung T11-02" theo
CA): signer chua rang buoc request voi authority cua caller.

Sua REV12 — dong ca T11-02 va T11-03 cho pham vi dev/test 1 host (CA xac nhan process separation
hien tai la "nen tang duoc chap nhan"; khong can doi lai co che digest/HMAC neu bo sung dung access
control):
  1. `_validate_socket_directory()`: startup FAIL NGAY neu thu muc cha cua socket path khong ton
     tai, LA symlink, KHONG thuoc so huu cua chinh tien trinh nay (uid), hoac co bit quyen group/
     other (mode & 0o077 != 0) — vd `/tmp` (1777) se bi TU CHOI, buoc caller phai tao 1 thu muc
     RIENG mode 0700 (xem `_stage0p_signing_service_helper.py`). Socket path ban than, neu DA la 1
     symlink co san, cung bi tu choi (chong tan cong "pre-create symlink tai duong dan du kien").
  2. Sau khi bind, `os.chmod(socket_path, 0o600)` — chi owner doc/ghi duoc file socket.
  3. `_peer_uid()` doc UID THAT cua tien trinh dang ket noi qua `SO_PEERCRED` (Linux-specific,
     dung duoc trong container Docker Linux cua du an) — TRUOC KHI doc BAT KY frame nao, so sanh
     voi `allowed_uid` (mac dinh = uid cua CHINH tien trinh signing service — mo hinh dev/test 1
     host, collector va service chay CUNG uid; co the ghi de qua `STAGE0P_SIGNING_ALLOWED_UID` cho
     muc dich test/vi tri trien khai co uid rieng that su). Peer khong khop -> tu choi NGAY, dong
     ket noi, KHONG doc frame nao (T11-02 yeu cau "reject unauthorized peers TRUOC khi doc raw
     content") — day CUNG LA co che T11-03 chon ("signer verify caller identity") thay vi xay 1 he
     thong one-time-token DB-issued rieng (CA cho phep ca 2 huong).
  4. Gioi han tai nguyen server-side: `asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)` gioi han so
     request dong thoi (chong flood/resource-exhaustion); `asyncio.wait_for(...,
     timeout=_REQUEST_TIMEOUT_SECONDS)` boc TOAN BO vong doi 1 ket noi (doc frame + xu ly + ghi
     response) — chan ca frame qua lon (da co `_MAX_FRAME_BYTES` tu REV11) LAN frame "cham" kieu
     slow-loris (ghi tung byte 1, khong bao gio hoan tat).
  5. T11-03 "khong log raw content hoac tra raw content trong error": da dung tu REV11 — moi
     nhanh loi (`SlotCryptoError`/`KeyError`/`ValueError`/`TypeError`/loi giao thuc) chi log
     `error_type` (ten class) hoac 1 thong diep KHONG chua plaintext (xac nhan qua ra soat
     `crypto.py:sign_capture` — cac `SlotCryptoError` chi mo ta ten truong/dieu kien sai, khong
     bao gio noi suy gia tri thuc). Rejected peer/request deu chi log COUNT-worthy field (uid,
     error_type) — khong bao gio raw_content. T11-03 "transcript/response phai one-time/short-
     lived": da duoc DB enforce (T10-04, TTL 60s + one-time capability consumption) — khong can
     them co che o tang signing service."""

import asyncio
import base64
import hashlib
import json
import os
import socket
import stat
import struct
import sys
from functools import partial

from app.config import settings
from app.services.pii.canonicalize import canonicalize
from app.services.pii.crypto import SlotCryptoError, sign_capture

_MAX_FRAME_BYTES = 1_000_000  # 1MB - du cho 1 tin nhan da cat toi da MAX_BYTES + metadata JSON
_SOCKET_FILE_MODE = 0o600
_SOCKET_DIR_FORBIDDEN_MODE_BITS = 0o077  # T11-02: khong duoc co bat ky bit group/other nao
_MAX_CONCURRENT_REQUESTS = 8
_REQUEST_TIMEOUT_SECONDS = 5.0
_PEERCRED_STRUCT = struct.Struct("3i")  # pid, uid, gid (Linux SO_PEERCRED)


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


def _validate_socket_directory(socket_path: str) -> None:
    """T11-02: startup FAIL NGAY neu thu muc cha khong an toan — khong ton tai, la symlink, khong
    thuoc so huu tien trinh nay, hoac co bat ky bit quyen group/other nao (vd `/tmp` mode 1777 se
    bi TU CHOI o day). Socket path ban than, neu DA la 1 symlink co san, cung bi tu choi (chong
    tan cong pre-create-symlink tai duong dan du kien)."""
    directory = os.path.dirname(socket_path) or "."
    if not os.path.isdir(directory):
        raise RuntimeError(f"signing socket directory khong ton tai: {directory}")
    if os.path.islink(directory):
        raise RuntimeError(f"signing socket directory la symlink - tu choi khoi dong: {directory}")
    st = os.stat(directory)
    if st.st_uid != os.getuid():
        raise RuntimeError(
            f"signing socket directory khong thuoc so huu tien trinh nay "
            f"(dir uid={st.st_uid}, process uid={os.getuid()}): {directory}")
    if stat.S_IMODE(st.st_mode) & _SOCKET_DIR_FORBIDDEN_MODE_BITS:
        raise RuntimeError(
            f"signing socket directory qua rong quyen (mode={oct(stat.S_IMODE(st.st_mode))}, "
            f"phai loai bo group/other access): {directory}")
    if os.path.lexists(socket_path) and os.path.islink(socket_path):
        raise RuntimeError(
            f"signing socket path la symlink co san - tu choi (co the la tan cong symlink): "
            f"{socket_path}")


def _peer_uid(writer: asyncio.StreamWriter) -> int | None:
    """T11-02: doc UID THAT cua tien trinh dang ket noi qua `SO_PEERCRED` (Linux). Tra `None` neu
    khong lay duoc (vd platform khong ho tro) — caller PHAI coi `None` la KHONG xac thuc duoc, tu
    choi (fail closed), khong bao gio coi la 'bo qua kiem tra'."""
    sock = writer.get_extra_info("socket")
    if sock is None:
        return None
    try:
        creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _PEERCRED_STRUCT.size)
    except OSError:
        return None
    _pid, uid, _gid = _PEERCRED_STRUCT.unpack(creds)
    return uid


def _allowed_uid() -> int:
    """T11-02: UID duy nhat duoc phep ket noi. Mac dinh = uid cua CHINH tien trinh signing service
    (mo hinh dev/test 1 host — collector va service chay CUNG uid). Co the ghi de qua
    `STAGE0P_SIGNING_ALLOWED_UID` (vd trien khai co uid rieng that su cho collector, hoac test co
    tinh 'unauthorized peer')."""
    override = os.environ.get("STAGE0P_SIGNING_ALLOWED_UID")
    if override is not None:
        return int(override)
    return os.getuid()


async def _handle_conn_authorized(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    raw_req = await _read_frame(reader)
    req = json.loads(raw_req.decode("utf-8"))
    try:
        resp = _handle_request(req)
    except (SlotCryptoError, KeyError, ValueError, TypeError) as e:
        # T11-03: chi log error_type/thong diep KHONG chua plaintext - khong bao gio raw_content.
        _log("m4_signing_request_rejected", error_type=type(e).__name__)
        resp = {"ok": False, "error": str(e)}
    await _write_frame(writer, json.dumps(resp).encode("utf-8"))


async def _handle_conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *,
                       semaphore: asyncio.Semaphore, allowed_uid: int) -> None:
    try:
        peer_uid = _peer_uid(writer)
        if peer_uid != allowed_uid:
            # T11-02: tu choi TRUOC KHI doc bat ky frame nao - khong bao gio cham toi noi dung
            # cua 1 peer chua xac thuc. Chi log uid (count-worthy), khong log raw content (T11-03).
            _log("m4_signing_peer_rejected", peer_uid=peer_uid)
            return
        async with semaphore:  # T11-02: gioi han so request dong thoi (chong flood)
            try:
                await asyncio.wait_for(_handle_conn_authorized(reader, writer),
                                       timeout=_REQUEST_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                # T11-02: chan ca frame qua lon (da co _MAX_FRAME_BYTES) LAN frame "cham" kieu
                # slow-loris (khong bao gio hoan tat trong _REQUEST_TIMEOUT_SECONDS).
                _log("m4_signing_request_timeout")
    except Exception as e:  # noqa: BLE001 - loi giao thuc/ket noi, khong de lo plaintext trong log
        _log("m4_signing_connection_error", error_type=type(e).__name__)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass


async def run_signing_service(socket_path: str, *, allowed_uid: int | None = None) -> None:
    _validate_socket_directory(socket_path)
    if os.path.lexists(socket_path):
        os.unlink(socket_path)
    resolved_allowed_uid = _allowed_uid() if allowed_uid is None else allowed_uid
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)
    handler = partial(_handle_conn, semaphore=semaphore, allowed_uid=resolved_allowed_uid)
    server = await asyncio.start_unix_server(handler, path=socket_path)
    os.chmod(socket_path, _SOCKET_FILE_MODE)  # T11-02: chi owner doc/ghi duoc file socket
    _log("m4_signing_service_started", socket_path=socket_path, allowed_uid=resolved_allowed_uid)
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
    try:
        asyncio.run(run_signing_service(socket_path, allowed_uid=_allowed_uid()))
    except RuntimeError as e:
        # T11-02: startup fail neu socket directory/path khong an toan (_validate_socket_directory).
        print(f"signing service tu choi khoi dong: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
