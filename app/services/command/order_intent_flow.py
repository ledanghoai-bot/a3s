"""Layer B — orchestrator-side order-intent CONTROL PLANE (CA Directive 223 + Amendment 224 + Review 225).

Intent server-owned la CONTROL PLANE THAT tu order-proposal DAU TIEN (225-01), KHONG phai lop khai bao
song song. Moi luot create_order: get-or-create MOT open intent cho (customer, conversation) roi DRIVE state
theo ket qua verify:
  - dia chi verified (may_bind)         -> ADDRESS_CHECK -> READY_TO_COMMIT  -> action 'ready'  (caller commit)
  - dia chi ambiguous/chua verified     -> ADDRESS_CHECK -> NEEDS_CLARIFICATION -> action 'clarify'
  - da COMMITTED + stale-confirm         -> action 'duplicate' (tra receipt cu, ZERO mutation)
  - loi thiet lap intent (enrolled route)-> action 'error' (FAIL-CLOSED, caller KHONG commit)

Correction = cung open intent duoc cap nhat (re-enter ADDRESS_CHECK, tang version) — KHONG tao intent song
song (unique index oi_one_open_per_conversation). Terminal transitions (cancel/escalate/expire) qua
`terminalize`. DB-AUTHORITATIVE (225-04): open + committed lookup tu DB, KHONG phu thuoc Redis (Redis flush/
restart/TTL khong doi order semantics). Tren enrolled order-intent route, loi -> FAIL-CLOSED zero mutation.
"""
from __future__ import annotations

import hashlib

from app.db_pool import acquire, release
from app.services.command import order_intent_service as svc
from app.services.safe_log import safe_exc

_FIELDS = ("sku", "quantity", "customer_name", "phone", "address")


def _mask_phone(phone) -> str:
    """Mask SDT cho admin-notify: giu 3 so cuoi (CA 251 §3.D: PII bounded, khong lo so day du)."""
    s = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return ("***" + s[-3:]) if len(s) >= 3 else (s or "***")


def _summary_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


async def _validate_ready(conn, row: dict) -> list[str]:
    """CA 234-02.4: revalidate draft (dang + SKU TON TAI) — dung o ca propose (truoc READY) lan
    try_server_commit (ngay truoc commit). Tra danh sach field xau (rong = du dieu kien)."""
    bad = svc.draft_invalid_fields(row)
    if svc.draft_complete(row):
        prod_ok = await conn.fetchval("SELECT 1 FROM products WHERE sku=$1", row["draft_sku"])
        if not prod_ok and "sku" not in bad:
            bad.append("sku")
    return bad


