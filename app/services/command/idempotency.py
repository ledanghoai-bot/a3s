"""Idempotency key + scope (I-B M1). Spec §6.2.

- API/dashboard: bat buoc header Idempotency-Key, 16-128 ky tu (charset an toan).
- AI chat: stable key = sha256(channel + provider_message_id + tool_call_id + command_type + version).
- scope unique = (command_type, command_version, idempotency_scope, idempotency_key).
"""
from __future__ import annotations

import re

from app.services.command import errors
from app.services.command.hashing import sha256_hex

_KEY_RE = re.compile(r"^[A-Za-z0-9._:\-]{16,128}$")


def validate_api_key(key: str | None) -> str:
    """Validate Idempotency-Key do client (dashboard/API) truyen. Raise CommandError (400)."""
    if key is None or key == "":
        raise errors.key_required()
    key = key.strip()
    if not _KEY_RE.match(key):
        raise errors.key_invalid("do dai 16-128, chi [A-Za-z0-9._:-].")
    return key


def ai_stable_key(*, channel: str, provider_message_id: str, command_type: str, version: int,
                  business_key: str) -> str:
    """Stable key cho AI (CR-04R): KHÔNG phụ thuộc tool_call_id (LLM sinh lại -> khác nhau).
    Neo vào provider message id THẬT + danh tính nghiệp vụ đã chuẩn hoá (business_key = request_hash
    của nội dung đơn). Hệ quả:
    - cùng inbound message + cùng nội dung đơn -> CÙNG key (effective-once qua retry/re-execution);
    - đơn khác nội dung trong cùng message -> key khác (nhiều đơn/1 message vẫn phân biệt được);
    - message khác -> key khác."""
    return sha256_hex(f"{channel}|{provider_message_id}|{command_type}|{version}|{business_key}")


def build_scope(command_type: str, channel: str, subject: str) -> str:
    """idempotency_scope = 'order.create:<channel>:<actor-or-customer>'. subject la id on-dinh."""
    return f"{command_type}:{channel}:{subject}"
