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


def ai_stable_key(*, channel: str, provider_message_id: str, tool_call_id: str,
                  command_type: str, version: int) -> str:
    """Stable key cho AI chat — cung tin nhan + cung tool call -> cung key (retry an toan)."""
    return sha256_hex(f"{channel}|{provider_message_id}|{tool_call_id}|{command_type}|{version}")


def build_scope(command_type: str, channel: str, subject: str) -> str:
    """idempotency_scope = 'order.create:<channel>:<actor-or-customer>'. subject la id on-dinh."""
    return f"{command_type}:{channel}:{subject}"
