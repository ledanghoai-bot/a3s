"""Order state machine — explicit transition matrix + guard (I-B M2 Slice 4). Spec §7.

Two-axis: order_status (business) + inventory_status (summary). Mọi transition PHẢI khớp matrix;
khác -> 409 illegal_order_transition. KHÔNG "sửa status" bằng CRUD generic (§7.3). Pure logic —
unit-testable, không I/O.
"""
from __future__ import annotations

from dataclasses import dataclass

# --- order_status (§7.1; M3-S1 thêm 'delivered') ---
ORDER_STATUSES = {
    "new", "confirmed", "processing", "ready_for_fulfillment", "fulfilled", "delivered",
    "delivery_failed", "return_requested", "return_inspection", "completed",
    "cancelled", "cancelled_by_exception",
}
TERMINAL = {"completed", "cancelled", "cancelled_by_exception"}

# --- inventory_status (§7.4) ---
INVENTORY_STATUSES = {
    "unreserved", "reserved", "partially_reserved", "fulfilled", "released", "return_inspection",
}

# inventory effect ổn định (contract, dùng trong receipt)
EFFECT_NONE = "none"
EFFECT_RESERVE = "reserve"
EFFECT_RELEASE = "reservation_released"
EFFECT_CONSUME = "reserved_consumed"
EFFECT_RETURN_INSPECT = "return_inspection"


@dataclass(frozen=True)
class TransitionSpec:
    to_status: str
    permission: str | None      # None = system/policy (không map RBAC perm trực tiếp)
    inventory_effect: str
    inventory_status_after: str | None  # None = giữ nguyên


# action (command verb) -> spec. Guard theo (from_status, action).
# Spec §7.2 matrix. Key = (from_status, action).
_MATRIX: dict[tuple[str, str], TransitionSpec] = {
    ("new", "confirm"):
        TransitionSpec("confirmed", "order.confirm", EFFECT_NONE, None),
    ("new", "cancel"):
        TransitionSpec("cancelled", "order.cancel", EFFECT_RELEASE, "released"),
    ("confirmed", "start_processing"):
        TransitionSpec("processing", "order.process", EFFECT_NONE, None),
    ("confirmed", "cancel"):
        TransitionSpec("cancelled", "order.cancel", EFFECT_RELEASE, "released"),
    ("processing", "ready_for_fulfillment"):
        TransitionSpec("ready_for_fulfillment", "order.fulfillment.prepare", EFFECT_NONE, None),
    ("processing", "cancel_by_exception"):
        TransitionSpec("cancelled_by_exception", "order.cancel.exception", EFFECT_RELEASE, "released"),
    ("ready_for_fulfillment", "fulfill"):
        TransitionSpec("fulfilled", "order.fulfill", EFFECT_CONSUME, "fulfilled"),
    # CA M2-S1-F03: mutation dùng quyền WRITE riêng, KHÔNG dùng order.transition.view (read-only).
    ("fulfilled", "complete"):
        TransitionSpec("completed", "order.complete", EFFECT_NONE, None),
    ("fulfilled", "mark_delivery_failed"):
        TransitionSpec("delivery_failed", "order.delivery.manage", EFFECT_NONE, None),
    ("fulfilled", "request_return"):
        TransitionSpec("return_requested", "order.return.manage", EFFECT_NONE, None),
    ("delivery_failed", "return_inspect"):
        TransitionSpec("return_inspection", "order.return.manage", EFFECT_RETURN_INSPECT, "return_inspection"),
    ("return_requested", "return_inspect"):
        TransitionSpec("return_inspection", "order.return.manage", EFFECT_RETURN_INSPECT, "return_inspection"),
    ("return_inspection", "complete"):
        TransitionSpec("completed", "order.complete", EFFECT_NONE, None),
    # --- M3-S1 (spec M3 §7.2). Legacy 'shipped' ≙ M2 'fulfilled' (Slice0 mapping) nên
    # "shipped -> delivered|delivery_failed" của spec = fulfilled -> delivered|delivery_failed,
    # "delivery_failed -> shipped(retry)" = delivery_failed -> fulfilled. Gate flag m3_delivered_lifecycle
    # nằm ở transition_service (module này pure). ---
    ("fulfilled", "mark_delivered"):
        TransitionSpec("delivered", "order.delivery.manage", EFFECT_NONE, None),
    ("delivered", "complete"):
        TransitionSpec("completed", "order.complete", EFFECT_NONE, None),
    ("delivered", "request_return"):
        TransitionSpec("return_requested", "order.return.manage", EFFECT_NONE, None),
    ("delivery_failed", "retry_delivery"):
        TransitionSpec("fulfilled", "order.delivery.manage", EFFECT_NONE, None),
    # Huỷ sau giao thất bại: reservation đã CONSUME tại fulfill -> KHÔNG release (EFFECT_NONE);
    # hàng vật lý quay về kho xử lý qua return_inspect hoặc adjustment SoD, không auto-cộng stock.
    ("delivery_failed", "cancel"):
        TransitionSpec("cancelled", "order.cancel.exception", EFFECT_NONE, None),
}

# Cặp transition thuộc M3 — chỉ hợp lệ khi flag m3_delivered_lifecycle bật (check ở service layer).
M3_PAIRS: set[tuple[str, str]] = {
    ("fulfilled", "mark_delivered"),
    ("delivered", "complete"),
    ("delivered", "request_return"),
    ("delivery_failed", "retry_delivery"),
    ("delivery_failed", "cancel"),
}


class IllegalTransition(Exception):
    """409 illegal_order_transition."""

    code = "illegal_order_transition"
    http_status = 409

    def __init__(self, from_status: str, action: str):
        super().__init__(f"Transition không hợp lệ: {from_status} --{action}-->")
        self.from_status = from_status
        self.action = action


def actions_for(from_status: str) -> list[str]:
    return sorted(a for (f, a) in _MATRIX if f == from_status)


def resolve(from_status: str, action: str) -> TransitionSpec:
    """Trả TransitionSpec hợp lệ hoặc raise IllegalTransition. Terminal -> luôn reject (§7.3)."""
    spec = _MATRIX.get((from_status, action))
    if spec is None:
        raise IllegalTransition(from_status, action)
    return spec