def _norm_addr(s) -> str:
    """CA 233-04: normalize dia chi free-text de PHAT HIEN THAY DOI theo fingerprint chuan hoa (khong phai
    bool(address) — dia chi lap lai giong het KHONG tinh la doi). Bo dau/hoa/space NHAT QUAN 2 phia."""
    import unicodedata
    s = unicodedata.normalize("NFD", (s if isinstance(s, str) else "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


async def _render_confirmation_summary(conn, draft: dict) -> str:
    """CA 233-02: server RENDER tom tat xac nhan tu DRAFT (khong de model viet lai). Customer-safe: ten SP,
    so luong, don gia, tong, nguoi nhan, SDT, dia chi giao. Dung lam reply THAT gui khach."""
    sku = draft.get("draft_sku")
    qty = draft.get("draft_quantity") or 0
    prod = await conn.fetchrow("SELECT name, price_vnd FROM products WHERE sku=$1", sku)
    pname = prod["name"] if prod else sku
    unit = prod["price_vnd"] if prod else 0
    total = unit * qty
    return (
        "Dạ em xác nhận lại đơn của anh/chị:\n"
        f"- Sản phẩm: {pname} — {qty} x {unit:,}đ = {total:,}đ\n"
        f"- Người nhận: {draft.get('draft_customer_name')}\n"
        f"- SĐT: {draft.get('draft_phone')}\n"
        f"- Địa chỉ giao: {draft.get('draft_address')}\n"
        "Anh/chị nhắn \"xác nhận\" để em chốt đơn giúp mình nhé ạ."
    ).replace(",", ".")


async def _to_address_check(conn, intent: dict, *, order_fp, addr_fp, resolution_id) -> dict | None:
    """Dua open intent ve ADDRESS_CHECK (tu COLLECTING/NEEDS_CLARIFICATION/READY_TO_COMMIT = correction) +
    cap nhat fingerprint/resolution. Tra row moi hoac None neu version lech."""
    st = intent["state"]
    if st == "ADDRESS_CHECK":
        # da o ADDRESS_CHECK (hiem giua luot) — chi cap nhat fingerprint qua 1 no-op transition khong hop le;
        # thay vao do ghi truc tiep fingerprint bang transition READY? Don gian: coi nhu da o dung state.
        return intent
    return await svc.transition(conn, intent["id"], expected_version=intent["state_version"],
                                to_state="ADDRESS_CHECK", order_fingerprint=order_fp,
                                verified_address_fingerprint=addr_fp, verified_resolution_id=resolution_id)


async def drive(*, customer_id: int | None, conversation_id, channel: str, order_fp: str,
                addr_fp: str | None = None, verified_resolution_id: str | None = None,
                verified: bool, explicit_new_order: bool = False) -> dict:
    """CA 225-01 control-plane driver. Tra {"action": ..., "order_intent_id": ...[, "committed_order_id"]}.
    action in {ready, clarify, duplicate, error, skip}. 'skip' = khong the tao intent (customer_id None) ->
    caller giu legacy (KHONG enrolled). Loi tren enrolled route -> 'error' (fail-closed)."""
    if customer_id is None:
        return {"action": "skip"}  # khach chua co row (pilot/tester luon co) -> khong enrolled
    conn = None
    try:
        conn = await acquire()
        async with conn.transaction():
            open_row = await svc.find_open_intent(
                conn, customer_id=customer_id, conversation_id=conversation_id, for_update=True)
            # Lazy-expiry (CA 225-01): open intent qua TTL -> terminalize EXPIRED deterministic, coi nhu
            # khong con open (request sau tao intent MOI — case 13).
            if open_row is not None and open_row.get("is_expired"):
                await svc.transition(conn, open_row["id"], expected_version=open_row["state_version"],
                                     to_state="EXPIRED", terminal_reason="ttl")
                open_row = None
            if open_row is None:
                # Khong con open intent. Stale-confirm (DB-authoritative) neu co COMMITTED cung fingerprint
                # va KHONG phai don moi tuong minh (225-04/§7.4). Nguoc lai -> intent MOI (225-05 case 15).
                if not explicit_new_order:
                    committed = await svc.find_recent_committed(
                        conn, customer_id=customer_id, conversation_id=conversation_id,
                        order_fingerprint=order_fp)
                    if committed is not None:
                        return {"action": "duplicate", "order_intent_id": str(committed["id"]),
                                "committed_order_id": committed["committed_order_id"]}
                new = await svc.create_intent(conn, customer_id=customer_id,
                                              conversation_id=conversation_id, channel=channel)
                open_row = await svc.get_intent(conn, new["id"], for_update=True)
            # Dua ve ADDRESS_CHECK + cap nhat fingerprint (correction cung intent), roi phan nhanh verified.
            ac = await _to_address_check(conn, open_row, order_fp=order_fp, addr_fp=addr_fp,
                                         resolution_id=verified_resolution_id)
            if ac is None:
                return {"action": "error"}  # version lech giua luot -> fail-closed
            iid = str(ac["id"])
            if verified:
                r = await svc.transition(conn, iid, expected_version=ac["state_version"],
                                         to_state="READY_TO_COMMIT")
                if r is None:
                    return {"action": "error"}
                return {"action": "ready", "order_intent_id": iid}
            r = await svc.transition(conn, iid, expected_version=ac["state_version"],
                                     to_state="NEEDS_CLARIFICATION")
            if r is None:
                return {"action": "error"}
            return {"action": "clarify", "order_intent_id": iid}
    except Exception as e:  # noqa: BLE001 — enrolled route: caller fail-closed tren 'error'
        print(f"[order_intent_flow] drive error (fail-closed): {safe_exc(e)}")
        return {"action": "error"}
    finally:
        if conn is not None:
            await release(conn)


async def _no_mutation_action(conn, row: dict) -> dict:
    """CA 234-02.1: de xuat/su kien TRUNG (khong delta) -> KHONG bump version / KHONG rerun resolution /
    KHONG regen summary. Chi DERIVE action tu state hien tai + tra summary da persist (neu READY)."""
    iid = row["id"]
    st = row["state"]
    if not svc.draft_complete(row):
        return {"action": "need_more", "order_intent_id": str(iid), "noop": True,
                "missing": [f for f in _FIELDS if row.get(f"draft_{f}") in (None, "")]}
    bad = await _validate_ready(conn, row)
    if bad:
        return {"action": "need_more", "order_intent_id": str(iid), "missing": bad, "invalid": True,
                "noop": True}
    if st == "READY_TO_COMMIT" and row.get("summary_presented_at") is not None:
        summary = await _render_confirmation_summary(conn, row)
        return {"action": "ready", "order_intent_id": str(iid), "summary": summary,
                "summary_persisted": True, "noop": True}
    return {"action": "clarify", "order_intent_id": str(iid), "noop": True}


async def propose_draft(*, customer_id: int | None, conversation_id, channel: str, proposed: dict,
                        verified: bool, addr_fp: str | None, verified_resolution_id: str | None,
                        address_changed: bool, explicit_new_order: bool = False,
                        clear_fields: list[str] | None = None) -> dict:
    """CA 232/233/234: PROPOSAL server-owned. Accumulate field vao durable draft + advance; KHONG commit.
    proposed = {sku,quantity,customer_name,phone,address} (None = KHONG de xuat/omit). clear_fields = field
    khach TUONG MINH yeu cau xoa (explicit-clear, 234-02.2). Tra {action, order_intent_id}:
      need_more/clarify/ready/already_committed/skip/error. 'noop' = luot nay khong doi gi (234-02.1)."""
    if customer_id is None:
        return {"action": "skip"}
    from app.services.command import order_intent as _oi
    clear_fields = [c for c in (clear_fields or []) if c in _FIELDS]
    conn = None
    try:
        conn = await acquire()
        async with conn.transaction():
            row = await svc.find_open_intent(conn, customer_id=customer_id,
                                             conversation_id=conversation_id, for_update=True)
            if row is not None and row.get("is_expired"):
                await svc.transition(conn, row["id"], expected_version=row["state_version"],
                                     to_state="EXPIRED", terminal_reason="ttl")
                row = None
            _existing = row is not None
            if row is None:
                # CA 234-02.5: sau COMMITTED chi tao intent MOI khi TUONG MINH reorder. Bat ke de xuat day
                # du hay PARTIAL/stale: neu hoi thoai DA co committed intent + KHONG explicit reorder -> tra
                # outcome cu (ZERO mutation, khong tao draft). Chi explicit reorder moi mo draft moi.
                if not explicit_new_order and await svc.has_committed_intent(
                        conn, customer_id=customer_id, conversation_id=conversation_id):
                    prior = None
                    if all(proposed.get(f) not in (None, "") for f in ("sku", "quantity", "customer_name", "phone")):
                        prior = await svc.find_recent_committed(
                            conn, customer_id=customer_id, conversation_id=conversation_id,
                            order_fingerprint=_oi.order_fingerprint(
                                sku=proposed["sku"], quantity=proposed["quantity"],
                                customer_name=proposed["customer_name"], phone=proposed["phone"],
                                address_fp=addr_fp))
                    return {"action": "already_committed", "noop": True,
                            "order_intent_id": str(prior["id"]) if prior else None,
                            "order_id": prior["committed_order_id"] if prior else None}
                new = await svc.create_intent(conn, customer_id=customer_id,
                                              conversation_id=conversation_id, channel=channel)
                row = await svc.get_intent(conn, new["id"], for_update=True)
            iid = row["id"]
            ver = row["state_version"]
            # CA 233-04: dia chi DOI theo fingerprint chuan hoa (khong phai bool(address)).
            _new_addr = proposed.get("address")
            _addr_changed = ("address" in clear_fields) or (
                bool(_new_addr) and _norm_addr(_new_addr) != _norm_addr(row.get("draft_address")))
            # CA 234-02.1: EXISTING intent + KHONG co delta (khong field moi khac, khong clear, khong doi
            # dia chi) -> NO-OP (khong bump version/rerun/regen). Idempotent redelivery/identical proposal.
            if _existing and not clear_fields and not _addr_changed and all(
                    proposed.get(f) is None or proposed.get(f) == row.get(f"draft_{f}") for f in _FIELDS):
                return await _no_mutation_action(conn, row)
            if _addr_changed:
                r = await svc.clear_address_binding(conn, iid, expected_version=ver)
                if r is not None:
                    ver = r["state_version"]
            else:
                # dia chi KHONG doi -> GIU verified binding cu (correction field khac khong re-verify tu dau).
                if not verified and row.get("verified_resolution_id") and row.get("verified_address_fingerprint"):
                    verified = True
                    addr_fp = addr_fp or row.get("verified_address_fingerprint")
                    verified_resolution_id = verified_resolution_id or row.get("verified_resolution_id")
            # Accumulate: field co gia tri -> set; field trong clear_fields (va khong duoc set) -> XOA (None).
            _da = {k: proposed[k] for k in _FIELDS if proposed.get(k) is not None}
            for cf in clear_fields:
                _da.setdefault(cf, None)
            d = await svc.update_draft(conn, iid, expected_version=ver, **_da) if _da else row
            if d is None:
                return {"action": "error"}
            ver = d["state_version"]
            # CA 234-02.3: thieu/sai field NGOAI COLLECTING -> REGRESSION ve COLLECTING (transition da cho
            # phep) — khong ket o READY voi draft khong du. draft_complete + validate (dang + SKU ton tai).
            bad = svc.draft_invalid_fields(d) if not svc.draft_complete(d) else await _validate_ready(conn, d)
            if bad:
                if d["state"] != "COLLECTING" and _oi.can_transition(d["state"], "COLLECTING"):
                    await svc.transition(conn, iid, expected_version=ver, to_state="COLLECTING")
                return {"action": "need_more", "order_intent_id": str(iid), "missing": bad,
                        "invalid": not svc.draft_complete(d) and any(
                            d.get(f"draft_{f}") not in (None, "") for f in bad)}
            # Du field + hop le -> fingerprint + ADDRESS_CHECK -> verified branch.
            ofp = _oi.order_fingerprint(sku=d["draft_sku"], quantity=d["draft_quantity"],
                                        customer_name=d["draft_customer_name"], phone=d["draft_phone"],
                                        address_fp=addr_fp)
            ac = await _to_address_check(conn, {**d, "state": d["state"], "state_version": ver},
                                         order_fp=ofp, addr_fp=addr_fp, resolution_id=verified_resolution_id)
            if ac is None:
                return {"action": "error"}
            ver = ac["state_version"]
            if not verified:
                await svc.transition(conn, iid, expected_version=ver, to_state="NEEDS_CLARIFICATION")
                return {"action": "clarify", "order_intent_id": str(iid)}
            r = await svc.transition(conn, iid, expected_version=ver, to_state="READY_TO_COMMIT")
            if r is None:
                return {"action": "error"}
            # CA 233-02 + 234-03: RENDER summary server-side, PERSIST server-response (messages, dedupe theo
            # intent+version) VA arm pending-confirm (present_summary + content_hash) ATOMIC trong 1 tx. Loi
            # -> raise -> rollback -> KHONG de armed pending-confirm ma khong co persisted response.
            summary = await _render_confirmation_summary(conn, d)
            chash = _summary_hash(summary)
            await svc.log_message_tx(conn, conversation_id, "bot", summary,
                                     dedupe_key=f"order_summary:{iid}:{r['state_version']}")
            armed = await svc.present_summary(conn, iid, expected_version=r["state_version"],
                                              order_fingerprint=ofp, content_hash=chash)
            if armed is None:
                raise RuntimeError("present_summary version race — rollback arm+persist")
            return {"action": "ready", "order_intent_id": str(iid), "summary": summary,
                    "summary_persisted": True}
    except Exception as e:  # noqa: BLE001 — enrolled route fail-closed
        print(f"[order_intent_flow] propose_draft error (fail-closed): {safe_exc(e)}")
        return {"action": "error"}
    finally:
        if conn is not None:
            await release(conn)


async def try_server_commit(*, customer_id: int | None, conversation_id, channel: str, actor_id: str,
                            provider_message_id: str | None) -> dict | None:
    """CA Directive 232 §6: SERVER tu chot READY draft khi khach xac nhan TUONG MINH — KHONG doi model goi
    create_order. Caller (orchestrator) da xac dinh tin nhan la high-precision confirmation TRUOC khi goi.

    Chi commit khi DONG THOI: intent open = READY_TO_COMMIT + draft du field + summary da present khop DUNG
    state_version + order_fingerprint hien tai (correction sau summary -> version/fingerprint doi -> stale ->
    KHONG commit). Xay envelope tu DRAFT + goi order_gateway.create_order_command (command/intent tx = only
    write path; guard _run_winner + idempotency intent -> exactly-once ke ca concurrent/redelivered).
    Tra dict ket qua (order_id/receipt/duplicate) neu commit; None neu khong du dieu kien (caller di tiep LLM)."""
    if customer_id is None:
        return None
    conn = None
    try:
        conn = await acquire()
        row = await svc.find_open_intent(conn, customer_id=customer_id, conversation_id=conversation_id)
    except Exception as e:  # noqa: BLE001
        print(f"[order_intent_flow] try_server_commit read skipped: {safe_exc(e)}")
        return None
    finally:
        if conn is not None:
            await release(conn)
    if row is None or row["state"] != "READY_TO_COMMIT":
        return None
    if not svc.draft_complete(row):
        return None
    # §6: summary PHAI vua present cho DUNG version/fingerprint hien tai (chong stale-summary sau correction).
    if row.get("summary_presented_at") is None:
        return None
    if row.get("summary_version") != row["state_version"] or \
            row.get("summary_fingerprint") != row.get("order_fingerprint"):
        return None
    # CA 234-02.4: REVALIDATE draft (dang + SKU TON TAI) NGAY TRUOC commit (early-out re; binding/expiry
    # AUTHORITATIVE do _run_winner kiem trong command tx da lock FOR UPDATE — CA 235-01). Sai -> KHONG commit.
    _conn2 = None
    try:
        _conn2 = await acquire()
        if await _validate_ready(_conn2, row):
            return None
    finally:
        if _conn2 is not None:
            await release(_conn2)
    from app.services.command import order_gateway as _ogw
    if not _ogw.can_route(channel):
        return None
    # Commit tu draft server-owned (khong lay tu model/LLM). _run_winner guard owner/channel/conv/fingerprint
    # + mark_committed atomic. Concurrent/redelivered -> 1 order + same receipt.
    return await _ogw.create_order_command(
        channel=channel, actor_type="customer", actor_id=actor_id, idempotency_key=None,
        provider_message_id=provider_message_id, psid=actor_id, conversation_id=conversation_id,
        customer_name=row["draft_customer_name"], phone=row["draft_phone"], address=row["draft_address"],
        sku=row["draft_sku"], quantity=row["draft_quantity"],
        verified_resolution_id=(str(row["verified_resolution_id"]) if row.get("verified_resolution_id")
                                else None),
        verified_address_fingerprint=row.get("verified_address_fingerprint"),
        order_intent_id=str(row["id"]))


async def terminalize(*, customer_id: int | None, conversation_id, to_state: str,
                      reason: str | None = None) -> bool:
    """Terminal transition cho open intent hien tai (CA 225-01: cancel/escalate/expire transition intent
    THAT). to_state in {CANCELLED, ESCALATED, EXPIRED}. Tra True neu da transition. Best-effort (khong vo
    reply). DB-authoritative."""
    if customer_id is None or to_state not in ("CANCELLED", "ESCALATED", "EXPIRED"):
        return False
    # CA 252-01: ESCALATED CHI voi reason code allowlist. Reason ngoai allowlist -> TU CHOI transition
    # (khong coerce, khong mutate, khong notify) -> caller giu intent o state hien tai.
    from app.services.command import order_intent as _oi
    if to_state == "ESCALATED" and reason not in _oi.ESCALATION_REASONS:
        print(f"[order_intent_flow] terminalize REFUSED: ESCALATED reason ngoai allowlist ('{reason}')")
        return False
    conn = None
    try:
        conn = await acquire()
        async with conn.transaction():
            open_row = await svc.find_open_intent(
                conn, customer_id=customer_id, conversation_id=conversation_id, for_update=True)
            if open_row is None:
                return False
            r = await svc.transition(conn, open_row["id"], expected_version=open_row["state_version"],
                                     to_state=to_state, terminal_reason=reason)
            if r is not None and to_state == "ESCALATED":
                # CA 251 §3.D: DURABLE admin-notify trong CUNG transaction voi transition ESCALATED.
                # dedupe theo intent+version (idempotent, retry khong gui trung). Payload bounded, SDT
                # masked; dia chi/ten cho staff channel (authorized). command_id=None (migration 062).
                from app.services.command import repository as _repo
                await _repo.insert_outbox(
                    conn, command_id=None, event_type="order.escalated.notify", event_version=1,
                    destination="telegram_admin",
                    dedupe_key=f"order_escalated:{open_row['id']}:{r['state_version']}",
                    payload={
                        "kind": "escalation",
                        "has_intent": True,
                        # CA 253-01.3: worker ghi delivery_attempts.correlation_id (NOT NULL). Escalation
                        # khong co command -> dung intent_id (UUID) lam correlation (stable qua retry).
                        "correlation_id": str(open_row["id"]),
                        "reason_code": reason or "unknown",
                        "channel": open_row.get("channel"),
                        "intent_id": str(open_row["id"]),
                        "conversation_id": open_row.get("conversation_id"),
                        "customer_name": open_row.get("draft_customer_name"),
                        "phone_masked": _mask_phone(open_row.get("draft_phone")),
                        "address": open_row.get("draft_address"),
                        "sku": open_row.get("draft_sku"),
                        "quantity": open_row.get("draft_quantity"),
                    },
                    max_attempts=8)
            return r is not None
    except Exception as e:  # noqa: BLE001
        print(f"[order_intent_flow] terminalize skipped: {safe_exc(e)}")
        return False
    finally:
        if conn is not None:
            await release(conn)
