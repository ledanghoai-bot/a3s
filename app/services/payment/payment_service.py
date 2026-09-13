"""M6 payment service — amount_due / evidence / status (CA Directive 265 + Review 266).

Tach 3 nghia: amount_due_vnd (can thu) / payment_events (evidence append-only) / amount_received_vnd (TONG shop
thuc nhan, cumulative) + status.
Transitions:
- BANK_TRANSFER: awaiting -> reported (customer_reported) -> [shop_confirmed_received -> settle].
- COD: awaiting -> collected (cod_collected) -> [reconciled -> settle].
- settle: amount_received == due -> confirmed/reconciled ; != due (THIEU hoac THUA) -> 'discrepancy' (CHO staff).
266-03: command_key -> DB-atomic idempotency (replay khong ghi/cong lai) + reference chong ghi lai CUNG chung tu.
266-04: sync_amount_due chi khi CHUA settled; neu da settled ma due doi -> 'discrepancy' (obligation phai xac nhan lai).
266-05: excess CUNG chua auto-confirm; correction BAT BUOC reason + corrects_event_id, dieu chinh amount_received.
266-08: eta_start set 1 lan (COD confirm / transfer received).
"""
from __future__ import annotations

from app.services import audit_service

METHODS = ("COD", "BANK_TRANSFER")
_SETTLED = {"confirmed", "reconciled"}


class PaymentError(Exception):
    """Fail-closed. Khong leak secret."""


def transfer_content(order_id: int) -> str:
    return f"3SCF {order_id}"


def _settle_status(method: str) -> str:
    return "confirmed" if method == "BANK_TRANSFER" else "reconciled"


async def _order_total(conn, order_id: int) -> int:
    t = await conn.fetchval("SELECT total_vnd FROM orders WHERE id=$1", order_id)
    if t is None:
        raise PaymentError(f"order {order_id} khong ton tai")
    return int(t)


async def _quoted_fee(conn, order_id: int) -> int | None:
    row = await conn.fetchrow("SELECT delivery_fee_vnd, fee_status FROM shipments WHERE order_id=$1", order_id)
    return int(row["delivery_fee_vnd"]) if row and row["fee_status"] == "quoted" else None


async def _compute_due(conn, order_id: int) -> int | None:
    fee = await _quoted_fee(conn, order_id)
    return (await _order_total(conn, order_id) + fee) if fee is not None else None


async def ensure_payment(conn, order_id: int, *, method: str, actor: str) -> dict:
    """Get-or-create. CA 266-01: cho DOI method chi khi status='awaiting' (chua co evidence)."""
    if method not in METHODS:
        raise PaymentError("method phai COD|BANK_TRANSFER")
    row = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", order_id)
    if row:
        if row["method"] != method:
            if row["status"] != "awaiting":
                raise PaymentError(f"khong the doi phuong thuc khi da co evidence (status={row['status']})")
            row = await conn.fetchrow(
                "UPDATE payments SET method=$2, version=version+1, updated_at=now() WHERE id=$1 AND version=$3 "
                "RETURNING *", row["id"], method, row["version"])
            await audit_service.record(conn, actor_type="cli", action="payment.method", actor_ref=actor,
                                       entity_type="payments", entity_id=str(row["id"]), after={"method": method})
        return dict(row)
    due = await _compute_due(conn, order_id)
    row = await conn.fetchrow(
        "INSERT INTO payments (order_id, method, amount_due_vnd, status) VALUES ($1,$2,$3,'awaiting') "
        "ON CONFLICT (order_id) DO UPDATE SET updated_at=now() RETURNING *", order_id, method, due)
    await audit_service.record(conn, actor_type="cli", action="payment.create", actor_ref=actor,
                               entity_type="payments", entity_id=str(row["id"]),
                               after={"order_id": order_id, "method": method, "amount_due_vnd": due})
    if method == "COD":  # CA 266-08: COD -> ETA tinh tu order confirmed (payment ensure)
        from app.services.fulfillment import shipment_service as _sh
        await _sh.set_eta_start(conn, order_id, source="cod_confirmed")
    return dict(row)


async def sync_amount_due_if_unsettled(conn, order_id: int, *, actor: str) -> None:
    """CA 266-04: cap nhat amount_due khi fee doi. Neu payment CHUA settled -> update + recompute discrepancy.
    Neu DA settled ma due doi -> 'discrepancy' (obligation thay doi phai xac nhan lai)."""
    pay = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", order_id)
    if not pay:
        return
    due = await _compute_due(conn, order_id)
    if due == pay["amount_due_vnd"]:
        return
    if pay["status"] in _SETTLED:
        await conn.execute(
            "UPDATE payments SET amount_due_vnd=$2, status='discrepancy', version=version+1, updated_at=now() "
            "WHERE id=$1", pay["id"], due)
        await audit_service.record(conn, actor_type="cli", action="payment.reopen", actor_ref=actor,
                                   entity_type="payments", entity_id=str(pay["id"]),
                                   before={"status": pay["status"]}, after={"amount_due_vnd": due,
                                                                            "status": "discrepancy"})
        return
    new_status = _reconcile_status(pay["method"], pay["amount_received_vnd"], due, pay["status"])
    await conn.execute("UPDATE payments SET amount_due_vnd=$2, status=$3, version=version+1, updated_at=now() "
                       "WHERE id=$1", pay["id"], due, new_status)


