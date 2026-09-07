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

from app.db_pool import acquire, release
from app.services.command import order_intent_service as svc
from app.services.safe_log import safe_exc


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


async def propose_draft(*, customer_id: int | None, conversation_id, channel: str, proposed: dict,
                        verified: bool, addr_fp: str | None, verified_resolution_id: str | None,
                        address_changed: bool, explicit_new_order: bool = False) -> dict:
    """CA 232 §2/§3/§5: model create_order = PROPOSAL. Accumulate field vao durable draft + advance state;
    KHONG commit (server commit khi confirm). Tra {action, order_intent_id}:
      need_more : thieu field -> COLLECTING (caller hoi field thieu)
      clarify   : dia chi chua verified -> NEEDS_CLARIFICATION
      ready     : du field + verified -> READY_TO_COMMIT + summary da present (caller present summary/hoi xac nhan)
      skip/error: khong enrolled / loi fail-closed
    proposed = {sku,quantity,customer_name,phone,address} (None neu model khong de xuat field do)."""
    if customer_id is None:
        return {"action": "skip"}
    from app.services.command import order_intent as _oi
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
            if row is None:
                # Sau COMMITTED: don moi/reorder tuong minh -> intent moi. Neu khong tuong minh + co committed
                # cung fingerprint thi day la stale (khong tao lai) — nhung propose luon la don-dang-gom nen tao moi.
                new = await svc.create_intent(conn, customer_id=customer_id,
                                              conversation_id=conversation_id, channel=channel)
                row = await svc.get_intent(conn, new["id"], for_update=True)
            iid = row["id"]
            ver = row["state_version"]
            # Address doi -> xoa binding cu truoc khi verify lai (§3/§5).
            if address_changed:
                r = await svc.clear_address_binding(conn, iid, expected_version=ver)
                if r is not None:
                    ver = r["state_version"]
            # Accumulate field (merge; field khach cung cap moi thay the).
            d = await svc.update_draft(
                conn, iid, expected_version=ver, sku=proposed.get("sku"),
                quantity=proposed.get("quantity"), customer_name=proposed.get("customer_name"),
                phone=proposed.get("phone"), address=proposed.get("address"))
            if d is None:
                return {"action": "error"}
            ver = d["state_version"]
            # Thieu field -> giu COLLECTING.
            if not svc.draft_complete(d):
                if d["state"] != "COLLECTING":
                    # dua ve COLLECTING (correction lam thieu field) — chi khi transition hop le
                    if _oi.can_transition(d["state"], "COLLECTING"):
                        await svc.transition(conn, iid, expected_version=ver, to_state="COLLECTING")
                return {"action": "need_more", "order_intent_id": str(iid),
                        "missing": [f for f in ("sku", "quantity", "customer_name", "phone", "address")
                                    if d.get(f"draft_{f}") in (None, "")]}
            # Du field: tinh order_fingerprint tu draft + addr_fp.
            ofp = _oi.order_fingerprint(sku=d["draft_sku"], quantity=d["draft_quantity"],
                                        customer_name=d["draft_customer_name"], phone=d["draft_phone"],
                                        address_fp=addr_fp)
            # -> ADDRESS_CHECK (set fingerprint + binding), roi phan nhanh verified.
            ac = await _to_address_check(conn, {**d, "state": d["state"], "state_version": ver},
                                         order_fp=ofp, addr_fp=addr_fp, resolution_id=verified_resolution_id)
            if ac is None:
                return {"action": "error"}
            ver = ac["state_version"]
            if not verified:
                r = await svc.transition(conn, iid, expected_version=ver, to_state="NEEDS_CLARIFICATION")
                return {"action": "clarify", "order_intent_id": str(iid)}
            # verified -> READY_TO_COMMIT + present summary (KHONG commit).
            r = await svc.transition(conn, iid, expected_version=ver, to_state="READY_TO_COMMIT")
            if r is None:
                return {"action": "error"}
            await svc.present_summary(conn, iid, expected_version=r["state_version"], order_fingerprint=ofp)
            return {"action": "ready", "order_intent_id": str(iid),
                    "draft": {"sku": d["draft_sku"], "quantity": d["draft_quantity"],
                              "customer_name": d["draft_customer_name"], "phone": d["draft_phone"]}}
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
            return r is not None
    except Exception as e:  # noqa: BLE001
        print(f"[order_intent_flow] terminalize skipped: {safe_exc(e)}")
        return False
    finally:
        if conn is not None:
            await release(conn)
