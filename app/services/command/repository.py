"""Repository cho command bus (I-B M1). Spec §5, §7.

MOI ham nhan sãn `conn` (connection cua transaction dang mo) — KHONG tu mo connection. Muc dich:
business mutation + command result + outbox insert + audit CUNG mot transaction (atomic, §5.2).
jsonb truyen dang JSON string + ::jsonb (khop convention audit_service). uuid nhan str (asyncpg parse).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

_INSERT_COMMAND = """
INSERT INTO command_executions
  (id, command_type, command_version, idempotency_scope, idempotency_key, request_hash, status,
   actor_type, actor_id, channel, customer_id, conversation_id, location_id,
   correlation_id, causation_id, request_payload, accepted_at, started_at)
VALUES
  ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb, now(), now())
"""


async def insert_command(conn, params: dict[str, Any]) -> None:
    """INSERT command row (status thuong 'processing'). Raise UniqueViolationError neu trung
    (command_type, version, scope, key) — day la co che effective-once (§8.1), KHONG check-then-insert."""
    await conn.execute(
        _INSERT_COMMAND,
        params["id"], params["command_type"], params["command_version"],
        params["idempotency_scope"], params["idempotency_key"], params["request_hash"],
        params["status"], params["actor_type"], params["actor_id"], params["channel"],
        params["customer_id"], params["conversation_id"], params["location_id"],
        params["correlation_id"], params["causation_id"], json.dumps(params["request_payload"]),
    )


async def get_by_scope_key(conn, command_type: str, version: int, scope: str, key: str):
    return await conn.fetchrow(
        "SELECT * FROM command_executions "
        "WHERE command_type=$1 AND command_version=$2 AND idempotency_scope=$3 AND idempotency_key=$4",
        command_type, version, scope, key,
    )


async def get_by_id(conn, command_id: str):
    return await conn.fetchrow("SELECT * FROM command_executions WHERE id=$1", command_id)


async def mark_succeeded(conn, command_id: str, result_payload: dict[str, Any],
                         resource_type: str, resource_id: str, customer_id: int | None):
    """processing -> succeeded (trigger cho phep). Set result/resource/completed_at. Return completed_at."""
    return await conn.fetchval(
        "UPDATE command_executions SET status='succeeded', result_payload=$2::jsonb, "
        "resource_type=$3, resource_id=$4, customer_id=COALESCE($5, customer_id), completed_at=now() "
        "WHERE id=$1 RETURNING completed_at",
        command_id, json.dumps(result_payload), resource_type, resource_id, customer_id,
    )


async def mark_failed_terminal(conn, command_id: str, error_code: str,
                               error_detail: dict[str, Any] | None):
    """processing -> failed_terminal (business reject). Persist error_code -> reject idempotent."""
    return await conn.fetchval(
        "UPDATE command_executions SET status='failed_terminal', error_code=$2, "
        "error_detail_redacted=$3::jsonb, completed_at=now() WHERE id=$1 RETURNING completed_at",
        command_id, error_code,
        json.dumps(error_detail) if error_detail is not None else None,
    )


async def insert_outbox(conn, *, command_id: str, event_type: str, event_version: int,
                        destination: str, dedupe_key: str, payload: dict[str, Any],
                        max_attempts: int) -> str | None:
    """Insert outbox event (status pending, available_at now). ON CONFLICT (destination,dedupe_key)
    DO NOTHING -> replay/retry cung dedupe khong tao trung (§8.3). Return outbox id hoac None neu trung."""
    return await conn.fetchval(
        "INSERT INTO outbox_events "
        "(id, command_id, event_type, event_version, destination, dedupe_key, payload, "
        " status, available_at, max_attempts) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,'pending', now(), $8) "
        "ON CONFLICT (destination, dedupe_key) DO NOTHING RETURNING id",
        str(uuid.uuid4()), command_id, event_type, event_version, destination, dedupe_key,
        json.dumps(payload), max_attempts,
    )
