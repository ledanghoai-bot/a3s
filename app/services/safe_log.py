"""safe_exc — sanitize exception/chuỗi trước khi ghi log (I-B M3 Slice 4, AC-M3-05).

Vấn đề nền (audit `docs/PHASE1B-M3-PII-LOG-AUDIT-VI.md`): `str(exception)` của httpx/asyncpg
thường nhúng URL đầy đủ (chứa bot token Telegram, access_token Meta) hoặc giá trị tham số
(SĐT/địa chỉ) vào message → lọt thẳng stdout. Mọi điểm print exception thô trong app PHẢI đi
qua `safe_exc(e)` (guard tĩnh: scripts/m3_pii_log_test.py [5]).

Không import gì từ app.* (tránh vòng import) — module lá, pure.
"""
from __future__ import annotations

import re
from urllib.parse import unquote

# Telegram bot token trong URL: /bot<digits>:<secret>/
_TG_TOKEN = re.compile(r"bot\d+:[A-Za-z0-9_-]+")
# Query param nhạy cảm: access_token / token / api_key / key / secret / authorization
_QS_SECRET = re.compile(r"((?:access_token|token|api_key|apikey|key|secret|authorization)=)[^&\s\"']+",
                        re.IGNORECASE)
# Bearer/credential trong header text
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
# SĐT VN (kể cả +84, có khoảng trắng/gạch giữa các cụm)
_PHONE = re.compile(r"(?:\+?84|0)(?:[\s.-]?\d){8,10}")
# Email
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_MAX_LEN = 300


def sanitize_text(text: str, max_len: int = _MAX_LEN) -> str:
    """Redact token/secret/SĐT/email trong một chuỗi tự do + cắt độ dài.
    Decode %XX trước khi quét để PII URL-encoded không lách guard (AC-M3-05 'encoded')."""
    s = str(text)
    try:
        s = unquote(s)
    except Exception:  # noqa: BLE001 — chuỗi lạ: giữ nguyên, vẫn quét
        pass
    s = _TG_TOKEN.sub("bot<REDACTED>", s)
    s = _QS_SECRET.sub(r"\1<REDACTED>", s)
    s = _BEARER.sub(r"\1<REDACTED>", s)
    s = _PHONE.sub("<PHONE>", s)
    s = _EMAIL.sub("<EMAIL>", s)
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


def safe_exc(e: BaseException, max_len: int = _MAX_LEN) -> str:
    """Chuỗi an toàn để log: '<ExcType>: <message đã redact/cắt>'."""
    return f"{type(e).__name__}: {sanitize_text(str(e), max_len=max_len)}"


def mask_ref(value: str | None, keep: int = 4) -> str:
    """Mask định danh (psid/username/IP...) giữ `keep` ký tự cuối để trace: 'abcdef' -> '…cdef'."""
    if not value:
        return "<none>"
    s = str(value)
    return ("…" + s[-keep:]) if len(s) > keep else "…" + s
