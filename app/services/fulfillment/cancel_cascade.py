"""CA Directive 387 §4.1 — cascade huy don sang M6/M7, chay TRONG transaction/savepoint cua lifecycle command huy.

Goi tu command/lifecycle._do_transition SAU apply_transition(cancel). Loi bat ky -> raise -> savepoint rollback toan bo
(khong de don huy ma shipment/payment/conversation dang do). KHONG goi hang van chuyen/ngan hang (khong external call).

Quy tac:
- Conversation M7 chua ket thuc -> 'cancelled' + journal (ly do + actor).
- staff_attention OPEN cua don -> resolved (note = ly do huy).
- Shipment chua ban giao hang (pending_prep | ready_to_ship) -> 'cancelled'. Da ban giao/dang giao/da giao/that bai/
  hoan (in_transit | delivered | delivery_failed | return_pending) -> CHAN huy thuong; chi nguoi co
  order.cancel.exception moi qua duoc, shipment GIU NGUYEN + mo staff_attention 'order_cancel_exception'.
- Payment CHUA co tien (status awaiting, amount_received 0, KHONG co payment_event bang chung) -> 'cancelled' +
  void payment_instructions (ban ghi append-only payment_instruction_voids). Co tien/bang chung (mot phan hoac du) -> KHONG tu huy/hoan: giu ledger + mo
  staff_attention 'refund_required' (so tien tham chieu).
Reminder/due-work dung tu nhien: conversation 'cancelled' khong con duoc run_due/run_routing chon; outbox M6/M7 cua
don da huy bi stale-check (outbox_worker) danh dau cancelled luc dispatch.
"""
from __future__ import annotations

from app.services.fulfillment import attention
from app.services.fulfillment import conversation as conv

CANCELLED_ORDER_STATUSES = ("cancelled", "cancelled_by_exception")
SHIPMENT_CANCELLABLE = ("pending_prep", "ready_to_ship")
SHIPMENT_HANDED_OFF = ("in_transit", "delivered", "delivery_failed", "return_pending")
EVIDENCE_KINDS = ("customer_reported", "cod_collected", "shop_confirmed_received", "reconciled", "correction",
                  "bank_auto_confirmed")
REASON_MIN, REASON_MAX = 5, 500


