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


async def ingest(conn, ev: IncomingTransfer, *, mode: str = "test") -> tuple[int, bool, bool]:
    """Tra (provider_event row id, created, conflict). created=False = duplicate cung (provider, event id).
    CA 274-01: cung event ID nhung KHAC payload_hash -> CONFLICT (fail-closed): ghi last_error='payload_hash_conflict'
    de staff thay, KHONG xu ly payload moi nhu duplicate lanh. Payload dau (first-come) van la ban ghi hop le."""
    rid = await conn.fetchval(
        "INSERT INTO provider_events (provider, provider_event_id, mode, payload_hash, raw) "
        "VALUES ($1,$2,$3,$4,$5::jsonb) ON CONFLICT (provider, provider_event_id) DO NOTHING RETURNING id",
        ev.provider, ev.provider_event_id, mode, ev.payload_hash, json.dumps(ev.raw_minimal, ensure_ascii=False))
    if rid is not None:
        return int(rid), True, False
    old = await conn.fetchrow(
        "SELECT id, payload_hash, processing_state FROM provider_events WHERE provider=$1 AND provider_event_id=$2",
        ev.provider, ev.provider_event_id)
    conflict = old["payload_hash"] != ev.payload_hash
    if conflict:
        # CA 275-02: cung event ID KHAC hash -> FAIL-CLOSED. Neu row chua xu ly ('received') -> chuyen 'error'
        # (terminal, worker KHONG chon) de KHONG tao financial effect tu payload nao cho toi khi staff xu ly.
        # (Da 'matched'/khac -> giu nguyen, chi ghi conflict + attention de staff thay.) Metadata KHONG secret.
        await conn.execute(
            "UPDATE provider_events SET processing_state = CASE WHEN processing_state='received' THEN 'error' "
            "ELSE processing_state END, match_reason='payload_hash_conflict', last_error='payload_hash_conflict', "
            "processed_at=now(), updated_at=now() WHERE id=$1", old["id"])
        codes = _sp.extract_codes(ev.raw_minimal.get("code"), ev.content)
        oid = codes[0] if len(codes) == 1 else None
        oexists = bool(oid and await conn.fetchval("SELECT 1 FROM orders WHERE id=$1", oid))
        await _att.open_attention(conn, oid if oexists else None, reason="unmatched_webhook",
                                  detail={"provider": ev.provider, "provider_event_id": ev.provider_event_id,
                                          "reason": "payload_hash_conflict", "code_order_id": oid},
                                  created_by="m7:webhook")
    return int(old["id"]), False, conflict


def _parse_accts(aa) -> set[str]:
    if isinstance(aa, str):
        return {a.strip() for a in aa.split(",") if a.strip()}
    if isinstance(aa, list):
        return {str(a).strip() for a in aa if str(a).strip()}
    return set()


