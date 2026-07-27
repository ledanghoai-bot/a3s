"""M2 lifecycle command service (I-B M2 Slice 5). Spec §8, §10, §11.3, §12, §13.1.

Wrap MỌI mutation lifecycle vào command envelope (effective-once) + apply_transition/inventory domain:
  insert command (unique) -> [savepoint] business validate+mutate -> mark_succeeded + audit + receipt.
Domain reject (illegal transition / SoD / stale / not-unit-head / insufficient) -> savepoint rollback
(mutation undone) -> command failed_terminal (reject idempotent, KHÔNG mutation). Duplicate key -> receipt
cũ; cùng key khác hash -> 409. Retry KHÔNG tạo movement/event mới (idempotency key domain-level).
"""
from __future__ import annotations

import uuid
from typing import Any

import asyncpg

from app.db_pool import acquire, release
from app.services import audit_service
from app.services.command import errors, registry
from app.services.command import receipt as receipt_mod
from app.services.command import repository as repo
from app.services.command.envelope import ACTOR_TYPES, CHANNELS, Actor, CommandEnvelope
from app.services.command.idempotency import build_scope
from app.services.command.observability import log_event
from app.services.inventory import repository as inv_repo
from app.services.inventory import service as inv_service
from app.services.inventory.errors import InventoryError
from app.services.order import transition_service as order_txn
from app.services.order import transitions
from app.services.order.events import append_order_event

SUCCEEDED, REJECTED, IN_PROGRESS = "succeeded", "rejected", "in_progress"


