"""M6 payment service — amount_due / evidence / status (CA Directive 265 §4.2/§4.3).

Tach 3 nghia:
- amount_due_vnd = so tien can thu (order.total + delivery_fee da chot); NULL khi fee chua co -> chua chot tong.
- payment_events (append-only) = evidence: khach bao / COD thu / shop xac nhan nhan / reconcile / correction.
- payments.status = shop da xac nhan toi dau. Delivered != paid; collected != reconciled; khach "da chuyen"/anh
  KHONG tu thanh confirmed.
Transitions:
- BANK_TRANSFER: awaiting -> reported (customer_reported) -> confirmed (shop_confirmed_received, du tien).
- COD: awaiting -> collected (cod_collected) -> reconciled (reconciled, du tien).
Partial/thieu -> KHONG auto-confirm (giu status, hien chenh lech, staff xu ly). Excess -> confirmed + ghi thua.
Idempotency: cung (payment_id, kind, reference) khong ghi/cong 2 lan. Evidence append-only (trigger DB).
Bank config versioned; instruction snapshot account version + noi dung deterministic tu ma don.
"""
from __future__ import annotations

from app.services import audit_service

METHODS = ("COD", "BANK_TRANSFER")


class PaymentError(Exception):
    """Fail-closed. Khong leak secret."""


def transfer_content(order_id: int) -> str:
    """Noi dung chuyen khoan DETERMINISTIC tu ma don."""
    return f"3SCF {order_id}"


async def _order_total(conn, order_id: int) -> int:
    t = await conn.fetchval("SELECT total_vnd FROM orders WHERE id=$1", order_id)
    if t is None:
        raise PaymentError(f"order {order_id} khong ton tai")
    return int(t)


async def _quoted_fee(conn, order_id: int) -> int | None:
    """delivery_fee neu shipment da 'quoted'; nguoc lai None (chua chot -> amount_due chua finalize)."""
    row = await conn.fetchrow("SELECT delivery_fee_vnd, fee_status FROM shipments WHERE order_id=$1", order_id)
    if row and row["fee_status"] == "quoted":
        return int(row["delivery_fee_vnd"])
    return None


async def ensure_payment(conn, order_id: int, *, method: str, actor: str) -> dict:
    """Get-or-create payment cho order. amount_due = order.total + fee (neu fee da quoted), else NULL."""
    if method not in METHODS:
        raise PaymentError("method phai COD|BANK_TRANSFER")
    row = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", order_id)
    if row:
        return dict(row)
    total = await _order_total(conn, order_id)
    fee = await _quoted_fee(conn, order_id)
    amount_due = (total + fee) if fee is not None else None
    row = await conn.fetchrow(
        "INSERT INTO payments (order_id, method, amount_due_vnd, status) VALUES ($1,$2,$3,'awaiting') "
        "ON CONFLICT (order_id) DO UPDATE SET updated_at=now() RETURNING *", order_id, method, amount_due)
    await audit_service.record(conn, actor_type="cli", action="payment.create", actor_ref=actor,
                               entity_type="payments", entity_id=str(row["id"]),
                               after={"order_id": order_id, "method": method, "amount_due_vnd": amount_due})
    return dict(row)


async def recompute_amount_due(conn, order_id: int, *, actor: str) -> dict:
    """Cap nhat amount_due khi fee da chot (Directive: truoc khi khach xac nhan tong phai co phi cu the)."""
    pay = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", order_id)
    if not pay:
        raise PaymentError(f"payment cho order {order_id} chua ton tai")
    total = await _order_total(conn, order_id)
    fee = await _quoted_fee(conn, order_id)
    amount_due = (total + fee) if fee is not None else None
    if amount_due != pay["amount_due_vnd"]:
        pay = await conn.fetchrow(
            "UPDATE payments SET amount_due_vnd=$2, version=version+1, updated_at=now() WHERE id=$1 RETURNING *",
            pay["id"], amount_due)
        await audit_service.record(conn, actor_type="cli", action="payment.amount_due", actor_ref=actor,
                                   entity_type="payments", entity_id=str(pay["id"]),
                                   after={"amount_due_vnd": amount_due})
    return dict(pay)


# kind hop le theo method + status ky vong truoc do (fail-closed thu tu)
_ADVANCE = {
    ("BANK_TRANSFER", "customer_reported"): ("reported", ("awaiting", "reported")),
    ("BANK_TRANSFER", "shop_confirmed_received"): ("confirmed", ("awaiting", "reported")),
    ("COD", "cod_collected"): ("collected", ("awaiting", "collected")),
    ("COD", "reconciled"): ("reconciled", ("collected",)),
}


