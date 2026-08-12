#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: access-control + request-authorization hardening cua signing
service THAT (F-M4-0P-T11-02/T11-03 REV12, F-M4-0P-T12-01/T12-02 REV13, F-M4-0P-T13-01/T13-02/
T13-03 REV14).

Chay:
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      -e REDIS_URL=redis://alpha3s-m4-redis:6379/0 \
      alpha3s-m4-test python scripts/m4_stage0p_signing_service_test.py

CA Technical Re-review #13 (T12-01 CLOSED AT DEV/TEST CODE-DESIGN LEVEL; F-M4-0P-T13-01/T13-02,
P1; F-M4-0P-T13-03, P2): REV13 payload chi gom
`batch_id|conversation_id|message_id|sample_id|purpose_code|txid|issued|expires` — CHUA buoc
canonical digest cua noi dung THAT, CHUA buoc customer_ref/conversation_ref (dung trong AAD/
transcript), CHUA co domain/operation tag, noi bang dau '|' KHONG unambiguous. `_replay_seen`
REV13 la dictionary TRONG BO NHO CUA 1 TIEN TRINH — restart signer xoa toan bo state, 2 signer
instance co 2 cache doc lap. Semaphore chi gioi han concurrency, khong gioi han TOC DO request.

Sua REV14 (xem `stage0p_signing_service.py` docstring cho chi tiet day du thiet ke):
  - T13-01: payload gio 14 truong (domain tag + identity + customer_ref/conversation_ref +
    canonical_digest_hex + char_truncated + nonce + issued/expires), noi bang LENGTH-PREFIX
    (khong con dau '|'). Signer tu canonicalize raw_content TRUOC, tu tinh digest, ROI moi doi
    chieu chu ky — bat ky sai lech noi dung/customer_ref/truncation-claim deu bi tu choi.
  - T13-02: token mang 1 nonce ngau nhien, tieu thu qua Redis `SET NX PX` (dung CHUNG moi signer
    instance, ton tai qua restart) thay `_replay_seen` trong-bo-nho.
  - T13-03: fixed-window admission budget (10s/40 request) AP DUNG SAU peer-UID check.