def _reconcile_status(method: str, received: int, due: int | None, cur: str) -> str:
    """Trang thai theo received vs due (chi cho cac buoc da co evidence nhan tien)."""
    if received <= 0:
        return cur
    if due is None:
        return "discrepancy"
    if received == due:
        return _settle_status(method)
    return "discrepancy"       # thieu HOAC thua -> cho staff


_ADVANCE = {
    ("BANK_TRANSFER", "customer_reported"): ("reported", ("awaiting", "reported", "discrepancy")),
    ("BANK_TRANSFER", "shop_confirmed_received"): ("settle", ("reported", "discrepancy", "confirmed")),
    ("COD", "cod_collected"): ("collected", ("awaiting", "collected", "discrepancy")),
    ("COD", "reconciled"): ("settle", ("collected", "discrepancy", "reconciled")),
}


async def record_evidence(conn, order_id: int, *, kind: str, amount_vnd: int | None, recorded_by: str,
                          command_key: str, reference: str | None = None, note: str | None = None,
                          attachment_ref: str | None = None, corrects_event_id: int | None = None) -> dict:
    """CA 266-03: command_key idempotent. CA 266-05: settle theo cumulative received; excess/thieu -> discrepancy."""
    if not command_key:
        raise PaymentError("thieu command_key (idempotency)")
    pay = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", order_id)
    if not pay:
        raise PaymentError(f"payment cho order {order_id} chua ton tai")
    method, cur = pay["method"], pay["status"]

    # idempotency 1: command_key (DB-atomic)
    dup = await conn.fetchrow("SELECT * FROM payment_events WHERE payment_id=$1 AND command_key=$2",
                              pay["id"], command_key)
    if dup:
        return {"payment": dict(pay), "event_id": str(dup["id"]), "duplicate": True,
                "status": cur, "discrepancy": _disc(pay)}
    # idempotency 2 (business): cung reference cho cung kind -> khong cong lai chung tu
    if reference:
        rdup = await conn.fetchrow(
            "SELECT id FROM payment_events WHERE payment_id=$1 AND kind=$2 AND reference=$3",
            pay["id"], kind, reference)
        if rdup:
            return {"payment": dict(pay), "event_id": str(rdup["id"]), "duplicate": True,
                    "status": cur, "discrepancy": _disc(pay)}

    if kind == "correction":
        if not note:
            raise PaymentError("correction BAT BUOC ly do (note)")
        if not corrects_event_id:
            raise PaymentError("correction phai tro ve event goc (corrects_event_id)")
        orig = await conn.fetchval("SELECT id FROM payment_events WHERE id=$1 AND payment_id=$2",
                                   corrects_event_id, pay["id"])
        if not orig:
            raise PaymentError("corrects_event_id khong thuoc payment nay")
        delta = int(amount_vnd or 0)     # dieu chinh received (co the am)
        ev = await _insert(conn, pay["id"], kind, amount_vnd, recorded_by, reference, note, attachment_ref,
                           command_key, corrects_event_id)
        new_received = max(0, pay["amount_received_vnd"] + delta)
        new_status = _reconcile_status(method, new_received, pay["amount_due_vnd"], cur)
        pay = await _update_payment(conn, pay, received=new_received, status=new_status)
        await audit_service.record(conn, actor_type="cli", action="payment.correction", actor_ref=recorded_by,
                                   entity_type="payments", entity_id=str(pay["id"]),
                                   after={"delta": delta, "received": new_received, "status": new_status})
        return {"payment": dict(pay), "event_id": str(ev["id"]), "duplicate": False,
                "status": new_status, "discrepancy": _disc(pay)}

    spec = _ADVANCE.get((method, kind))
    if spec is None:
        raise PaymentError(f"kind '{kind}' khong hop le cho method {method}")
    to_status, valid_from = spec
    if cur not in valid_from:
        raise PaymentError(f"sai thu tu: {method} status={cur} khong the ghi '{kind}'")

    ev = await _insert(conn, pay["id"], kind, amount_vnd, recorded_by, reference, note, attachment_ref,
                       command_key, None)

    if to_status == "settle":
        # cong vao TONG shop thuc nhan roi so voi due (== -> settled ; != -> discrepancy)
        got = int(amount_vnd or 0)
        new_received = pay["amount_received_vnd"] + got
        due = pay["amount_due_vnd"]
        if due is None:
            raise PaymentError("amount_due chua chot (fee chua co) — khong the xac nhan da nhan")
        new_status = _reconcile_status(method, new_received, due, cur)
        pay = await _update_payment(conn, pay, received=new_received, status=new_status)
        if new_status == "confirmed":   # transfer received -> ETA start
            from app.services.fulfillment import shipment_service as _sh
            await _sh.set_eta_start(conn, order_id, source="transfer_received")
        from app.services.fulfillment import notify as _n
        await _n.notify_payment(conn, order_id, kind=kind, new_status=new_status, version=pay["version"])
    else:
        new_status = to_status
        if new_status != cur:
            pay = await _update_payment(conn, pay, received=pay["amount_received_vnd"], status=new_status)
        if kind == "customer_reported":
            from app.services.fulfillment import notify as _n
            await _n.notify_payment(conn, order_id, kind=kind, new_status=new_status, version=pay["version"])

    await audit_service.record(conn, actor_type="cli", action="payment.evidence", actor_ref=recorded_by,
                               entity_type="payments", entity_id=str(pay["id"]),
                               before={"status": cur}, after={"kind": kind, "status": pay["status"],
                                                              "received": pay["amount_received_vnd"]})
    return {"payment": dict(pay), "event_id": str(ev["id"]), "duplicate": False,
            "status": pay["status"], "discrepancy": _disc(pay)}


