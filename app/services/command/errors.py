"""Stable error codes cho command bus (I-B M1). Spec §6.2, §10.2.

Error code la HOP DONG on-dinh (client/test doi chieu) — KHONG doi chuoi khi da phat hanh.
CommandError mang code + http_status + message an toan (khong PII). Business reject -> 422.
"""
from __future__ import annotations


class CommandError(Exception):
    """Loi command co error_code on-dinh + http_status de API map truc tiep."""

    def __init__(self, code: str, message: str, http_status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# --- Envelope / idempotency (client contract) ---
IDEMPOTENCY_KEY_REQUIRED = "idempotency_key_required"     # 400
IDEMPOTENCY_KEY_INVALID = "idempotency_key_invalid"       # 400
IDEMPOTENCY_CONFLICT = "idempotency_conflict"             # 409 (cung key, khac hash)
COMMAND_IN_PROGRESS = "command_in_progress"               # 202
UNKNOWN_COMMAND_TYPE = "unknown_command_type"             # 422
INVALID_ENVELOPE = "invalid_envelope"                     # 422

# --- order.create business rejects (§17 AC map -> 422, khong tao order) ---
INVALID_QUANTITY = "invalid_quantity"
INVALID_PHONE = "invalid_phone"
PRODUCT_NOT_FOUND = "product_not_found"
INSUFFICIENT_STOCK = "insufficient_stock"
QUANTITY_EXCEEDS_AUTO_LIMIT = "quantity_exceeds_auto_limit"


def key_required() -> CommandError:
    return CommandError(IDEMPOTENCY_KEY_REQUIRED, "Thieu Idempotency-Key.", http_status=400)


def key_invalid(detail: str) -> CommandError:
    return CommandError(IDEMPOTENCY_KEY_INVALID, f"Idempotency-Key khong hop le: {detail}", http_status=400)


def idempotency_conflict() -> CommandError:
    return CommandError(
        IDEMPOTENCY_CONFLICT,
        "Idempotency-Key da dung voi payload khac (conflict).",
        http_status=409,
    )


def unknown_command(command_type: str, version: int) -> CommandError:
    return CommandError(
        UNKNOWN_COMMAND_TYPE, f"Command khong ho tro: {command_type} v{version}", http_status=422
    )
