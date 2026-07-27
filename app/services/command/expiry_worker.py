"""Reservation expiry worker (I-B M2 Slice 6). Spec §11.

Claim reservation đến hạn (status=active, expires_at<=now, order.status='new') theo batch nhỏ, rồi
GỌI command service `inventory.reservation.expire` cho từng row — KHÔNG viết balance trực tiếp trong
worker (§11.1). Idempotency key = `reservation.expire:<id>:<expected_expires_at>` (§8.2) -> repeated
polls / nhiều worker KHÔNG nhân đôi. Redis TTL KHÔNG phải source of truth (§11.2). Kill switch riêng
qua flag; reservation không bị bỏ quên (poll lại lần sau).
"""
from __future__ import annotations

from app.config import settings
from app.db_pool import acquire, release
from app.services.command import lifecycle, registry
from app.services.command.envelope import Actor
from app.services.command.observability import log_event

DEFAULT_BATCH = 100


async def _claim_due(conn, batch: int) -> list[dict]:
    """Đọc reservation đến hạn (read-only; command boundary mới là nơi lock/mutate)."""
    rows = await conn.fetch(
        "SELECT r.id, r.expires_at FROM inventory_reservations r "
        "JOIN orders o ON o.id = r.order_id "
        "WHERE r.status='active' AND r.expires_at IS NOT NULL AND r.expires_at <= now() "
        "  AND o.status='new' "
        "ORDER BY r.expires_at LIMIT $1",
        batch,
    )
    return [{"id": str(r["id"]), "expires_at": r["expires_at"].isoformat()} for r in rows]


async def run_once(batch: int = DEFAULT_BATCH) -> dict:
    """Một vòng: claim due reservations -> execute expire command mỗi cái. Trả stats.
    An toàn gọi lặp: idempotency key theo (reservation_id, expected_expires_at)."""
    if not settings.m2_inventory_ledger:
        return {"skipped": "flag_off", "claimed": 0, "expired": 0, "noop": 0}
    conn = await acquire()
    try:
        due = await _claim_due(conn, batch)
    finally:
        await release(conn)

    expired = noop = failed = 0
    for item in due:
        key = f"reservation.expire:{item['id']}:{item['expires_at']}"
        env = lifecycle.build_lifecycle_envelope(
            command_type=registry.RESERVATION_EXPIRE,
            payload={"reservation_id": item["id"], "expected_expires_at": item["expires_at"]},
            actor=Actor("system", "expiry-worker"), channel="dashboard", idempotency_key=key)
        try:
            receipt = await lifecycle.execute_lifecycle(env)
            outcome = (receipt.result or {}).get("outcome") if receipt.result else None
            if outcome == "expired":
                expired += 1
            else:
                noop += 1
        except Exception as e:  # noqa: BLE001 — 1 reservation lỗi không được làm hỏng cả batch
            failed += 1
            log_event("reservation.expire.error", reservation_id=item["id"], error=str(e)[:200])

    stats = {"claimed": len(due), "expired": expired, "noop": noop, "failed": failed}
    if due:
        log_event("reservation.expiry.sweep", **stats)
    return stats
