"""Observability cho command bus (I-B M1 Slice 10). Spec §12.

Stack KHONG co Prometheus -> metrics suy tu DB (giong app/services/metrics.py). command_bus_metrics()
tra snapshot; evaluate_alerts() cham nguong §12.2 -> danh sach alert dang fire (P1/P2). log_event()
in structured log co command_id/correlation_id/... (cam raw PII, §12.1).
"""
from __future__ import annotations

import json

from app.db_pool import acquire, release

# §12.2 thresholds
OLDEST_PENDING_P1_SECONDS = 15 * 60
STALE_PROCESSING_P2_SECONDS = 5 * 60
RETRY_RATIO_P2 = 0.10
CREDENTIAL_ERROR_CLASSES = ("http_401", "http_403")


def log_event(event: str, **fields) -> None:
    """Structured log 1 dong (JSON). Chi id/metadata — KHONG raw PII (§12.1)."""
    try:
        print("[cmd] " + json.dumps({"event": event, **fields}, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001 - log khong duoc lam vo flow
        print(f"[cmd] {event} {fields}")


async def command_bus_metrics(conn=None) -> dict:
    own = conn is None
    if own:
        conn = await acquire()
    try:
        cmd_by_status = {r["status"]: r["count"] for r in await conn.fetch(
            "SELECT status, count(*) AS count FROM command_executions GROUP BY status")}
        outbox_by_status = {r["status"]: r["count"] for r in await conn.fetch(
            "SELECT status, count(*) AS count FROM outbox_events GROUP BY status")}
        attempts_by_outcome = {r["outcome"]: r["count"] for r in await conn.fetch(
            "SELECT outcome, count(*) AS count FROM delivery_attempts GROUP BY outcome")}
        conflicts = await conn.fetchval(
            "SELECT count(*) FROM audit_log WHERE action='command.idempotency_conflict'")
        oldest_pending = await conn.fetchval(
            "SELECT COALESCE(EXTRACT(EPOCH FROM (now() - MIN(available_at))), 0) FROM outbox_events "
            "WHERE status IN ('pending','retry_scheduled') AND available_at <= now()")
        stale_processing = await conn.fetchval(
            "SELECT count(*) FROM command_executions WHERE status='processing' "
            "AND started_at < now() - ($1 * interval '1 second')", STALE_PROCESSING_P2_SECONDS)
        dead_letter = outbox_by_status.get("dead_lettered", 0)
        # retry ratio 30 phut gan nhat
        window = await conn.fetchrow(
            "SELECT count(*) FILTER (WHERE outcome IN ('retryable_error','unknown')) AS retry_n, "
            "count(*) AS total FROM delivery_attempts WHERE started_at >= now() - interval '30 minutes'")
        retry_ratio = (window["retry_n"] / window["total"]) if window["total"] else 0.0
        credential_errors = await conn.fetchval(
            "SELECT count(*) FROM delivery_attempts WHERE error_class = ANY($1::text[]) "
            "AND started_at >= now() - interval '15 minutes'", list(CREDENTIAL_ERROR_CLASSES))
        return {
            "commands_by_status": cmd_by_status,
            "outbox_by_status": outbox_by_status,
            "delivery_attempts_by_outcome": attempts_by_outcome,
            "idempotency_conflict_total": int(conflicts or 0),
            "outbox_oldest_pending_age_seconds": float(oldest_pending or 0),
            "outbox_dead_letter_total": int(dead_letter or 0),
            "stale_processing_total": int(stale_processing or 0),
            "delivery_retry_ratio_30m": round(float(retry_ratio), 3),
            "credential_error_15m": int(credential_errors or 0),
        }
    finally:
        if own:
            await release(conn)


def evaluate_alerts(m: dict) -> list[dict]:
    """Cham nguong §12.2 -> danh sach alert fire. Khong tat dead-letter alert (§12.2)."""
    alerts: list[dict] = []
    if m["outbox_oldest_pending_age_seconds"] > OLDEST_PENDING_P1_SECONDS:
        alerts.append({"severity": "P1", "name": "outbox_oldest_pending",
                       "detail": f"{int(m['outbox_oldest_pending_age_seconds'])}s > {OLDEST_PENDING_P1_SECONDS}s"})
    if m["outbox_dead_letter_total"] > 0:
        alerts.append({"severity": "P1", "name": "dead_letter_present",
                       "detail": f"{m['outbox_dead_letter_total']} event can operator xu ly"})
    if m["credential_error_15m"] > 0:
        alerts.append({"severity": "P1", "name": "credential_outage",
                       "detail": f"{m['credential_error_15m']} loi 401/403 trong 15 phut"})
    if m["delivery_retry_ratio_30m"] > RETRY_RATIO_P2:
        alerts.append({"severity": "P2", "name": "high_retry_ratio",
                       "detail": f"{m['delivery_retry_ratio_30m']:.0%} > {RETRY_RATIO_P2:.0%}"})
    if m["stale_processing_total"] > 0:
        alerts.append({"severity": "P2", "name": "stale_command_processing",
                       "detail": f"{m['stale_processing_total']} command processing > 5 phut"})
    return alerts
