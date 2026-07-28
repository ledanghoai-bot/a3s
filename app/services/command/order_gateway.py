"""Adapter: route legacy create-order callers -> command service (I-B M1 Slice 4).

Feature flag `settings.m1_reliable_order_command`. Tra ve dict TUONG THICH legacy
(order_id/status/sku/quantity/unit_price_vnd/total_vnd/... hoac {"error":...}) de caller cu
(orchestrator/dashboard) khong phai doi cach doc ket qua — chi them `receipt`/`duplicate`.

Import order_service (asyncpg) — caller import LAZY trong ham de tranh vong import voi tools.
"""
from __future__ import annotations

from app.services.command import errors, idempotency, order_service, registry
from app.services.command import receipt as receipt_mod
from app.services.command.envelope import CHANNELS, Actor, build_order_create_envelope


def can_route(channel: str) -> bool:
    """Chi route khi channel hop le (messenger/telegram_customer/dashboard). Nguoc lai -> legacy."""
    return channel in CHANNELS


async def create_order_command(
    *, channel: str, actor_type: str, actor_id, idempotency_key: str | None = None,
    customer_name: str, phone: str, address: str, sku: str, quantity: int,
    unit_price_vnd: int | None = None, psid: str | None = None,
    conversation_id: int | None = None, correlation_id: str | None = None,
    causation_id: str | None = None, provider_message_id: str | None = None,
) -> dict:
    """Build envelope + execute_order_create + adapt ve legacy dict. Loi validate/conflict ->
    {"error":..., "error_code":...} (khong raise ra caller — giu contract legacy).

    CR-04R: neu idempotency_key None (luong AI) -> DERIVE key on-dinh tu channel + provider_message_id
    + danh tinh nghiep vu (request_hash cua noi dung don), KHONG dung tool_call_id. Dashboard/manual
    truyen key that (header/UUID) -> dung nguyen."""
    raw: dict = {
        "customer_name": customer_name, "phone": phone, "address": address,
        "sku": sku, "quantity": quantity,
    }
    if unit_price_vnd is not None:
        raw["unit_price_vnd"] = unit_price_vnd
    if psid:
        raw["psid"] = psid
    try:
        if idempotency_key is None:
            if not provider_message_id:
                raise errors.key_required()
            normalized = registry.validate_order_create_payload(raw)
            business_key = registry.compute_request_hash(
                registry.ORDER_CREATE, registry.ORDER_CREATE_VERSION,
                registry.order_create_hash_input(normalized))
            idempotency_key = idempotency.ai_stable_key(
                channel=channel, provider_message_id=provider_message_id,
                command_type=registry.ORDER_CREATE, version=registry.ORDER_CREATE_VERSION,
                business_key=business_key)
        env = build_order_create_envelope(
            raw_payload=raw, actor=Actor(actor_type, str(actor_id)), channel=channel,
            idempotency_key=idempotency_key, conversation_id=conversation_id,
            correlation_id=correlation_id, causation_id=causation_id,
        )
        rec = await order_service.execute_order_create(env)
    except errors.CommandError as e:
        return {"error": e.message, "error_code": e.code}

    if rec.outcome == receipt_mod.SUCCEEDED and rec.result and rec.resource:
        r = rec.result
        return {
            "order_id": rec.resource["id"], "status": r["status"], "sku": r["sku"],
            "quantity": r["quantity"], "unit_price_vnd": r["unit_price_vnd"],
            "total_vnd": r["total_vnd"], "customer_name": customer_name,
            "phone": phone, "address": address,
            "receipt": rec.to_dict(),
            "customer_message": receipt_mod.customer_message(rec),
            "duplicate": rec.duplicate,
            "note": "Don da duoc ghi nhan (M1 command bus).",
        }
    # rejected / in_progress -> legacy error shape (caller kiem tra "error")
    return {
        "error": f"Don khong duoc tao ({rec.error_code or rec.outcome}).",
        "error_code": rec.error_code, "outcome": rec.outcome, "receipt": rec.to_dict(),
    }


async def create_order_http(
    *, actor_id, idempotency_key: str | None, customer_name: str, phone: str, address: str,
    sku: str, quantity: int, unit_price_vnd: int | None = None, psid: str | None = None,
    conversation_id: int | None = None,
) -> tuple[int, dict, float | None]:
    """HTTP variant cho dashboard endpoints (§10.2). Tra (status_code, body, retry_after_seconds).
    Actor = staff (dashboard). Bat buoc Idempotency-Key. Map:
    201 first success / 200 duplicate / 202 in_progress / 409 conflict / 422 reject/validation / 400 key."""
    raw: dict = {"customer_name": customer_name, "phone": phone, "address": address,
                 "sku": sku, "quantity": quantity}
    if unit_price_vnd is not None:
        raw["unit_price_vnd"] = unit_price_vnd
    if psid:
        raw["psid"] = psid
    try:
        idempotency.validate_api_key(idempotency_key)  # 400 neu thieu/sai
        env = build_order_create_envelope(
            raw_payload=raw, actor=Actor("staff", str(actor_id)), channel="dashboard",
            idempotency_key=idempotency_key, conversation_id=conversation_id,
        )
        rec = await order_service.execute_order_create(env)
    except errors.CommandError as e:
        return e.http_status, {"error_code": e.code, "detail": e.message}, None

    if rec.outcome == receipt_mod.SUCCEEDED and rec.result and rec.resource:
        r = rec.result
        body = {
            "receipt": rec.to_dict(),
            "customer_message": receipt_mod.customer_message(rec),
            # legacy fields song song (canary coexistence §10.2)
            "order_id": rec.resource["id"], "status": r["status"], "sku": r["sku"],
            "quantity": r["quantity"], "unit_price_vnd": r["unit_price_vnd"],
            "total_vnd": r["total_vnd"], "duplicate": rec.duplicate,
        }
        return (200 if rec.duplicate else 201), body, None
    if rec.outcome == receipt_mod.IN_PROGRESS:
        return 202, {"receipt": rec.to_dict()}, 2.0
    # rejected -> 422 error code on-dinh
    return 422, {"error_code": rec.error_code, "receipt": rec.to_dict()}, None
