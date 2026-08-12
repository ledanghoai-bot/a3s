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
     them co che o tang signing service.

CA Technical Re-review #12 (F-M4-0P-T12-01/T12-02, P1): REV12 dat `allowed_uid` MAC DINH bang
`os.getuid()` cua CHINH tien trinh signing service — vi collector va service REV12 chay CUNG uid
trong mo hinh dev/test 1 host, "peer uid khop allowed_uid" luon DUNG cho BAT KY tien trinh nao chay
cung uid do (khong rieng collector) — CA: "signer van la oracle cho moi process cung UID". Test
"wrong peer UID" cu chi doi gia tri EXPECTED sai roi ket noi tu CUNG 1 principal — khong chung minh
co 2 principal THAT. Dong thoi, request van chua rang buoc voi 1 authorization/scope cu the — signer
van ky bat ky request nao qua duoc peer-UID check.

Sua REV13 — dong ca 2 finding:

T12-01 (danh tinh he dieu hanh THAT tach biet, khong con "tu tin chinh minh"):
  - `_allowed_uid()` KHONG con mac dinh `os.getuid()` — PHAI cau hinh tuong minh qua
    `STAGE0P_SIGNING_ALLOWED_UID`, thieu thi `main()` tu choi khoi dong (fail closed). Loai bo hoan
    toan truong hop "tu tin chinh minh" (signer tu dong coi UID cua no la UID duoc phep).
  - Signer VA collector gio chay duoi 2 UID THAT KHAC NHAU (`m4-signer`/`m4-collector`, tao qua
    `useradd`, xem `_stage0p_signing_service_helper.py:ensure_service_accounts()`). Vi socket file
    mode 0600 owner-only (T11-02) se chan CA CHINH collector (khac uid voi signer), them tham so
    `shared_gid` (env `STAGE0P_SIGNING_SHARED_GID`) — khi duoc cau hinh, thu muc socket dung mode
    0710 (owner rwx, group CHI `--x` de di qua, KHONG doc/ghi duoc noi dung thu muc) + gid dung
    group chia se, file socket mode 0660 (owner+group rw) — CA da liet ke ro "socket mode 0600
    hoac group policy toi thieu tuong duong" la 2 lua chon hop le. KHONG dung `shared_gid` (mac
    dinh, giu nguyen mo hinh 1-UID REV11/REV12) van dung DUNG mode 0600 nghiem ngat cu.
  - Evidence (`m4_stage0p_signing_service_test.py`) dung 2 UID HE DIEU HANH THAT KHAC NHAU — 1
    tien trinh con chay duoi UID "collector" that su goi thanh cong, 1 tien trinh con KHAC chay
    duoi UID thu 3 (khong phai signer, khong phai collector, khong thuoc shared group) bi tu choi
    TRUOC khi frame duoc doc.

T12-02 (rang buoc request voi authority/scope, chong replay - Huong 1 CA de xuat: DB/trusted-
coordinator cap 1 authorization ngan han):
  - `m4_stage0p_fetch_message_content()` (migration 039 §5b, CUNG transaction voi capability T4-01)
    gio TU KY 1 "signing authorization" HMAC-SHA256 TTL 30s buoc vao CHINH
    (batch_id, conversation_id, message_id, sample_id, purpose_code, txid) cua request — collector
    CHI relay nguyen ven token nay (opaque, `key_version|issued_epoch|expires_epoch|signature_hex`)
    sang signing service qua IPC, khong tu tao/sua duoc (khong giu khoa `m4_signing_auth_verify_key_b64`
    — CHI signing service moi doc truong nay tu moi truong CUA CHINH NO).
  - `_verify_signing_authorization()`: tai dung payload TU CAC TRUONG DA CO san trong `req` (khong
    tin tuong bat ky truong nao TRONG token ngoai issued/expires/key_version/signature — batch_id/
    conversation_id/message_id/sample_id/purpose_code/txid DEU lay tu chinh `req`, roi doi chieu chu
    ky) — bat ky truong nao trong `req` bi sua doi (kha ca do 1 collector-adjacent process gia mao)
    se lam HMAC khong khop, bi tu choi TRUOC khi ky/ma hoa bat ky noi dung nao.
  - Chong replay: 1 cache trong-bo-nho (`_replay_seen`, vong doi = tien trinh) khoa boi
    (txid, sample_id) — request THU HAI voi CUNG cap doi nay trong cua so replay bi tu choi, ke ca
    khi token con hieu luc TTL.
  - Ket hop: 3 lop doc lap (peer-UID T11-02/T12-01, chu ky authorization T12-02, DB verify transcript
    T8-02/T10-04) — 1 process CUNG UID voi signer nhung KHONG co token hop le van khong ky duoc gi;
    1 token hop le nhung sai UID cung bi chan truoc khi doc frame.

