"""CA Directive 243 (Gate F): M5 full-scope (public/customer-wide) scope resolution — MOT nguon duy nhat,
server-side, per-channel. Full-scope ON cho channel => moi customer identity hop le cua channel do enrolled
(khong phu thuoc allowlist). gate_e_kill_switch uu tien cao nhat. Body/sender/LLM KHONG duoc chon scope.

Dung boolean per-channel tuong minh (typed, config-validated o config.py) thay vi sentinel mo ho trong CSV.
"""
from __future__ import annotations

from app.config import settings

M5_CHANNELS = frozenset({"telegram_customer", "messenger"})


def gate_e_fullscope(channel: str | None) -> bool:
    """True neu Gate E/M5 order-wiring full-scope BAT cho channel (public/customer-wide). Kill switch chan
    tat ca (kiem o caller/route). Channel khong hop le -> False (fail-closed)."""
    if channel == "telegram_customer":
        return bool(settings.gate_e_fullscope_telegram_customer)
    if channel == "messenger":
        return bool(settings.gate_e_fullscope_messenger)
    return False


def resolver_fullscope(channel: str | None) -> bool:
    """True neu address resolver full-scope BAT cho channel. Channel khong hop le -> False."""
    if channel == "telegram_customer":
        return bool(settings.address_resolver_fullscope_telegram_customer)
    if channel == "messenger":
        return bool(settings.address_resolver_fullscope_messenger)
    return False


def readback() -> dict:
    """CA 243 §2.2: runtime readback — channel/full-scope/kill-switch/wiring state. KHONG chua secret."""
    return {
        "gate_e_kill_switch": bool(settings.gate_e_kill_switch),
        "enable_gate_e_order_wiring": bool(settings.enable_gate_e_order_wiring),
        "enable_address_resolver": bool(settings.enable_address_resolver),
        "m1_reliable_order_command": bool(settings.m1_reliable_order_command),
        "gate_e_fullscope": {
            "telegram_customer": bool(settings.gate_e_fullscope_telegram_customer),
            "messenger": bool(settings.gate_e_fullscope_messenger),
        },
        "address_resolver_fullscope": {
            "telegram_customer": bool(settings.address_resolver_fullscope_telegram_customer),
            "messenger": bool(settings.address_resolver_fullscope_messenger),
        },
        "gate_e_canary_customer_ids": settings.gate_e_canary_customer_ids or "",
        "address_resolver_pilot_customer_ids": settings.address_resolver_pilot_customer_ids or "",
    }
