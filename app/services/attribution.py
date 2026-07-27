"""UTM attribution — sanitize/mapping version hóa (I-B M3 Slice 2). Spec M3 §7.3.

Nguyên tắc:
  - Ghi TƯỜNG MINH từ input của kênh (web form/API) — KHÔNG suy UTM từ prefix/text (bài học `tg:`).
  - KHÔNG PII trong UTM: chặn giá trị dạng SĐT/email/khoảng trắng tự do.
  - `utm_term` chỉ nhận khi caller thật sự gửi — không synthesize.
  - Deterministic: cùng input -> cùng output; unknown key bị DROP (backward/forward compat).
Pure logic, không I/O — unit-testable.
"""
from __future__ import annotations

import re

# Bump khi đổi allowlist/quy tắc — ghi vào Delivery Package (mapping được version, spec §7.3).
MAPPING_VERSION = 1

ALLOWED_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")

# Token campaign: chữ/số + . _ ~ + / - ; 1..100 ký tự, bắt đầu bằng chữ/số. Không space, không '@'.
_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~+/-]{0,99}$")
# PII guard: chuỗi số kiểu SĐT VN (kể cả lẫn trong token) -> từ chối.
_PHONE_LIKE = re.compile(r"(?:\+?84|0)\d{8,10}")


class UTMValidationError(ValueError):
    """422 — UTM cung cấp nhưng không hợp lệ (KHÔNG áp cho request thiếu UTM)."""

    def __init__(self, field: str, reason: str):
        super().__init__(f"UTM khong hop le: {field} ({reason})")
        self.field = field
        self.reason = reason


def sanitize_utm(raw: dict | None) -> dict[str, str]:
    """Trả dict chỉ gồm ALLOWED_KEYS hợp lệ. None/{} -> {}. Unknown key -> drop.
    Giá trị sai định dạng / nghi PII -> raise UTMValidationError (không nhận mù)."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise UTMValidationError("utm", "phai la object")
    out: dict[str, str] = {}
    for key in ALLOWED_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        if not isinstance(val, str):
            raise UTMValidationError(key, "phai la chuoi")
        val = val.strip()
        if not val:
            continue
        if not _VALUE_RE.match(val):
            raise UTMValidationError(key, "token khong hop le (chi chu/so/._~+/-, <=100)")
        if _PHONE_LIKE.search(val) or "@" in val:
            raise UTMValidationError(key, "nghi chua PII — tu choi")
        out[key] = val
    return out
