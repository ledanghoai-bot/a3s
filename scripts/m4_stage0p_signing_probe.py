#!/usr/bin/env python
"""I-B M4 Stage 0P — canary probe cho signing service THAT (A08-COR-01, dap
PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-1-VI.md F-A08-R1-03, sua theo
PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-2-VI.md F-A08-R2-02: "collector duoc
trao signing authorization key" — REV1 cua probe nay tu ky canary TRONG CUNG tien trinh chay duoi
UID m4-collector, nghia la m4-collector nam giu `M4_SIGNING_AUTH_VERIFY_KEY_B64` (symmetric) va VE
LY THUYET co the tu mint 1 authorization cho BAT KY noi dung nao — vo hieu hoa ranh gioi
signer/collector ma 14 vong CA Technical Review da xay dung.

REV2 (hien tai) TACH LAM 2 SUBCOMMAND CHAY O 2 DANH TINH KHAC NHAU:

  mint-token   (chay duoi danh tinh operator/mac dinh cua container `api`, KHONG PHAI
               `--user m4-collector`) — CAN `M4_SIGNING_AUTH_VERIFY_KEY_B64`, tu sinh cac truong
               canary (sample_id/txid/canonical_digest_hex/...) roi ky 1 `signing_authorization`
               DUY NHAT, TTL ngan (20s), chi hop le cho CHINH XAC noi dung canary co dinh — in ra
               STDOUT 1 dong duy nhat: base64(JSON) chua token + cac truong khong-bi-mat can de
               submit lai (KHONG chua khoa).

  submit       (chay duoi `--user m4-collector`, khop dung danh tinh collector production) — CHI
               can `M4_STAGE0P_SIGNING_SOCKET` + blob tu `mint-token`
               (`M4_SIGNING_PROBE_TOKEN`) — KHONG BAO GIO doc/can `M4_SIGNING_AUTH_VERIFY_KEY_B64`
               (khong co code path nao trong nhanh nay doc bien do — xem scenario P-08 kiem tra
               tinh bang grep + P-09 kiem tra bang chay that voi bien BI LO vao env van khong
               dung toi). Gui dung 1 request da-ky-san qua socket — khong the tu sua bat ky truong
               nao (sample_id/txid/canonical_digest_hex/...) vi lam vay se lam sai chu ky da ky
               boi `mint-token`, bi signing service tu choi (T13-01 tamper-detection co san,
               scenario P-10 chung minh lai qua chinh flow moi nay).

Ca 2 buoc dung CHUNG thuat toan production that (import truc tiep tu
`app.services.pii.stage0p_signing_service`, khong copy tay, tranh drift) — payload la du lieu
CANARY ro rang gia lap, KHONG BAO GIO dung batch_id/customer_ref/conversation thuoc ve rehearsal/
production that, va KHONG ghi gi vao DB (chi goi signing service qua socket, khong dung
`m4_stage0p_fetch_message_content()`).

Vi du chay THAT (xem thom docs/M4-STAGE0P-SIGNING-SERVICE-RUNBOOK-VI.md §4):
    # Buoc 1 - danh tinh operator (KHONG --user m4-collector), can khoa:
    TOKEN=$(docker compose -f docker-compose.prod.yml exec \\
        -e M4_SIGNING_AUTH_VERIFY_KEY_B64 \\
        api python scripts/m4_stage0p_signing_probe.py mint-token)
    # Buoc 2 - danh tinh m4-collector THAT, KHONG can khoa, chi can token vua mint:
    docker compose -f docker-compose.prod.yml exec --user m4-collector \\
        -e M4_SIGNING_PROBE_TOKEN="$TOKEN" \\
        api python scripts/m4_stage0p_signing_probe.py submit

Exit 0 (submit) = signing path hoat dong day du (peer UID + rate-limit + nonce + auth-signature +
canonicalize + encrypt + sign THAT SU thanh cong). Exit 1 = that bai (socket khong ket noi duoc,
signing service tu choi, hoac loi khac) — KHONG BAO GIO in raw content/ciphertext/plaintext/khoa ra
output, chi in ok/loi dang tom tat."""

import argparse
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
_TOKEN_TTL_SECONDS = 20


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"thieu bien moi truong bat buoc {name} (xem runbook)")
    return val


def _build_canary_fields() -> dict:
    """Sinh cac truong MO TA canary request — KHONG bi mat (sample_id/txid la ngau nhien nhung
    khong tu than tiet lo gi, canonical_digest_hex la digest cua NOI DUNG CANARY CO DINH da cong
    khai trong chinh file nay) — tach rieng khoi buoc KY de `mint-token`/`submit` dung chung 1
    nguon sinh, khong the lech."""
    from app.services.pii.canonicalize import canonicalize  # noqa: PLC0415
    canonical_text, _truncated = canonicalize(_CANARY_CONTENT)
    canonical_digest_hex = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    return {
        "sample_id": f"canary-{uuid.uuid4()}",
        "txid": int(time.time() * 1000) % 2_000_000_000,
        "conversation_id": 1,
        "message_id": 1,
        "customer_ref": "m4-canary-customer-ref",
        "canonical_digest_hex": canonical_digest_hex,
    }


