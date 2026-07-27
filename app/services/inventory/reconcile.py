"""Reconciliation service (I-B M2 Slice 3). Spec §13.1 reconcile_inventory, §17.1 equations.

Cho mỗi balance:
  balance.on_hand   == Σ movement.on_hand_delta
  balance.reserved  == Σ movement.reserved_delta
  balance.reserved  == Σ active reservation.quantity_remaining
  products.stock     == balance.available   (chỉ default location, compatibility window)

KHÔNG "force sync": chỉ phát hiện + report mismatch (Spec §680). Không tự sửa balance mù.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReconciliationReport:
    balances_checked: int = 0
    mismatches: list[str] = field(default_factory=list)
    checked_stock_compat: bool = False

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def as_dict(self) -> dict:
        return {
            "balances_checked": self.balances_checked,
            "mismatches": self.mismatches,
            "checked_stock_compat": self.checked_stock_compat,
            "ok": self.ok,
        }


async def reconcile_inventory(conn, *, check_stock_compat: bool = True) -> ReconciliationReport:
    rep = ReconciliationReport()
    rows = await conn.fetch(
        "SELECT b.location_id, b.product_id, b.on_hand, b.reserved, "
        " coalesce((SELECT sum(on_hand_delta) FROM inventory_movements m "
        "   WHERE m.location_id=b.location_id AND m.product_id=b.product_id),0) AS led_on_hand, "
        " coalesce((SELECT sum(reserved_delta) FROM inventory_movements m "
        "   WHERE m.location_id=b.location_id AND m.product_id=b.product_id),0) AS led_reserved, "
        " coalesce((SELECT sum(quantity_remaining) FROM inventory_reservations r "
        "   WHERE r.location_id=b.location_id AND r.product_id=b.product_id AND r.status='active'),0) AS active_resv "
        "FROM inventory_balances b"
    )
    rep.balances_checked = len(rows)
    for r in rows:
        key = f"loc{r['location_id']}/prod{r['product_id']}"
        if r["on_hand"] != r["led_on_hand"]:
            rep.mismatches.append(f"{key}: on_hand {r['on_hand']} != ledger {r['led_on_hand']}")
        if r["reserved"] != r["led_reserved"]:
            rep.mismatches.append(f"{key}: reserved {r['reserved']} != ledger {r['led_reserved']}")
        if r["reserved"] != r["active_resv"]:
            rep.mismatches.append(f"{key}: reserved {r['reserved']} != active_resv {r['active_resv']}")

    if check_stock_compat:
        rep.checked_stock_compat = True
        stock_rows = await conn.fetch(
            "SELECT p.id, p.stock, b.on_hand - b.reserved AS available "
            "FROM products p JOIN inventory_balances b ON b.product_id=p.id "
            "JOIN inventory_locations l ON l.id=b.location_id WHERE l.is_default AND l.is_active"
        )
        for r in stock_rows:
            if r["stock"] != r["available"]:
                rep.mismatches.append(
                    f"prod{r['id']}: products.stock {r['stock']} != available {r['available']}"
                )
    return rep
