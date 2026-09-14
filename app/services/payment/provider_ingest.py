"""M7-C0 provider event ingest + matching (CA Directive 272 §3.5). SePay TEST MODE la connector dau tien.

ingest(): ghi BEN VUNG raw envelope (unique provider+event id; duplicate -> tra row cu, khong effect) — webhook tra
nhanh, xu ly domain o worker (run_once) retry-safe.
process(): matching TAT DINH dong thoi: direction IN + account duoc phep + DUNG 1 ma `3SCF <id>` + payment/instruction
ton tai + state eligible (awaiting/reported/discrepancy, method BANK_TRANSFER) + amount == amount_due (exact).
  PASS -> payment_service.record_provider_confirmation (kind bank_auto_confirmed, command_key = provider event) ->
          confirmed + notify 1 lan (payment service) + hoi thoai completed.
  Thieu/thua tien, code rong/sai/trung, account sai, payment da dong/khong phai CK, khong tim thay don -> unmatched/
  discrepancy + staff_attention; KHONG auto-confirm, KHONG refund. Lech tien co payment -> ghi evidence? KHONG:
  chi staff doi chieu (272 §3.5), event giu o 'discrepancy' de dashboard hien.
AI KHONG tham gia; module nay khong sinh text cho khach.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.config import settings
from app.services.fulfillment import attention as _att
from app.services.payment import payment_service as _pay
from app.services.providers import sepay as _sp
from app.services.providers.base import IncomingTransfer
from app.services.safe_log import safe_exc

BATCH = 25


async def ingest(conn, ev: IncomingTransfer, *, mode: str = "test") -> tuple[int, bool]:
    """Tra (provider_event row id, created). created=False = duplicate (cung provider+event id)."""
    rid = await conn.fetchval(
        "INSERT INTO provider_events (provider, provider_event_id, mode, payload_hash, raw) "
        "VALUES ($1,$2,$3,$4,$5::jsonb) ON CONFLICT (provider, provider_event_id) DO NOTHING RETURNING id",
        ev.provider, ev.provider_event_id, mode, ev.payload_hash, json.dumps(ev.raw_minimal, ensure_ascii=False))
    if rid is not None:
        return int(rid), True
    old = await conn.fetchrow("SELECT id, payload_hash FROM provider_events WHERE provider=$1 AND provider_event_id=$2",
                              ev.provider, ev.provider_event_id)
    return int(old["id"]), False


def _allowed_accounts(active_account: str | None) -> set[str]:
    out = {a.strip() for a in (settings.sepay_allowed_accounts or "").split(",") if a.strip()}
    if active_account:
        out.add(active_account.strip())
    return out


async def _finish(conn, row_id: int, *, state: str, reason: str, order_id=None, payment_id=None,
                  payment_event_id=None) -> None:
    await conn.execute(
        "UPDATE provider_events SET processing_state=$2, match_reason=$3, order_id=$4, payment_id=$5, "
        "payment_event_id=$6, processed_at=now(), attempts=attempts+1, updated_at=now() WHERE id=$1",
        row_id, state, reason, order_id, payment_id, payment_event_id)


def _from_row(row) -> IncomingTransfer:
    raw = row["raw"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    amt = raw.get("transferAmount")
    amount = int(amt) if isinstance(amt, int) and not isinstance(amt, bool) else (
        int(amt) if isinstance(amt, str) and amt.isdigit() else None)
    return IncomingTransfer(
        provider=row["provider"], provider_event_id=row["provider_event_id"],
        direction=("in" if str(raw.get("transferType") or "").lower() == "in" else "out"
                   if str(raw.get("transferType") or "").lower() == "out" else "unknown"),
        account_number=(str(raw.get("accountNumber")).strip() if raw.get("accountNumber") is not None else None),
        amount_vnd=amount, content=str(raw.get("content") or ""), reference=raw.get("referenceCode"),
        occurred_at=raw.get("transactionDate"), gateway=raw.get("gateway"), payload_hash=row["payload_hash"],
        raw_minimal=raw)


async def process(conn, row_id: int, *, actor: str = "m7:provider") -> str:
    """Xu ly 1 event (trong tx). Tra processing_state ket qua. Idempotent theo state (chi 'received' duoc xu ly)."""
    row = await conn.fetchrow("SELECT * FROM provider_events WHERE id=$1 FOR UPDATE", row_id)
    if not row or row["processing_state"] != "received":
        return row["processing_state"] if row else "missing"
    ev = _from_row(row)
    provider = ev.provider

    async def _unmatched(reason: str, *, state: str = "unmatched", order_id=None, payment_id=None,
                         att_reason: str = "unmatched_webhook", order_exists: bool = True) -> str:
        await _finish(conn, row_id, state=state, reason=reason, order_id=order_id, payment_id=payment_id)
        # staff_attention.order_id la FK -> don khong ton tai: attention khong gan don (order_id NULL, ma don trong detail)
        await _att.open_attention(conn, order_id if order_exists else None, reason=att_reason,
                                  detail={"provider": provider, "provider_event_id": ev.provider_event_id,
                                          "reason": reason, "amount_vnd": ev.amount_vnd,
                                          "reference": ev.reference, "code_order_id": order_id}, created_by=actor)
        return state

    if ev.direction != "in":
        await _finish(conn, row_id, state="ignored", reason=f"direction_{ev.direction}")
        return "ignored"
    active_acct = await conn.fetchval("SELECT account_number FROM bank_accounts WHERE active")
    allowed = _allowed_accounts(active_acct)
    if not ev.account_number or ev.account_number not in allowed:
        return await _unmatched("account_not_allowed")
    codes = _sp.extract_codes(ev.raw_minimal.get("code"), ev.content)
    if not codes:
        return await _unmatched("code_missing")
    if len(codes) > 1:
        return await _unmatched("code_multiple")
    order_id = codes[0]
    pay = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", order_id)
    if not pay:
        exists = bool(await conn.fetchval("SELECT 1 FROM orders WHERE id=$1", order_id))
        return await _unmatched("order_or_payment_not_found", order_id=order_id, order_exists=exists)
    if pay["method"] != "BANK_TRANSFER":
        return await _unmatched("payment_not_bank_transfer", order_id=order_id, payment_id=pay["id"])
    instr = await conn.fetchval("SELECT count(*) FROM payment_instructions WHERE payment_id=$1", pay["id"])
    if not instr:
        return await _unmatched("no_instruction", order_id=order_id, payment_id=pay["id"])
    if pay["status"] not in ("awaiting", "reported", "discrepancy"):
        return await _unmatched(f"payment_closed_{pay['status']}", order_id=order_id, payment_id=pay["id"])
    if ev.amount_vnd is None or ev.amount_vnd <= 0:
        return await _unmatched("amount_invalid", order_id=order_id, payment_id=pay["id"])
    due = pay["amount_due_vnd"]
    if due is None:
        return await _unmatched("amount_due_unknown", order_id=order_id, payment_id=pay["id"], state="discrepancy",
                                att_reason="payment_mismatch")
    if int(ev.amount_vnd) != int(due):
        kind = "excess" if int(ev.amount_vnd) > int(due) else "partial"
        return await _unmatched(f"amount_mismatch_{kind}", order_id=order_id, payment_id=pay["id"],
                                state="discrepancy", att_reason="payment_mismatch")
    # PASS: exact code + exact amount + eligible state -> deterministic payment service (command_key = provider event)
    try:
        res = await _pay.record_provider_confirmation(conn, order_id, amount_vnd=int(ev.amount_vnd), provider=provider,
                                                      provider_event_id=ev.provider_event_id, reference=ev.reference)
    except _pay.PaymentError as e:
        await _finish(conn, row_id, state="error", reason=f"payment_error:{str(e)[:120]}", order_id=order_id,
                      payment_id=pay["id"])
        await _att.open_attention(conn, order_id, reason="payment_mismatch",
                                  detail={"provider_event_id": ev.provider_event_id, "error": str(e)[:160]},
                                  created_by=actor)
        return "error"
    await _finish(conn, row_id, state="matched", reason="exact_match" + (":replay" if res.get("duplicate") else ""),
                  order_id=order_id, payment_id=pay["id"], payment_event_id=int(res["event_id"]))
    return "matched"


async def run_once(*, limit: int = BATCH) -> dict:
    from app.db_pool import acquire, release
    stats = {"claimed": 0, "matched": 0, "unmatched": 0, "discrepancy": 0, "ignored": 0, "error": 0}
    conn = await acquire()
    try:
        ids = [r["id"] for r in await conn.fetch(
            "SELECT id FROM provider_events WHERE processing_state='received' ORDER BY received_at LIMIT $1", limit)]
        for rid in ids:
            stats["claimed"] += 1
            try:
                async with conn.transaction():
                    st = await process(conn, rid)
                stats[st] = stats.get(st, 0) + 1
            except Exception as e:  # noqa: BLE001 — giu 'received' de retry vong sau; ghi last_error
                stats["error"] += 1
                try:
                    await conn.execute("UPDATE provider_events SET attempts=attempts+1, last_error=$2, updated_at=now() "
                                       "WHERE id=$1", rid, safe_exc(e)[:300])
                except Exception:  # noqa: BLE001
                    pass
    finally:
        await release(conn)
    return stats


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