Script nay test TRUC TIEP tang signing service (khong qua collector/DB — `m4_stage0p_kill_test.py`/
`m4_stage0p_sampling_test.py` da chung minh round-trip THAT qua collector that su VOI token DB
THAT ky/Redis THAT, script nay tap trung vao lop access-control + xac minh token adversarial):

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
  [9] T12-02: sample_id trong request khac voi luc ky (tampered field) -> chu ky khong khop.
  [10] T13-01: raw_content bi thay the SAU KHI token da ky cho noi dung KHAC -> digest khong khop.
  [11] T13-01: customer_ref bi thay the (dung trong AAD/transcript) -> chu ky khong khop.
  [12] T13-01: db_char_truncated claim bi thay doi -> chu ky khong khop.
  [13] T12-02: signing_authorization da het han -> tu choi.
  [14] T12-02: TTL vuot qua muc cho phep (30s) -> tu choi.
  [15] T12-02: key_version khong duoc ho tro -> tu choi.
  [16] T13-01: dinh dang token sai (thieu phan, gio la 5 phan) -> tu choi.
  [17] T13-02: replay — dung LAI CHINH XAC 1 token da dung thanh cong (CUNG 1 signer instance,
       Redis THAT) -> lan 2 bi tu choi.
  [18] T13-02: replay SAU KHI signer instance RESTART (tien trinh MOI, CUNG Redis+auth key) —
       token da dung TRUOC restart van bi tu choi (state Redis TON TAI qua restart).
  [19] T13-02: 2 signer instance KHAC NHAU (socket khac, CUNG Redis+auth key) nhan CUNG 1 token
       DONG THOI -> DUNG 1 thanh cong (Redis SET NX PX dung CHUNG giua cac instance).
  [20] T13-03: burst vuot ngan sach rate-limit -> mot phan bi tu choi TRUOC khi doc frame (khong
       co response), tu phuc hoi co kiem soat sau khi cua so lan sau bat dau.
  [21] F-A08-R2-01: khoi dong THAT qua 3 khoa dang FILE (`<NAME>_FILE`, khong con gia tri THO
       trong environment) voi permission dung (0400, chinh chu so huu) -> thanh cong, round-trip
       ky/ma hoa/giai ma day du.
  [22] F-A08-R2-01: file khoa co bit group/other (world-readable, mo phong bind-mount host khong
       giu dung permission - xem evidence Windows-host POC trong correction report) -> service TU
       CHOI khoi dong, khong bao gio doc noi dung/lang nghe socket.
  [23] F-A08-R2-01: file khoa KHONG thuoc so huu tien trinh signing service (chu so huu khac, du
       permission mode dung) -> service TU CHOI khoi dong.
  [24] F-A08-R3-01: THU MUC CHA cua 3 file khoa la root:root 0700 (dung y het bug runbook CA
       Review 3 phat hien), chay duoi UID signer THAT (khong phai UID tien trinh test/root) ->
       service TU CHOI khoi dong vi khong traverse duoc vao thu muc cha, du TUNG FILE ben trong co
       permission/chu so huu dung.
  [25] F-A08-R3-01: THU MUC CHA duoc chown dung cho UID signer (khop runbook DA SUA) -> service
       (UID signer THAT) khoi dong THANH CONG, round-trip day du - Linux evidence THAT (khong phai
       hanh vi Windows bind-mount)."""

import asyncio
import base64
import hashlib
import hmac as hmac_module
import json
import os
import pwd
import stat
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from _stage0p_signing_service_helper import (  # noqa: E402
    _SOCKET_FILE_MODE,
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
_AUTH_DOMAIN_TAG = "m4-stage0p-sign-capture-v1"
_DEFAULT_BATCH_ID = "11111111-1111-1111-1111-111111111111"
_DEFAULT_PURPOSE = "m4-stage0p-training-sample-v1"
# T13-03: PHAI khop CHINH XAC _RATE_LIMIT_WINDOW_SECONDS trong stage0p_signing_service.py - test
# nay chay o TIEN TRINH KHAC nen khong import truc tiep duoc hang so cua service.
_RATE_LIMIT_WINDOW_SECONDS_REF = 10.0


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


def _lenpfx_join(*fields) -> bytes:
    """PHAI khop CHINH XAC thuat toan `stage0p_signing_service.py:_lenpfx_join()` / migration 039
    (`m4_stage0p_fetch_message_content`, vong lap ARRAY) — moi truong tien to boi do dai byte cua
    chinh no, noi tiep khong dau phan cach."""
    out = bytearray()
    for f in fields:
        b = str(f).encode("utf-8")
        out += str(len(b)).encode("ascii") + b":" + b
    return bytes(out)


def _sign_test_authorization(auth_key: bytes, *, batch_id: str, conversation_id: int,
                             message_id: int, sample_id: str, customer_ref: str, purpose_code: str,
                             txid: int, canonical_digest_hex: str, char_truncated: bool,
                             nonce: str | None = None, issued_epoch: int | None = None,
                             expires_epoch: int | None = None, key_version: str = _AUTH_KEY_VERSION,
                             ttl_seconds: int = 30) -> str:
    """Mo phong `m4_stage0p_fetch_message_content()` tu ky 1 signing authorization (migration 039
    §5b, REV14 T13-01/T13-02) — dung CHINH XAC thuat toan payload length-prefix 14 truong +
    HMAC-SHA256 ma `stage0p_signing_service.py:_verify_signing_authorization()` doi chieu lai."""
    now_epoch = int(time.time())
    issued_epoch = now_epoch if issued_epoch is None else issued_epoch
    expires_epoch = (issued_epoch + ttl_seconds) if expires_epoch is None else expires_epoch
    nonce = nonce or str(uuid.uuid4())
    conversation_id_str = str(conversation_id)
    payload = _lenpfx_join(
        _AUTH_DOMAIN_TAG, str(batch_id), conversation_id_str, str(message_id), str(sample_id),
        str(customer_ref), conversation_id_str, str(purpose_code), str(txid), canonical_digest_hex,
        ("1" if char_truncated else "0"), nonce, str(issued_epoch), str(expires_epoch),
    )
    sig = hmac_module.new(auth_key, payload, hashlib.sha256).digest()
    return f"{key_version}|{issued_epoch}|{expires_epoch}|{nonce}|{sig.hex()}"


def _build_request(auth_key: bytes, *, sample_id: str, raw_content: str, message_id: int = 1,
                   batch_id: str = _DEFAULT_BATCH_ID, conversation_id: int = 1,
                   customer_ref: str = "cust-1", purpose_code: str = _DEFAULT_PURPOSE, txid: int = 1,
                   db_char_truncated: bool = False, auth_overrides: dict | None = None) -> dict:
    """Xay 1 request DAY DU (bao gom signing_authorization dung, tru khi `auth_overrides` co y lam
    sai lech mot phan) — dung cho ca happy-path lan cac kich ban adversarial. `canonical_digest_hex`
    ky trong token tu tinh TU CHINH `raw_content` duoc truyen (khop dung thuat toan signer se tu
    lam) — cac kich ban T13-01 muon gia mao NOI DUNG phai sua `req["raw_content"]` SAU KHI ham nay
    tra ve (token van con ky cho noi dung GOC), khong truyen thang noi dung gia vao day."""
    canonical_text, _t = canonicalize(raw_content)
    canonical_digest_hex = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    auth_kwargs = dict(batch_id=batch_id, conversation_id=conversation_id, message_id=message_id,
                       sample_id=sample_id, customer_ref=customer_ref, purpose_code=purpose_code,
                       txid=txid, canonical_digest_hex=canonical_digest_hex,
                       char_truncated=db_char_truncated)
    auth_kwargs.update(auth_overrides or {})
    token = _sign_test_authorization(auth_key, **auth_kwargs)
    return {
        "batch_id": batch_id, "conversation_id": conversation_id, "message_id": message_id,
        "sample_id": sample_id, "raw_content": raw_content, "customer_ref": customer_ref,
        "conversation_ref": str(conversation_id), "purpose_code": purpose_code, "txid": txid,
        "signing_authorization": token, "db_char_truncated": db_char_truncated,
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
    """Tra ve None neu ket noi bi dong TRUOC KHI gui xong request (vd rate-limit T13-03 dong
    ket noi ngay sau accept, co the roi vao dung luc client dang ghi) — CUNG 1 y nghia voi "khong
    co response" tu `_raw_read_response`, khong phai loi test."""
    reader, writer = await asyncio.open_unix_connection(path=socket_path)
    try:
        try:
            await _raw_send_request(writer, req)
        except (ConnectionResetError, BrokenPipeError, OSError):
            return None
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