async def record_evidence(conn, order_id: int, *, kind: str, amount_vnd: int | None, recorded_by: str,
                          reference: str | None = None, note: str | None = None,
                          attachment_ref: str | None = None) -> dict:
    """Append evidence + advance status theo method. 'correction' chi ghi lich su, khong doi status tu dong.
    Idempotent: cung (payment_id, kind, reference) da ton tai -> tra ket qua cu, khong cong tien lan nua."""
    pay = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", order_id)
    if not pay:
        raise PaymentError(f"payment cho order {order_id} chua ton tai")
    method, cur = pay["method"], pay["status"]

    # idempotency theo reference (§4.2: cung reference/evidence gui lai khong cong tien lan nua)
    if reference:
        dup = await conn.fetchrow(
            "SELECT id FROM payment_events WHERE payment_id=$1 AND kind=$2 AND reference=$3",
            pay["id"], kind, reference)
        if dup:
            return {"payment": dict(pay), "event_id": str(dup["id"]), "duplicate": True,
                    "status": cur, "discrepancy": None}

    if kind == "correction":
        ev = await _insert_event(conn, pay["id"], kind, amount_vnd, recorded_by, reference, note, attachment_ref)
        await audit_service.record(conn, actor_type="cli", action="payment.correction", actor_ref=recorded_by,
                                   entity_type="payments", entity_id=str(pay["id"]),
                                   after={"amount_vnd": amount_vnd, "reason": bool(note)})
        return {"payment": dict(pay), "event_id": str(ev["id"]), "duplicate": False,
                "status": cur, "discrepancy": None}

    spec = _ADVANCE.get((method, kind))
    if spec is None:
        raise PaymentError(f"kind '{kind}' khong hop le cho method {method}")
    to_status, valid_from = spec
    if cur not in valid_from:
        raise PaymentError(f"sai thu tu: {method} status={cur} khong the ghi '{kind}'")

    ev = await _insert_event(conn, pay["id"], kind, amount_vnd, recorded_by, reference, note, attachment_ref)

    # advance status CHI khi la buoc confirm/reconcile va tien du (partial/thieu -> khong auto-confirm)
    discrepancy = None
    new_status = to_status
    if kind in ("shop_confirmed_received", "reconciled"):
        due = pay["amount_due_vnd"]
        if due is None:
            raise PaymentError("amount_due chua chot (fee chua co) — khong the xac nhan du tien")
        got = amount_vnd if amount_vnd is not None else 0
        if got < due:
            discrepancy = {"kind": "partial", "due": due, "got": got, "delta": got - due}
            new_status = cur  # KHONG auto-confirm khi thieu -> giu nguyen, staff xu ly
        elif got > due:
            discrepancy = {"kind": "excess", "due": due, "got": got, "delta": got - due}
            # excess: da du tien -> confirm/reconcile, ghi thua
    if new_status != cur:
        pay = await conn.fetchrow(
            "UPDATE payments SET status=$2, version=version+1, updated_at=now() WHERE id=$1 AND version=$3 "
            "RETURNING *", pay["id"], new_status, pay["version"])
        if pay is None:
            raise PaymentError("version conflict (concurrent) — huy")
    await audit_service.record(conn, actor_type="cli", action="payment.evidence", actor_ref=recorded_by,
                               entity_type="payments", entity_id=str(pay["id"]),
                               before={"status": cur}, after={"kind": kind, "status": new_status,
                                                              "discrepancy": discrepancy})
    from app.services.fulfillment import (
        notify as _n,  # CA 265 §4.4: notify khach (lazy: tranh circular)
    )
    await _n.notify_payment(conn, order_id, kind=kind, new_status=new_status)
    return {"payment": dict(pay), "event_id": str(ev["id"]), "duplicate": False,
            "status": new_status, "discrepancy": discrepancy}


async def _insert_event(conn, payment_id, kind, amount_vnd, recorded_by, reference, note, attachment_ref):
    return await conn.fetchrow(
        "INSERT INTO payment_events (payment_id, kind, amount_vnd, recorded_by, reference, note, attachment_ref) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *",
        payment_id, kind, amount_vnd, recorded_by, reference, note, attachment_ref)


# ---------------- Bank account config + instruction ----------------

async def set_bank_account(conn, *, bank: str, account_number: str, holder_name: str, actor: str,
                           branch: str | None = None, is_test: bool = False) -> dict:
    """Tao account version moi + deactivate active cu (1 active). account_number giu nguyen TEXT (so 0 dau)."""
    if not (bank and account_number and holder_name):
        raise PaymentError("thieu bank/account_number/holder_name")
    prev = await conn.fetchrow("SELECT * FROM bank_accounts WHERE active")
    new_version = (prev["version"] + 1) if prev else 1
    async with conn.transaction():
        if prev:
            await conn.execute("UPDATE bank_accounts SET active=false, updated_at=now() WHERE id=$1", prev["id"])
        row = await conn.fetchrow(
            "INSERT INTO bank_accounts (bank, account_number, holder_name, branch, version, active, is_test) "
            "VALUES ($1,$2,$3,$4,$5,true,$6) RETURNING *", bank, account_number, holder_name, branch,
            new_version, is_test)
    await audit_service.record(conn, actor_type="cli", action="bank.config", actor_ref=actor,
                               entity_type="bank_accounts", entity_id=str(row["id"]),
                               after={"bank": bank, "version": new_version, "is_test": is_test})
    return dict(row)


async def generate_instruction(conn, order_id: int, *, actor: str) -> dict:
    """Snapshot active bank account + noi dung deterministic tu ma don. KHONG doi lich su khi account doi sau."""
    pay = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", order_id)
    if not pay:
        raise PaymentError(f"payment cho order {order_id} chua ton tai")
    if pay["method"] != "BANK_TRANSFER":
        raise PaymentError("instruction chi cho BANK_TRANSFER")
    acct = await conn.fetchrow("SELECT * FROM bank_accounts WHERE active")
    if not acct:
        # chua cau hinh -> bao ro, cho chon COD/lien he staff (Directive §4.3)
        raise PaymentError("chua cau hinh tai khoan nhan tien (chuyen khoan) — chon COD hoac lien he nhan vien")
    content = transfer_content(order_id)
    row = await conn.fetchrow(
        "INSERT INTO payment_instructions (order_id, payment_id, bank_account_id, account_version, "
        "bank_snapshot, account_number_snapshot, holder_snapshot, transfer_content, amount_vnd, is_test) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *",
        order_id, pay["id"], acct["id"], acct["version"], acct["bank"], acct["account_number"],
        acct["holder_name"], content, pay["amount_due_vnd"], acct["is_test"])
    await audit_service.record(conn, actor_type="cli", action="payment.instruction", actor_ref=actor,
                               entity_type="payment_instructions", entity_id=str(row["id"]),
                               after={"order_id": order_id, "account_version": acct["version"]})
    return dict(row)