class LifecycleReject(Exception):
    def __init__(self, code: str, message: str, http_status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# Domain errors coi là business reject (savepoint rollback -> failed_terminal idempotent).
_REJECTS = (transitions.IllegalTransition, InventoryError, LifecycleReject)


def _reject_code(e: Exception) -> str:
    return getattr(e, "code", "lifecycle_reject")


# ---------------------------------------------------------------------------
# Payload validation (per command type) — non-PII, stored == hash_input
# ---------------------------------------------------------------------------
def _need(payload: dict, *keys) -> None:
    for k in keys:
        if payload.get(k) in (None, ""):
            raise errors.CommandError(errors.INVALID_ENVELOPE, f"Thiếu field bắt buộc: {k}")


def _pos_int(payload: dict, key: str) -> int:
    v = payload.get(key)
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
        raise errors.CommandError(errors.INVALID_QUANTITY, f"{key} phải là số nguyên > 0.")
    return v


def _validate(command_type: str, payload: dict) -> dict:
    if command_type in registry.TRANSITION_ACTION:
        _need(payload, "order_id")
        out = {"order_id": int(payload["order_id"])}
        if payload.get("reason"):
            out["reason"] = str(payload["reason"])[:500]
        return out
    if command_type == registry.RESERVATION_EXTEND:
        _need(payload, "reservation_id")
        return {"reservation_id": str(payload["reservation_id"]), "extend_hours": _pos_int(payload, "extend_hours")}
    if command_type == registry.RESERVATION_EXPIRE:
        _need(payload, "reservation_id", "expected_expires_at")
        return {"reservation_id": str(payload["reservation_id"]),
                "expected_expires_at": str(payload["expected_expires_at"])}
    if command_type == registry.ADJUST_REQUEST:
        _need(payload, "location_id", "product_id", "quantity_delta", "reason")
        qd = payload["quantity_delta"]
        if not isinstance(qd, int) or isinstance(qd, bool) or qd == 0:
            raise errors.CommandError(errors.INVALID_QUANTITY, "quantity_delta phải là số nguyên != 0.")
        out = {"location_id": int(payload["location_id"]), "product_id": int(payload["product_id"]),
               "quantity_delta": qd, "reason": str(payload["reason"])[:500]}
        if payload.get("evidence_ref"):
            out["evidence_ref"] = str(payload["evidence_ref"])[:200]
        return out
    if command_type in (registry.ADJUST_APPROVE, registry.ADJUST_REJECT):
        _need(payload, "request_id")
        out = {"request_id": str(payload["request_id"])}
        if command_type == registry.ADJUST_REJECT:
            _need(payload, "reason")
        if payload.get("reason"):
            out["reason"] = str(payload["reason"])[:500]
        return out
    raise errors.unknown_command(command_type, 1)


def build_lifecycle_envelope(
    *, command_type: str, payload: dict[str, Any], actor: Actor, channel: str, idempotency_key: str,
    correlation_id: str | None = None, causation_id: str | None = None, command_id: str | None = None,
) -> CommandEnvelope:
    if channel not in CHANNELS:
        raise errors.CommandError(errors.INVALID_ENVELOPE, f"channel không hợp lệ: {channel}")
    if actor.type not in ACTOR_TYPES or not actor.id:
        raise errors.CommandError(errors.INVALID_ENVELOPE, "actor không hợp lệ.")
    registry.require_registered(command_type, 1)
    normalized = _validate(command_type, payload)
    request_hash = registry.compute_request_hash(command_type, 1, normalized)
    scope = build_scope(command_type, channel, actor.id)
    env = CommandEnvelope(
        command_id=command_id or str(uuid.uuid4()), command_type=command_type, command_version=1,
        idempotency_key=idempotency_key, idempotency_scope=scope, actor=actor, channel=channel,
        customer_id=None, conversation_id=None, location_id=normalized.get("location_id"),
        correlation_id=correlation_id or str(uuid.uuid4()), causation_id=causation_id,
        requested_at="", request_hash=request_hash, payload=normalized, stored_payload=normalized,
    )
    env.validate()
    return env


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------
async def execute_lifecycle(env: CommandEnvelope) -> receipt_mod.CommandReceipt:
    conn = await acquire()
    try:
        try:
            async with conn.transaction():
                await repo.insert_command(conn, env.as_insert_params(status="processing"))
                try:
                    async with conn.transaction():  # savepoint quanh business mutation
                        result_payload, resource, audit_action, audit_after = await _dispatch(conn, env)
                except _REJECTS as de:  # noqa: PERF203
                    return await _reject(conn, env, _reject_code(de), str(de))
                completed_at = await repo.mark_succeeded(
                    conn, env.command_id, result_payload, resource["type"], str(resource["id"]), None)
                atype, aref, asid = _actor(env)
                await audit_service.record(
                    conn, atype, audit_action, actor_ref=aref, actor_staff_id=asid,
                    entity_type=resource["type"], entity_id=str(resource["id"]),
                    after=audit_after, correlation_id=env.correlation_id)
                log_event(f"{env.command_type}.succeeded", command_id=env.command_id,
                          correlation_id=env.correlation_id, resource_id=resource["id"])
                return _receipt(env, SUCCEEDED, completed_at, resource=resource, result=result_payload)
            # unreachable
        except asyncpg.UniqueViolationError as e:
            if getattr(e, "constraint_name", None) == "command_executions_idem_key":
                return await _resolve_duplicate(conn, env)
            raise
    finally:
        await release(conn)


async def _reject(conn, env, code, detail) -> receipt_mod.CommandReceipt:
    completed_at = await repo.mark_failed_terminal(conn, env.command_id, code, {"detail": detail[:300]})
    log_event(f"{env.command_type}.rejected", command_id=env.command_id,
              correlation_id=env.correlation_id, error_code=code)
    return _receipt(env, REJECTED, completed_at, error_code=code)


async def _resolve_duplicate(conn, env) -> receipt_mod.CommandReceipt:
    existing = await repo.get_by_scope_key(
        conn, env.command_type, env.command_version, env.idempotency_scope, env.idempotency_key)
    if existing is None:
        return _receipt(env, IN_PROGRESS, None, duplicate=True)
    if existing["request_hash"] != env.request_hash:
        async with conn.transaction():
            atype, aref, asid = _actor(env)
            await audit_service.record(
                conn, atype, "command.idempotency_conflict", actor_ref=aref, actor_staff_id=asid,
                entity_type="command", entity_id=str(existing["id"]),
                reason="idempotency-key reuse voi payload khac", correlation_id=env.correlation_id)
        raise errors.idempotency_conflict()
    out = REJECTED if existing["status"] == "failed_terminal" else (
        SUCCEEDED if existing["status"] == "succeeded" else IN_PROGRESS)
    res = None
    if existing["resource_id"]:
        res = {"type": existing["resource_type"], "id": existing["resource_id"]}
    result = existing["result_payload"]
    if isinstance(result, str):
        import json
        result = json.loads(result)
    return _receipt(env, out, existing["completed_at"], resource=res, result=result,
                    error_code=existing["error_code"], duplicate=True)


def _receipt(env, outcome, committed_at, *, resource=None, result=None, error_code=None,
             duplicate=False) -> receipt_mod.CommandReceipt:
    ts = committed_at.isoformat() if hasattr(committed_at, "isoformat") else committed_at
    return receipt_mod.CommandReceipt(
        receipt_id=f"cmd_{env.command_id}", command_id=env.command_id, command_type=env.command_type,
        command_version=1, outcome=outcome, committed_at=ts, correlation_id=env.correlation_id,
        duplicate=duplicate, resource=resource, result=result if outcome == SUCCEEDED else None,
        error_code=error_code)


def _actor(env) -> tuple[str, str, int | None]:
    if env.actor.type == "staff":
        try:
            return "staff", env.actor.id, int(env.actor.id)
        except ValueError:
            return "staff", env.actor.id, None
    return env.actor.type, env.actor.id, None


def _staff_id(env) -> int:
    if env.actor.type != "staff":
        raise LifecycleReject("staff_required", "Thao tác này yêu cầu staff actor.", 403)
    try:
        return int(env.actor.id)
    except ValueError as e:
        raise LifecycleReject("staff_required", "actor.id staff không hợp lệ.", 403) from e


# ---------------------------------------------------------------------------
# Dispatch -> (result_payload, resource, audit_action, audit_after)
# ---------------------------------------------------------------------------
async def _dispatch(conn, env: CommandEnvelope):
    ct = env.command_type
    if ct in registry.TRANSITION_ACTION:
        return await _do_transition(conn, env)
    if ct == registry.RESERVATION_EXTEND:
        return await _do_reservation_extend(conn, env)
    if ct == registry.RESERVATION_EXPIRE:
        return await _do_reservation_expire(conn, env)
    if ct == registry.ADJUST_REQUEST:
        return await _do_adjust_request(conn, env)
    if ct == registry.ADJUST_APPROVE:
        return await _do_adjust_decision(conn, env, approve=True)
    if ct == registry.ADJUST_REJECT:
        return await _do_adjust_decision(conn, env, approve=False)
    raise errors.unknown_command(ct, 1)


async def _do_transition(conn, env):
    p = env.payload
    order_id = p["order_id"]
    action = registry.TRANSITION_ACTION[env.command_type]
    if env.command_type == registry.ORDER_CANCEL:
        row = await conn.fetchrow("SELECT status FROM orders WHERE id=$1 FOR UPDATE", order_id)
        if row is None:
            raise transitions.IllegalTransition("<missing>", "cancel")
        action = "cancel_by_exception" if row["status"] == "processing" else "cancel"
    res = await order_txn.apply_transition(
        conn, order_id=order_id, action=action, actor_type=env.actor.type, actor_id=env.actor.id,
        correlation_id=env.correlation_id, command_id=env.command_id, reason=p.get("reason"))
    result = {"order_id": order_id, "from_status": res.from_status, "to_status": res.to_status,
              "inventory_effect": res.inventory_effect, "affected_quantity": res.affected_quantity}
    return result, {"type": "order", "id": order_id}, f"order.{action}", result


async def _do_reservation_extend(conn, env):
    p = env.payload
    rid = uuid.UUID(p["reservation_id"])
    r = await conn.fetchrow("SELECT * FROM inventory_reservations WHERE id=$1 FOR UPDATE", rid)
    if r is None or r["status"] != "active":
        raise LifecycleReject("reservation_not_active", "Reservation không active.", 409)
    new_exp = await conn.fetchval(
        "UPDATE inventory_reservations SET expires_at = now() + ($2 || ' hours')::interval "
        "WHERE id=$1 RETURNING expires_at", rid, str(p["extend_hours"]))
    await append_order_event(
        conn, order_id=r["order_id"], event_type="reservation.extended", to_status="",
        from_status="", idempotency_key=f"cmd:{env.command_id}:resv_extend:{rid}",
        correlation_id=env.correlation_id, actor_type=env.actor.type, actor_id=env.actor.id,
        command_id=env.command_id, reason=f"extend {p['extend_hours']}h")
    result = {"reservation_id": str(rid), "expires_at": new_exp.isoformat() if new_exp else None}
    return result, {"type": "reservation", "id": str(rid)}, "reservation.extend", result


async def _do_reservation_expire(conn, env):
    p = env.payload
    rid = uuid.UUID(p["reservation_id"])
    r = await conn.fetchrow(
        "SELECT r.*, o.status AS order_status, (r.expires_at <= now()) AS due "
        "FROM inventory_reservations r JOIN orders o ON o.id=r.order_id WHERE r.id=$1 FOR UPDATE", rid)
    # idempotent no-op: đã terminal / order không còn 'new' / chưa tới hạn (vd đã extend sau claim).
    if (r is None or r["status"] != "active" or r["order_status"] != "new"
            or r["expires_at"] is None or not r["due"]):
        result = {"reservation_id": str(rid), "outcome": "noop"}
        return result, {"type": "reservation", "id": str(rid)}, "reservation.expire", result
    # release (expired) + restore legacy stock + cancel order
    await inv_service.release_reservation(
        conn, r, terminal_status="expired", idem_prefix=f"cmd:{env.command_id}",
        actor_type="system", actor_id="expiry-worker", correlation_id=env.correlation_id,
        command_id=env.command_id)
    await conn.execute("UPDATE products SET stock = stock + $1 WHERE id = $2",
                       r["quantity_remaining"], r["product_id"])
    await conn.execute(
        "UPDATE orders SET status='cancelled', inventory_status='released', status_updated_at=now() "
        "WHERE id=$1", r["order_id"])
    await append_order_event(
        conn, order_id=r["order_id"], event_type="order.reservation_expired", to_status="cancelled",
        from_status="new", inventory_status_before="reserved", inventory_status_after="released",
        idempotency_key=f"cmd:{env.command_id}:event:{r['order_id']}:expired",
        correlation_id=env.correlation_id, actor_type="system", actor_id="expiry-worker",
        command_id=env.command_id, reason="reservation TTL expired")
    result = {"reservation_id": str(rid), "outcome": "expired", "order_id": r["order_id"],
              "released_quantity": r["quantity_remaining"]}
    return result, {"type": "reservation", "id": str(rid)}, "reservation.expire", result


async def _do_adjust_request(conn, env):
    staff_id = _staff_id(env)
    p = env.payload
    loc, pid, qd = p["location_id"], p["product_id"], p["quantity_delta"]
    await inv_repo.lock_balances(conn, loc, [pid])
    bal = await inv_repo.get_balance(conn, loc, pid)
    on_hand = bal["on_hand"] if bal else 0
    threshold = inv_service.compute_threshold(on_hand)
    is_large = abs(qd) >= threshold
    req_id = uuid.uuid4()
    status = "pending" if is_large else "applied"
    await conn.execute(
        "INSERT INTO inventory_adjustment_requests "
        "(id,location_id,product_id,quantity_delta,threshold_at_request,is_large,reason,evidence_ref,"
        " status,requested_by_staff_id,request_command_id,applied_at) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)",
        req_id, loc, pid, qd, threshold, is_large, p["reason"], p.get("evidence_ref"),
        status, staff_id, env.command_id, None)
    if not is_large:
        # small: apply ngay (movement) + set applied_at
        await inv_service.apply_adjustment(
            conn, location_id=loc, product_id=pid, quantity_delta=qd,
            idem_prefix=f"cmd:{env.command_id}", actor_type="staff", actor_id=str(staff_id),
            correlation_id=env.correlation_id, reason=p["reason"], reference_id=str(req_id),
            command_id=env.command_id)
        await conn.execute("UPDATE inventory_adjustment_requests SET applied_at=now() WHERE id=$1", req_id)
    result = {"request_id": str(req_id), "is_large": is_large, "status": status,
              "threshold": threshold, "quantity_delta": qd}
    return result, {"type": "adjustment", "id": str(req_id)}, "inventory.adjust.request", result


async def _do_adjust_decision(conn, env, *, approve: bool):
    staff_id = _staff_id(env)
    p = env.payload
    req_id = uuid.UUID(p["request_id"])
    req = await conn.fetchrow(
        "SELECT * FROM inventory_adjustment_requests WHERE id=$1 FOR UPDATE", req_id)
    if req is None:
        raise LifecycleReject("adjustment_not_found", "Không tìm thấy adjustment request.", 404)
    if req["status"] != "pending":
        raise LifecycleReject("adjustment_not_pending", f"Request đã ở trạng thái {req['status']}.", 409)
    # SoD (§12.3): approver/rejecter != requester
    if staff_id == req["requested_by_staff_id"]:
        raise LifecycleReject("separation_of_duties", "Người duyệt phải khác người yêu cầu.", 403)
    if approve:
        # Unit Head scope (§12.4): approver phải là unit_head của location
        is_head = await conn.fetchval(
            "SELECT 1 FROM inventory_unit_members WHERE staff_id=$1 AND location_id=$2 AND unit_role='unit_head'",
            staff_id, req["location_id"])
        if not is_head:
            raise LifecycleReject("not_unit_head", "Chỉ Unit Head của location được duyệt.", 403)
        # revalidate balance/threshold (§12.3): nếu threshold hiện tại khác -> stale
        await inv_repo.lock_balances(conn, req["location_id"], [req["product_id"]])
        bal = await inv_repo.get_balance(conn, req["location_id"], req["product_id"])
        on_hand_now = bal["on_hand"] if bal else 0
        if inv_service.compute_threshold(on_hand_now) != req["threshold_at_request"]:
            raise LifecycleReject("adjustment_stale", "Balance đã đổi; threshold stale — không apply mù.", 409)
        await inv_service.apply_adjustment(
            conn, location_id=req["location_id"], product_id=req["product_id"],
            quantity_delta=req["quantity_delta"], idem_prefix=f"cmd:{env.command_id}",
            actor_type="staff", actor_id=str(staff_id), correlation_id=env.correlation_id,
            reason=req["reason"], reference_id=str(req_id), command_id=env.command_id)
        await conn.execute(
            "UPDATE inventory_adjustment_requests SET status='applied', approved_by_staff_id=$2, "
            "decided_at=now(), applied_at=now(), decision_command_id=$3 WHERE id=$1",
            req_id, staff_id, env.command_id)
        new_status = "applied"
    else:
        await conn.execute(
            "UPDATE inventory_adjustment_requests SET status='rejected', approved_by_staff_id=$2, "
            "decided_at=now(), decision_command_id=$3 WHERE id=$1", req_id, staff_id, env.command_id)
        new_status = "rejected"
    action = "inventory.adjust.approve" if approve else "inventory.adjust.reject"
    result = {"request_id": str(req_id), "status": new_status, "decided_by": staff_id}
    return result, {"type": "adjustment", "id": str(req_id)}, action, result
