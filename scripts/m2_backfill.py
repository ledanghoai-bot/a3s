#!/usr/bin/env python3
"""M2 Slice 2 — inventory backfill + reconciliation tooling (Spec §15, §17.1).

Cutover tooling: dựng inventory_balances/reservations/movements từ legacy `products.stock` +
active-unfulfilled orders. KHÔNG copy mù stock. Resumable, deterministic, checksum, abort-on-anomaly.

Usage (chạy trong container, DATABASE_URL từ env hoặc --url):
  python scripts/m2_backfill.py audit                 # §15.4 pre-flight; exit!=0 nếu anomaly
  python scripts/m2_backfill.py plan  [--report P]    # dry-run: reconstruct + checksum, KHÔNG ghi
  python scripts/m2_backfill.py apply [--report P]    # audit -> apply (idempotent) -> reconcile
  python scripts/m2_backfill.py reconcile             # chỉ chạy §17.1 equations, exit!=0 nếu mismatch

Reconstruct (§15.4):
  opening_reserved  = Σ quantity của order_items thuộc order active-unfulfilled (status new/confirmed)
  opening_on_hand   = products.stock + opening_reserved
  opening_available = products.stock            (= on_hand - reserved)

Default location: code 'default-fulfillment' (Spec §15.3); display name PO-approved = 'Kho chính'.
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

import asyncpg

DEFAULT_LOCATION_CODE = "default-fulfillment"
DEFAULT_LOCATION_NAME = "Kho chính"  # PO-approved (a. Kho chính)
DEFAULT_LOCATION_TYPE = "fulfillment"

# Legacy status semantics (Spec §15.4, khớp Slice0 audit)
ACTIVE_UNFULFILLED = {"new", "confirmed"}
CONSUMED = {"shipped", "done"}          # đã tiêu thụ, KHÔNG cộng lại
CANCELLED = {"cancelled"}
KNOWN = ACTIVE_UNFULFILLED | CONSUMED | CANCELLED


def _url() -> str:
    if "--url" in sys.argv:
        u = sys.argv[sys.argv.index("--url") + 1]
    else:
        u = os.environ.get("DATABASE_URL") or "postgresql://alpha3s:alpha3s@db:5432/alpha3s"
    return u.replace("+asyncpg", "")


# ---------------------------------------------------------------------------
# §15.4 pre-flight audit — abort on anomaly / unknown
# ---------------------------------------------------------------------------
async def audit(conn) -> dict:
    anomalies = []
    statuses = await conn.fetch(
        "SELECT o.status, count(*) AS n, coalesce(sum(oi.quantity),0) AS qty "
        "FROM orders o LEFT JOIN order_items oi ON oi.order_id=o.id GROUP BY o.status ORDER BY o.status"
    )
    status_map = {r["status"]: {"orders": r["n"], "qty": int(r["qty"])} for r in statuses}

    unknown = [s for s in status_map if s not in KNOWN]
    if unknown:
        anomalies.append(f"unknown_status={unknown}")

    neg = await conn.fetchval("SELECT count(*) FROM products WHERE stock < 0")
    if neg:
        anomalies.append(f"negative_stock_products={neg}")

    orphan = await conn.fetchval(
        "SELECT count(*) FROM order_items oi LEFT JOIN products p ON p.id=oi.product_id WHERE p.id IS NULL"
    )
    if orphan:
        anomalies.append(f"orphan_order_items={orphan}")

    # missing product cho order active (không resolve được product để reserve)
    missing_active = await conn.fetchval(
        "SELECT count(*) FROM orders o JOIN order_items oi ON oi.order_id=o.id "
        "LEFT JOIN products p ON p.id=oi.product_id "
        "WHERE o.status = ANY($1::text[]) AND p.id IS NULL",
        list(ACTIVE_UNFULFILLED),
    )
    if missing_active:
        anomalies.append(f"active_missing_product={missing_active}")

    return {"status_breakdown": status_map, "anomalies": anomalies, "ok": not anomalies}


# ---------------------------------------------------------------------------
# Reconstruct plan (deterministic) — không ghi
# ---------------------------------------------------------------------------
async def build_plan(conn) -> dict:
    products = await conn.fetch("SELECT id, sku, stock FROM products ORDER BY id")
    # active reservations: mỗi order_item của order active-unfulfilled
    resv_rows = await conn.fetch(
        "SELECT oi.id AS order_item_id, oi.order_id, oi.product_id, oi.quantity "
        "FROM orders o JOIN order_items oi ON oi.order_id=o.id "
        "WHERE o.status = ANY($1::text[]) AND oi.quantity > 0 "
        "ORDER BY oi.product_id, oi.id",
        list(ACTIVE_UNFULFILLED),
    )
    reserved_by_product: dict[int, int] = {}
    reservations: list[dict] = []
    for r in resv_rows:
        pid = r["product_id"]
        reserved_by_product[pid] = reserved_by_product.get(pid, 0) + r["quantity"]
        reservations.append(dict(r))

    balances = []
    for p in products:
        pid = p["id"]
        opening_reserved = reserved_by_product.get(pid, 0)
        opening_on_hand = p["stock"] + opening_reserved
        balances.append({
            "product_id": pid,
            "sku": p["sku"],
            "legacy_stock": p["stock"],
            "opening_reserved": opening_reserved,
            "opening_on_hand": opening_on_hand,
            "opening_available": opening_on_hand - opening_reserved,  # == legacy_stock
        })

    checksum = hashlib.sha256(
        json.dumps(
            {
                "balances": [
                    [b["product_id"], b["opening_on_hand"], b["opening_reserved"]] for b in balances
                ],
                "reservations": [
                    [r["order_item_id"], r["order_id"], r["product_id"], r["quantity"]]
                    for r in reservations
                ],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    return {"balances": balances, "reservations": reservations, "checksum": checksum}


# ---------------------------------------------------------------------------
# Apply (idempotent / resumable)
# ---------------------------------------------------------------------------
async def resolve_default_location(conn) -> int:
    loc = await conn.fetchval(
        "SELECT id FROM inventory_locations WHERE code=$1", DEFAULT_LOCATION_CODE
    )
    if loc is None:
        loc = await conn.fetchval(
            "INSERT INTO inventory_locations (code,name,location_type,is_default,is_active) "
            "VALUES ($1,$2,$3,true,true) RETURNING id",
            DEFAULT_LOCATION_CODE, DEFAULT_LOCATION_NAME, DEFAULT_LOCATION_TYPE,
        )
    # invariant: đúng một default active (partial unique index đã enforce; đây là double-check)
    n = await conn.fetchval(
        "SELECT count(*) FROM inventory_locations WHERE is_default AND is_active"
    )
    if n != 1:
        raise SystemExit(f"STOP: {n} default-active locations (phải đúng 1)")
    return loc


async def apply(conn, plan: dict, batch: str) -> None:
    loc = await resolve_default_location(conn)
    for b in plan["balances"]:
        pid = b["product_id"]
        on_hand = b["opening_on_hand"]
        # 1) balance row (idempotent): tạo với reserved=0, set absolute reserved ở bước 4
        await conn.execute(
            "INSERT INTO inventory_balances (location_id,product_id,on_hand,reserved) "
            "VALUES ($1,$2,$3,0) ON CONFLICT (location_id,product_id) DO NOTHING",
            loc, pid, on_hand,
        )
        # 2) opening_balance movement (idempotent qua idempotency_key)
        await conn.execute(
            "INSERT INTO inventory_movements "
            "(id,location_id,product_id,movement_type,on_hand_delta,reserved_delta,"
            " before_on_hand,after_on_hand,before_reserved,after_reserved,"
            " reference_type,reference_id,idempotency_key,actor_type,actor_id,correlation_id,reason) "
            "VALUES ($1,$2,$3,'opening_balance',$4,0,0,$4,0,0,'backfill',$5,$6,'system','m2-backfill',$7,$8) "
            "ON CONFLICT (idempotency_key) DO NOTHING",
            uuid.uuid4(), loc, pid, on_hand, batch,
            f"backfill:opening:{loc}:{pid}", uuid.UUID(batch),
            f"opening_balance reconstruct (stock={b['legacy_stock']} + reserved={b['opening_reserved']})",
        )

    # 3) reservations + reserve movements (deterministic before/after cumulative)
    cum: dict[int, int] = {}
    for r in plan["reservations"]:
        pid = r["product_id"]
        qty = r["quantity"]
        before = cum.get(pid, 0)
        after = before + qty
        cum[pid] = after
        resv_id = uuid.uuid5(uuid.NAMESPACE_OID, f"backfill:resv:{r['order_item_id']}")
        await conn.execute(
            "INSERT INTO inventory_reservations "
            "(id,order_id,order_item_id,location_id,product_id,quantity_initial,quantity_remaining,"
            " status,idempotency_key) "
            "VALUES ($1,$2,$3,$4,$5,$6,$6,'active',$7) ON CONFLICT (idempotency_key) DO NOTHING",
            resv_id, r["order_id"], r["order_item_id"], loc, pid, qty,
            f"backfill:resv:{r['order_item_id']}",
        )
        await conn.execute(
            "INSERT INTO inventory_movements "
            "(id,location_id,product_id,reservation_id,order_id,order_item_id,movement_type,"
            " on_hand_delta,reserved_delta,before_on_hand,after_on_hand,before_reserved,after_reserved,"
            " reference_type,reference_id,idempotency_key,actor_type,actor_id,correlation_id) "
            "VALUES ($1,$2,$3,$4,$5,$6,'reserve',0,$7,$8,$8,$9,$10,'order_item',$11,$12,'system','m2-backfill',$13) "
            "ON CONFLICT (idempotency_key) DO NOTHING",
            uuid.uuid4(), loc, pid, resv_id, r["order_id"], r["order_item_id"],
            qty, plan_on_hand(plan, pid), before, after,
            str(r["order_item_id"]), f"backfill:reserve:{r['order_item_id']}", uuid.UUID(batch),
        )
    # 4) set absolute reserved trên balance (idempotent) từ plan
    for b in plan["balances"]:
        await conn.execute(
            "UPDATE inventory_balances SET reserved=$3 WHERE location_id=$1 AND product_id=$2",
            loc, b["product_id"], b["opening_reserved"],
        )


def plan_on_hand(plan: dict, product_id: int) -> int:
    for b in plan["balances"]:
        if b["product_id"] == product_id:
            return b["opening_on_hand"]
    raise KeyError(product_id)


# ---------------------------------------------------------------------------
# §17.1 reconciliation equations
# ---------------------------------------------------------------------------
async def reconcile(conn) -> dict:
    mismatches = []
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
    for r in rows:
        key = f"loc{r['location_id']}/prod{r['product_id']}"
        if r["on_hand"] != r["led_on_hand"]:
            mismatches.append(f"{key}: on_hand {r['on_hand']} != ledger {r['led_on_hand']}")
        if r["reserved"] != r["led_reserved"]:
            mismatches.append(f"{key}: reserved {r['reserved']} != ledger {r['led_reserved']}")
        if r["reserved"] != r["active_resv"]:
            mismatches.append(f"{key}: reserved {r['reserved']} != active_resv {r['active_resv']}")

    # products.stock == balance.available (compatibility window, default location)
    stock_rows = await conn.fetch(
        "SELECT p.id, p.stock, b.on_hand - b.reserved AS available "
        "FROM products p JOIN inventory_balances b ON b.product_id=p.id "
        "JOIN inventory_locations l ON l.id=b.location_id WHERE l.is_default AND l.is_active"
    )
    for r in stock_rows:
        if r["stock"] != r["available"]:
            mismatches.append(f"prod{r['id']}: products.stock {r['stock']} != available {r['available']}")

    return {"balances_checked": len(rows), "mismatches": mismatches, "ok": not mismatches}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
async def run(cmd: str, report_path: str | None) -> int:
    conn = await asyncpg.connect(_url())
    try:
        if cmd == "audit":
            a = await audit(conn)
            print(json.dumps(a, ensure_ascii=False, indent=2))
            return 0 if a["ok"] else 2

        if cmd in ("plan", "apply"):
            a = await audit(conn)
            if not a["ok"]:
                print("ABORT — anomalies: " + "; ".join(a["anomalies"]))
                print(json.dumps(a, ensure_ascii=False, indent=2))
                return 2
            plan = await build_plan(conn)
            batch = str(uuid.uuid4())
            report = {"command": cmd, "batch": batch, "audit": a, "plan": plan}
            if cmd == "apply":
                async with conn.transaction():
                    await apply(conn, plan, batch)
                report["reconcile"] = await reconcile(conn)
                report["applied"] = report["reconcile"]["ok"]
            if report_path:
                Path(report_path).write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            print(f"checksum={plan['checksum']}  balances={len(plan['balances'])}  "
                  f"reservations={len(plan['reservations'])}")
            if cmd == "apply":
                rc = report["reconcile"]
                print(f"reconcile: {'OK' if rc['ok'] else 'MISMATCH'} "
                      f"({rc['balances_checked']} balances)")
                if not rc["ok"]:
                    for m in rc["mismatches"]:
                        print("  ! " + m)
                    return 3
            return 0

        if cmd == "reconcile":
            rc = await reconcile(conn)
            print(json.dumps(rc, ensure_ascii=False, indent=2))
            return 0 if rc["ok"] else 3

        print(f"unknown command: {cmd}")
        return 64
    finally:
        await conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["audit", "plan", "apply", "reconcile"])
    ap.add_argument("--report")
    ap.add_argument("--url")
    args, _ = ap.parse_known_args()
    sys.exit(asyncio.run(run(args.command, args.report)))


if __name__ == "__main__":
    main()