async def _spawn_with_secret_files(socket_path: str, *, sample_key: bytes, hmac_key: bytes,
                                   auth_verify_key: bytes, allowed_uid: int, secret_dir: str,
                                   file_mode: int = 0o400, owner_uid: int | None = None,
                                   run_as_uid: int | None = None,
                                   wait_ready: bool = True) -> asyncio.subprocess.Process:
    """F-A08-R2-01: spawn service doc 3 khoa qua `<NAME>_FILE` (thay vi gia tri THO qua env truc
    tiep nhu `_spawn_raw_process`) - ghi 3 file TRONG `secret_dir`, chmod/chown NGAY sau moi lan
    ghi (TRUOC KHI spawn tien trinh - quan trong: chmod SAU KHI spawn se co RACE that, service co
    the doc file truoc khi permission kip sua) roi tro `_FILE` toi dung duong dan. `file_mode`/
    `owner_uid` cho phep kich ban [22]/[23] dung SAI permission/chu so huu tu dau, khong can sua
    lai sau khi tien trinh da chay."""
    def _write(name: str, value: bytes) -> str:
        path = os.path.join(secret_dir, name)
        with open(path, "wb") as f:
            f.write(base64.b64encode(value))
        os.chmod(path, file_mode)
        if owner_uid is not None:
            os.chown(path, owner_uid, -1)
        return path
    sample_path = _write("sample_key", sample_key)
    hmac_path = _write("transcript_hmac_key", hmac_key)
    auth_path = _write("signing_auth_key", auth_verify_key)
    env = os.environ.copy()
    env["STAGE0P_SIGNING_SOCKET"] = socket_path
    env["M4_SAMPLE_KEY_B64_FILE"] = sample_path
    env["M4_TRANSCRIPT_HMAC_KEY_B64_FILE"] = hmac_path
    env["M4_SIGNING_AUTH_VERIFY_KEY_B64_FILE"] = auth_path
    env["STAGE0P_SIGNING_ALLOWED_UID"] = str(allowed_uid)
    for name in ("M4_SAMPLE_KEY_B64", "M4_TRANSCRIPT_HMAC_KEY_B64", "M4_SIGNING_AUTH_VERIFY_KEY_B64"):
        env.pop(name, None)  # dam bao KHONG con gia tri THO nao trong env - chi con duong dan file
    kwargs = {}
    if run_as_uid is not None:
        # F-A08-R3-01: chay THAT duoi UID signer THAT (khong phai UID cua tien trinh test/root nhu
        # [21]-[23]) - can thiet de kiem duoc parent-directory traversal THAT (root tao thu muc,
        # UID KHAC phai doc duoc/khong doc duoc tuy permission - khong the tai hien bang cach chay
        # cung UID voi nguoi tao thu muc).
        kwargs["user"] = run_as_uid
        kwargs["group"] = pwd.getpwuid(run_as_uid).pw_gid
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.services.pii.stage0p_signing_service",
        cwd=str(ROOT), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        **kwargs,
    )
    if not wait_ready:
        return proc
    # Khop dung logic doi san sang cua start_signing_service() (helper da qua nhieu vong review) -
    # doi CA socket ton tai LAN dung mode cuoi cung, khong chi "file ton tai" (tranh race voi
    # os.chmod() ben trong service chay SAU bind()).
    deadline = time.monotonic() + 5.0
    while True:
        if os.path.exists(socket_path):
            try:
                if stat.S_IMODE(os.stat(socket_path).st_mode) == _SOCKET_FILE_MODE:
                    break
            except OSError:
                pass
        if proc.returncode is not None:
            out = await proc.stdout.read()
            raise RuntimeError(
                f"signing service thoat som (exit={proc.returncode}): {out.decode(errors='replace')}")
        if time.monotonic() > deadline:
            proc.terminate()
            raise RuntimeError("signing service khong tao socket (dung mode) trong 5s")
        await asyncio.sleep(0.05)
    return proc