class CancelBlocked(Exception):
    """Huy thuong bi chan (vd shipment da ban giao) — lifecycle chuyen thanh reject 409/403."""

    def __init__(self, code: str, message: str, http_status: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def normalize_reason(reason) -> str:
    """Ly do bat buoc 5-500 ky tu sau trim (Directive 387 §1). Sai -> ValueError."""
    r = (reason or "").strip() if isinstance(reason, str) else ""
    if not (REASON_MIN <= len(r) <= REASON_MAX):
        raise ValueError(f"ly do huy phai {REASON_MIN}-{REASON_MAX} ky tu (sau trim)")
    return r


async def apply(conn, *, order_id: int, reason: str, actor: str, command_id: str, can_exception: bool) -> dict:
    """Tra tom tat cac effect (dua vao result/audit cua command). Raise CancelBlocked neu bi chan."""
    out: dict = {"conversation": None, "attention_resolved": [], "shipment": None, "payment": None,
                 "instructions_voided": 0, "attention_opened": []}
    note = f"order cancelled: {reason}"

    # ---- Shipment gate TRUOC (neu bi chan thi khong lam gi khac) ----
    sh = await conn.fetchrow("SELECT id, status FROM shipments WHERE order_id=$1 FOR UPDATE", order_id)
    handed_off = bool(sh and sh["status"] in SHIPMENT_HANDED_OFF)
    if handed_off and not can_exception:
        raise CancelBlocked("shipment_handed_off",
                            f"Shipment da o trang thai '{sh['status']}' — can quyen order.cancel.exception", 409)
    # ---- Van don GHN (CA Directive 393 §5): truoc dispatch -> cancelled_before_dispatch (khong HTTP); da dispatch/
    # tao/khong chac chan -> KHONG gia vo huy GHN: chan huy thuong (raise), exception -> giu provider state + attention.
    from app.services.fulfillment import ghn_shipment_create as _gsc
    ghn = await _gsc.on_order_cancel(conn, order_id, reason=reason, actor=actor, can_exception=can_exception)
    out["ghn_create"] = ghn
    ghn_dispatched = bool(ghn and ghn.get("kept"))

    # ---- Conversation M7 ----
    fc = await conv.get(conn, order_id, lock=True)
    if fc and fc["step"] not in (conv.COMPLETED, conv.CANCELLED):
        await conv._set_step(conn, fc, step=conv.CANCELLED)
        await conv._journal(conn, order_id, command_key=f"order_cancel:{command_id}", source="staff",
                            from_step=fc["step"], to_step=conv.CANCELLED,
                            detail={"reason": reason, "actor": actor, "command_id": str(command_id)}, reply_text=None)
        out["conversation"] = {"from": fc["step"], "to": conv.CANCELLED}

    # ---- staff_attention dang mo -> resolved ----
    for a in await conn.fetch("SELECT id FROM staff_attention WHERE order_id=$1 AND status='open' FOR UPDATE",
                              order_id):
        if await attention.resolve(conn, a["id"], resolved_by=actor, note=note):
            out["attention_resolved"].append(a["id"])

    # ---- Shipment ----
    if sh:
        if sh["status"] in SHIPMENT_CANCELLABLE and not ghn_dispatched:
            await conn.execute("UPDATE shipments SET status='cancelled', cancelled_at=now(), version=version+1, "
                               "updated_at=now() WHERE id=$1", sh["id"])
            out["shipment"] = {"from": sh["status"], "to": "cancelled"}
        elif handed_off or ghn_dispatched:
            aid = await attention.open_attention(
                conn, order_id, reason="order_cancel_exception",
                detail={"shipment_status": sh["status"], "reason": reason, "by": actor,
                        "ghn_create": ghn}, created_by=actor)
            out["shipment"] = {"from": sh["status"], "to": sh["status"], "kept": "handed_off_exception"}
            if aid:
                out["attention_opened"].append({"id": aid, "reason": "order_cancel_exception"})

    # ---- Payment ----
    p = await conn.fetchrow("SELECT id, status, method, amount_due_vnd, amount_received_vnd FROM payments "
                            "WHERE order_id=$1 FOR UPDATE", order_id)
    if p and p["status"] != "cancelled":
        evidence = await conn.fetchval(
            "SELECT count(*) FROM payment_events WHERE payment_id=$1 AND kind = ANY($2::text[])",
            p["id"], list(EVIDENCE_KINDS))
        received = p["amount_received_vnd"] or 0
        if p["status"] == "awaiting" and received == 0 and not evidence:
            await conn.execute("UPDATE payments SET status='cancelled', cancelled_at=now(), version=version+1, "
                               "updated_at=now() WHERE id=$1", p["id"])
            # instruction BAT BIEN (pi_no_mutate) -> void = dong append-only payment_instruction_voids
            n = await conn.execute(
                "INSERT INTO payment_instruction_voids (instruction_id, order_id, reason, command_id, voided_by) "
                "SELECT id, order_id, $2, $3, $4 FROM payment_instructions WHERE payment_id=$1 "
                "ON CONFLICT (instruction_id) DO NOTHING", p["id"], note[:600], str(command_id), actor)
            out["payment"] = {"from": p["status"], "to": "cancelled"}
            out["instructions_voided"] = int(n.split()[-1]) if n else 0
        else:
            aid = await attention.open_attention(
                conn, order_id, reason="refund_required",
                detail={"payment_status": p["status"], "method": p["method"], "amount_due_vnd": p["amount_due_vnd"],
                        "amount_received_vnd": received, "evidence_events": evidence, "reason": reason,
                        "by": actor}, created_by=actor)
            out["payment"] = {"from": p["status"], "to": p["status"], "kept": "money_or_evidence_present"}
            if aid:
                out["attention_opened"].append({"id": aid, "reason": "refund_required"})
    return out
