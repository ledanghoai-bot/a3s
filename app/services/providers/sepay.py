"""SePay connector — M7-C0 TEST MODE (CA Directive 272 §3.5). Chi NHAN webhook incoming-transfer (doc tin hieu),
KHONG goi API ngan hang, KHONG chuyen/hoan tien, KHONG credential/OTP.

Envelope SePay (docs.sepay.vn/webhooks): {id, gateway, transactionDate, accountNumber, code, content, transferType
('in'|'out'), transferAmount, accumulated, subAccount, referenceCode, description}. Auth Test Mode: header
`Authorization: Apikey <SEPAY_TEST_API_KEY>` (cau hinh tren SePay). Live (C1) can HMAC-SHA256/tuong duong — KHONG
nam trong directive nay (mode live bi tu choi o webhook khi flag live chua mo).

parse_envelope -> IncomingTransfer (provider-neutral); extract_code -> ma don tu content/code (`3SCF <id>`).
"""
from __future__ import annotations

import hmac
import json
import re
from typing import Any

from app.services.providers.base import IncomingTransfer, payload_hash

PROVIDER = "sepay"
# CA 322/323: prefix do Dashboard cau hinh (khong hard-code, co the chua so vd '3SCF'). Noi dung sinh = "<PREFIX> <order_id>".
# Tach order_id = token TOAN SO phan tach boi khoang trang (khong dinh vao prefix). Binding CHINH XAC theo snapshot
# instruction o provider_ingest (khong tin regex global) -> foreign prefix/wrong content fail-closed.
_CODE_RE = re.compile(r"(?:^|\s)0*(\d{1,12})(?=\s|$)")
_KEEP = ("id", "gateway", "transactionDate", "accountNumber", "code", "content", "transferType", "transferAmount",
         "subAccount", "referenceCode", "description")


class SepayError(ValueError):
    pass


def looks_like_test_key(key: str | None) -> bool:
    """Kiem tra ĐINH DANG (co can cu) cua SePay Test API key — KHONG phai xac thuc voi SePay (offline khong the).
    SePay Apikey la token opaque dai, khong khoang trang. Dung cho readiness 'stored/decryptable', khong claim authenticated.
    Rang buoc: chuoi, >=16 ky tu, chi chu/so/-/_ (khong whitespace/control). Fail -> readiness key_format."""
    if not isinstance(key, str):
        return False
    k = key.strip()
    return len(k) >= 16 and k == key and re.fullmatch(r"[A-Za-z0-9_\-]{16,}", k) is not None


def verify_test_auth(authorization: str | None, expected_key: str) -> bool:
    """Test Mode: 'Apikey <key>' so sanh hang so thoi gian. Thieu key cau hinh -> False (fail-closed)."""
    if not expected_key or not authorization:
        return False
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "apikey":
        return False
    return hmac.compare_digest(parts[1].strip(), expected_key)


def extract_codes(*texts: str | None) -> list[int]:
    """Tat ca order_id tim thay sau prefix-token bat ky (de phat hien TRUNG ma -> staff). Prefix cu the do
    Dashboard cau hinh; binding chinh xac theo snapshot instruction (provider_ingest)."""
    out: list[int] = []
    for t in texts:
        if not t:
            continue
        for m in _CODE_RE.finditer(str(t)):
            try:
                v = int(m.group(1))
            except ValueError:
                continue
            if v not in out:
                out.append(v)
    return out


def parse_envelope(raw: bytes) -> IncomingTransfer:
    try:
        js = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise SepayError(f"json invalid: {type(e).__name__}") from e
    if not isinstance(js, dict):
        raise SepayError("envelope phai la object")
    ev_id = js.get("id")
    if ev_id is None or str(ev_id).strip() == "":
        raise SepayError("thieu id (provider event id)")
    amt = js.get("transferAmount")
    amount: int | None
    if isinstance(amt, bool):
        amount = None
    elif isinstance(amt, int):
        amount = amt
    elif isinstance(amt, float) and amt.is_integer():
        amount = int(amt)
    elif isinstance(amt, str) and amt.strip().isdigit():
        amount = int(amt.strip())
    else:
        amount = None
    ttype = str(js.get("transferType") or "").strip().lower()
    direction = "in" if ttype == "in" else ("out" if ttype == "out" else "unknown")
    minimal: dict[str, Any] = {k: js.get(k) for k in _KEEP if k in js}
    return IncomingTransfer(
        provider=PROVIDER, provider_event_id=str(ev_id), direction=direction,
        account_number=(str(js.get("accountNumber")).strip() if js.get("accountNumber") is not None else None),
        amount_vnd=amount, content=str(js.get("content") or ""),
        reference=(str(js.get("referenceCode")).strip() if js.get("referenceCode") else None),
        occurred_at=(str(js.get("transactionDate")) if js.get("transactionDate") else None),
        gateway=(str(js.get("gateway")) if js.get("gateway") else None),
        payload_hash=payload_hash(raw), raw_minimal=minimal,
    )
