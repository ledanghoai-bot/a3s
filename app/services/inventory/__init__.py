"""Inventory domain (I-B M2 — Order and Inventory Correctness). Spec §9, §10, §17.

Package thuần domain: repository (balance/reservation/ledger primitive), service (reserve/release/
fulfill/adjust), reconcile (§17.1). MỌI mutation qua apply_movement (ledger append-only + balance
materialized + invariant + idempotent). Lock ordering §10.4. Flags M2 default OFF; runtime wiring ở
Slice 4/5. Import lazy để không kéo asyncpg vào unit thuần.
"""
from app.services.inventory import errors, reconcile, repository, service  # noqa: F401
from app.services.inventory.errors import InventoryError  # noqa: F401
from app.services.inventory.repository import MovementEffect  # noqa: F401

__all__ = ["errors", "reconcile", "repository", "service", "InventoryError", "MovementEffect"]
