"""CA Review 235-03: RECONCILER durable cho staff-history receipt row.

Khi `_log_receipt_to_messages` loi sau khi order da commit, order + customer-receipt (outbox) VAN nguyen
nhung staff-visible messages row co the thieu. Reconciler nay — chay moi vong outbox_worker — tim cac
order.receipt.customer da co outbox NHUNG chua co staff messages row (dedupe order_receipt:{order_id}) va
ghi bu ĐÚNG MOT lan (ON CONFLICT DO NOTHING). Idempotent: chay lai KHONG them row. KHONG gui lai receipt
cho khach (chi ghi DB messages). KHONG mo them kenh outbound — customer outbox van la duong giao khach.
"""
from __future__ import annotations

from app.db_pool import acquire, release
from app.services.command import order_intent_service as svc
from app.services.safe_log import safe_exc


async def reconcile_staff_receipts(limit: int = 200) -> int:
    """Ghi bu staff-history receipt row con thieu (theo stable identity order_receipt:{order_id}). Tra so row
    MOI ghi. Best-effort (khong raise ra worker)."""
    conn = None
    made = 0
    try:
        conn = await acquire()
        rows = await conn.fetch(
            "SELECT (oe.payload->>'order_id')::int AS oid, oe.payload->>'text' AS text, o.customer_id "
            "FROM outbox_events oe JOIN orders o ON o.id = (oe.payload->>'order_id')::int "
            "WHERE oe.event_type='order.receipt.customer' "
            "AND NOT EXISTS (SELECT 1 FROM messages m "
            "                WHERE m.dedupe_key = 'order_receipt:'||(oe.payload->>'order_id')) "
            "ORDER BY oe.created_at DESC LIMIT $1", limit)
        for r in rows:
            conv = await conn.fetchval(
                "SELECT id FROM conversations WHERE customer_id=$1 ORDER BY id DESC LIMIT 1", r["customer_id"])
            if conv is None:
                continue
            text = r["text"] or f"Đơn #{r['oid']} đã được ghi nhận."
            created = await svc.log_message_tx(conn, conv, "bot", text,
                                               dedupe_key=f"order_receipt:{r['oid']}")
            if created:
                made += 1
    except Exception as e:  # noqa: BLE001 — reconcile fail KHONG vo worker
        print(f"[staff_receipt_reconcile] skipped (retryable): {safe_exc(e)}")
    finally:
        if conn is not None:
            await release(conn)
    return made
