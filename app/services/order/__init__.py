"""Order state machine + transition service (I-B M2 — Order and Inventory Correctness). Spec §7.

transitions: matrix + guard (pure). events: append_order_event. transition_service: shared engine
(apply_transition + reserve_on_create). Flags M2 default OFF; runtime wiring Slice 4/5.
"""
from app.services.order import events, transition_service, transitions  # noqa: F401
from app.services.order.transitions import IllegalTransition  # noqa: F401

__all__ = ["events", "transition_service", "transitions", "IllegalTransition"]
