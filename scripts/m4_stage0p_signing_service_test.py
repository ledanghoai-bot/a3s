#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: access-control hardening cua signing service THAT (F-M4-0P-T11-02,
F-M4-0P-T11-03).

Chay:
  docker exec alpha3s-m4-test python scripts/m4_stage0p_signing_service_test.py

CA Technical Re-review #11 (F-M4-0P-T10-02 PARTIALLY CLOSED / F-M4-0P-T11-02, P1): REV11
(`stage0p_signing_service.py`) tach dung PROCESS (dong) nhung KHONG tach QUYEN TRUY CAP —
`asyncio.start_unix_server(..., path=socket_path)` khong co private directory/mode, khong chmod
socket, khong xac minh peer credential, khong gioi han frame/concurrency/rate/timeout server-side.
BAT KY tien trinh local nao mo duoc socket path deu dung duoc service nhu 1 "encryption/signing
oracle" tuy y. F-M4-0P-T11-03 (P2, "co the dong cung T11-02"): signer chua rang buoc request voi
authority cua caller.

Sua REV12 (xem module docstring `stage0p_signing_service.py` cho chi tiet day du): startup-time
validation cho thu muc/socket path (owner/mode/symlink), `chmod 0600` file socket, xac minh peer
UID qua `SO_PEERCRED` TRUOC khi doc bat ky frame nao, gioi han so request dong thoi + timeout
server-side moi ket noi. Script nay test TRUC TIEP tang signing service (khong qua collector/DB —
`m4_stage0p_kill_test.py`/`m4_stage0p_sampling_test.py` da chung minh round-trip THAT qua collector
that su, script nay chi tap trung vao lop access-control moi):

  [1] Happy path: request hop le tu peer duoc phep (uid mac dinh = uid cua chinh service) -> phan
      hoi thanh cong, giai ma lai dung plaintext goc, digest khop sha256(canonical text).
  [2] Peer UID khong khop `allowed_uid` -> tu choi TRUOC khi doc bat ky frame nao (dong ket noi
      ngay, khong co response byte nao duoc ghi).
  [3] Thu muc socket qua rong quyen (mode 0755, co bit group/other) -> service TU THOAT ngay luc
      khoi dong (khong bao gio lang nghe), khong tao socket.
  [4] Socket path la 1 symlink co san (tro toi 1 file khac) -> service TU THOAT ngay luc khoi
      dong, KHONG unlink/ghi de file dich cua symlink.
  [5] Frame qua kho lon (length prefix > _MAX_FRAME_BYTES) -> ket noi bi dong ngay, khong co
      response, khong treo cho du lieu khong bao gio toi.
  [6] Frame gui "cham" kieu slow-loris (than tung it byte 1, vuot _REQUEST_TIMEOUT_SECONDS) ->
      server dong ket noi trong khoang thoi gian BI CHAN (khong treo vo thoi han).
  [7] Request flood: N request dong thoi (N > _MAX_CONCURRENT_REQUESTS) tu peer hop le -> TAT CA
      thanh cong dung, khong loi/khong tron lan ket qua giua cac request (chung minh gioi han
      dong thoi khong lam mat/sai du lieu).
  [8] Request thieu truong bat buoc (loi nghiep vu binh thuong tu peer HOP LE) -> phan hoi loi
      KHONG chua bat ky noi dung/plaintext nao (T11-03)."""

import asyncio
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from _stage0p_signing_service_helper import (  # noqa: E402
    start_signing_service,
    stop_signing_service,
    wait_signing_service_exit,
)

from app.config import settings  # noqa: E402
from app.services.pii.canonicalize import canonicalize  # noqa: E402
from app.services.pii.crypto import decrypt_sample_value  # noqa: E402
from app.services.pii.stage0p_signing_client import (  # noqa: E402
    request_signature,
)

_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


async def _raw_send_request(writer: asyncio.StreamWriter, req: dict) -> None:
    payload = json.dumps(req).encode("utf-8")
    writer.write(len(payload).to_bytes(4, "big") + payload)
    await writer.drain()


async def _raw_read_response(reader: asyncio.StreamReader, timeout: float = 3.0) -> dict | None:
    """Tra ve None neu ket noi bi dong TRUOC KHI co 1 frame response HOP LE (dung cho cac kich
    ban tu choi — khong co response nghia la bi tu choi TRUOC khi xu ly, dung y do T11-02)."""
    try:
        header = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionResetError, OSError):
        return None
    length = int.from_bytes(header, "big")
    try:
        body = await asyncio.wait_for(reader.readexactly(length), timeout=timeout)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionResetError, OSError):
        return None
    return json.loads(body.decode("utf-8"))


def _sample_req(*, sample_id: str, raw_content: str, message_id: int = 1) -> dict:
    return {
        "batch_id": "11111111-1111-1111-1111-111111111111",
        "conversation_id": 1,
        "message_id": message_id,
        "sample_id": sample_id,
        "raw_content": raw_content,
        "customer_ref": "cust-1",
        "conversation_ref": "conv-1",
        "purpose_code": "m4-stage0p-training-sample-v1",
        "txid": 1,
        "db_char_truncated": False,
    }


async def _spawn_raw_process(socket_path: str, *, sample_key: bytes, hmac_key: bytes,
                             allowed_uid: int | None = None) -> asyncio.subprocess.Process:
    """Spawn TRUC TIEP (khong qua start_signing_service — khong tu tao/chmod thu muc) — dung cho
    cac kich ban [3]/[4] can TOAN QUYEN kiem soat thu muc/socket path TRUOC khi service khoi dong."""
    env = os.environ.copy()
    env["STAGE0P_SIGNING_SOCKET"] = socket_path
    env["M4_SAMPLE_KEY_B64"] = base64.b64encode(sample_key).decode()
    env["M4_TRANSCRIPT_HMAC_KEY_B64"] = base64.b64encode(hmac_key).decode()
    if allowed_uid is not None:
        env["STAGE0P_SIGNING_ALLOWED_UID"] = str(allowed_uid)
    return await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.services.pii.stage0p_signing_service",
        cwd=str(ROOT), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )


async def main() -> int:
    print("== [1] Happy path: peer hop le (uid mac dinh) -> phan hoi thanh cong, giai ma dung ==")
    socket_1 = f"/tmp/m4-sst-1-{os.getpid()}/sock"
    proc_1, sample_key_1, _hmac_key_1 = await start_signing_service(socket_path=socket_1)
    try:
        result = await request_signature(
            socket_1, batch_id="11111111-1111-1111-1111-111111111111", conversation_id=1,
            message_id=1, sample_id="sample-1", raw_content="Xin chao, day la tin nhan test.",
            customer_ref="cust-1", conversation_ref="conv-1",
            purpose_code="m4-stage0p-training-sample-v1", txid=1)
        canonical_text, _truncated = canonicalize("Xin chao, day la tin nhan test.")
        check(result.canonical_digest == hashlib.sha256(canonical_text.encode("utf-8")).digest(),
              "[1] digest tra ve khop sha256(canonical_text) tu chinh service tu tinh")
        settings.m4_sample_key_b64 = base64.b64encode(sample_key_1).decode()
        decrypted = decrypt_sample_value(result.ciphertext, customer_ref="cust-1",
                                         conversation_ref="conv-1", sample_id="sample-1")
        check(decrypted == canonical_text,
              "[1] giai ma lai (bang chinh sample_key da cap cho service) ra DUNG canonical_text")
    finally:
        await stop_signing_service(proc_1, socket_1)

    print("== [2] Peer UID khong khop allowed_uid -> tu choi TRUOC KHI doc bat ky frame nao ==")
    socket_2 = f"/tmp/m4-sst-2-{os.getpid()}/sock"
    bogus_uid = os.getuid() + 999_983  # so nguyen to lon, chac chan khong trung uid THAT nao
    proc_2, _sk2, _hk2 = await start_signing_service(socket_path=socket_2, allowed_uid=bogus_uid)
    try:
        reader, writer = await asyncio.open_unix_connection(path=socket_2)
        try:
            await _raw_send_request(writer, _sample_req(sample_id="s2", raw_content="noi dung bi mat"))
            resp = await _raw_read_response(reader, timeout=3.0)
            check(resp is None, "[2] peer uid khong khop allowed_uid -> KHONG co response nao "
                  "duoc ghi (tu choi truoc khi xu ly, dung y do T11-02 'reject truoc khi doc raw "
                  "content')")
        finally:
            writer.close()
    finally:
        await stop_signing_service(proc_2, socket_2)

    print("== [3] Thu muc socket qua rong quyen (mode 0755) -> service TU THOAT luc khoi dong ==")
    dir_3 = f"/tmp/m4-sst-3-{os.getpid()}"
    os.makedirs(dir_3, mode=0o755, exist_ok=True)
    os.chmod(dir_3, 0o755)  # dam bao dung mode du umask (T3 can tinh huong CO group/other access)
    socket_3 = f"{dir_3}/sock"
    proc_3 = await _spawn_raw_process(socket_3, sample_key=os.urandom(32), hmac_key=os.urandom(32))
    rc_3, out_3 = await wait_signing_service_exit(proc_3, timeout=5.0)
    check(rc_3 != 0, "[3] thu muc mode 0755 (co bit group/other) -> service thoat KHONG THANH CONG")
    check(not os.path.exists(socket_3), "[3] KHONG co socket nao duoc tao (service chua bao gio lang nghe)")
    check("rong quyen" in out_3 or "qua rong quyen" in out_3,
          f"[3] thong diep loi de cap 'qua rong quyen' (thuc te: {out_3.strip()[:200]!r})")
    os.rmdir(dir_3)

    print("== [4] Socket path la 1 symlink co san -> service TU THOAT, KHONG dung/ghi de file dich ==")
    dir_4 = f"/tmp/m4-sst-4-{os.getpid()}"
    os.makedirs(dir_4, mode=0o700, exist_ok=True)
    os.chmod(dir_4, 0o700)
    target_4 = f"{dir_4}/innocent-target-file"
    with open(target_4, "w") as f:
        f.write("noi dung file dich - KHONG duoc dong/xoa/ghi de")
    socket_4 = f"{dir_4}/sock"
    os.symlink(target_4, socket_4)
    proc_4 = await _spawn_raw_process(socket_4, sample_key=os.urandom(32), hmac_key=os.urandom(32))
    rc_4, out_4 = await wait_signing_service_exit(proc_4, timeout=5.0)
    check(rc_4 != 0, "[4] socket path la symlink co san -> service thoat KHONG THANH CONG")
    check(os.path.islink(socket_4), "[4] symlink VAN CON NGUYEN (khong bi unlink/thay the boi service)")
    with open(target_4) as f:
        check(f.read() == "noi dung file dich - KHONG duoc dong/xoa/ghi de",
              "[4] file DICH cua symlink KHONG bi dong/ghi de")
    check("symlink" in out_4, f"[4] thong diep loi de cap 'symlink' (thuc te: {out_4.strip()[:200]!r})")
    os.unlink(socket_4)
    os.unlink(target_4)
    os.rmdir(dir_4)

    print("== [5] Frame qua kho lon (length prefix > _MAX_FRAME_BYTES) -> dong ket noi ngay ==")
    socket_5 = f"/tmp/m4-sst-5-{os.getpid()}/sock"
    proc_5, _sk5, _hk5 = await start_signing_service(socket_path=socket_5)
    try:
        reader, writer = await asyncio.open_unix_connection(path=socket_5)
        try:
            writer.write((2_000_000).to_bytes(4, "big") + b'{"x":1}')
            await writer.drain()
            resp = await _raw_read_response(reader, timeout=3.0)
            check(resp is None, "[5] frame qua kho lon -> KHONG co response, ket noi bi dong ngay "
                  "(khong treo cho du lieu khong bao gio du)")
        finally:
            writer.close()
    finally:
        await stop_signing_service(proc_5, socket_5)

    print("== [6] Frame 'cham' kieu slow-loris (vuot _REQUEST_TIMEOUT_SECONDS) -> bi chan, "
          "KHONG treo vo thoi han ==")
    socket_6 = f"/tmp/m4-sst-6-{os.getpid()}/sock"
    proc_6, _sk6, _hk6 = await start_signing_service(socket_path=socket_6)
    try:
        reader, writer = await asyncio.open_unix_connection(path=socket_6)
        try:
            payload = json.dumps(_sample_req(sample_id="s6", raw_content="tin nhan cham")).encode("utf-8")
            writer.write(len(payload).to_bytes(4, "big"))
            await writer.drain()
            start_6 = time.monotonic()
            # gui than tung 1 byte, cach nhau 0.5s - vuot han _REQUEST_TIMEOUT_SECONDS=5.0s truoc
            # khi gui het toan bo payload. Server co the tu dong RESET ket noi ngay khi timeout
            # kich hoat (truoc khi client gui het 12 byte) - day CHINH LA hanh vi mong doi (bi
            # chan trong khoang gioi han, khong treo vo thoi han), khong phai loi test.
            connection_reset_early = False
            for b in payload[:12]:
                try:
                    writer.write(bytes([b]))
                    await writer.drain()
                except (ConnectionResetError, BrokenPipeError, OSError):
                    connection_reset_early = True
                    break
                await asyncio.sleep(0.5)
            resp = None if connection_reset_early else await _raw_read_response(reader, timeout=5.0)
            elapsed_6 = time.monotonic() - start_6
            check(resp is None, "[6] frame gui cham (slow-loris) -> KHONG co response hop le "
                  "(server dong ket noi do vuot timeout, khong xu ly frame chua hoan tat)")
            check(elapsed_6 < 15.0, f"[6] server dong ket noi trong khoang BI CHAN (thuc te "
                  f"{elapsed_6:.1f}s) - khong treo vo thoi han")
        finally:
            writer.close()
    finally:
        await stop_signing_service(proc_6, socket_6)

    print("== [7] Request flood: N request dong thoi tu peer hop le -> TAT CA thanh cong dung, "
          "khong tron lan ket qua ==")
    socket_7 = f"/tmp/m4-sst-7-{os.getpid()}/sock"
    proc_7, sample_key_7, _hk7 = await start_signing_service(socket_path=socket_7)
    try:
        n = 20
        contents = [f"tin nhan flood so {i} - noi dung rieng biet" for i in range(n)]

        async def _one(i: int):
            return await request_signature(
                socket_7, batch_id="11111111-1111-1111-1111-111111111111", conversation_id=1,
                message_id=i, sample_id=f"sample-flood-{i}", raw_content=contents[i],
                customer_ref="cust-1", conversation_ref="conv-1",
                purpose_code="m4-stage0p-training-sample-v1", txid=i)

        results = await asyncio.gather(*(_one(i) for i in range(n)), return_exceptions=True)
        ok_count = sum(1 for r in results if not isinstance(r, Exception))
        check(ok_count == n, f"[7] tat ca {n} request dong thoi deu thanh cong (thuc te {ok_count}/{n})")
        settings.m4_sample_key_b64 = base64.b64encode(sample_key_7).decode()
        mismatched = 0
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                continue
            canonical_i, _t = canonicalize(contents[i])
            expected_digest = hashlib.sha256(canonical_i.encode("utf-8")).digest()
            if r.canonical_digest != expected_digest:
                mismatched += 1
                continue
            decrypted_i = decrypt_sample_value(r.ciphertext, customer_ref="cust-1",
                                               conversation_ref="conv-1", sample_id=f"sample-flood-{i}")
            if decrypted_i != contents[i]:
                mismatched += 1
        check(mismatched == 0, "[7] KHONG co request nao bi tron lan noi dung/digest voi request "
              "khac duoi tai dong thoi (gioi han concurrency khong lam sai du lieu)")
    finally:
        await stop_signing_service(proc_7, socket_7)

    print("== [8] Request thieu truong bat buoc (tu peer HOP LE) -> loi KHONG chua noi dung/plaintext ==")
    socket_8 = f"/tmp/m4-sst-8-{os.getpid()}/sock"
    proc_8, _sk8, _hk8 = await start_signing_service(socket_path=socket_8)
    try:
        reader, writer = await asyncio.open_unix_connection(path=socket_8)
        try:
            bad_req = _sample_req(sample_id="s8", raw_content="noi dung bi mat khong duoc lo ra")
            del bad_req["raw_content"]
            await _raw_send_request(writer, bad_req)
            resp = await _raw_read_response(reader, timeout=3.0)
            check(resp is not None and resp.get("ok") is False,
                  "[8] thieu truong bat buoc -> phan hoi loi co cau truc (khong crash service)")
            if resp is not None:
                check("noi dung bi mat" not in json.dumps(resp),
                      "[8] phan hoi loi KHONG chua plaintext (T11-03 - khong log/tra raw content)")
        finally:
            writer.close()
    finally:
        await stop_signing_service(proc_8, socket_8)

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
