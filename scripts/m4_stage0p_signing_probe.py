#!/usr/bin/env python
"""I-B M4 Stage 0P — canary probe cho signing service THAT (A08-COR-01, dap
PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-1-VI.md F-A08-R1-03: "status/readiness
chua chung minh signing path usable — chi kiem PID cmdline va socket existence").

Khac voi kiem tra "socket file ton tai" (chi chung minh tien trinh dang lang nghe, KHONG chung
minh peer-UID/rate-limit/nonce/auth-signature/canonicalize/encrypt/sign THAT SU hoat dong dung),
script nay gui 1 request KY THAT qua socket, dung CHINH XAC thuat toan `signing_authorization`
production dung (tai su dung truc tiep tu `app.services.pii.stage0p_signing_service` — khong copy
tay, tranh drift) — payload la du lieu CANARY ro rang gia lap, KHONG BAO GIO dung batch_id/
customer_ref/conversation thuoc ve rehearsal/production that, va KHONG ghi gi vao DB (chi goi
signing service qua socket, khong dung `m4_stage0p_fetch_message_content()`).

Chay TU DUNG danh tinh collector that (production):
    docker compose -f docker-compose.prod.yml exec --user m4-collector \\
        -e M4_SIGNING_AUTH_VERIFY_KEY_B64="$M4_SIGNING_AUTH_VERIFY_KEY_B64" \\
        api python scripts/m4_stage0p_signing_probe.py

`M4_SIGNING_AUTH_VERIFY_KEY_B64` PHAI la CUNG gia tri da dua cho `m4-signer` luc
`docker compose --profile m4-signing up -d m4-signer` (xem runbook) — day la khoa DUY NHAT script
nay can, KHONG BAO GIO doc/can M4_TRANSCRIPT_HMAC_KEY_B64/M4_SAMPLE_KEY_B64 (2 khoa do CHI signing
service moi can, xac nhan qua kich ban test [P-04]).

Exit 0 = signing path hoat dong day du (peer UID + rate-limit + nonce + auth-signature +
canonicalize + encrypt + sign THAT SU thanh cong). Exit 1 = that bai (socket khong ket noi duoc,
signing service tu choi, hoac loi khac) — KHONG BAO GIO in raw content/ciphertext/plaintext ra
output, chi in ok/loi dang tom tat."""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncio  # noqa: E402

from app.services.pii.stage0p_signing_client import (  # noqa: E402
    SigningServiceError,
    request_signature,
)
from app.services.pii.stage0p_signing_service import (  # noqa: E402
    _AUTH_DOMAIN_TAG,
    _SIGNING_AUTH_KEY_VERSION,
    _lenpfx_join,
)

_CANARY_BATCH_ID = "00000000-0000-0000-0000-000000000001"
_CANARY_PURPOSE_CODE = "m4-signing-canary-probe-v1"
_CANARY_CONTENT = "M4 SIGNING SERVICE CANARY PROBE - KHONG PHAI DU LIEU THAT"


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"thieu bien moi truong bat buoc {name} (can CUNG gia tri da dua cho "
                         "m4-signer luc start - xem runbook)")
    return val


def _sign_canary_authorization(auth_key: bytes, *, conversation_id: int, message_id: int,
                               sample_id: str, customer_ref: str, txid: int,
                               canonical_digest_hex: str) -> str:
    """Tu ky 1 signing_authorization canary — dung CHINH XAC `_lenpfx_join`/`_AUTH_DOMAIN_TAG`/
    `_SIGNING_AUTH_KEY_VERSION` IMPORT TRUC TIEP tu `stage0p_signing_service.py` (khong copy tay)
    de dam bao khong bao gio drift khoi thuat toan production that dung de xac minh. MOI truong
    o day PHAI khop CHINH XAC (ca thu tu lan gia tri) voi request THAT SU se gui qua
    `request_signature()` trong `_run_probe()` - lech du 1 truong se lam chu ky khong khop."""
    now_epoch = int(time.time())
    expires_epoch = now_epoch + 20
    nonce = str(uuid.uuid4())
    conversation_id_str = str(conversation_id)
    payload = _lenpfx_join(
        _AUTH_DOMAIN_TAG, _CANARY_BATCH_ID, conversation_id_str, str(message_id), sample_id,
        customer_ref, conversation_id_str, _CANARY_PURPOSE_CODE, str(txid),
        canonical_digest_hex, "0", nonce, str(now_epoch), str(expires_epoch),
    )
    sig = hmac.new(auth_key, payload, hashlib.sha256).digest()
    return f"{_SIGNING_AUTH_KEY_VERSION}|{now_epoch}|{expires_epoch}|{nonce}|{sig.hex()}"


async def _run_probe(socket_path: str, auth_key: bytes) -> dict:
    from app.services.pii.canonicalize import canonicalize  # noqa: PLC0415
    canonical_text, _truncated = canonicalize(_CANARY_CONTENT)
    canonical_digest_hex = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    sample_id = f"canary-{uuid.uuid4()}"
    txid = int(time.time() * 1000) % 2_000_000_000
    conversation_id = 1
    message_id = 1
    customer_ref = "m4-canary-customer-ref"
    signing_authorization = _sign_canary_authorization(
        auth_key, conversation_id=conversation_id, message_id=message_id, sample_id=sample_id,
        customer_ref=customer_ref, txid=txid, canonical_digest_hex=canonical_digest_hex)

    result = await request_signature(
        socket_path, batch_id=_CANARY_BATCH_ID, conversation_id=conversation_id,
        message_id=message_id, sample_id=sample_id, raw_content=_CANARY_CONTENT,
        customer_ref=customer_ref, conversation_ref=str(conversation_id),
        purpose_code=_CANARY_PURPOSE_CODE, txid=txid,
        signing_authorization=signing_authorization)
    return {
        "key_version": result.key_version,
        "canonical_len": result.canonical_len,
        "canonical_digest_matches": result.canonical_digest == bytes.fromhex(canonical_digest_hex),
    }


def main() -> int:
    socket_path = os.environ.get("M4_STAGE0P_SIGNING_SOCKET") or os.environ.get(
        "STAGE0P_SIGNING_SOCKET") or "/run/m4-signing/signing.sock"
    auth_key = base64.b64decode(_require_env("M4_SIGNING_AUTH_VERIFY_KEY_B64"), validate=True)
    try:
        detail = asyncio.run(_run_probe(socket_path, auth_key))
    except SigningServiceError as e:
        print(json.dumps({"event": "m4_signing_probe_failed", "ok": False,
                          "error_type": type(e).__name__, "socket_path": socket_path},
                         sort_keys=True))
        return 1
    except Exception as e:  # noqa: BLE001 - loi ha tang (khong ket noi duoc, timeout...)
        print(json.dumps({"event": "m4_signing_probe_failed", "ok": False,
                          "error_type": type(e).__name__, "socket_path": socket_path},
                         sort_keys=True))
        return 1
    print(json.dumps({"event": "m4_signing_probe_ok", "ok": True, "socket_path": socket_path,
                      **detail}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
