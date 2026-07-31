#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: access-control + request-authorization hardening cua signing
service THAT (F-M4-0P-T11-02/T11-03 REV12, F-M4-0P-T12-01/T12-02 REV13).

Chay:
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      alpha3s-m4-test python scripts/m4_stage0p_signing_service_test.py

CA Technical Re-review #12 (F-M4-0P-T12-01, P1): REV12 `allowed_uid` mac dinh `os.getuid()` cua
CHINH tien trinh signing service — vi collector va service REV12 chay CUNG uid trong mo hinh dev/
test 1 host, "peer uid khop allowed_uid" luon DUNG cho BAT KY tien trinh nao chay cung uid do
(khong rieng collector). Test "wrong peer UID" REV12 chi doi gia tri EXPECTED sai roi ket noi tu
CUNG 1 principal — khong chung minh co 2 principal THAT.

Sua REV13: kich ban [2] duoi day dung 3 UID HE DIEU HANH THAT KHAC NHAU (`ensure_service_accounts()`
— `m4-signer`/`m4-collector` cung 1 group chia se, `m4-other` KHONG thuoc group do), spawn signing
service THAT SU duoi UID `m4-signer` (tham so `run_as_uid`), va goi `request_signature()` TU 1
TIEN TRINH CON THAT chay duoi UID `m4-collector` (thanh cong) / `m4-other` (bi tu choi TRUOC khi
frame duoc doc) — khong chi mo phong bang cach doi gia tri expected trong CUNG 1 tien trinh.

CA Technical Re-review #12 (F-M4-0P-T12-02, P1): sau khi qua UID check, REV12 signer chap nhan
request chua batch_id/message identity/purpose_code/txid/raw content do caller TU KHAI BAO — khong
co one-time authorization/policy chung minh request thuoc 1 capture capability hop le.

Sua REV13: `m4_stage0p_fetch_message_content()` (migration) tu ky 1 "signing authorization" HMAC
ngan han (30s) buoc vao (batch_id, conversation_id, message_id, sample_id, purpose_code, txid) —
signer tu xac minh chu ky nay (`M4_SIGNING_AUTH_VERIFY_KEY_B64`) truoc khi dong y ky/ma hoa. Kich
ban [9]-[14] duoi day mo phong CAC LOAI SAI KHAC NHAU cua token nay (tampered field/het han/TTL vuot/
key_version sai/dinh dang sai/replay) — TAT CA phai bi tu choi TRUOC khi ky/ma hoa bat ky noi dung
nao. Vi day la kiem tra o TANG SIGNING SERVICE (khong phai DB), cac kich ban nay tu xay token bang
CHINH `auth_verify_key` da cap cho 1 instance service cu the (mo phong DB tu ky) — dung thuat toan
GIONG HET migration 039 §5b (payload pipe-joined 8 truong + HMAC-SHA256, xem
`stage0p_signing_service.py:_verify_signing_authorization()`).