def _sign_canary_authorization(auth_key: bytes, fields: dict) -> str:
    """Tu ky 1 signing_authorization canary — dung CHINH XAC `_lenpfx_join`/`_AUTH_DOMAIN_TAG`/
    `_SIGNING_AUTH_KEY_VERSION` IMPORT TRUC TIEP tu `stage0p_signing_service.py` (khong copy tay)
    de dam bao khong bao gio drift khoi thuat toan production that dung de xac minh. CHI goi tu
    `mint-token` (danh tinh operator, giu khoa) — KHONG BAO GIO goi tu `submit` (danh tinh
    m4-collector, F-A08-R2-02: collector khong duoc nam giu khoa nay)."""
    now_epoch = int(time.time())
    expires_epoch = now_epoch + _TOKEN_TTL_SECONDS
    nonce = str(uuid.uuid4())
    conversation_id_str = str(fields["conversation_id"])
    payload = _lenpfx_join(
        _AUTH_DOMAIN_TAG, _CANARY_BATCH_ID, conversation_id_str, str(fields["message_id"]),
        fields["sample_id"], fields["customer_ref"], conversation_id_str, _CANARY_PURPOSE_CODE,
        str(fields["txid"]), fields["canonical_digest_hex"], "0", nonce, str(now_epoch),
        str(expires_epoch),
    )
    sig = hmac.new(auth_key, payload, hashlib.sha256).digest()
    return f"{_SIGNING_AUTH_KEY_VERSION}|{now_epoch}|{expires_epoch}|{nonce}|{sig.hex()}"


def cmd_mint_token(_args) -> int:
    """Chay duoi danh tinh operator (KHONG --user m4-collector) — CAN khoa, KHONG BAO GIO chay
    duoi m4-collector (F-A08-R2-02)."""
    auth_key = base64.b64decode(_require_env("M4_SIGNING_AUTH_VERIFY_KEY_B64"), validate=True)
    fields = _build_canary_fields()
    signing_authorization = _sign_canary_authorization(auth_key, fields)
    blob = {**fields, "signing_authorization": signing_authorization}
    # 1 dong duy nhat tren stdout, de operator capture qua command substitution ($(...)) va
    # chuyen thang cho buoc `submit` — KHONG chua khoa duoi bat ky dang nao, chi chua token DA KY
    # (chi hop le DUNG 1 lan, DUNG cho canary noi dung co dinh, TTL 20s).
    print(base64.b64encode(json.dumps(blob, sort_keys=True).encode("utf-8")).decode("ascii"))
    return 0


async def _submit(socket_path: str, blob: dict) -> dict:
    result = await request_signature(
        socket_path, batch_id=_CANARY_BATCH_ID, conversation_id=blob["conversation_id"],
        message_id=blob["message_id"], sample_id=blob["sample_id"], raw_content=_CANARY_CONTENT,
        customer_ref=blob["customer_ref"], conversation_ref=str(blob["conversation_id"]),
        purpose_code=_CANARY_PURPOSE_CODE, txid=blob["txid"],
        signing_authorization=blob["signing_authorization"])
    return {
        "key_version": result.key_version,
        "canonical_len": result.canonical_len,
        "canonical_digest_matches":
            result.canonical_digest == bytes.fromhex(blob["canonical_digest_hex"]),
        # H2-A-2: canary la cong DAU TIEN cua ceremony, nen no phai bat duoc mot backend ky bat doi
        # xung hong NGAY — truoc khi bat ky sample nao duoc ghi.
        #
        # Probe chay duoi vai `m4-collector` va KHONG duoc cham backend/khoa, nen no khong the tu
        # verify chu ky bang public key. Nhung no kiem duoc ba dieu co y nghia va do duoc:
        #   * thuat toan dung la Ed25519 (khong phai mot the khac lot vao),
        #   * chu ky dung 64 byte (backend tra rac se lo ra ngay),
        #   * key_id/key_version duoc cong bo de nguoi van hanh doi chieu voi registry.
        # Verify mat ma DAY DU la viec cua verifier ngoai DB (`m4_stage0p_verify_transcripts.py`),
        # noi co public key — do la dung phan cong: nguoi verify khong can bi mat nao.
        "sig_alg": result.sig_alg,
        "sig_alg_dung_ed25519": result.sig_alg == "Ed25519",
        "sig_key_id": result.sig_key_id,
        "sig_key_ver": result.sig_key_ver,
        "signature_asym_dung_64_byte": len(result.signature_asym) == 64,
    }


def cmd_submit(_args) -> int:
    """Chay duoi `--user m4-collector` THAT — KHONG doc/can `M4_SIGNING_AUTH_VERIFY_KEY_B64` o bat
    ky dong nao trong nhanh nay (F-A08-R2-02: xac nhan bang grep tinh, scenario P-08)."""
    socket_path = os.environ.get("M4_STAGE0P_SIGNING_SOCKET") or os.environ.get(
        "STAGE0P_SIGNING_SOCKET") or "/run/m4-signing/signing.sock"
    token_b64 = _require_env("M4_SIGNING_PROBE_TOKEN")
    try:
        blob = json.loads(base64.b64decode(token_b64, validate=True))
    except Exception:  # noqa: BLE001 - token hong/khong doc duoc, tu choi sach
        print(json.dumps({"event": "m4_signing_probe_failed", "ok": False,
                          "error_type": "InvalidTokenBlob", "socket_path": socket_path},
                         sort_keys=True))
        return 1
    try:
        detail = asyncio.run(_submit(socket_path, blob))
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("mint-token").set_defaults(func=cmd_mint_token)
    sub.add_parser("submit").set_defaults(func=cmd_submit)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
