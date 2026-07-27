"""order_events append (I-B M2 Slice 4). Spec §9.5, §7.

Append-only timeline; MỘT legal transition = MỘT event idempotent (UNIQUE idempotency_key).
Trigger DB chặn UPDATE/DELETE. Không I/O ngoài conn của caller.
"""
from __future__ import annotations

import json
import uuid


async def append_order_event(
    conn,
    *,
    order_id: int,
    event_type: str,
    to_status: str,
    idempotency_key: str,
    correlation_id,
    actor_type: str,
    actor_id: str,
    from_status: str | None = None,
    inventory_status_before: str | None = None,
    inventory_status_after: str | None = None,
    reason: str | None = None,
    command_id=None,
    causation_id: str | None = None,
    event_version: int = 1,
    metadata: dict | None = None,
) -> bool:
    """Append event idempotent. Trả True nếu mới chèn, False nếu đã tồn tại (replay)."""
    row = await conn.fetchrow(
        "INSERT INTO order_events "
        "(id,order_id,event_type,event_version,from_status,to_status,"
        " inventory_status_before,inventory_status_after,actor_type,actor_id,reason,"
        " command_id,correlation_id,causation_id,idempotency_key,metadata_redacted) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16) "
        "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id",
        uuid.uuid4(), order_id, event_type, event_version, from_status, to_status,
        inventory_status_before, inventory_status_after, actor_type, actor_id, reason,
        command_id, correlation_id, causation_id, idempotency_key,
        json.dumps(metadata or {}),
    )
    return row is not None