CA Technical Re-review #13 (T12-01 CLOSED AT DEV/TEST CODE-DESIGN LEVEL; F-M4-0P-T13-01/T13-02,
P1; F-M4-0P-T13-03, P2): REV13 payload chi gom
`batch_id|conversation_id|message_id|sample_id|purpose_code|txid|issued|expires` — CHUA buoc
canonical digest cua noi dung THAT, CHUA buoc customer_ref/conversation_ref (dung trong AAD/
transcript), CHUA co domain/operation tag, va noi chuoi bang '|' KHONG unambiguous (khong length-
prefixed). CA: "một authorized collector process có thể fetch message/token hợp lệ, thay
raw_content hoặc AAD-related fields và vẫn yêu cầu signer tạo ciphertext/signature" — signing-
oracle gap T12-02 nham toi VAN CON TON TAI. Dong thoi `_replay_seen` REV13 la dictionary TRONG BO
NHO CUA 1 TIEN TRINH — restart signer xoa toan bo state, 2 signer instance co 2 cache doc lap —
KHONG phai one-time semantics THAT SU.

Sua REV14 — dong ca 3 finding:

T13-01 (buoc authorization voi content digest + toan bo output-affecting input):
  - `m4_stage0p_fetch_message_content()` (migration) gio TU DERIVE `customer_id` tu CHINH
    `m4_stage0p_capture_progress` (KHONG con nhan tu caller — 1 diem caller-tu-khai nua bi loai bo,
    dung nguyen tac T4-04/T5-01/T9-02), TU TINH `canonical_digest_hex` tu CHINH canonical text
    (`v_canon`) no vua tinh cho `fetched_canonical_digest` (T4-01/T6-02) — CUNG 1 gia tri, khong
    tinh lai rieng. Payload gio la 14 truong (domain tag co dinh
    `m4-stage0p-sign-capture-v1` + batch/conversation/message/sample identity + customer_ref +
    conversation_ref + purpose_code + txid + canonical_digest_hex + char_truncated + nonce +
    issued/expires), noi bang LENGTH-PREFIX (`<so-byte>:<gia-tri>` noi tiep, khong dung dau phan
    cach `|`) — loai bo hoan toan kha nang 1 truong chua ky tu dac biet lam lech ranh gioi cac
    truong khac.
  - Signer (`_verify_signing_authorization`) gio nhan THEM `canonical_digest_hex`/`char_truncated`
    do CHINH no tu tinh (SAU KHI da canonicalize `raw_content` — thu tu bat buoc: canonicalize
    TRUOC, verify authorization SAU, ky SAU CUNG) — tai dung CHINH XAC thuat toan length-prefix
    phia DB de doi chieu chu ky. `conversation_ref` dung trong ma hoa/AAD KHONG con lay tu
    `req["conversation_ref"]` (truong caller tu khai, khong doc lap voi conversation_id) — signer
    TU DERIVE `str(conversation_id)` (da la 1 truong duoc bind qua chu ky) thay vi tin 1 truong
    rieng co the bi tach roi khoi conversation_id that.
  - Bat ky truong nao (raw_content, customer_ref, db_char_truncated, ...) bi sai lech so voi luc
    DB ky deu lam HMAC khong khop — tu choi TRUOC khi ma hoa/ky, dong dung "signing-oracle" gap.

T13-02 (chong replay BEN VUNG/DUNG CHUNG moi signer instance, ton tai qua restart):
  - Token gio mang 1 `nonce` ngau nhien (`gen_random_uuid()`, 128-bit) — buoc VAO payload (chong
    gia mao) VA dua RIENG vao token (ngoai payload, cung vi tri voi issued/expires) de signer dung
    lam khoa tieu thu.
  - Thay `_replay_seen` (dict trong-bo-nho) bang Redis `SET NX PX` (`_consume_nonce_once()`) — TTL
    Redis = thoi gian con lai cua token + bien an toan, tu don khi token that su het han. Dung
    CHUNG `settings.redis_url` (CUNG instance Redis moi collector/pending-check khac dang dung,
    KHONG phai secret — chi la ha tang dung chung) — nen state chong replay giờ BEN VUNG qua
    restart signer VA dung CHUNG giua NHIEU signer instance (khong con moi process 1 cache rieng).
    Redis loi/timeout -> FAIL CLOSED (tu choi, khong tien toi ky) — dung nguyen tac fail-closed da
    dung xuyen suot Stage 0P (`stage0p_eligibility.py:is_pending_deletion`).
  - Thu tu bat buoc: verify chu ky+digest TRUOC (khong tac dung phu) -> tieu thu nonce qua Redis
    (atomic, CHI SAU KHI da xac nhan token hop le) -> ky/ma hoa SAU CUNG. Neu signer chet SAU khi
    tieu thu nonce nhung TRUOC khi tra ket qua ve collector, nonce do vinh vien mat hieu luc (dung
    y "one-time") — collector PHAI fetch capability+token MOI (khong the retry voi token cu), dung
    tinh than consume-on-use da dung nhieu lan (T4-01/T7-01) trong du an nay.

