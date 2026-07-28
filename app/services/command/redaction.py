"""Redaction/masking cho command payload (I-B M1). Spec §6.1, §7.4.

Tai su dung bo redactor de quy cua audit_service (_redact_value: loc credential+PII nested).
Nguyen tac luu tru: request_payload/outbox payload dung ALLOWLIST + masked phone; KHONG luu
address raw/token/full provider payload. mask_phone giu 3 so cuoi de trace, khong lo so day du.
"""
from __future__ import annotations

from app.services.audit_service import _redact_value


def mask_phone(phone: str | None) -> str | None:
    """Giu 3 chu so cuoi: '0912345678' -> '***678'. None -> None."""
    if not phone:
        return phone
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) < 4:
        return "***"
    return "***" + digits[-3:]


def redact_generic(payload: dict | None) -> dict | None:
    """Safety net: redact de quy bat ky dict (credential+PII) truoc khi ghi log/error_detail.
    Tra ve dict (khong phai JSON string) de luu vao cot JSONB."""
    if payload is None:
        return None
    return _redact_value(payload)
