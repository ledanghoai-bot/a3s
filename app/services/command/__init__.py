"""Command bus domain contract (I-B M1 — Reliable Command and Receipt).

Governing: A3S-PHASE1B-M1-SPEC-001 v1.0.0. Package thuan domain (envelope/hash/idempotency/
registry/receipt/retry/redaction) — KHONG side effect I/O; service layer (Slice 3) dung repository
+ transaction. Import lazy tu submodule de tranh keo asyncpg vao unit test thuan.
"""
from app.services.command import (  # noqa: F401
    errors,
    hashing,
    idempotency,
    receipt,
    redaction,
    registry,
    retry,
)
from app.services.command.envelope import (  # noqa: F401
    Actor,
    CommandEnvelope,
    build_order_create_envelope,
)
from app.services.command.errors import CommandError  # noqa: F401
from app.services.command.receipt import CommandReceipt  # noqa: F401

__all__ = [
    "errors",
    "hashing",
    "idempotency",
    "receipt",
    "redaction",
    "registry",
    "retry",
    "Actor",
    "CommandEnvelope",
    "build_order_create_envelope",
    "CommandError",
    "CommandReceipt",
]
