"""CA Directive 404 §2C — tra vet 1 lan bao phi tu `command_key` (read-only, redacted).

Chuoi doi chieu: route operation (command_key) -> order -> address snapshot (id/resolution/dataset) -> route decision
(shipments.routing_*) -> provider_quote_log (endpoint, response_class, http, duration, trace) -> outbox cua don quanh
thoi diem do -> audit shipment.route_quote. Chap nhan: command_key goc (m7 route-quote), co tien to `dash:` (Dashboard
F2) va `m7_routing:<order_id>` / `order:<order_id>` (luong bot/worker, khong co route operation).
KHONG tra: token, so tai khoan, request/response body, SDT/ten/dia chi text, payload outbox.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.services.fulfillment import shipment_service as _sh


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _row(r, keys) -> dict:
    return {k: _iso(r[k]) for k in keys}


async def trace(conn, command_key: str) -> dict:
    key = (command_key or "").strip()
    if not key:
        return {"error": "command_key_required"}
    keys = [key] if key.startswith(("dash:", "m7_routing:", "order:")) else [key, f"dash:{key}"]
    ops = [dict(r) for r in await conn.fetch(
        "SELECT id, order_id, action, command_key, state, provider, error_code, attempts, created_at, updated_at "
        "FROM fulfillment_route_operations WHERE command_key = ANY($1::text[]) ORDER BY id", keys)]
    order_ids = sorted({o["order_id"] for o in ops})
    if not order_ids and key.startswith(("m7_routing:", "order:")):
        try:
            order_ids = [int(key.split(":", 1)[1])]
        except ValueError:
            order_ids = []
    logs = [dict(r) for r in await conn.fetch(
        "SELECT id, order_id, trace_key, route_operation_id, endpoint, response_class, status, http_status, "
        "duration_ms, request_fingerprint, created_at FROM provider_quote_log "
        "WHERE trace_key = ANY($1::text[]) OR route_operation_id = ANY($2::bigint[]) ORDER BY id",
        keys, [o["id"] for o in ops])]
    orders = []
    for oid in order_ids:
        o = await conn.fetchrow("SELECT id, status, origin_channel, created_at FROM orders WHERE id=$1", oid)
        if o is None:
            continue
        snap = await conn.fetchrow(
            "SELECT id, resolution_id, province_code, ward_code, dataset_version, verification_method, verified_at "
            "FROM order_address_snapshot WHERE order_id=$1", oid)
        sh = await conn.fetchrow(
            "SELECT id, status, version, routing_source, routing_version, routing_reason, routing_province_code, "
            "routing_ward_code, zone, fee_status, delivery_fee_vnd, eta_text, quote_provider, quote_source, "
            "quote_rule_version, quoted_at FROM shipments WHERE order_id=$1", oid)
        t0 = min([x["created_at"] for x in ops if x["order_id"] == oid] or [o["created_at"]]) - timedelta(minutes=1)
        outbox = [_row(r, ("id", "event_type", "destination", "status", "attempt_count", "dedupe_key", "created_at",
                           "delivered_at"))
                  for r in await conn.fetch(
                      "SELECT id::text AS id, event_type, destination, status, attempt_count, dedupe_key, created_at, "
                      "delivered_at FROM outbox_events WHERE payload->>'order_id' = $1 AND created_at >= $2 "
                      "ORDER BY created_at LIMIT 50", str(oid), t0)]
        audits = [_row(r, ("id", "action", "actor_ref", "created_at")) for r in await conn.fetch(
            "SELECT id, action, actor_ref, created_at FROM audit_log WHERE action='shipment.route_quote' "
            "AND entity_type='shipments' AND entity_id=$1 AND created_at >= $2 ORDER BY id", str(sh["id"]) if sh
            else "-", t0)]
        shd = None
        if sh:
            shd = _row(sh, sh.keys())
            shd["zone_label"] = _sh.zone_label(sh["routing_source"], sh["zone"])
        orders.append({
            "order": _row(o, ("id", "status", "origin_channel", "created_at")),
            "address_snapshot": _row(snap, snap.keys()) if snap else None,
            "route_decision": shd, "outbox": outbox, "audit": audits,
            "quote_logs": [_row(x, x.keys()) for x in logs if x["order_id"] == oid],
        })
    return {"command_key": key, "matched_keys": keys, "route_operations": [_row(o, o.keys()) for o in ops],
            "orders": orders, "provider_calls": sum(1 for x in logs if x["endpoint"]),
            "quote_log_count": len(logs)}
