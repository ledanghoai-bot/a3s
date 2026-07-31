#!/usr/bin/env python
"""I-B M4 Stage 0P — helper T12-01 (REV13): goi `request_signature()` TU CHINH tien trinh nay (dung
lam target cho `subprocess`/`asyncio.create_subprocess_exec(..., user=<uid>)` trong
`_stage0p_signing_service_helper.py:request_signature_as_uid()`) — chung minh 1 IPC request THAT
xuat phat tu 1 OS UID cu the, khong phai chi mo phong bang cach doi gia tri expected trong CUNG 1
tien trinh (day CHINH LA diem CA tu choi o Correction #12).

Giao thuc: doc 1 JSON request tu stdin, in 1 JSON response ra stdout (dong duy nhat). KHONG bao
gio in raw_content/plaintext ra ngoai JSON response chuan (tranh log ro ri qua stdout/stderr cua
subprocess)."""

import asyncio
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.pii.stage0p_signing_client import (  # noqa: E402
    SigningServiceError,
    request_signature,
)


async def main() -> int:
    req = json.loads(sys.stdin.read())
    try:
        result = await request_signature(
            req["socket_path"], batch_id=req["batch_id"], conversation_id=req["conversation_id"],
            message_id=req["message_id"], sample_id=req["sample_id"], raw_content=req["raw_content"],
            customer_ref=req["customer_ref"], conversation_ref=req["conversation_ref"],
            purpose_code=req["purpose_code"], txid=req["txid"],
            signing_authorization=req["signing_authorization"],
            db_char_truncated=req.get("db_char_truncated", False),
            timeout=req.get("timeout", 5.0),
        )
        print(json.dumps({
            "ok": True,
            "ciphertext_b64": base64.b64encode(result.ciphertext).decode("ascii"),
            "canonical_len": result.canonical_len,
            "truncated": result.truncated,
            "canonical_digest_hex": result.canonical_digest.hex(),
            "key_version": result.key_version,
        }))
    except SigningServiceError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
    except Exception as e:  # noqa: BLE001 - loi ha tang bat ngo, van tra JSON co cau truc
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