async def main() -> int:
    print("== [1] Happy path: peer hop le, signing_authorization dung -> phan hoi thanh cong, "
          "giai ma dung ==")
    socket_1 = f"/tmp/m4-sst-1-{os.getpid()}/sock"
    proc_1, sample_key_1, _hmac_key_1, auth_key_1 = await start_signing_service(
        socket_path=socket_1, allowed_uid=os.getuid())
    try:
        req_1 = _build_request(auth_key_1, sample_id="sample-1",
                               raw_content="Xin chao, day la tin nhan test.")
        result = await request_signature(
            socket_1, batch_id=req_1["batch_id"], conversation_id=req_1["conversation_id"],
            message_id=req_1["message_id"], sample_id=req_1["sample_id"],
            raw_content=req_1["raw_content"], customer_ref=req_1["customer_ref"],
            conversation_ref=req_1["conversation_ref"], purpose_code=req_1["purpose_code"],
            txid=req_1["txid"], signing_authorization=req_1["signing_authorization"])
        canonical_text, _truncated = canonicalize("Xin chao, day la tin nhan test.")
        check(result.canonical_digest == hashlib.sha256(canonical_text.encode("utf-8")).digest(),
              "[1] digest tra ve khop sha256(canonical_text) tu chinh service tu tinh")
        settings.m4_sample_key_b64 = base64.b64encode(sample_key_1).decode()
        decrypted = decrypt_sample_value(result.ciphertext, customer_ref="cust-1",
                                         conversation_ref="1", sample_id="sample-1")
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
            req_i = _build_request(auth_key_7, sample_id=f"sample-flood-{i}", raw_content=contents[i],
                                   message_id=i, txid=i)
            return await request_signature(
                socket_7, batch_id=req_i["batch_id"], conversation_id=req_i["conversation_id"],
                message_id=req_i["message_id"], sample_id=req_i["sample_id"],
                raw_content=req_i["raw_content"], customer_ref=req_i["customer_ref"],
                conversation_ref=req_i["conversation_ref"], purpose_code=req_i["purpose_code"],
                txid=req_i["txid"], signing_authorization=req_i["signing_authorization"])

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
                                               conversation_ref="1", sample_id=f"sample-flood-{i}")
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

    print("== [9]-[16] signing_authorization adversarial - tat ca phai bi tu choi TRUOC khi ky/ma "
          "hoa bat ky noi dung nao ==")
    socket_9 = f"/tmp/m4-sst-9-{os.getpid()}/sock"
    proc_9, _sk9, _hk9, auth_key_9 = await start_signing_service(socket_path=socket_9, allowed_uid=os.getuid())
    try:
        print("  -- [9] token ky cho sample_id KHAC (tampered field) --")
        req_9 = _build_request(auth_key_9, sample_id="sample-real", raw_content="noi dung that",
                               auth_overrides={"sample_id": "sample-GIA-mao"})
        resp_9 = await _raw_request(socket_9, req_9, timeout=3.0)
        check(resp_9 is not None and resp_9.get("ok") is False and "chu ky khong khop" in resp_9.get("error", ""),
              f"[9] sample_id trong request khac voi luc ky -> chu ky khong khop, tu choi (thuc te: {resp_9})")

        print("  -- [10] T13-01: raw_content bi thay the SAU KHI token da ky cho noi dung KHAC --")
        req_10 = _build_request(auth_key_9, sample_id="s10-content-tamper",
                                raw_content="noi dung THAT duoc uy quyen")
        req_10["raw_content"] = "noi dung GIA da bi thay the boi 1 tien trinh gian doan"
        resp_10 = await _raw_request(socket_9, req_10, timeout=3.0)
        check(resp_10 is not None and resp_10.get("ok") is False and "chu ky khong khop" in resp_10.get("error", ""),
              f"[10] raw_content bi thay doi -> digest khac, chu ky khong khop, tu choi TRUOC khi "
              f"ma hoa noi dung gia (thuc te: {resp_10})")

        print("  -- [11] T13-01: customer_ref bi thay the (dung trong AAD/transcript) --")
        req_11 = _build_request(auth_key_9, sample_id="s11-customer-tamper", raw_content="noi dung s11",
                                customer_ref="cust-that")
        req_11["customer_ref"] = "cust-gia-mao"
        resp_11 = await _raw_request(socket_9, req_11, timeout=3.0)
        check(resp_11 is not None and resp_11.get("ok") is False and "chu ky khong khop" in resp_11.get("error", ""),
              f"[11] customer_ref bi thay doi -> chu ky khong khop, tu choi (thuc te: {resp_11})")

        print("  -- [12] T13-01: db_char_truncated claim bi thay doi --")
        req_12 = _build_request(auth_key_9, sample_id="s12-trunc-tamper", raw_content="noi dung s12",
                                db_char_truncated=False)
        req_12["db_char_truncated"] = True
        resp_12 = await _raw_request(socket_9, req_12, timeout=3.0)
        check(resp_12 is not None and resp_12.get("ok") is False and "chu ky khong khop" in resp_12.get("error", ""),
              f"[12] db_char_truncated claim khac voi luc ky -> chu ky khong khop, tu choi "
              f"(thuc te: {resp_12})")

        print("  -- [13] token da het han --")
        past = int(time.time()) - 3600
        req_13 = _build_request(auth_key_9, sample_id="s13", raw_content="noi dung s13",
                                auth_overrides={"issued_epoch": past, "expires_epoch": past + 30})
        resp_13 = await _raw_request(socket_9, req_13, timeout=3.0)
        check(resp_13 is not None and resp_13.get("ok") is False and "het han" in resp_13.get("error", ""),
              f"[13] token het han tu lau -> tu choi (thuc te: {resp_13})")

        print("  -- [14] TTL vuot qua muc cho phep (30s) --")
        now_epoch = int(time.time())
        req_14 = _build_request(auth_key_9, sample_id="s14", raw_content="noi dung s14",
                                auth_overrides={"issued_epoch": now_epoch, "expires_epoch": now_epoch + 3600})
        resp_14 = await _raw_request(socket_9, req_14, timeout=3.0)
        check(resp_14 is not None and resp_14.get("ok") is False and "TTL" in resp_14.get("error", ""),
              f"[14] TTL 3600s vuot qua 30s cho phep -> tu choi (thuc te: {resp_14})")

        print("  -- [15] key_version khong duoc ho tro --")
        req_15 = _build_request(auth_key_9, sample_id="s15", raw_content="noi dung s15",
                                auth_overrides={"key_version": "m4-signing-auth-v99-khong-ton-tai"})
        resp_15 = await _raw_request(socket_9, req_15, timeout=3.0)
        check(resp_15 is not None and resp_15.get("ok") is False and "key_version" in resp_15.get("error", ""),
              f"[15] key_version sai -> tu choi (thuc te: {resp_15})")

        print("  -- [16] dinh dang token sai (thieu phan, gio la 5 phan) --")
        req_16 = _build_request(auth_key_9, sample_id="s16", raw_content="noi dung s16")
        req_16["signing_authorization"] = "chi-1-phan-khong-du"
        resp_16 = await _raw_request(socket_9, req_16, timeout=3.0)
        check(resp_16 is not None and resp_16.get("ok") is False and "dinh dang" in resp_16.get("error", ""),
              f"[16] token dinh dang sai -> tu choi (thuc te: {resp_16})")

        print("  -- [17] replay: dung LAI CHINH XAC 1 token da dung thanh cong (CUNG instance) --")
        req_17 = _build_request(auth_key_9, sample_id="s17", raw_content="noi dung s17")
        resp_17a = await _raw_request(socket_9, req_17, timeout=3.0)
        check(resp_17a is not None and resp_17a.get("ok") is True,
              f"[17] lan 1 (token con moi, chua dung) -> thanh cong (thuc te: {resp_17a and resp_17a.get('ok')})")
        resp_17b = await _raw_request(socket_9, req_17, timeout=3.0)
        check(resp_17b is not None and resp_17b.get("ok") is False and "replay" in resp_17b.get("error", ""),
              f"[17] lan 2 (CUNG token) -> tu choi (replay, Redis) (thuc te: {resp_17b})")
    finally:
        await stop_signing_service(proc_9, socket_9)

    print("== [18] T13-02: replay SAU KHI signer instance RESTART (tien trinh MOI, CUNG Redis+auth "
          "key) — token dung TRUOC restart van bi tu choi ==")
    socket_18 = f"/tmp/m4-sst-18-{os.getpid()}/sock"
    shared_auth_key_18 = os.urandom(32)
    proc_18a, _sk18a, _hk18a, _ak18a = await start_signing_service(
        socket_path=socket_18, allowed_uid=os.getuid(), auth_verify_key=shared_auth_key_18)
    req_18 = _build_request(shared_auth_key_18, sample_id="s18-restart", raw_content="noi dung s18")
    resp_18a = await _raw_request(socket_18, req_18, timeout=3.0)
    check(resp_18a is not None and resp_18a.get("ok") is True,
          f"[18] lan 1 TRUOC restart -> thanh cong (thuc te: {resp_18a and resp_18a.get('ok')})")
    await stop_signing_service(proc_18a, socket_18)

    proc_18b, _sk18b, _hk18b, _ak18b = await start_signing_service(
        socket_path=socket_18, allowed_uid=os.getuid(), auth_verify_key=shared_auth_key_18)
    try:
        resp_18b = await _raw_request(socket_18, req_18, timeout=3.0)
        check(resp_18b is not None and resp_18b.get("ok") is False and "replay" in resp_18b.get("error", ""),
              f"[18] SAU restart (tien trinh signer MOI) -> CUNG token van bi tu choi (replay) - "
              f"chung minh state Redis TON TAI qua process restart, khac han cache trong-bo-nho "
              f"REV13 (thuc te: {resp_18b})")
    finally:
        await stop_signing_service(proc_18b, socket_18)

    print("== [19] T13-02: 2 signer instance KHAC NHAU (socket khac, CUNG Redis+auth key) nhan CUNG "
          "1 token DONG THOI -> DUNG 1 thanh cong ==")
    socket_19a = f"/tmp/m4-sst-19a-{os.getpid()}/sock"
    socket_19b = f"/tmp/m4-sst-19b-{os.getpid()}/sock"
    shared_auth_key_19 = os.urandom(32)
    proc_19a, _sk19a, _hk19a, _ak19a = await start_signing_service(
        socket_path=socket_19a, allowed_uid=os.getuid(), auth_verify_key=shared_auth_key_19)
    proc_19b, _sk19b, _hk19b, _ak19b = await start_signing_service(
        socket_path=socket_19b, allowed_uid=os.getuid(), auth_verify_key=shared_auth_key_19)
    try:
        req_19 = _build_request(shared_auth_key_19, sample_id="s19-2instances", raw_content="noi dung s19")
        resp_19a, resp_19b = await asyncio.gather(
            _raw_request(socket_19a, req_19, timeout=5.0),
            _raw_request(socket_19b, req_19, timeout=5.0),
        )
        ok_count_19 = sum(1 for r in (resp_19a, resp_19b) if r is not None and r.get("ok") is True)
        check(ok_count_19 == 1,
              f"[19] 2 signer instance KHAC NHAU, CUNG token, goi DONG THOI -> DUNG 1 thanh cong "
              f"(thuc te {ok_count_19}/2 — Redis SET NX PX dung CHUNG giua cac instance, T13-02) "
              f"[{resp_19a}, {resp_19b}]")
    finally:
        await stop_signing_service(proc_19a, socket_19a)
        await stop_signing_service(proc_19b, socket_19b)

    print("== [20] T13-03: burst vuot ngan sach rate-limit -> mot phan bi tu choi TRUOC khi doc "
          "frame, tu phuc hoi co kiem soat sau khi cua so lan sau bat dau ==")
    socket_20 = f"/tmp/m4-sst-20-{os.getpid()}/sock"
    proc_20, _sk20, _hk20, auth_key_20 = await start_signing_service(socket_path=socket_20, allowed_uid=os.getuid())
    try:
        n_burst = 60  # vuot han ngan sach 40/10s cua service

        async def _burst_one(i: int):
            req_i = _build_request(auth_key_20, sample_id=f"s20-burst-{i}",
                                   raw_content=f"noi dung burst {i}", message_id=1000 + i, txid=1000 + i)
            return await _raw_request(socket_20, req_i, timeout=3.0)

        results_20 = await asyncio.gather(*(_burst_one(i) for i in range(n_burst)))
        ok_20 = sum(1 for r in results_20 if r is not None and r.get("ok") is True)
        none_20 = sum(1 for r in results_20 if r is None)
        check(ok_20 <= 40, f"[20] burst {n_burst} request trong 1 cua so -> KHONG vuot ngan sach "
              f"40 request duoc XU LY (thuc te {ok_20} thanh cong)")
        check(none_20 > 0, f"[20] it nhat 1 request bi tu choi boi rate-limit (khong co response - "
              f"tu choi TRUOC khi doc frame) (thuc te {none_20}/{n_burst} khong co response)")

        await asyncio.sleep(_RATE_LIMIT_WINDOW_SECONDS_REF + 0.5)
        req_recover = _build_request(auth_key_20, sample_id="s20-recover",
                                     raw_content="noi dung phuc hoi", message_id=2000, txid=2000)
        resp_recover = await _raw_request(socket_20, req_recover, timeout=3.0)
        check(resp_recover is not None and resp_recover.get("ok") is True,
              f"[20] SAU KHI cua so cu het han -> request MOI thanh cong (tu phuc hoi co kiem soat) "
              f"(thuc te: {resp_recover})")
    finally:
        await stop_signing_service(proc_20, socket_20)

    print("== [21] F-A08-R2-01: khoi dong THAT qua 3 khoa dang FILE (khong con gia tri THO trong "
          "env) voi permission dung (0400, chinh chu) -> thanh cong, round-trip day du ==")
    signer_uid_21, _collector_uid_21, _other_21, _shared_21 = ensure_service_accounts()
    dir_21 = f"/tmp/m4-sst-21-{os.getpid()}"
    secrets_dir_21 = f"{dir_21}/secrets"
    socket_dir_21 = f"{dir_21}/sock-dir"
    os.makedirs(secrets_dir_21, mode=0o700, exist_ok=True)
    os.makedirs(socket_dir_21, mode=0o700, exist_ok=True)
    os.chmod(secrets_dir_21, 0o700)
    os.chmod(socket_dir_21, 0o700)
    socket_21 = f"{socket_dir_21}/sock"
    sample_key_21, hmac_key_21, auth_key_21 = os.urandom(32), os.urandom(32), os.urandom(32)
    proc_21 = await _spawn_with_secret_files(
        socket_21, sample_key=sample_key_21, hmac_key=hmac_key_21, auth_verify_key=auth_key_21,
        allowed_uid=os.getuid(), secret_dir=secrets_dir_21, file_mode=0o400)
    try:
        req_21 = _build_request(auth_key_21, sample_id="s21-file-secrets",
                                raw_content="noi dung test khoa dang file")
        result_21 = await request_signature(
            socket_21, batch_id=req_21["batch_id"], conversation_id=req_21["conversation_id"],
            message_id=req_21["message_id"], sample_id=req_21["sample_id"],
            raw_content=req_21["raw_content"], customer_ref=req_21["customer_ref"],
            conversation_ref=req_21["conversation_ref"], purpose_code=req_21["purpose_code"],
            txid=req_21["txid"], signing_authorization=req_21["signing_authorization"])
        check(bool(result_21.key_version),
              f"[21] service khoi dong THANH CONG qua khoa dang FILE va ky DUNG (round-trip khong "
              f"loi, thuc te key_version={result_21.key_version!r})")
        settings.m4_sample_key_b64 = base64.b64encode(sample_key_21).decode()
        plaintext_21 = decrypt_sample_value(result_21.ciphertext, customer_ref="cust-1",
                                            conversation_ref="1", sample_id="s21-file-secrets")
        canonical_text_21, _t21 = canonicalize("noi dung test khoa dang file")
        check(plaintext_21 == canonical_text_21,
              "[21] giai ma lai (bang chinh sample_key da doc tu FILE) ra DUNG canonical_text")
    finally:
        await stop_signing_service(proc_21, socket_21)
        for path_21 in os.listdir(secrets_dir_21):
            os.unlink(os.path.join(secrets_dir_21, path_21))
        os.rmdir(secrets_dir_21)
        os.rmdir(dir_21)

    print("== [22] F-A08-R2-01: 1 file khoa co bit group/other (world-readable, mo phong bind-mount "
          "khong giu dung permission) -> service TU CHOI khoi dong, KHONG bao gio doc noi dung ==")
    dir_22 = f"/tmp/m4-sst-22-{os.getpid()}"
    secrets_dir_22 = f"{dir_22}/secrets"
    socket_dir_22 = f"{dir_22}/sock-dir"
    os.makedirs(secrets_dir_22, mode=0o700, exist_ok=True)
    os.makedirs(socket_dir_22, mode=0o700, exist_ok=True)
    os.chmod(secrets_dir_22, 0o700)
    os.chmod(socket_dir_22, 0o700)
    socket_22 = f"{socket_dir_22}/sock"
    proc_22 = await _spawn_with_secret_files(
        socket_22, sample_key=os.urandom(32), hmac_key=os.urandom(32),
        auth_verify_key=os.urandom(32), allowed_uid=os.getuid(), secret_dir=secrets_dir_22,
        file_mode=0o644,  # CO Y qua rong (world-readable) - mo phong bind-mount hong permission
        wait_ready=False)  # mong doi THAT BAI - dung wait_signing_service_exit rieng ben duoi
    paths_22 = [os.path.join(secrets_dir_22, p) for p in os.listdir(secrets_dir_22)]
    rc_22, out_22 = await wait_signing_service_exit(proc_22, timeout=5.0)
    check(rc_22 != 0, "[22] file khoa mode 0644 (world-readable) -> service thoat KHONG THANH CONG")
    check(not os.path.exists(socket_22), "[22] KHONG co socket nao duoc tao (service chua bao gio "
                                        "lang nghe/dung khoa)")
    check("rong quyen" in out_22 or "qua rong quyen" in out_22,
          f"[22] thong diep loi de cap 'qua rong quyen' (thuc te: {out_22.strip()[:200]!r})")
    for p in paths_22:
        os.unlink(p)
    os.rmdir(secrets_dir_22)
    os.rmdir(socket_dir_22)
    os.rmdir(dir_22)

    print("== [23] F-A08-R2-01: 1 file khoa KHONG thuoc so huu tien trinh signing service (chu so "
          "huu khac) -> service TU CHOI khoi dong ==")
    _signer_uid_23, collector_uid_23, _other_23, _shared_23 = ensure_service_accounts()
    dir_23 = f"/tmp/m4-sst-23-{os.getpid()}"
    secrets_dir_23 = f"{dir_23}/secrets"
    socket_dir_23 = f"{dir_23}/sock-dir"
    os.makedirs(secrets_dir_23, mode=0o700, exist_ok=True)
    os.makedirs(socket_dir_23, mode=0o700, exist_ok=True)
    os.chmod(secrets_dir_23, 0o700)
    os.chmod(socket_dir_23, 0o700)
    socket_23 = f"{socket_dir_23}/sock"
    proc_23 = await _spawn_with_secret_files(
        socket_23, sample_key=os.urandom(32), hmac_key=os.urandom(32),
        auth_verify_key=os.urandom(32), allowed_uid=os.getuid(), secret_dir=secrets_dir_23,
        file_mode=0o400,  # dung permission...
        owner_uid=collector_uid_23,  # ...nhung SAI chu so huu (khong phai UID service dang chay)
        wait_ready=False)  # mong doi THAT BAI - dung wait_signing_service_exit rieng ben duoi
    paths_23 = [os.path.join(secrets_dir_23, p) for p in os.listdir(secrets_dir_23)]
    rc_23, out_23 = await wait_signing_service_exit(proc_23, timeout=5.0)
    check(rc_23 != 0, "[23] file khoa sai chu so huu -> service thoat KHONG THANH CONG")
    check(not os.path.exists(socket_23), "[23] KHONG co socket nao duoc tao")
    check("khong thuoc so huu" in out_23,
          f"[23] thong diep loi de cap sai chu so huu (thuc te: {out_23.strip()[:200]!r})")
    for p in paths_23:
        os.chown(p, os.getuid(), -1)  # tra lai quyen root de xoa duoc
        os.unlink(p)
    os.rmdir(secrets_dir_23)
    os.rmdir(socket_dir_23)
    os.rmdir(dir_23)

    print("== [24] F-A08-R3-01: THU MUC CHA cua 3 file khoa root:root 0700 (dung y HET runbook lỗi "
          "CA Review 3 phat hien), du TUNG FILE ben trong permission DUNG, chay duoi UID signer "
          "THAT (khong phai UID cua tien trinh test) -> service TU CHOI khoi dong vi KHONG traverse "
          "duoc vao thu muc cha ==")
    signer_uid_24, _collector_uid_24, _other_24, shared_gid_24 = ensure_service_accounts()
    dir_24 = f"/tmp/m4-sst-24-{os.getpid()}"
    secrets_dir_24 = f"{dir_24}/secrets"
    socket_dir_24 = f"{dir_24}/sock-dir"
    os.makedirs(secrets_dir_24, mode=0o700, exist_ok=True)
    os.chmod(secrets_dir_24, 0o700)  # CO Y KHONG chown cho signer_uid_24 - GIONG HET bug runbook
                                     # (root:root 0700 - chi root traverse duoc)
    os.makedirs(socket_dir_24, mode=0o700, exist_ok=True)
    os.chown(socket_dir_24, signer_uid_24, shared_gid_24)  # socket dir van phai dung (khong phai
    os.chmod(socket_dir_24, 0o700)                          # trong tam kich ban nay)
    socket_24 = f"{socket_dir_24}/sock"
    proc_24 = await _spawn_with_secret_files(
        socket_24, sample_key=os.urandom(32), hmac_key=os.urandom(32),
        auth_verify_key=os.urandom(32), allowed_uid=os.getuid(), secret_dir=secrets_dir_24,
        file_mode=0o400, owner_uid=signer_uid_24,  # TUNG FILE dung permission/chu so huu...
        run_as_uid=signer_uid_24,  # ...nhung chay duoi UID signer THAT (khong phai root/test)
        wait_ready=False)  # mong doi THAT BAI - dung wait_signing_service_exit rieng ben duoi
    rc_24, out_24 = await wait_signing_service_exit(proc_24, timeout=5.0)
    check(rc_24 != 0, "[24] thu muc cha root:root 0700 -> service (UID signer that) thoat KHONG "
                      "THANH CONG du tung file ben trong permission dung")
    check(not os.path.exists(socket_24), "[24] KHONG co socket nao duoc tao (chua bao gio doc "
                                        "duoc secret, chua toi buoc lang nghe)")
    check("thu muc cha" in out_24 and "khong thuoc so huu" in out_24,
          f"[24] thong diep loi de cap RO RANG la THU MUC CHA (khong phai file) sai chu so huu "
          f"(thuc te: {out_24.strip()[:250]!r})")
    for p in os.listdir(secrets_dir_24):
        os.unlink(os.path.join(secrets_dir_24, p))
    os.rmdir(secrets_dir_24)
    os.rmdir(socket_dir_24)
    os.rmdir(dir_24)

    print("== [25] F-A08-R3-01: THU MUC CHA cua 3 file khoa duoc chown DUNG cho UID signer (khop "
          "runbook DA SUA, khong con root:root) -> service (UID signer THAT) khoi dong THANH CONG, "
          "round-trip day du ==")
    signer_uid_25, _collector_uid_25, _other_25, shared_gid_25 = ensure_service_accounts()
    dir_25 = f"/tmp/m4-sst-25-{os.getpid()}"
    secrets_dir_25 = f"{dir_25}/secrets"
    socket_dir_25 = f"{dir_25}/sock-dir"
    os.makedirs(secrets_dir_25, mode=0o700, exist_ok=True)
    os.chown(secrets_dir_25, signer_uid_25, shared_gid_25)  # KHAC [24]: chown dung cho signer UID
    os.chmod(secrets_dir_25, 0o700)
    os.makedirs(socket_dir_25, mode=0o700, exist_ok=True)
    os.chown(socket_dir_25, signer_uid_25, shared_gid_25)
    os.chmod(socket_dir_25, 0o700)
    socket_25 = f"{socket_dir_25}/sock"
    sample_key_25, hmac_key_25, auth_key_25 = os.urandom(32), os.urandom(32), os.urandom(32)
    proc_25 = await _spawn_with_secret_files(
        socket_25, sample_key=sample_key_25, hmac_key=hmac_key_25, auth_verify_key=auth_key_25,
        allowed_uid=os.getuid(), secret_dir=secrets_dir_25, file_mode=0o400,
        owner_uid=signer_uid_25, run_as_uid=signer_uid_25)
    try:
        req_25 = _build_request(auth_key_25, sample_id="s25-parent-dir-fixed",
                                raw_content="noi dung test thu muc cha da sua dung")
        result_25 = await request_signature(
            socket_25, batch_id=req_25["batch_id"], conversation_id=req_25["conversation_id"],
            message_id=req_25["message_id"], sample_id=req_25["sample_id"],
            raw_content=req_25["raw_content"], customer_ref=req_25["customer_ref"],
            conversation_ref=req_25["conversation_ref"], purpose_code=req_25["purpose_code"],
            txid=req_25["txid"], signing_authorization=req_25["signing_authorization"])
        check(bool(result_25.key_version),
              f"[25] service (UID signer THAT) khoi dong THANH CONG qua thu muc cha da chown dung, "
              f"round-trip khong loi (thuc te key_version={result_25.key_version!r})")
        settings.m4_sample_key_b64 = base64.b64encode(sample_key_25).decode()
        plaintext_25 = decrypt_sample_value(result_25.ciphertext, customer_ref="cust-1",
                                            conversation_ref="1", sample_id="s25-parent-dir-fixed")
        canonical_text_25, _t25 = canonicalize("noi dung test thu muc cha da sua dung")
        check(plaintext_25 == canonical_text_25,
              "[25] giai ma lai ra DUNG canonical_text - xac nhan Linux evidence THAT (khong phai "
              "Windows bind-mount) chap nhan duoc cho production path")
    finally:
        await stop_signing_service(proc_25, socket_25)
        for p in os.listdir(secrets_dir_25):
            os.unlink(os.path.join(secrets_dir_25, p))
        os.rmdir(secrets_dir_25)
        os.rmdir(dir_25)

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
