#!/usr/bin/env python3
"""M3 Slice 4 evidence — PII-safe logging (AC-M3-05; §13.19 #5; audit PHASE1B-M3-PII-LOG-AUDIT-VI.md).

Chay (khong can DB):
  docker exec -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/m3_pii_log_test.py

Chung minh:
  1. sanitize_text/safe_exc: redact bot token Telegram trong URL, access_token/query secret,
     Bearer, SDT VN (0/+84, co space/dot/dash), email; giu tieng Viet co dau; cat do dai.
  2. Encoded: SDT/token URL-encoded (%XX) khong lach guard.
  3. httpx.HTTPStatusError voi URL chua token -> safe_exc sach.
  4. log_event (observability) enforce redact_generic: field phone/address/psid bi mask;
     fallback unserializable KHONG in repr tho (chi ten key).
  5. Static guard toan app/: khong con pattern nguy hiem da audit —
     print bare ': {e}' / in reply content / in raw event dead-letter.
"""
import contextlib
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.services.command.observability import log_event  # noqa: E402
from app.services.safe_log import mask_ref, safe_exc, sanitize_text  # noqa: E402

_fail = []


def check(cond, label):
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        _fail.append(label)


def main():  # noqa: C901
    print("[1] sanitize_text / safe_exc")
    s = sanitize_text("GET https://api.telegram.org/bot123456:AAHdqwe-RT_9x/sendMessage failed")
    check("bot<REDACTED>" in s and "AAHdqwe" not in s, f"TG token redacted ({s})")
    s = sanitize_text("https://graph.facebook.com/1234?fields=name&access_token=EAABsbCS1iHgBA")
    check("access_token=<REDACTED>" in s and "EAABsbCS" not in s, f"access_token redacted ({s})")
    s = sanitize_text("Authorization: Bearer sk-abc123def")
    check("sk-abc123def" not in s, f"Bearer redacted ({s})")
    for ph in ["0912345678", "+84 912 345 678", "0912-345-678", "0912.345.678"]:
        s = sanitize_text(f"khach bao so {ph} nhe")
        check("<PHONE>" in s and not re.search(r"\d{6}", s), f"phone '{ph}' redacted ({s})")
    s = sanitize_text("mail toi a.b+c@example.com.vn nhe")
    check("<EMAIL>" in s and "example" not in s, f"email redacted ({s})")
    s = sanitize_text("Giao tới quận Hoàn Kiếm nhé — tiếng Việt giữ nguyên")
    check("Hoàn Kiếm" in s, "tieng Viet co dau giu nguyen (khong pha noi dung thuong)")
    s = sanitize_text("x" * 500)
    check(len(s) <= 302, f"truncate 300 (len={len(s)})")

    print("[2] encoded PII khong lach")
    s = sanitize_text("callback?phone=0912%20345%20678")
    check("<PHONE>" in s and "345" not in s, f"phone URL-encoded redacted ({s})")
    s = sanitize_text("u=https%3A%2F%2Fapi.telegram.org%2Fbot99:ZZtok%2FsendMessage")
    check("bot<REDACTED>" in s and "ZZtok" not in s, f"token URL-encoded redacted ({s})")

    print("[3] httpx.HTTPStatusError -> safe_exc sach")
    req = httpx.Request("GET", "https://api.telegram.org/bot777:SECRETTOK/getUpdates?timeout=50")
    resp = httpx.Response(409, request=req)
    try:
        resp.raise_for_status()
        check(False, "raise_for_status should raise")
    except httpx.HTTPStatusError as e:
        out = safe_exc(e)
        check("SECRETTOK" not in out and "bot<REDACTED>" in out, f"HTTPStatusError redacted ({out})")
        check(out.startswith("HTTPStatusError:"), "safe_exc co ten exception type")

    print("[4] log_event enforce redact_generic")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        log_event("test.event", order_id=5, phone="0912345678", address="12 Le Loi, HN",
                  psid="9876543210", note="ok")
    out = buf.getvalue()
    check("0912345678" not in out, f"phone field masked ({out.strip()})")
    check("12 Le Loi" not in out, "address field masked")
    check("9876543210" not in out, "psid field masked")
    check('"order_id": 5' in out, "id/metadata giu nguyen")

    class Unserializable:
        def __repr__(self):
            raise RuntimeError("boom 0912345678")
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        log_event("test.bad", weird=Unserializable(), phone="0912345678")
    out2 = buf2.getvalue()
    check("0912345678" not in out2, f"fallback khong in repr tho ({out2.strip()})")

    check(mask_ref("abcdef123") == "…f123" and mask_ref(None) == "<none>", "mask_ref")

    print("[5] static guard toan app/ (pattern da audit khong quay lai)")
    bad = []
    for p in (ROOT / "app").rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        rel = p.relative_to(ROOT).as_posix()
        if re.search(r'print\(f"[^"]*: \{e\}', text):
            bad.append(f"{rel}: bare ': {{e}}' print")
        if re.search(r'print\([^)]*reply\[:\d+\]', text):
            bad.append(f"{rel}: print reply content")
        if re.search(r'DEAD-LETTER[^"]*\{event\}', text):
            bad.append(f"{rel}: print raw dead-letter event")
    check(not bad, f"khong con pattern nguy hiem (got {bad})")

    print("\n" + ("ALL PASS" if not _fail else f"FAIL: {_fail}"))
    return 0 if not _fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
