"""Command envelope (I-B M1). Spec §6.1.

Envelope mang 2 payload tach biet:
- `payload`: normalized FULL (co address) — chi ton tai trong RAM, service dung de mutate.
- `stored_payload`: allowlist (masked phone, KHONG address) — ghi vao cot request_payload (JSONB).

Server sinh command_id/correlation_id neu chua co. KHONG tin actor/customer/conversation id do LLM
tu tao — orchestrator/API inject tu trusted context (§6.1). Builder validate + tinh request_hash.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.command import errors, idempotency, registry

CHANNELS = {"messenger", "telegram_customer", "dashboard"}
ACTOR_TYPES = {"customer", "staff", "system"}


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_uuid() -> str:
    return str(uuid.uuid4())


@dataclass
class Actor:
    type: str
    id: str


@dataclass
class CommandEnvelope:
    command_id: str
    command_type: str
    command_version: int
    idempotency_key: str
    idempotency_scope: str
    actor: Actor
    channel: str
    customer_id: int | None
    conversation_id: int | None
    location_id: int | None
    correlation_id: str
    causation_id: str | None
    requested_at: str
    request_hash: str
    payload: dict[str, Any]          # normalized FULL (in-memory)
    stored_payload: dict[str, Any]   # allowlist (persisted)

    def validate(self) -> None:
        if self.channel not in CHANNELS:
            raise errors.CommandError(errors.INVALID_ENVELOPE, f"channel khong hop le: {self.channel}")
        if self.actor.type not in ACTOR_TYPES:
            raise errors.CommandError(errors.INVALID_ENVELOPE, f"actor.type khong hop le: {self.actor.type}")
        if not self.actor.id:
            raise errors.CommandError(errors.INVALID_ENVELOPE, "actor.id bat buoc.")
        if len(self.request_hash) != 64:
            raise errors.CommandError(errors.INVALID_ENVELOPE, "request_hash phai 64 hex.")
        registry.require_registered(self.command_type, self.command_version)

    def as_insert_params(self, status: str = "accepted") -> dict[str, Any]:
        """Map -> cot command_executions cho INSERT (repository json-encode request_payload).
        request_payload = stored_payload (da allowlist/mask)."""
        now = _now_rfc3339()
        return {
            "id": self.command_id,
            "command_type": self.command_type,
            "command_version": self.command_version,
            "idempotency_scope": self.idempotency_scope,
            "idempotency_key": self.idempotency_key,
            "request_hash": self.request_hash,
            "status": status,
            "actor_type": self.actor.type,
            "actor_id": self.actor.id,
            "channel": self.channel,
            "customer_id": self.customer_id,
            "conversation_id": self.conversation_id,
            "location_id": self.location_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "request_payload": self.stored_payload,
            "accepted_at": now,
        }


def build_order_create_envelope(
    *,
    raw_payload: dict[str, Any],
    actor: Actor,
    channel: str,
    idempotency_key: str,
    customer_id: int | None = None,
    conversation_id: int | None = None,
    location_id: int | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    command_id: str | None = None,
) -> CommandEnvelope:
    """Dung envelope order.create v1 tu input tho + trusted context. Validate + hash.
    Raise CommandError khi payload/channel/actor invalid (KHONG tao order)."""
    if channel not in CHANNELS:
        raise errors.CommandError(errors.INVALID_ENVELOPE, f"channel khong hop le: {channel}")
    if actor.type not in ACTOR_TYPES or not actor.id:
        raise errors.CommandError(errors.INVALID_ENVELOPE, "actor khong hop le.")

    normalized = registry.validate_order_create_payload(raw_payload)
    hash_input = registry.order_create_hash_input(normalized)
    request_hash = registry.compute_request_hash(
        registry.ORDER_CREATE, registry.ORDER_CREATE_VERSION, hash_input
    )
    stored = registry.order_create_stored_payload(normalized)
    scope = idempotency.build_scope(registry.ORDER_CREATE, channel, actor.id)

    env = CommandEnvelope(
        command_id=command_id or _new_uuid(),
        command_type=registry.ORDER_CREATE,
        command_version=registry.ORDER_CREATE_VERSION,
        idempotency_key=idempotency_key,
        idempotency_scope=scope,
        actor=actor,
        channel=channel,
        customer_id=customer_id,
        conversation_id=conversation_id,
        location_id=location_id,
        correlation_id=correlation_id or _new_uuid(),
        causation_id=causation_id,
        requested_at=_now_rfc3339(),
        request_hash=request_hash,
        payload=normalized,
        stored_payload=stored,
    )
    env.validate()
    return env