def _disc(pay) -> dict | None:
    due, got = pay["amount_due_vnd"], pay["amount_received_vnd"]
    if pay["status"] != "discrepancy" or due is None:
        return None
    return {"kind": "excess" if got > due else "partial", "due": due, "received": got, "delta": got - due}


async def _update_payment(conn, pay, *, received: int, status: str) -> dict:
    row = await conn.fetchrow(
        "UPDATE payments SET amount_received_vnd=$2, status=$3, version=version+1, updated_at=now() "
        "WHERE id=$1 AND version=$4 RETURNING *", pay["id"], received, status, pay["version"])
    if row is None:
        raise PaymentError("version conflict (concurrent) — huy")
    return dict(row)


async def _insert(conn, payment_id, kind, amount_vnd, recorded_by, reference, note, attachment_ref,
                  command_key, corrects_event_id):
    return await conn.fetchrow(
        "INSERT INTO payment_events (payment_id, kind, amount_vnd, recorded_by, reference, note, attachment_ref, "
        "command_key, corrects_event_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
        "ON CONFLICT (payment_id, command_key) DO NOTHING RETURNING *",
        payment_id, kind, amount_vnd, recorded_by, reference, note, attachment_ref, command_key, corrects_event_id)


# ---------------- Bank account config + instruction ----------------

async def set_bank_account(conn, *, bank: str, account_number: str, holder_name: str, actor: str,
                           branch: str | None = None, is_test: bool = False) -> dict:
    if not (bank and account_number and holder_name):
        raise PaymentError("thieu bank/account_number/holder_name")
    prev = await conn.fetchrow("SELECT * FROM bank_accounts WHERE active")
    new_version = (prev["version"] + 1) if prev else 1
    if prev:
        await conn.execute("UPDATE bank_accounts SET active=false, updated_at=now() WHERE id=$1", prev["id"])
    row = await conn.fetchrow(
        "INSERT INTO bank_accounts (bank, account_number, holder_name, branch, version, active, is_test) "
        "VALUES ($1,$2,$3,$4,$5,true,$6) RETURNING *", bank, account_number, holder_name, branch, new_version,
        is_test)
    await audit_service.record(conn, actor_type="cli", action="bank.config", actor_ref=actor,
                               entity_type="bank_accounts", entity_id=str(row["id"]),
                               after={"bank": bank, "version": new_version, "is_test": is_test})
    return dict(row)


async def generate_instruction(conn, order_id: int, *, actor: str) -> dict:
    pay = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", order_id)
    if not pay:
        raise PaymentError(f"payment cho order {order_id} chua ton tai")
    if pay["method"] != "BANK_TRANSFER":
        raise PaymentError("instruction chi cho BANK_TRANSFER")
    if pay["amount_due_vnd"] is None:   # CA 266-04: khong phat instruction tu amount chua chot
        raise PaymentError("chua chot tong tien (phi giao chua co) — khong phat huong dan chuyen khoan")
    acct = await conn.fetchrow("SELECT * FROM bank_accounts WHERE active")
    if not acct:
        raise PaymentError("chua cau hinh tai khoan nhan tien — chon COD hoac lien he nhan vien")
    row = await conn.fetchrow(
        "INSERT INTO payment_instructions (order_id, payment_id, bank_account_id, account_version, "
        "bank_snapshot, account_number_snapshot, holder_snapshot, transfer_content, amount_vnd, is_test) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *",
        order_id, pay["id"], acct["id"], acct["version"], acct["bank"], acct["account_number"],
        acct["holder_name"], transfer_content(order_id), pay["amount_due_vnd"], acct["is_test"])
    await audit_service.record(conn, actor_type="cli", action="payment.instruction", actor_ref=actor,
                               entity_type="payment_instructions", entity_id=str(row["id"]),
                               after={"order_id": order_id, "account_version": acct["version"]})
    return dict(row)
