"""Operational Outbound Dispatcher (I-B M3 Slice 5). Spec M3 §7.6; Directive §5-S5.

Luồng: committed business event → outbox (M1: dedupe/retry/dead-letter — KHÔNG framework song song)
→ permission/suppression decision (consent S3) → approved template version (032) → channel adapter
→ delivery receipt/dead letter (M1 delivery_attempts).

Quyết định tại THỜI ĐIỂM GỬI (không phải lúc enqueue) — consent mới nhất thắng:
  - deny            -> "suppressed": SendResult ok=True, error_class='suppressed:<reason>:<decision_ref>'
                       (đã xử lý xong một cách CÓ CHỦ ĐÍCH — không retry, không dead-letter;
                        decision_ref nằm trong delivery_attempts.error_class = outbound audit).
  - unavailable     -> P03 transactional: vẫn gửi (consent-infra outage không được chặn receipt);
                       P05/P06: FAIL-CLOSED — SendResult retryable 'consent_unavailable' (thử lại sau).
  - allow           -> render template (approved) -> adapter theo destination.
Template không approved / thiếu param -> terminal (dead-letter, không gửi mù).
Adapter: tái dùng sender M1 (messenger/telegram_customer/telegram_admin); `zalo_zns` = STUB
(vendor/OA chưa duyệt -> terminal 'vendor_not_approved', spec §4.2). Adapter KHÔNG chứa journey policy.
Marketing/lifecycle tương lai bắt buộc mang purpose + policy decision + idempotency (enqueue_outbound).
"""
from __future__ import annotations

from app.db_pool import acquire, release
from app.services import consent
from app.services.command import repository as cmd_repo
from app.services.command.outbox_worker import (
    OUTBOX_DEST_MESSENGER,
    OUTBOX_DEST_TELEGRAM_ADMIN,
    OUTBOX_DEST_TELEGRAM_CUSTOMER,
    SendResult,
    _messenger_send,
    _telegram_customer_send,
    telegram_send,
)

DISPATCH_MARKER = "outbound.message"
DEST_ZALO_ZNS = "zalo_zns"

# destination -> channel (cho consent check per-channel)
_DEST_CHANNEL = {
    OUTBOX_DEST_MESSENGER: "messenger",
    OUTBOX_DEST_TELEGRAM_CUSTOMER: "telegram_customer",
    DEST_ZALO_ZNS: "zalo_zns",
}


async def enqueue_outbound(
    conn,
    *,
    command_id,
    customer_id: int,
    customer_ref: str,
    destination: str,
    purpose_code: str,
    template_key: str,
    template_version: int,
    params: dict,
    dedupe_key: str,
    max_attempts: int,
) -> str | None:
    """Đường vào DUY NHẤT cho outbound qua dispatcher: purpose + template ref + idempotency
    (dedupe_key). KHÔNG nhận free text — nội dung chỉ sinh từ approved template lúc gửi."""
    payload = {
        "dispatch": DISPATCH_MARKER,
        "customer_id": customer_id,
        "customer_ref": customer_ref,
        "purpose_code": purpose_code,
        "template_key": template_key,
        "template_version": template_version,
        "params": params,
    }
    return await cmd_repo.insert_outbox(
        conn, command_id=command_id, event_type=DISPATCH_MARKER, event_version=1,
        destination=destination, dedupe_key=dedupe_key, payload=payload,
        max_attempts=max_attempts)


async def _render(conn, template_key: str, template_version: int, params: dict) -> tuple[str | None, str | None]:
    """-> (text, error_class). Chỉ render template APPROVED đúng version (immutable registry)."""
    row = await conn.fetchrow(
        "SELECT body, status FROM outbound_templates WHERE template_key=$1 AND version=$2",
        template_key, template_version)
    if row is None or row["status"] != "approved":
        return None, "template_not_approved"
    try:
        return row["body"].format(**(params or {})), None
    except (KeyError, IndexError):
        return None, "template_params_missing"


async def _adapter_send(destination: str, payload: dict) -> SendResult:
    """Channel adapter thuần vận chuyển — KHÔNG journey policy (Directive §5-S5)."""
    if destination == OUTBOX_DEST_MESSENGER:
        return await _messenger_send(payload)
    if destination == OUTBOX_DEST_TELEGRAM_CUSTOMER:
        return await _telegram_customer_send(payload)
    if destination == OUTBOX_DEST_TELEGRAM_ADMIN:  # ops alert only
        return await telegram_send(destination, payload)
    if destination == DEST_ZALO_ZNS:
        # STUB: interface sẵn, tích hợp thật BỊ CHẶN tới khi OA/vendor review duyệt (spec §4.2).
        return SendResult(ok=False, http_status=403, error_class="vendor_not_approved")
    return SendResult(ok=False, http_status=400, error_class="unknown_destination")


async def deliver_outbound(destination: str, payload: dict, *, send_adapter=None,
                           check_fn=None) -> SendResult:
    """Xử lý 1 outbox event dạng dispatch (gọi từ outbox_worker.deliver).
    send_adapter/check_fn inject được để test không chạm provider thật."""
    send_adapter = send_adapter or _adapter_send
    check_fn = check_fn or consent.check_permission
    conn = await acquire()
    try:
        purpose = payload.get("purpose_code") or ""
        channel = _DEST_CHANNEL.get(destination, "any")
        decision = await check_fn(conn, customer_id=payload.get("customer_id"),
                                  purpose_code=purpose, channel=channel)
        if decision.decision == "deny":
            # Suppression = kết cục CÓ CHỦ ĐÍCH: đánh dấu delivered với audit decision_ref,
            # KHÔNG gửi, KHÔNG retry (spec §7.4: audit lưu decision_ref, không copy evidence).
            return SendResult(ok=True, http_status=None, provider_message_id=None,
                              error_class=f"suppressed:{decision.reason_code}:{decision.decision_ref}")
        if decision.decision == "unavailable" and purpose != "P03_TRANSACTIONAL":
            # fail-closed cho marketing/lifecycle: KHÔNG gửi khi không xác định được consent.
            return SendResult(ok=False, error_class="consent_unavailable")  # retryable

        text, err = await _render(conn, payload.get("template_key") or "",
                                  int(payload.get("template_version") or 0),
                                  payload.get("params"))
        if err:
            return SendResult(ok=False, http_status=400, error_class=err)  # terminal
        out_payload = {"customer_ref": payload.get("customer_ref"), "text": text,
                       "decision_ref": decision.decision_ref}
        return await send_adapter(destination, out_payload)
    finally:
        await release(conn)
