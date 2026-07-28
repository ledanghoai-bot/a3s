"""Inventory domain errors (I-B M2). Spec §6, §10.

Error code là HỢP ĐỒNG ổn định (client/test đối chiếu) — KHÔNG đổi chuỗi khi đã phát hành.
Business reject -> 422; conflict/stale -> 409.
"""
from __future__ import annotations


class InventoryError(Exception):
    """Lỗi domain tồn kho có error_code ổn định + http_status."""

    def __init__(self, code: str, message: str, http_status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# --- codes (contract) ---
INSUFFICIENT_INVENTORY = "insufficient_inventory"     # 422 (available < requested)
INVARIANT_VIOLATION = "inventory_invariant_violation"  # 422 (on_hand<0 / reserved<0 / reserved>on_hand)
NO_DEFAULT_LOCATION = "no_default_location"           # 422
RESERVATION_NOT_ACTIVE = "reservation_not_active"     # 409
ADJUSTMENT_STALE = "adjustment_stale"                 # 409 (before snapshot khác balance hiện tại)


def insufficient(product_id: int, requested: int, available: int) -> InventoryError:
    return InventoryError(
        INSUFFICIENT_INVENTORY,
        f"Không đủ tồn cho product {product_id}: cần {requested}, còn {available}.",
        http_status=422,
    )


def invariant(detail: str) -> InventoryError:
    return InventoryError(INVARIANT_VIOLATION, f"Vi phạm invariant tồn kho: {detail}", http_status=422)


def no_default_location() -> InventoryError:
    return InventoryError(NO_DEFAULT_LOCATION, "Chưa cấu hình default fulfillment location.", 422)


def reservation_not_active(reservation_id: str) -> InventoryError:
    return InventoryError(RESERVATION_NOT_ACTIVE, f"Reservation {reservation_id} không ở trạng thái active.", 409)


def adjustment_stale() -> InventoryError:
    return InventoryError(ADJUSTMENT_STALE, "Balance đã thay đổi; before snapshot cũ — không apply mù.", 409)