T13-03 (P2, request-rate/admission budget):
  - `asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)` REV13 CHI gioi han so request DONG THOI, khong
    gioi han TOC DO request TUAN TU. Them `_check_rate_limit()` — fixed-window (10s, toi da 40
    request/cua so) TRUOC KHI xu ly 1 ket noi da qua peer-UID check — vuot han bi tu choi ngay
    (`m4_signing_rate_limited`), tu phuc hoi khi cua so lan sau bat dau."""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import socket
import stat
import struct
import sys
import time
from functools import partial

import redis.asyncio as aioredis

from app.config import settings
from app.services.pii.canonicalize import canonicalize
from app.services.pii.crypto import SlotCryptoError, _load_key, sign_capture

_MAX_FRAME_BYTES = 1_000_000  # 1MB - du cho 1 tin nhan da cat toi da MAX_BYTES + metadata JSON
_SOCKET_FILE_MODE = 0o600
_SOCKET_FILE_MODE_SHARED = 0o660  # T12-01: mo hinh shared_gid - owner+group rw, khong OTHER
_SOCKET_DIR_FORBIDDEN_MODE_BITS = 0o077  # T11-02: khong duoc co bat ky bit group/other nao
_MAX_CONCURRENT_REQUESTS = 8
_REQUEST_TIMEOUT_SECONDS = 5.0
_PEERCRED_STRUCT = struct.Struct("3i")  # pid, uid, gid (Linux SO_PEERCRED)

# T13-03: fixed-window admission budget - AP DUNG SAU peer-UID check (chi tinh traffic tu peer da
# xac thuc). 40/10s rong hon han 20 request DONG THOI cua kich ban [7] hien co (khong pha vo
# evidence cu) nhung van la 1 TRAN THAT, co the vuot va tu phuc hoi khi cua so lan sau bat dau.
_RATE_LIMIT_WINDOW_SECONDS = 10.0
_RATE_LIMIT_MAX_REQUESTS = 40

# T12-02: PHAI khop CHINH XAC key_version DB dung khi ky (migration 039 provisioning) - khong ho
# tro nhieu key_version dong thoi (dung mo hinh don-khoa-hoat-dong nhu m4_transcript_hmac_key_b64).
_SIGNING_AUTH_KEY_VERSION = "m4-signing-auth-v1"
_SIGNING_AUTH_MAX_TTL_SECONDS = 30
_SIGNING_AUTH_CLOCK_SKEW_SECONDS = 5
# T13-01: domain/operation tag co dinh - truong DAU TIEN trong payload length-prefix, phan biet
# muc dich token nay voi bat ky loai authorization nao khac co the ton tai trong tuong lai.
_AUTH_DOMAIN_TAG = "m4-stage0p-sign-capture-v1"
# T13-02: Redis SET NX PX dung cho tieu thu nonce 1 lan - CHUNG cho moi signer instance, ton tai
# qua restart (khac han _replay_seen trong-bo-nho REV13 da bi CA tu choi).
_NONCE_KEY_PREFIX = "m4-signing-nonce:"
_NONCE_REDIS_TIMEOUT_SECONDS = 3.0
_NONCE_TTL_BUFFER_SECONDS = 30


class SigningAuthorizationError(Exception):
    """Signing authorization thieu/sai dinh dang/chu ky khong khop/het han/da bi replay (T12-02/
    T13-01/T13-02)."""


_rate_limit_timestamps: list[float] = []


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


def _lenpfx_join(*fields: str) -> bytes:
    """T13-01: ma hoa canonical KHONG mo ho — moi truong tien to boi do dai byte cua chinh no
    (`<so-byte>:<gia-tri>`) roi noi tiep, KHONG dung ky tu phan cach nao ca — loai bo hoan toan
    kha nang 1 gia tri truong CHUA 1 ky tu "phan cach" nao do lam lech ranh gioi cac truong con
    lai. PHAI khop CHINH XAC thuat toan PL/pgSQL phia migration 039 (vong lap qua ARRAY, noi
    `octet_length(field)::text || ':' || field`)."""
    out = bytearray()
    for f in fields:
        b = f.encode("utf-8")
        out += str(len(b)).encode("ascii") + b":" + b
    return bytes(out)


def _verify_signing_authorization(token: str, req: dict, *, canonical_digest_hex: str,
                                  char_truncated: bool) -> tuple[str, int]:
    """T12-02/T13-01: xac minh 1 signing authorization DB da ky trong CUNG transaction voi
    capability T4-01 (`m4_stage0p_fetch_message_content`). PHAI goi SAU KHI da tu canonicalize
    `raw_content` va tu tinh `canonical_digest_hex`/`char_truncated` — token gio buoc CA 2 gia tri
    nay (T13-01, dong "signing-oracle" gap: doi noi dung/AAD-affecting field ma khong sua token se
    lam HMAC khong khop). `conversation_ref` dung trong payload la `str(conversation_id)` (DA duoc
    bind qua chinh conversation_id) — KHONG doc tu `req["conversation_ref"]` (truong caller tu
    khai, co the bi tach roi khoi conversation_id that). Tra ve `(nonce, expires_epoch)` — caller
    (`_handle_request`) PHAI tu tieu thu nonce qua Redis (T13-02) TRUOC khi ky/ma hoa."""
    parts = token.split("|")
    if len(parts) != 5:
        raise SigningAuthorizationError("signing_authorization dinh dang khong hop le")
    key_version, issued_s, expires_s, nonce, sig_hex = parts
    if key_version != _SIGNING_AUTH_KEY_VERSION:
        raise SigningAuthorizationError("signing_authorization key_version khong duoc ho tro")
    if not nonce:
        raise SigningAuthorizationError("signing_authorization thieu nonce")
    try:
        issued_epoch = int(issued_s)
        expires_epoch = int(expires_s)
        sig = bytes.fromhex(sig_hex)
    except ValueError as e:
        raise SigningAuthorizationError("signing_authorization truong khong hop le") from e

    if expires_epoch <= issued_epoch:
        raise SigningAuthorizationError("signing_authorization expires_epoch phai sau issued_epoch")
    if expires_epoch - issued_epoch > _SIGNING_AUTH_MAX_TTL_SECONDS:
        raise SigningAuthorizationError("signing_authorization TTL vuot qua muc cho phep")
    now_epoch = time.time()
    if now_epoch > expires_epoch + _SIGNING_AUTH_CLOCK_SKEW_SECONDS:
        raise SigningAuthorizationError("signing_authorization da het han")
    if now_epoch < issued_epoch - _SIGNING_AUTH_CLOCK_SKEW_SECONDS:
        raise SigningAuthorizationError("signing_authorization issued_epoch trong tuong lai")

    verify_key = _load_key(settings.m4_signing_auth_verify_key_b64, "m4_signing_auth_verify_key_b64")
    conversation_id_str = str(req["conversation_id"])
    payload = _lenpfx_join(
        _AUTH_DOMAIN_TAG, str(req["batch_id"]), conversation_id_str, str(req["message_id"]),
        str(req["sample_id"]), str(req["customer_ref"]), conversation_id_str,
        str(req["purpose_code"]), str(req["txid"]), canonical_digest_hex,
        "1" if char_truncated else "0", nonce, str(issued_epoch), str(expires_epoch),
    )
    expected_sig = hmac.new(verify_key, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_sig, sig):
        raise SigningAuthorizationError("signing_authorization chu ky khong khop (noi dung/request "
                                        "bi sua doi hoac khong xuat phat tu 1 fetch_message_content that)")
    return nonce, expires_epoch


async def _consume_nonce_once(nonce: str, *, expires_epoch: int) -> None:
    """T13-02: tieu thu nonce ATOMIC qua Redis `SET NX PX` — dung CHUNG cho MOI signer instance
    (khong con la cache trong-bo-nho rieng tung tien trinh nhu REV13/T12-02), TON TAI QUA process
    restart (Redis la tien trinh RIENG). Redis loi/timeout -> FAIL CLOSED (tu choi request, KHONG
    tien toi ky) — dung nguyen tac fail-closed da dung xuyen suot Stage 0P cho moi kiem tra phu
    thuoc Redis (xem `stage0p_eligibility.py:is_pending_deletion`)."""
    ttl_seconds = max(1, expires_epoch - int(time.time())) + _NONCE_TTL_BUFFER_SECONDS
    key = _NONCE_KEY_PREFIX + nonce
    try:
        redis = await aioredis.from_url(settings.redis_url, decode_responses=True,
                                        socket_timeout=_NONCE_REDIS_TIMEOUT_SECONDS,
                                        socket_connect_timeout=_NONCE_REDIS_TIMEOUT_SECONDS)
        try:
            ok = await asyncio.wait_for(
                redis.set(key, "1", nx=True, ex=ttl_seconds), timeout=_NONCE_REDIS_TIMEOUT_SECONDS)
        finally:
            await redis.aclose()
    except Exception as e:  # noqa: BLE001 - Redis loi/hang/timeout -> fail closed
        _log("m4_signing_nonce_consume_redis_error", error_type=type(e).__name__)
        raise SigningAuthorizationError(
            "khong the xac minh one-time nonce (Redis loi/timeout) - tu choi (fail closed)") from e
    if not ok:
        raise SigningAuthorizationError("signing_authorization da duoc su dung (replay, Redis)")


async def _handle_request(req: dict) -> dict:
    """REV11 T10-01: canonicalize + tu tinh digest/length/truncated TU raw_content — KHONG nhan
    bat ky gia tri nao trong so do tu `req` nhu authority (chi nhan raw_content + identity).
    REV14 T13-01/T13-02: thu tu BAT BUOC — canonicalize TRUOC (de co canonical_digest_hex/
    char_truncated that su) -> verify chu ky authorization (doi chieu CA 2 gia tri vua tinh) ->
    tieu thu nonce qua Redis (atomic, 1 lan) -> CHI SAU DO moi ky/ma hoa."""
    raw_content = req["raw_content"]
    canonical_text, was_truncated = canonicalize(raw_content)
    # DB-computed flag (noi dung GOC dai hon 2000 ky tu TRUOC khi cat ve raw_content) - KHONG the
    # tu suy ra tu raw_content da bi cat, nen phai nhan tu caller nhu 1 DU KIEN (khong phai
    # "authority" ve digest/length như CA lo ngai) roi OR vao ket qua tu-canonicalize cua chinh
    # service - van la service quyet dinh gia tri CUOI CUNG, khong phai collector.
    was_truncated = was_truncated or bool(req.get("db_char_truncated", False))
    canonical_digest_hex = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()

    nonce, expires_epoch = _verify_signing_authorization(
        req["signing_authorization"], req,
        canonical_digest_hex=canonical_digest_hex, char_truncated=was_truncated)
    await _consume_nonce_once(nonce, expires_epoch=expires_epoch)

    # T13-01: conversation_ref dung trong ma hoa/AAD TU DERIVE tu conversation_id (da duoc bind qua
    # chu ky) - KHONG doc tu req["conversation_ref"] (truong caller tu khai rieng biet).
    conversation_ref = str(req["conversation_id"])
    blob, transcript_bytes, signature, key_version = sign_capture(
        canonical_text,
        batch_id=req["batch_id"], conversation_id=req["conversation_id"],
        message_id=req["message_id"], sample_id=req["sample_id"],
        customer_ref=req["customer_ref"], conversation_ref=conversation_ref,
        canonical_len=len(canonical_text), truncated=was_truncated,
        txid=req["txid"], purpose_code=req["purpose_code"],
    )
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


def _check_rate_limit(now_mono: float) -> bool:
    """T13-03: fixed-window admission budget — True neu request duoc phep tien hanh (va tu ghi
    nhan luc do vao cua so). Danh cho traffic DA qua peer-UID check (T11-02/T12-01) — chi tinh
    ngan sach cho peer da xac thuc, khong lien quan gioi han concurrency (`_MAX_CONCURRENT_REQUESTS`,
    von chi gioi han so request DANG XU LY DONG THOI, khong gioi han TOC DO request tuan tu)."""
    global _rate_limit_timestamps
    cutoff = now_mono - _RATE_LIMIT_WINDOW_SECONDS
    _rate_limit_timestamps = [t for t in _rate_limit_timestamps if t > cutoff]
    if len(_rate_limit_timestamps) >= _RATE_LIMIT_MAX_REQUESTS:
        return False
    _rate_limit_timestamps.append(now_mono)
    return True


def _validate_socket_directory(socket_path: str, *, shared_gid: int | None = None) -> None:
    """T11-02/T12-01: startup FAIL NGAY neu thu muc cha khong an toan — khong ton tai, la symlink,
    khong thuoc so huu tien trinh nay, hoac co bit quyen KHONG PHU HOP (vd `/tmp` mode 1777 se bi
    TU CHOI o day). Socket path ban than, neu DA la 1 symlink co san, cung bi tu choi (chong tan
    cong pre-create-symlink tai duong dan du kien).

    `shared_gid`: T12-01 (REV13) — mo hinh 2 OS identity THAT su khac nhau (signer/collector) can
    1 co che de collector THAT SU mo duoc socket file (mode 0600 owner-only REV11/REV12 se chan
    CA CHINH collector, khong chi ke tan cong). CA cho phep ro rang "socket mode 0600 hoac group
    policy toi thieu tuong duong" — khi `shared_gid` duoc truyen, thu muc PHAI thuoc dung group do
    VA CHI duoc phep bit group `--x` (thuc thi/di qua, KHONG doc/ghi — khong the liet ke noi dung
    thu muc, chi mo duoc file socket neu DA BIET dung duong dan), KHONG duoc co bat ky bit OTHER
    nao. Neu `shared_gid` la None (mac dinh, mo hinh 1-UID REV11/REV12 khong doi), giu NGUYEN kiem
    tra nghiem ngat cu (KHONG duoc co bat ky bit group/other nao ca)."""
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
    mode = stat.S_IMODE(st.st_mode)
    if shared_gid is None:
        if mode & _SOCKET_DIR_FORBIDDEN_MODE_BITS:
            raise RuntimeError(
                f"signing socket directory qua rong quyen (mode={oct(mode)}, phai loai bo "
                f"group/other access): {directory}")
    else:
        if mode & 0o007:
            raise RuntimeError(
                f"signing socket directory co OTHER access (mode={oct(mode)}) - khong hop le "
                f"du dang dung mo hinh shared_gid: {directory}")
        if mode & 0o070 not in (0, 0o010):
            raise RuntimeError(
                f"signing socket directory group access qua rong (mode={oct(mode)}) - mo hinh "
                f"shared_gid CHI cho phep group '--x' (di qua, khong doc/ghi): {directory}")
        if st.st_gid != shared_gid:
            raise RuntimeError(
                f"signing socket directory khong thuoc dung shared_gid "
                f"(dir gid={st.st_gid}, expected={shared_gid}): {directory}")
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
    """T12-01: UID duy nhat duoc phep ket noi — PHAI cau hinh TUONG MINH qua
    `STAGE0P_SIGNING_ALLOWED_UID`, KHONG CON mac dinh `os.getuid()` cua chinh tien trinh nay (REV12
    coi "tu tin chinh minh" la 1 lo hong — bat ky process nao cung uid VOI SIGNER deu qua duoc check
    do la CHINH no). Thieu bien moi truong nay -> RuntimeError, `main()` tu choi khoi dong (fail
    closed) thay vi ngam dinh 1 gia tri khong that su xac dinh duoc collector la ai."""
    override = os.environ.get("STAGE0P_SIGNING_ALLOWED_UID")
    if override is None:
        raise RuntimeError(
            "STAGE0P_SIGNING_ALLOWED_UID chua duoc dat - REV13 T12-01 khong con mac dinh "
            "os.getuid() cua chinh signing service (tu tin chinh minh la 1 lo hong)")
    return int(override)


async def _handle_conn_authorized(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    raw_req = await _read_frame(reader)
    req = json.loads(raw_req.decode("utf-8"))
    try:
        resp = await _handle_request(req)
    except (SlotCryptoError, SigningAuthorizationError, KeyError, ValueError, TypeError) as e:
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
        if not _check_rate_limit(time.monotonic()):
            # T13-03: ngan sach admission vuot han - tu choi NGAY, khong doc frame (cung tinh than
            # fail-closed-truoc-frame nhu peer-UID check).
            _log("m4_signing_rate_limited")
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


async def run_signing_service(socket_path: str, *, allowed_uid: int | None = None,
                              shared_gid: int | None = None) -> None:
    _validate_socket_directory(socket_path, shared_gid=shared_gid)
    if os.path.lexists(socket_path):
        os.unlink(socket_path)
    resolved_allowed_uid = _allowed_uid() if allowed_uid is None else allowed_uid
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)
    handler = partial(_handle_conn, semaphore=semaphore, allowed_uid=resolved_allowed_uid)
    server = await asyncio.start_unix_server(handler, path=socket_path)
    if shared_gid is None:
        os.chmod(socket_path, _SOCKET_FILE_MODE)  # T11-02: chi owner doc/ghi duoc file socket
    else:
        # T12-01: owner + group duoc phep doc/ghi (collector THAT SU la thanh vien group nay moi
        # mo duoc socket - group khac/other KHONG the). Chgrp hop le vi tien trinh nay (owner file
        # vua tao) la thanh vien cua shared_gid (khong can quyen root cho buoc nay).
        os.chown(socket_path, -1, shared_gid)
        os.chmod(socket_path, _SOCKET_FILE_MODE_SHARED)
    _log("m4_signing_service_started", socket_path=socket_path, allowed_uid=resolved_allowed_uid,
        shared_gid=shared_gid)
    async with server:
        await server.serve_forever()


_SECRET_FILE_FORBIDDEN_MODE_BITS = 0o077  # group/other: khong duoc co bat ky bit nao


def _validate_secret_parent_directory(file_path: str) -> None:
    """F-A08-R3-01 (dap PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-3-VI.md): thu
    muc CHA cua secret file PHAI thuoc so huu CHINH tien trinh nay va khong duoc co bat ky bit
    group/other nao — CUNG triet ly va CUNG pattern voi `_validate_socket_directory()` o tren, ap
    dung rieng cho thu muc chua 3 file khoa (F-A08-R2-01).

    Neu chi kiem tung FILE (nhu REV2 lam) ma bo qua thu muc CHA, 1 runbook vo y tao thu muc cha
    `root:root 0700` (chi root traverse duoc) van khien tien trinh signer (UID 5001) KHONG BAO GIO
    mo duoc file du file ban than co permission dung 0400/5001:5000 — day CHINH LA lo hong that su
    (khong phai ly thuyet) CA Review 3 phat hien trong chinh runbook REV2. `os.stat(directory)` o
    day THANH CONG du process khong traverse duoc VAO thu muc (stat 1 doi tuong chi can quyen tren
    THU MUC CHA CUA NO, khong phai tren chinh no) — nen kiem duoc TRUOC KHI thu mo file ben trong,
    cho ra thong bao loi dung nguyen nhan thay vi "khong ton tai" gay nham lan."""
    directory = os.path.dirname(file_path) or "."
    if not os.path.isdir(directory):
        raise RuntimeError(f"thu muc cha cua secret file khong ton tai: {directory}")
    if os.path.islink(directory):
        raise RuntimeError(f"thu muc cha cua secret file la symlink - tu choi doc: {directory}")
    st = os.stat(directory)
    if st.st_uid != os.getuid():
        raise RuntimeError(
            f"thu muc cha cua secret file khong thuoc so huu tien trinh nay (dir uid={st.st_uid}, "
            f"process uid={os.getuid()}): {directory}")
    mode = stat.S_IMODE(st.st_mode)
    if mode & _SECRET_FILE_FORBIDDEN_MODE_BITS:
        raise RuntimeError(
            f"thu muc cha cua secret file qua rong quyen (mode={oct(mode)}, phai loai bo "
            f"group/other access): {directory}")


def _read_secret_env_or_file(name: str) -> str:
    """F-A08-R2-01 (dap PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-2-VI.md): doc
    secret tu FILE (bien `<NAME>_FILE` tro toi duong dan, vd bind-mount tu 1 thu muc host operator
    tu chuan bi voi chown/chmod dung UID cua tien trinh nay) NEU CO — khong con bake gia tri THAT
    vao `environment:` cua docker-compose (REV1 cu lam vay, `docker inspect m4-signer` se hien gia
    tri o `Config.Env`; REV2 nay chi con thay 1 duong dan file, khong con gia tri).

    TU KIEM TRA quyen file doc lap (KHONG chi tin bind-mount host giu dung permission — do la hanh
    vi Linux chuan nhung KHONG the tu kiem chung tu ben trong 1 tien trinh dang chay, va moi truong
    sandbox non-Linux/Windows-host-bind-mount da CHUNG MINH THUC TE co the bo qua permission hoan
    toan, xem `scripts/m4_stage0p_signing_service_test.py` kich ban [22]/[23]) — cung triet ly
    phong thu-o-nhieu-lop da qua 14 vong CA Technical Review cho `_validate_socket_directory()` o
    tren: tu choi khoi dong NGAY neu file co BAT KY bit group/other nao (mode & 0o077 != 0) hoac
    khong thuoc so huu CHINH tien trinh nay.

    F-A08-R3-01 (dap PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-3-VI.md): TRUOC KHI
    dung toi CHINH file, tu kiem THU MUC CHA rieng (`_validate_secret_parent_directory()`) — neu
    thu muc cha khong thuoc so huu tien trinh nay hoac qua rong quyen, `os.path.isfile(file_path)`
    o duoi se am tham tra `False` (Python nuot `OSError`/`PermissionError` ben trong ham nay) va
    bao loi SAI ly do ("khong ton tai" thay vi "khong the traverse vao thu muc cha") — kiem thu muc
    cha TRUOC, DOC LAP voi kiem file, cho ra thong bao loi dung nguyen nhan.

    Fallback ve bien `<NAME>` THO (gia tri truc tiep, hanh vi REV1/REV0 cu) neu `<NAME>_FILE`
    khong duoc dat — GIU NGUYEN duong sandbox test hien co (khong phai security boundary, khong
    thay doi hanh vi da duoc kiem qua nhieu vong review truoc do)."""
    file_path = os.environ.get(f"{name}_FILE")
    if not file_path:
        return os.environ.get(name, "")
    _validate_secret_parent_directory(file_path)
    if not os.path.isfile(file_path):
        raise RuntimeError(f"{name}_FILE tro toi duong dan khong ton tai/khong phai file thuong: "
                           f"{file_path}")
    if os.path.islink(file_path):
        raise RuntimeError(f"{name}_FILE la symlink - tu choi doc (chong tan cong symlink): "
                           f"{file_path}")
    st = os.stat(file_path)
    mode = stat.S_IMODE(st.st_mode)
    if mode & _SECRET_FILE_FORBIDDEN_MODE_BITS:
        raise RuntimeError(
            f"{name}_FILE qua rong quyen (mode={oct(mode)}, phai loai bo group/other access): "
            f"{file_path}")
    if st.st_uid != os.getuid():
        raise RuntimeError(
            f"{name}_FILE khong thuoc so huu tien trinh nay (file uid={st.st_uid}, process "
            f"uid={os.getuid()}): {file_path}")
    with open(file_path, encoding="utf-8") as f:
        return f.read().strip()


def main() -> int:
    socket_path = os.environ.get("STAGE0P_SIGNING_SOCKET")
    if not socket_path:
        print("STAGE0P_SIGNING_SOCKET chua duoc dat", file=sys.stderr)
        return 2
    # T13-02: Redis dung cho tieu thu nonce 1-lan (_consume_nonce_once) - KHONG phai secret, chi la
    # ha tang dung chung (cung instance moi collector/pending-check khac) - doc tu moi truong CUA
    # CHINH tien trinh nay, mac dinh ve gia tri chung cua settings neu khong ghi de.
    settings.redis_url = os.environ.get("REDIS_URL", settings.redis_url)
    shared_gid_s = os.environ.get("STAGE0P_SIGNING_SHARED_GID")
    shared_gid = int(shared_gid_s) if shared_gid_s else None
    try:
        sample_key_b64 = _read_secret_env_or_file("M4_SAMPLE_KEY_B64")
        hmac_key_b64 = _read_secret_env_or_file("M4_TRANSCRIPT_HMAC_KEY_B64")
        auth_verify_key_b64 = _read_secret_env_or_file("M4_SIGNING_AUTH_VERIFY_KEY_B64")
        if not sample_key_b64 or not hmac_key_b64 or not auth_verify_key_b64:
            raise RuntimeError(
                "M4_SAMPLE_KEY_B64/M4_TRANSCRIPT_HMAC_KEY_B64/M4_SIGNING_AUTH_VERIFY_KEY_B64 (hoac "
                "cac bien _FILE tuong ung) chua duoc dat day du")
        # REV11 T10-02/REV13 T12-02: 3 khoa nay CHI ton tai trong settings cua CHINH tien trinh nay
        # - collector khong bao gio dat 3 bien moi truong/file nay trong process cua no (xem
        # evidence scripts).
        settings.m4_sample_key_b64 = sample_key_b64
        settings.m4_transcript_hmac_key_b64 = hmac_key_b64
        settings.m4_signing_auth_verify_key_b64 = auth_verify_key_b64
        allowed_uid = _allowed_uid()
        asyncio.run(run_signing_service(socket_path, allowed_uid=allowed_uid, shared_gid=shared_gid))
    except RuntimeError as e:
        # T11-02/T12-01: startup fail neu socket directory/path khong an toan
        # (_validate_socket_directory) hoac STAGE0P_SIGNING_ALLOWED_UID chua cau hinh (_allowed_uid);
        # F-A08-R2-01: hoac secret file khong an toan/thieu (_read_secret_env_or_file).
        print(f"signing service tu choi khoi dong: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
