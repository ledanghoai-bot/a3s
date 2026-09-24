"""M7 staff_attention queue (CA Directive 272 §4). 1 dong OPEN / (order, reason) — mo lai trung = no-op (idempotent).
Mo hang doi + bao admin (outbox telegram_admin, dedupe theo attention id) TRONG CUNG transaction voi transition.
Resolve = staff (RBAC fulfillment.attention_resolve) + audit; KHONG tu dong doi payment/shipment state.
"""
from __future__ import annotations

import json

from app.services import audit_service
from app.services.command import repository as cmd_repo

REASONS = ("address", "quote", "account", "method", "payment_mismatch", "unmatched_webhook",
           "payment_timeout", "large_order_review", "quantity_unit_review",   # CA Amendment 273
           "provider_error", "other",
           "refund_required", "order_cancel_exception")                       # CA Directive 387 (huy don)
CANCEL_REASONS = ("refund_required", "order_cancel_exception")
ADMIN_EVENT = "fulfillment.staff.notify"


async def open_attention(conn, order_id: int | None, *, reason: str, detail: dict | None, created_by: str,
                         notify_admin: bool = True) -> int | None:
    """Tra id dong moi, None neu da co OPEN cung (order, reason) (khong tao trung, khong notify lai)."""
    if reason not in REASONS:
        raise ValueError(f"reason khong hop le: {reason}")
    row_id = await conn.fetchval(
        "INSERT INTO staff_attention (order_id, reason, detail, created_by) VALUES ($1,$2,$3::jsonb,$4) "
        "ON CONFLICT (order_id, reason) WHERE status='open' DO NOTHING RETURNING id",
        order_id, reason, json.dumps(detail or {}), created_by)
    if row_id is None:
        return None
    await audit_service.record(conn, actor_type="system", action="fulfillment.attention_open",
                               actor_ref=created_by, entity_type="staff_attention", entity_id=str(row_id),
                               after={"order_id": order_id, "reason": reason})
    if notify_admin:
        detail_text = ", ".join(f"{k}={v}" for k, v in (detail or {}).items() if k not in ("raw",))[:160]
        await cmd_repo.insert_outbox(
            conn, command_id=None, event_type=ADMIN_EVENT, event_version=1, destination="telegram_admin",
            dedupe_key=f"staff_attention:{row_id}",
            payload={"kind": "staff_attention", "order_id": order_id, "reason": reason,
                     "detail_text": detail_text, "attention_id": row_id},
            max_attempts=8)
    return row_id


async def resolve(conn, attention_id: int, *, resolved_by: str, note: str) -> dict | None:
    if not note or not note.strip():
        raise ValueError("resolution_note bat buoc")
    row = await conn.fetchrow(
        "UPDATE staff_attention SET status='resolved', resolved_at=now(), resolved_by=$2, resolution_note=$3 "
        "WHERE id=$1 AND status='open' RETURNING *", attention_id, resolved_by, note.strip())
    if row is None:
        return None
    await audit_service.record(conn, actor_type="staff", action="fulfillment.attention_resolve",
                               actor_ref=resolved_by, entity_type="staff_attention", entity_id=str(attention_id),
                               after={"order_id": row["order_id"], "reason": row["reason"]}, reason=note.strip())
    return dict(row)


async def list_open(conn, *, limit: int = 200) -> list[dict]:
    rows = await conn.fetch(
        "SELECT a.id, a.order_id, a.reason, a.detail, a.created_at, a.created_by, "
        "fc.step AS conversation_step, p.status AS payment_status, p.method AS payment_method, "
        "s.routing_source, s.fee_status, o.status AS order_status "
        "FROM staff_attention a LEFT JOIN fulfillment_conversations fc ON fc.order_id=a.order_id "
        "LEFT JOIN payments p ON p.order_id=a.order_id LEFT JOIN shipments s ON s.order_id=a.order_id "
        "LEFT JOIN orders o ON o.id=a.order_id "
        # CA 387: don da huy chi con hien attention hau-huy (hoan tien / ngoai le shipment)
        "WHERE a.status='open' AND (o.status IS NULL OR o.status NOT IN ('cancelled','cancelled_by_exception') "
        "OR a.reason = ANY($2::text[])) ORDER BY a.created_at LIMIT $1", limit, list(CANCEL_REASONS))
    return [dict(r) for r in rows]