async def _allowed_accounts(conn) -> tuple[set[str], bool]:
    """Gate account cho phep — PRECEDENCE tat dinh (CA 315-02), tra (accounts, enforce).
    - module OFF: baseline env; enforce chi khi env co cau hinh (giu hanh vi M6/M7).
    - module ON + active SePay DB config: DB allowlist la NGUON QUYET DINH (KHONG union env). enforce=True luon ->
      DB empty/invalid => fail-closed (reject moi account, khong roi ve env stale).
    - module ON + KHONG co active DB record: chi fallback env khi settings_integrations_env_fallback; nguoc lai
      fail-closed (enforce=True, rong).
    enforce=True + set rong => moi account bi tu choi (fail-closed)."""
    env = {a.strip() for a in (settings.sepay_allowed_accounts or "").split(",") if a.strip()}
    if not settings.settings_integrations_enabled:
        return env, bool(env)
    row = await conn.fetchrow(
        "SELECT config_public FROM integrations WHERE provider='sepay' AND mode='test' AND enabled "
        "AND archived_at IS NULL ORDER BY id DESC LIMIT 1")
    if row:
        cp = row["config_public"]
        cp = json.loads(cp) if isinstance(cp, str) else (cp or {})
        return _parse_accts(cp.get("allowed_accounts")), True   # DB authoritative + fail-closed
    if settings.settings_integrations_env_fallback:
        return env, bool(env)
    return set(), True   # module ON, no DB, no fallback -> fail-closed


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

    # CA 274-02/275-03: event gan DUNG 1 order code nhung khong khop instruction/payment -> shared escalation
    # payment_mismatch (chuyen conversation staff_attention + bao khach ly do; KHONG kem so tien/tai khoan).
    async def _discrepancy(reason: str, *, order_id, payment_id) -> str:
        await _finish(conn, row_id, state="discrepancy", reason=reason, order_id=order_id, payment_id=payment_id)
        from app.services.fulfillment import conversation as _conv
        res = await _conv.escalate(conn, order_id, reason="payment_mismatch", actor=actor,
                                   detail={"provider": provider, "provider_event_id": ev.provider_event_id,
                                           "reason": reason})
        if res is None:   # khong co conversation active -> global attention cho staff
            await _att.open_attention(conn, order_id, reason="payment_mismatch",
                                      detail={"provider_event_id": ev.provider_event_id, "reason": reason},
                                      created_by=actor)
        return "discrepancy"

    if ev.direction != "in":
        await _finish(conn, row_id, state="ignored", reason=f"direction_{ev.direction}")
        return "ignored"
    # CA 274-01: C0 Test Mode CHI xu ly row mode='test'; row live KHONG duoc C0 auto-confirm.
    if row["mode"] != "test":
        return await _unmatched("mode_not_test", state="ignored", order_exists=False)
    # CA 274-01: KHONG dung active bank. Config sepay_allowed_accounts CHI la gate phong ve khi duoc cau hinh;
    # rang buoc CHINH la snapshot cua instruction (account_number_snapshot) kiem o duoi.
    allowed, enforce = await _allowed_accounts(conn)
    if enforce and (not ev.account_number or ev.account_number not in allowed):
        return await _unmatched("account_not_allowed")
    codes = _sp.extract_codes(ev.raw_minimal.get("code"), ev.content)
    if not codes:
        return await _unmatched("code_missing")
    if len(codes) > 1:
        return await _unmatched("code_multiple")
    order_id = codes[0]
    pay = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1 FOR UPDATE", order_id)   # lock payment
    if not pay:
        exists = bool(await conn.fetchval("SELECT 1 FROM orders WHERE id=$1", order_id))
        return await _unmatched("order_or_payment_not_found", order_id=order_id, order_exists=exists)
    # CA Directive 387: tien ve cho don DA HUY (instruction da void) -> KHONG auto-confirm, KHONG mo lai hoi thoai;
    # giu ledger provider_event + attention 'refund_required' cho staff hoan tien (idempotent theo (order, reason)).
    if await conn.fetchval("SELECT status IN ('cancelled','cancelled_by_exception') FROM orders WHERE id=$1", order_id):
        return await _unmatched("order_cancelled", order_id=order_id, payment_id=pay["id"], att_reason="refund_required")
    if pay["method"] != "BANK_TRANSFER":
        # CA 275-03: event gan don COD (order-bound) -> shared escalation, khong de conversation ket o awaiting.
        return await _discrepancy("payment_not_bank_transfer", order_id=order_id, payment_id=pay["id"])
    # CA 274-01: bind vao instruction HIEN HANH cua conversation (fulfillment_conversations.instruction_id);
    # fallback instruction moi nhat cua payment. Exact-match theo SNAPSHOT cua chinh instruction do.
    cur_iid = await conn.fetchval("SELECT instruction_id FROM fulfillment_conversations WHERE order_id=$1", order_id)
    if cur_iid is not None:
        instr = await conn.fetchrow("SELECT * FROM payment_instructions WHERE id=$1", cur_iid)
    else:
        instr = await conn.fetchrow("SELECT * FROM payment_instructions WHERE payment_id=$1 ORDER BY id DESC LIMIT 1",
                                    pay["id"])
    if not instr:
        return await _discrepancy("no_current_instruction", order_id=order_id, payment_id=pay["id"])
    if await conn.fetchval("SELECT 1 FROM payment_instruction_voids WHERE instruction_id=$1", instr["id"]):
        # CA 387: instruction da void -> khong bao gio match
        return await _unmatched("instruction_voided", order_id=order_id, payment_id=pay["id"], att_reason="refund_required")
    # CA 274-01/275-03: mac dinh C0 chi auto-confirm instruction TEST. CA 331 NGOAI LE — S0 tester REAL-BANK:
    # cho instruction thoat (is_test=false) auto-confirm CHI KHI gate day du: connector test-mode ON + live OFF +
    # provider event mode=test + order thuoc EXACT tester scope PO (SERVER-SIDE resolved identity qua customer_id cua
    # order, KHONG tin webhook body — 331 §3.6). Nguoc lai -> escalate. is_test van giu trong data/snapshot/UI; KHONG
    # dung mo S1/live/public.
    if not instr["is_test"]:
        from app.services.fulfillment.m7_scope import m7_enabled_for
        order_cid = await conn.fetchval("SELECT customer_id FROM orders WHERE id=$1", order_id)
        tester_realbank_ok = (bool(settings.m7_sepay_test_connector)
                              and not bool(settings.sepay_live_enabled)
                              and row["mode"] == "test"
                              and m7_enabled_for(order_cid))
        if not tester_realbank_ok:
            return await _discrepancy("instruction_not_test", order_id=order_id, payment_id=pay["id"])
    if int(instr["order_id"]) != int(order_id):
        return await _discrepancy("instruction_order_mismatch", order_id=order_id, payment_id=pay["id"])
    # CA 322/323: match theo SNAPSHOT instruction (khong regex/prefix global). Content webhook PHAI chua transfer_content
    # snapshot (prefix + order) cua chinh instruction hien hanh -> foreign/wrong prefix fail-closed, khong cross-match
    # prefix cu (3SCF) vs moi (SEVQR). Case-insensitive (ngan hang thuong upper).
    _tc = str(instr["transfer_content"] or "").strip().upper()
    _hay = f"{ev.content or ''} {ev.raw_minimal.get('code') or ''}".upper()
    if not _tc or _tc not in _hay:
        return await _discrepancy("transfer_content_snapshot_mismatch", order_id=order_id, payment_id=pay["id"])
    if pay["status"] not in ("awaiting", "reported", "discrepancy"):
        return await _unmatched(f"payment_closed_{pay['status']}", order_id=order_id, payment_id=pay["id"])
    if ev.amount_vnd is None or ev.amount_vnd <= 0:
        return await _unmatched("amount_invalid", order_id=order_id, payment_id=pay["id"])
    # CA 274-01: EXACT match theo snapshot instruction da gui (account + amount), KHONG theo active/current due.
    # CA 275-03: event gan dung 1 order code nhung account/amount khong khop instruction -> shared escalation
    # payment_mismatch (chuyen conversation + bao khach ly do). Chi no-code/multi-code/order-not-found moi giu
    # global unmatched (khong lam gian doan conversation).
    if str(instr["account_number_snapshot"]) != str(ev.account_number):
        return await _discrepancy("account_snapshot_mismatch", order_id=order_id, payment_id=pay["id"])
    if int(instr["amount_vnd"]) != int(ev.amount_vnd):
        kind = "excess" if int(ev.amount_vnd) > int(instr["amount_vnd"]) else "partial"
        return await _discrepancy(f"amount_snapshot_mismatch_{kind}", order_id=order_id, payment_id=pay["id"])
    # PASS: exact instruction snapshot (account+amount) + eligible state -> deterministic payment service
    try:
        res = await _pay.record_provider_confirmation(conn, order_id, amount_vnd=int(ev.amount_vnd), provider=provider,
                                                      provider_event_id=ev.provider_event_id, reference=ev.reference)
    except _pay.PaymentError as e:
        await _finish(conn, row_id, state="error", reason=f"payment_error:{str(e)[:120]}", order_id=order_id,
                      payment_id=pay["id"])
        from app.services.fulfillment import conversation as _conv
        await _conv.escalate(conn, order_id, reason="payment_mismatch", actor=actor,
                             detail={"provider_event_id": ev.provider_event_id, "error": str(e)[:160]})
        return "error"
    await _finish(conn, row_id, state="matched", reason="exact_match" + (":replay" if res.get("duplicate") else ""),
                  order_id=order_id, payment_id=pay["id"], payment_event_id=int(res["event_id"]))
    return "matched"


async def run_once(*, limit: int = BATCH) -> dict:
    from app.db_pool import acquire, release
    stats = {"claimed": 0, "matched": 0, "unmatched": 0, "discrepancy": 0, "ignored": 0, "error": 0}
    # CA 315-03: connector OFF -> worker INERT (khong claim/process). SePay la provider duy nhat feed provider_events;
    # kill-switch m7_sepay_test_connector tat => khong xu ly bat ky event ton dong nao (fail-closed dormant).
    if not settings.m7_sepay_test_connector:
        return {**stats, "skipped": "connector_off"}
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