Script nay test TRUC TIEP tang signing service (khong qua collector/DB — `m4_stage0p_kill_test.py`/
`m4_stage0p_sampling_test.py` da chung minh round-trip THAT qua collector that su VOI token DB THAT
ky, script nay tap trung vao lop access-control + xac minh token adversarial):

  [1] Happy path: request hop le (peer duoc phep, signing_authorization dung) -> phan hoi thanh
      cong, giai ma lai dung plaintext goc, digest khop sha256(canonical text).
  [2] T12-01: 3 UID HE DIEU HANH THAT (signer/collector/other) — collector THAT thanh cong,
      other THAT bi tu choi TRUOC khi doc frame.
  [3] Thu muc socket qua rong quyen (mode 0755) -> service TU THOAT ngay luc khoi dong.
  [4] Socket path la 1 symlink co san -> service TU THOAT ngay luc khoi dong, KHONG dung file dich.
  [5] Frame qua kho lon -> ket noi bi dong ngay.
  [6] Frame gui "cham" kieu slow-loris -> server dong ket noi trong khoang thoi gian BI CHAN.
  [7] Request flood: N request dong thoi tu peer hop le -> TAT CA thanh cong dung, khong tron lan.
  [8] Request thieu truong bat buoc -> phan hoi loi KHONG chua noi dung/plaintext.
  [9] T12-02: signing_authorization ky cho sample_id KHAC (tampered field) -> chu ky khong khop.
  [10] T12-02: signing_authorization da het han (expires_epoch trong qua khu) -> tu choi.
  [11] T12-02: TTL vuot qua muc cho phep (30s) -> tu choi.
  [12] T12-02: key_version khong duoc ho tro -> tu choi.
  [13] T12-02: dinh dang token sai (thieu phan) -> tu choi.
  [14] T12-02: replay — dung LAI CHINH XAC 1 token da dung thanh cong -> lan 2 bi tu choi."""

import asyncio
import base64
import hashlib
import hmac as hmac_module
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from _stage0p_signing_service_helper import (  # noqa: E402
    ensure_service_accounts,
    request_signature_as_uid,
    start_signing_service,
    stop_signing_service,
    wait_signing_service_exit,
)

from app.config import settings  # noqa: E402
from app.services.pii.canonicalize import canonicalize  # noqa: E402
from app.services.pii.crypto import decrypt_sample_value  # noqa: E402
from app.services.pii.stage0p_signing_client import request_signature  # noqa: E402

_fail: list[str] = []

_AUTH_KEY_VERSION = "m4-signing-auth-v1"
_DEFAULT_BATCH_ID = "11111111-1111-1111-1111-111111111111"
_DEFAULT_PURPOSE = "m4-stage0p-training-sample-v1"


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


def _sign_test_authorization(auth_key: bytes, *, batch_id: str, conversation_id: int,
                             message_id: int, sample_id: str, purpose_code: str, txid: int,
                             issued_epoch: int | None = None, expires_epoch: int | None = None,
                             key_version: str = _AUTH_KEY_VERSION, ttl_seconds: int = 30) -> str:
    """Mo phong `m4_stage0p_fetch_message_content()` tu ky 1 signing authorization (migration 039
    §5b) — dung CHINH XAC thuat toan payload pipe-joined 8 truong + HMAC-SHA256 ma
    `stage0p_signing_service.py:_verify_signing_authorization()` doi chieu lai."""
    now_epoch = int(time.time())
    issued_epoch = now_epoch if issued_epoch is None else issued_epoch
    expires_epoch = (issued_epoch + ttl_seconds) if expires_epoch is None else expires_epoch
    payload = "|".join([
        str(batch_id), str(conversation_id), str(message_id), str(sample_id), str(purpose_code),
        str(txid), str(issued_epoch), str(expires_epoch),
    ]).encode("utf-8")
    sig = hmac_module.new(auth_key, payload, hashlib.sha256).digest()
    return f"{key_version}|{issued_epoch}|{expires_epoch}|{sig.hex()}"


def _build_request(auth_key: bytes, *, sample_id: str, raw_content: str, message_id: int = 1,
                   batch_id: str = _DEFAULT_BATCH_ID, conversation_id: int = 1,
                   purpose_code: str = _DEFAULT_PURPOSE, txid: int = 1,
                   auth_overrides: dict | None = None) -> dict:
    """Xay 1 request DAY DU (bao gom signing_authorization dung, tru khi `auth_overrides` co y lam
    sai lech mot phan) — dung cho ca happy-path lan cac kich ban adversarial T12-02."""
    auth_kwargs = dict(batch_id=batch_id, conversation_id=conversation_id, message_id=message_id,
                       sample_id=sample_id, purpose_code=purpose_code, txid=txid)
    auth_kwargs.update(auth_overrides or {})
    token = _sign_test_authorization(auth_key, **auth_kwargs)
    return {
        "batch_id": batch_id, "conversation_id": conversation_id, "message_id": message_id,
        "sample_id": sample_id, "raw_content": raw_content, "customer_ref": "cust-1",
        "conversation_ref": "conv-1", "purpose_code": purpose_code, "txid": txid,
        "signing_authorization": token, "db_char_truncated": False,
    }


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


async def _raw_request(socket_path: str, req: dict, *, timeout: float = 3.0) -> dict | None:
    reader, writer = await asyncio.open_unix_connection(path=socket_path)
    try:
        await _raw_send_request(writer, req)
        return await _raw_read_response(reader, timeout=timeout)
    finally:
        writer.close()


async def _spawn_raw_process(socket_path: str, *, sample_key: bytes, hmac_key: bytes,
                             auth_verify_key: bytes, allowed_uid: int) -> asyncio.subprocess.Process:
    """Spawn TRUC TIEP (khong qua start_signing_service — khong tu tao/chmod thu muc) — dung cho
    cac kich ban [3]/[4] can TOAN QUYEN kiem soat thu muc/socket path TRUOC khi service khoi dong."""
    env = os.environ.copy()
    env["STAGE0P_SIGNING_SOCKET"] = socket_path
    env["M4_SAMPLE_KEY_B64"] = base64.b64encode(sample_key).decode()
    env["M4_TRANSCRIPT_HMAC_KEY_B64"] = base64.b64encode(hmac_key).decode()
    env["M4_SIGNING_AUTH_VERIFY_KEY_B64"] = base64.b64encode(auth_verify_key).decode()
    env["STAGE0P_SIGNING_ALLOWED_UID"] = str(allowed_uid)
    return await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.services.pii.stage0p_signing_service",
        cwd=str(ROOT), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )


async def main() -> int:
    print("== [1] Happy path: peer hop le, signing_authorization dung -> phan hoi thanh cong, "
          "giai ma dung ==")
    socket_1 = f"/tmp/m4-sst-1-{os.getpid()}/sock"
    proc_1, sample_key_1, _hmac_key_1, auth_key_1 = await start_signing_service(
        socket_path=socket_1, allowed_uid=os.getuid())
    try:
        result = await request_signature(
            socket_1, batch_id=_DEFAULT_BATCH_ID, conversation_id=1, message_id=1,
            sample_id="sample-1", raw_content="Xin chao, day la tin nhan test.",
            customer_ref="cust-1", conversation_ref="conv-1", purpose_code=_DEFAULT_PURPOSE,
            txid=1, signing_authorization=_sign_test_authorization(
                auth_key_1, batch_id=_DEFAULT_BATCH_ID, conversation_id=1, message_id=1,
                sample_id="sample-1", purpose_code=_DEFAULT_PURPOSE, txid=1))
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

    print("== [2] T12-01: 3 UID HE DIEU HANH THAT (signer/collector/other) — collector THAT "
          "thanh cong, other THAT bi tu choi TRUOC khi doc frame ==")
    signer_uid, collector_uid, other_uid, shared_gid = ensure_service_accounts()
    socket_2 = f"/tmp/m4-sst-2-{os.getpid()}/sock"
    proc_2, _sk2, _hk2, auth_key_2 = await start_signing_service(
        socket_path=socket_2, allowed_uid=collector_uid,
        run_as_uid=signer_uid, shared_gid=shared_gid)
    try:
        req_2 = _build_request(auth_key_2, sample_id="s2-collector", raw_content="noi dung s2")
        req_2 = {**req_2, "socket_path": socket_2}
        resp_collector = await request_signature_as_uid(collector_uid, req_2)
        check(resp_collector.get("ok") is True,
              "[2] collector THAT (UID rieng, thanh vien group chia se) -> thanh cong")

        req_2b = _build_request(auth_key_2, sample_id="s2-other", raw_content="noi dung bi mat s2b")
        req_2b = {**req_2b, "socket_path": socket_2}
        resp_other = await request_signature_as_uid(other_uid, req_2b)
        check(resp_other.get("ok") is False,
              "[2] other THAT (UID thu 3, KHONG thuoc group chia se) -> bi tu choi (khong thanh "
              f"cong ky duoc gi) - thuc te: {resp_other}")
    finally:
        await stop_signing_service(proc_2, socket_2)

    print("== [3] Thu muc socket qua rong quyen (mode 0755) -> service TU THOAT luc khoi dong ==")
    dir_3 = f"/tmp/m4-sst-3-{os.getpid()}"
    os.makedirs(dir_3, mode=0o755, exist_ok=True)
    os.chmod(dir_3, 0o755)  # dam bao dung mode du umask (T3 can tinh huong CO group/other access)
    socket_3 = f"{dir_3}/sock"
    proc_3 = await _spawn_raw_process(socket_3, sample_key=os.urandom(32), hmac_key=os.urandom(32),
                                      auth_verify_key=os.urandom(32), allowed_uid=os.getuid())
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
    proc_4 = await _spawn_raw_process(socket_4, sample_key=os.urandom(32), hmac_key=os.urandom(32),
                                      auth_verify_key=os.urandom(32), allowed_uid=os.getuid())
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
    proc_5, _sk5, _hk5, _ak5 = await start_signing_service(socket_path=socket_5, allowed_uid=os.getuid())
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
    proc_6, _sk6, _hk6, auth_key_6 = await start_signing_service(socket_path=socket_6, allowed_uid=os.getuid())
    try:
        reader, writer = await asyncio.open_unix_connection(path=socket_6)
        try:
            req_6 = _build_request(auth_key_6, sample_id="s6", raw_content="tin nhan cham")
            payload = json.dumps(req_6).encode("utf-8")
            writer.write(len(payload).to_bytes(4, "big"))
            await writer.drain()
            start_6 = time.monotonic()
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
    proc_7, sample_key_7, _hk7, auth_key_7 = await start_signing_service(socket_path=socket_7, allowed_uid=os.getuid())
    try:
        n = 20
        contents = [f"tin nhan flood so {i} - noi dung rieng biet" for i in range(n)]

        async def _one(i: int):
            return await request_signature(
                socket_7, batch_id=_DEFAULT_BATCH_ID, conversation_id=1, message_id=i,
                sample_id=f"sample-flood-{i}", raw_content=contents[i], customer_ref="cust-1",
                conversation_ref="conv-1", purpose_code=_DEFAULT_PURPOSE, txid=i,
                signing_authorization=_sign_test_authorization(
                    auth_key_7, batch_id=_DEFAULT_BATCH_ID, conversation_id=1, message_id=i,
                    sample_id=f"sample-flood-{i}", purpose_code=_DEFAULT_PURPOSE, txid=i))

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
    proc_8, _sk8, _hk8, auth_key_8 = await start_signing_service(socket_path=socket_8, allowed_uid=os.getuid())
    try:
        bad_req = _build_request(auth_key_8, sample_id="s8", raw_content="noi dung bi mat khong duoc lo ra")
        del bad_req["raw_content"]
        resp = await _raw_request(socket_8, bad_req, timeout=3.0)
        check(resp is not None and resp.get("ok") is False,
              "[8] thieu truong bat buoc -> phan hoi loi co cau truc (khong crash service)")
        if resp is not None:
            check("noi dung bi mat" not in json.dumps(resp),
                  "[8] phan hoi loi KHONG chua plaintext (T11-03 - khong log/tra raw content)")
    finally:
        await stop_signing_service(proc_8, socket_8)

    print("== [9]-[14] T12-02: signing_authorization adversarial - tat ca phai bi tu choi TRUOC "
          "khi ky/ma hoa bat ky noi dung nao ==")
    socket_9 = f"/tmp/m4-sst-9-{os.getpid()}/sock"
    proc_9, _sk9, _hk9, auth_key_9 = await start_signing_service(socket_path=socket_9, allowed_uid=os.getuid())
    try:
        print("  -- [9] token ky cho sample_id KHAC (tampered field) --")
        req_9 = _build_request(auth_key_9, sample_id="sample-real", raw_content="noi dung that",
                               auth_overrides={"sample_id": "sample-GIA-mao"})
        resp_9 = await _raw_request(socket_9, req_9, timeout=3.0)
        check(resp_9 is not None and resp_9.get("ok") is False and "chu ky khong khop" in resp_9.get("error", ""),
              f"[9] sample_id trong request khac voi luc ky -> chu ky khong khop, tu choi (thuc te: {resp_9})")

        print("  -- [10] token da het han --")
        past = int(time.time()) - 3600
        req_10 = _build_request(auth_key_9, sample_id="s10", raw_content="noi dung s10",
                                auth_overrides={"issued_epoch": past, "expires_epoch": past + 30})
        resp_10 = await _raw_request(socket_9, req_10, timeout=3.0)
        check(resp_10 is not None and resp_10.get("ok") is False and "het han" in resp_10.get("error", ""),
              f"[10] token het han tu lau -> tu choi (thuc te: {resp_10})")

        print("  -- [11] TTL vuot qua muc cho phep (30s) --")
        now_epoch = int(time.time())
        req_11 = _build_request(auth_key_9, sample_id="s11", raw_content="noi dung s11",
                                auth_overrides={"issued_epoch": now_epoch, "expires_epoch": now_epoch + 3600})
        resp_11 = await _raw_request(socket_9, req_11, timeout=3.0)
        check(resp_11 is not None and resp_11.get("ok") is False and "TTL" in resp_11.get("error", ""),
              f"[11] TTL 3600s vuot qua 30s cho phep -> tu choi (thuc te: {resp_11})")

        print("  -- [12] key_version khong duoc ho tro --")
        req_12 = _build_request(auth_key_9, sample_id="s12", raw_content="noi dung s12",
                                auth_overrides={"key_version": "m4-signing-auth-v99-khong-ton-tai"})
        resp_12 = await _raw_request(socket_9, req_12, timeout=3.0)
        check(resp_12 is not None and resp_12.get("ok") is False and "key_version" in resp_12.get("error", ""),
              f"[12] key_version sai -> tu choi (thuc te: {resp_12})")

        print("  -- [13] dinh dang token sai (thieu phan) --")
        req_13 = _build_request(auth_key_9, sample_id="s13", raw_content="noi dung s13")
        req_13["signing_authorization"] = "chi-1-phan-khong-du"
        resp_13 = await _raw_request(socket_9, req_13, timeout=3.0)
        check(resp_13 is not None and resp_13.get("ok") is False and "dinh dang" in resp_13.get("error", ""),
              f"[13] token dinh dang sai -> tu choi (thuc te: {resp_13})")

        print("  -- [14] replay: dung LAI CHINH XAC 1 token da dung thanh cong --")
        req_14 = _build_request(auth_key_9, sample_id="s14", raw_content="noi dung s14")
        resp_14a = await _raw_request(socket_9, req_14, timeout=3.0)
        check(resp_14a is not None and resp_14a.get("ok") is True,
              f"[14] lan 1 (token con moi, chua dung) -> thanh cong (thuc te: {resp_14a and resp_14a.get('ok')})")
        resp_14b = await _raw_request(socket_9, req_14, timeout=3.0)
        check(resp_14b is not None and resp_14b.get("ok") is False and "replay" in resp_14b.get("error", ""),
              f"[14] lan 2 (CUNG token) -> tu choi (replay) (thuc te: {resp_14b})")
    finally:
        await stop_signing_service(proc_9, socket_9)

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
