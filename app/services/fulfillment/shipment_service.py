"""M6 shipment service — quote/status/attempt (CA Directive 265 + Review 266). Domain SONG SONG orders.status.

266-02: eligibility guard dung chung — handover chi khi fee quoted + payment du dieu kien (COD hop le / transfer
  da confirmed); attempt chi khi in_transit; terminal giu nguyen; het 3 luot -> return_pending (staff review).
266-03: mutation nhan command_key -> DB-atomic idempotency (replay khong tao attempt/effect moi); quote/carrier
  co optimistic version CAS (chong overwrite stale).
266-04: quote chi truoc handover; snapshot quote_rule_version; sau quote dong bo amount_due neu payment CHUA
  confirmed (khong am tham tang phi tren payment da xac nhan).
266-08: eta_start_at set 1 lan (COD confirm / transfer received), KHONG reset khi retry/doi tracking.
KHONG tu cong ton kho khi giao that bai/hoan.
"""
from __future__ import annotations

import hashlib
import json as _json

from app.services import audit_service
from app.services.fulfillment import quote as _q

POLICY_VERSION = "robanme-giao-nhan-2026-09"
# CA Directive 396 §3.2: Dashboard quote voi gate dashboard_route_quote_enabled OFF -> provider KHONG goi HTTP, tra
# quote_required voi ly do nay (KHONG phai loi provider -> attention 'quote', khong 'provider_error').
DASHBOARD_GATE_OFF_REASON = "ghn_dashboard_gate_off"


def _fingerprint(*parts) -> str:
    """CA 267-02: fingerprint on-dinh cua payload -> cung command_key khac payload bi tu choi."""
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _attempt_replay(conn, sh, ex, new_fp: str) -> dict:
    """CA 267-02: replay cung command_key -> so fingerprint; khac payload -> reject (khong tra nham ket qua cu)."""
    stored = ex["command_fingerprint"]
    if stored is not None and stored != new_fp:
        raise ShipmentError("command_key da dung cho attempt payload khac — tu choi (idempotency mismatch)")
    used = await conn.fetchval("SELECT count(*) FROM shipment_delivery_attempts WHERE shipment_id=$1", sh["id"])
    return {"attempt": dict(ex), "shipment_status": sh["status"], "attempts_used": used, "duplicate": True}

ALLOWED = {
    "pending_prep": {"ready_to_ship"},
    "ready_to_ship": {"in_transit", "pending_prep"},
    "in_transit": {"delivered", "delivery_failed"},
    "delivery_failed": {"in_transit", "return_pending"},
    "delivered": set(),
    "return_pending": set(),
}
TERMINAL = {"delivered", "return_pending"}
MAX_ATTEMPTS = 3


class ShipmentError(Exception):
    """Fail-closed. Khong leak secret."""


async def ensure_shipment(conn, order_id: int, *, actor: str) -> dict:
    row = await conn.fetchrow("SELECT * FROM shipments WHERE order_id=$1", order_id)
    if row:
        return dict(row)
    if not await conn.fetchval("SELECT 1 FROM orders WHERE id=$1", order_id):
        raise ShipmentError(f"order {order_id} khong ton tai")
    row = await conn.fetchrow(
        "INSERT INTO shipments (order_id, status, zone, fee_status) VALUES ($1,'pending_prep','unknown','unknown') "
        "ON CONFLICT (order_id) DO UPDATE SET updated_at=now() RETURNING *", order_id)
    await audit_service.record(conn, actor_type="cli", action="shipment.create", actor_ref=actor,
                               entity_type="shipments", entity_id=str(row["id"]), after={"order_id": order_id})
    return dict(row)


async def get_shipment(conn, order_id: int) -> dict | None:
    """Read-only: shipment row hien tai (dung cho replay idempotent route-quote — ket qua da apply)."""
    row = await conn.fetchrow("SELECT * FROM shipments WHERE order_id=$1", order_id)
    if not row:
        return None
    out = dict(row)
    out["attention_reason"] = None
    return out


async def _load_zone_rows(conn):
    return [dict(r) for r in await conn.fetch(
        "SELECT province_code, ward_code, zone, active FROM delivery_zones WHERE active")]


async def _load_fee_rules(conn):
    return [dict(r) for r in await conn.fetch(
        "SELECT zone, weight_min_g, weight_max_g, fee_vnd, quote_required, version, active "
        "FROM shipping_fee_rules WHERE active")]


async def _order_weight(conn, order_id: int) -> int | None:
    items = [dict(r) for r in await conn.fetch(
        "SELECT oi.quantity, p.shipping_weight_g FROM order_items oi JOIN products p ON p.id=oi.product_id "
        "WHERE oi.order_id=$1", order_id)]
    return _q.order_shipping_weight_g(items) if items else None


def _pre_handover(status: str) -> bool:
    return status in ("pending_prep", "ready_to_ship")


async def auto_quote(conn, order_id: int, *, actor: str) -> dict:
    sh = await ensure_shipment(conn, order_id, actor=actor)
    if not _pre_handover(sh["status"]):
        raise ShipmentError(f"khong the quote khi shipment o trang thai '{sh['status']}' (da/dang giao)")
    snap = await conn.fetchrow(
        "SELECT province_code, ward_code FROM order_address_snapshot WHERE order_id=$1", order_id)
    zone = _q.resolve_zone(snap["province_code"] if snap else None,
                           snap["ward_code"] if snap else None, await _load_zone_rows(conn))
    weight = await _order_weight(conn, order_id)
    rules = await _load_fee_rules(conn)
    rule = _q.matched_rule(zone, weight, rules)
    if weight is None:
        fee, fee_status, rv = None, "unknown", None
    elif rule is None:
        fee, fee_status, rv = None, "quote_required", None
    elif rule["quote_required"]:
        fee, fee_status, rv = None, "quote_required", rule["version"]
    else:
        fee, fee_status, rv = int(rule["fee_vnd"]), "quoted", rule["version"]
    return await _apply_quote(conn, sh, zone=zone, weight_g=weight, fee_vnd=fee, fee_status=fee_status,
                              eta=_q.eta_text(zone), quote_source="auto_rule", rule_version=rv, actor=actor)


async def route_and_quote(conn, order_id: int, *, actor: str, ghn_result=None, open_attention: bool = True) -> dict:
    """M7 (Directive 272 §3.2/§3.4): dinh tuyen TAT DINH tu order_address_snapshot + allowlist hieu luc, roi bao phi:
      SELF_DELIVERY -> bang phi noi bo (zone bmt_inner); GHN -> provider read-only quote (fail-closed quote_required);
      MANUAL_REVIEW -> quote_required. Snapshot route + quote (rule/mapping version, fingerprint, fee/ETA, inputs,
      quoted_at) vao shipments; version CAS; dong bo amount_due (payment chua settled). quote_required/manual ->
      mo staff_attention (idempotent). KHONG bao gio tra 0d khi khong biet phi."""
    from app.services.fulfillment import attention as _att
    from app.services.fulfillment import routing as _r

    sh = await ensure_shipment(conn, order_id, actor=actor)
    if not _pre_handover(sh["status"]):
        raise ShipmentError(f"khong the quote khi shipment o trang thai '{sh['status']}' (da/dang giao)")
    route = await _r.resolve_for_order(conn, order_id)
    weight = await _order_weight(conn, order_id)
    snapshot: dict = {"route": {"source": route.source, "reason": route.reason, "version": route.version,
                                "province_code": route.province_code, "ward_code": route.ward_code},
                      "inputs": {"weight_g": weight}}
    fee, fee_status, rv, eta, qprov, att_reason = None, "quote_required", None, None, "manual", None
    policy_version_col, quote_source_col = POLICY_VERSION, "auto_route"   # D340: fallback ghi de -> fallback_policy
    if route.source == _r.SELF_DELIVERY:
        zone = "bmt_inner"
        rule = _q.matched_rule(zone, weight, await _load_fee_rules(conn))
        qprov = "self_rule"
        if weight is None:
            fee_status, att_reason = "unknown", "quote"
            snapshot["fee"] = {"reason": "weight_missing"}
        elif rule is None or rule["quote_required"]:
            rv = rule["version"] if rule else None
            att_reason = "quote"
            snapshot["fee"] = {"reason": "no_rule_or_quote_required", "rule_version": rv}
        else:
            fee, fee_status, rv = int(rule["fee_vnd"]), "quoted", rule["version"]
            snapshot["fee"] = {"fee_vnd": fee, "rule_version": rv, "policy_version": POLICY_VERSION}
        eta = _q.eta_text(zone)
    elif route.source == _r.GHN:
        zone = "province" if route.province_code == "66" else "unknown"
        qprov = "ghn"
        if weight is None:
            fee_status, att_reason = "unknown", "quote"
            snapshot["fee"] = {"provider": "ghn", "reason": "weight_missing"}
        else:
            # GHN HTTP da goi NGOAI transaction (conversation.prepare_ghn_quote / API 2 pha) -> ghn_result.
            # CA 341-01: request dung CHUNG helper build_ghn_request (kich thuoc tu the tich dong thung D340) voi luc goi
            # HTTP -> fingerprint khop; API quote va fallback dung CUNG chargeable inputs (req_detail).
            from app.services.fulfillment import fallback_quote as _fb
            from app.services.providers.base import QUOTE_OK, QuoteResult
            req, req_reason, req_detail = await _fb.build_ghn_request(conn, order_id, route, weight)
            snapshot["request"] = req_detail
            if req is None:
                # Thieu kich thuoc/x HOAC hang nang >20 kg (CA 354) -> KHONG goi GHN (prepare_ghn_quote cung khong goi),
                # fallback KHONG bao phi -> manual/staff.
                att_reason = "quote"
                from app.services.fulfillment import shipping_policy as _sp
                if req_reason == _sp.HEAVY_GOODS_REASON:
                    snapshot["fee"] = {"provider": "ghn", **(req_detail.get("heavy_goods") or _sp.heavy_detail(weight))}
                else:
                    snapshot["fee"] = {"provider": "ghn", "reason": "packing_input_missing", "packing_reason": req_reason}
            else:
                snapshot["inputs"].update({"length_cm": req.length_cm, "width_cm": req.width_cm,
                                           "height_cm": req.height_cm})
                res = ghn_result
                if res is None:
                    from app.config import settings as _st
                    res = QuoteResult(status="quote_required", provider="ghn",
                                      reason="ghn_disabled" if not _st.m7_ghn_quote else "ghn_no_result",
                                      request_fingerprint=req.fingerprint())
                elif res.request_fingerprint != req.fingerprint():
                    res = QuoteResult(status="quote_required", provider="ghn", reason="ghn_fingerprint_mismatch",
                                      request_fingerprint=req.fingerprint())
                snapshot["fee"] = res.snapshot()
                if res.status == QUOTE_OK and res.fee_vnd is not None:
                    fee, fee_status, eta = int(res.fee_vnd), "quoted", res.eta_text
                else:
                    att_reason = "provider_error" if res.reason.startswith("ghn_") and res.reason not in (
                        "ghn_disabled", "ghn_not_configured", DASHBOARD_GATE_OFF_REASON) else "quote"
                    # CA Directive 340: API GHN khong dung duoc + flag fallback ON -> bao gia theo policy V2. KHONG retry
                    # provider sau ambiguous. Quote API hop le -> KHONG toi day.
                    from app.config import settings as _st_fb
                    if _st_fb.ghn_fallback_enabled:
                        _policy = await _fb.load_policy(conn)
                        if _policy:
                            _fee, _reason, _fdetail = _fb.compute_fallback_fee(
                                _policy, route.province_code, req_detail["chargeable_weight_kg"])
                            if _fee is not None:
                                fee, fee_status, eta = int(_fee), "quoted", _q.eta_text(zone)
                                quote_source_col = "fallback_policy"
                                policy_version_col = _policy["policy_version"]
                                snapshot["fee"] = {**snapshot["fee"], **req_detail, **_fdetail, "fee_vnd": int(_fee),
                                                   "api_error_reason": res.reason}
                                att_reason = "quote"   # van mo staff_attention (340 §1.4)
                            else:
                                snapshot["fee"] = {**snapshot["fee"], "fallback_reason": _reason}
    else:  # MANUAL_REVIEW
        zone = "unknown"
        att_reason = "address"
        snapshot["fee"] = {"reason": route.reason}
    row = await conn.fetchrow(
        "UPDATE shipments SET zone=$2, weight_g=$3, delivery_fee_vnd=$4, fee_status=$5, eta_text=$6, "
        "policy_version=$7, quote_rule_version=$8, quote_source=$9, routing_source=$10, routing_version=$11, "
        "routing_province_code=$12, routing_ward_code=$13, routing_reason=$14, routed_at=now(), quote_provider=$15, "
        "quote_snapshot=$16::jsonb, quoted_at=now(), version=version+1, updated_at=now() "
        "WHERE id=$1 AND version=$17 RETURNING *",
        sh["id"], zone, weight, fee, fee_status, eta, policy_version_col, rv, quote_source_col, route.source,
        route.version, route.province_code, route.ward_code, route.reason, qprov, _json.dumps(snapshot), sh["version"])
    if row is None:
        raise ShipmentError("version conflict (concurrent) — tai lai roi thu lai")
    await audit_service.record(conn, actor_type="system", action="shipment.route_quote", actor_ref=actor,
                               entity_type="shipments", entity_id=str(sh["id"]),
                               after={"route": route.source, "routing_version": route.version, "fee_vnd": fee,
                                      "fee_status": fee_status, "provider": qprov})
    from app.services.payment import payment_service as _p
    await _p.sync_amount_due_if_unsettled(conn, order_id, actor=actor)
    if open_attention and att_reason:
        await _att.open_attention(conn, order_id, reason=att_reason,
                                  detail={"route": route.source, "route_reason": route.reason,
                                          "fee_status": fee_status, "quote_reason": snapshot["fee"].get("reason")},
                                  created_by=actor)
    out = dict(row)
    out["attention_reason"] = att_reason
    return out


async def set_manual_quote(conn, order_id: int, *, actor: str, zone: str | None = None,
                           weight_g: int | None = None, fee_vnd: int | None = None,
                           eta_text: str | None = None) -> dict:
    sh = await ensure_shipment(conn, order_id, actor=actor)
    if not _pre_handover(sh["status"]):
        raise ShipmentError(f"khong the quote khi shipment o trang thai '{sh['status']}'")
    z = zone or sh["zone"]
    if fee_vnd is not None:
        if not isinstance(fee_vnd, int) or fee_vnd < 0:
            raise ShipmentError("fee_vnd phai nguyen >= 0")
        fee, fee_status = int(fee_vnd), "quoted"
    else:
        fee, fee_status = None, "quote_required"
    return await _apply_quote(conn, sh, zone=z, weight_g=weight_g if weight_g is not None else sh["weight_g"],
                              fee_vnd=fee, fee_status=fee_status,
                              eta=eta_text or sh["eta_text"] or _q.eta_text(z),
                              quote_source="staff_manual", rule_version=None, actor=actor)


async def _apply_quote(conn, sh, *, zone, weight_g, fee_vnd, fee_status, eta, quote_source, rule_version, actor):
    row = await conn.fetchrow(
        "UPDATE shipments SET zone=$2, weight_g=$3, delivery_fee_vnd=$4, fee_status=$5, eta_text=$6, "
        "policy_version=$7, quote_rule_version=$8, quote_source=$9, version=version+1, updated_at=now() "
        "WHERE id=$1 AND version=$10 RETURNING *",
        sh["id"], zone, weight_g, fee_vnd, fee_status, eta, POLICY_VERSION, rule_version, quote_source,
        sh["version"])
    if row is None:
        raise ShipmentError("version conflict (concurrent) — tai lai roi thu lai")
    await audit_service.record(conn, actor_type="cli", action="shipment.quote", actor_ref=actor,
                               entity_type="shipments", entity_id=str(sh["id"]),
                               after={"zone": zone, "fee_vnd": fee_vnd, "fee_status": fee_status,
                                      "source": quote_source, "rule_version": rule_version})
    # CA 266-04: dong bo amount_due sang payment CHI khi payment chua confirmed/reconciled (khong am tham
    # tang phi tren payment da xac nhan). Cross-domain best-effort trong cung tx.
    from app.services.payment import payment_service as _p
    await _p.sync_amount_due_if_unsettled(conn, sh["order_id"], actor=actor)
    # M7: tong da gui cho khach (hoi thoai) KHONG con dung sau re-quote -> staff reconfirm (khong tu gui tong moi).
    if row["delivery_fee_vnd"] != sh["delivery_fee_vnd"] or row["fee_status"] != sh["fee_status"]:
        from app.services.fulfillment import conversation as _fc
        await _fc.on_quote_changed(conn, sh["order_id"], actor=actor)
    return dict(row)


async def set_carrier(conn, order_id: int, *, actor: str, carrier: str | None, tracking_text: str | None,
                      expected_version: int | None = None) -> dict:
    sh = await ensure_shipment(conn, order_id, actor=actor)
    if expected_version is not None and expected_version != sh["version"]:
        raise ShipmentError("version conflict — tai lai roi thu lai")
    row = await conn.fetchrow(
        "UPDATE shipments SET carrier=$2, tracking_text=$3, version=version+1, updated_at=now() "
        "WHERE id=$1 AND version=$4 RETURNING *", sh["id"], carrier, tracking_text, sh["version"])
    if row is None:
        raise ShipmentError("version conflict (concurrent) — huy")
    await audit_service.record(conn, actor_type="cli", action="shipment.carrier", actor_ref=actor,
                               entity_type="shipments", entity_id=str(sh["id"]),
                               after={"carrier": carrier, "tracking": bool(tracking_text)})
    return dict(row)


async def _handover_eligible(conn, order_id: int, sh: dict) -> tuple[bool, str]:
    """CA 266-02: chi ban giao khi fee da chot + payment du dieu kien."""
    if sh["fee_status"] != "quoted":
        return False, "phi giao chua chot (fee_status != quoted)"
    pay = await conn.fetchrow("SELECT method, status, amount_due_vnd FROM payments WHERE order_id=$1", order_id)
    if not pay:
        return False, "chua co payment cho don"
    if pay["amount_due_vnd"] is None:
        return False, "amount_due chua chot"
    if pay["method"] == "BANK_TRANSFER" and pay["status"] != "confirmed":
        return False, "chuyen khoan chua duoc shop xac nhan du tien (status != confirmed)"
    # COD: order confirmed + quote hop le la du (thu tien khi giao)
    return True, ""


async def set_eta_start(conn, order_id: int, *, source: str) -> None:
    """CA 266-08: set moc bat dau ETA MOT LAN (khong reset). Goi tu payment (COD confirm/transfer received)."""
    await conn.execute(
        "UPDATE shipments SET eta_start_at=now(), eta_start_source=$2, updated_at=now() "
        "WHERE order_id=$1 AND eta_start_at IS NULL", order_id, source)


async def change_status(conn, order_id: int, to_status: str, *, actor: str,
                        expected_version: int | None = None) -> dict:
    sh = await conn.fetchrow("SELECT * FROM shipments WHERE order_id=$1", order_id)
    if not sh:
        raise ShipmentError(f"shipment cho order {order_id} chua ton tai")
    frm = sh["status"]
    if to_status not in ALLOWED.get(frm, set()):
        raise ShipmentError(f"transition khong hop le: {frm} -> {to_status}")
    if expected_version is not None and expected_version != sh["version"]:
        raise ShipmentError("version conflict — tai lai roi thu lai")
    # CA 266-02: ban giao (-> in_transit) phai du dieu kien nghiep vu
    if to_status == "in_transit":
        # tu delivery_failed -> in_transit (retry) chi khi con luot; va luon can eligibility
        if frm == "delivery_failed":
            used = await conn.fetchval("SELECT count(*) FROM shipment_delivery_attempts WHERE shipment_id=$1",
                                       sh["id"])
            if used >= MAX_ATTEMPTS:
                raise ShipmentError("da het 3 luot giao — chuyen return_pending/staff review, khong retry")
        ok, why = await _handover_eligible(conn, order_id, dict(sh))
        if not ok:
            raise ShipmentError(f"chua du dieu kien ban giao: {why}")
    set_handover = ", handover_at=now()" if to_status == "in_transit" and sh["handover_at"] is None else ""
    row = await conn.fetchrow(
        f"UPDATE shipments SET status=$2, version=version+1, updated_at=now(){set_handover} "
        "WHERE id=$1 AND version=$3 RETURNING *", sh["id"], to_status, sh["version"])
    if row is None:
        raise ShipmentError("version conflict (concurrent) — huy cap nhat")
    await audit_service.record(conn, actor_type="cli", action="shipment.status", actor_ref=actor,
                               entity_type="shipments", entity_id=str(sh["id"]),
                               before={"status": frm}, after={"status": to_status})
    from app.services.fulfillment import notify as _n
    await _n.notify_shipment(conn, order_id, to_status=to_status, sh=dict(row), version=row["version"])
    return dict(row)


async def record_attempt(conn, order_id: int, *, actor: str, command_key: str, result: str,
                         reason: str | None = None, note: str | None = None, next_contact_at=None) -> dict:
    """CA 266-02/03: attempt chi khi in_transit; command_key idempotent (replay -> tra attempt cu, khong tao moi);
    success -> delivered; fail o luot 3 -> return_pending (staff); fail truoc do -> delivery_failed."""
    if not command_key:
        raise ShipmentError("thieu command_key (idempotency)")
    if result not in ("success", "failed", "no_contact", "rescheduled"):
        raise ShipmentError("result khong hop le")
    # CA 267-02: khoa aggregate shipment -> hai attempt khac command_key SERIALIZE (khong cung doc count/attempt_no
    # -> khong con loi DB uq_attempt_no; request sau thay state moi roi xu ly dung theo state hien hanh).
    sh = await conn.fetchrow("SELECT * FROM shipments WHERE order_id=$1 FOR UPDATE", order_id)
    if not sh:
        raise ShipmentError(f"shipment cho order {order_id} chua ton tai")
    fp = _fingerprint("att", result, reason, note, next_contact_at)
    # replay idempotent theo command_key (+ fingerprint: cung key khac payload -> reject)
    ex = await conn.fetchrow(
        "SELECT * FROM shipment_delivery_attempts WHERE shipment_id=$1 AND command_key=$2", sh["id"], command_key)
    if ex:
        return await _attempt_replay(conn, sh, ex, fp)
    if sh["status"] != "in_transit":
        raise ShipmentError(f"chi ghi attempt khi shipment 'in_transit' (dang la '{sh['status']}')")
    used = await conn.fetchval("SELECT count(*) FROM shipment_delivery_attempts WHERE shipment_id=$1", sh["id"])
    if used >= MAX_ATTEMPTS:
        raise ShipmentError(f"da du {MAX_ATTEMPTS} lan giao — chuyen staff review, khong tao lan thu 4")
    attempt_no = used + 1
    att = await conn.fetchrow(
        "INSERT INTO shipment_delivery_attempts (shipment_id, attempt_no, result, reason, note, "
        "next_contact_at, recorded_by, command_key, command_fingerprint) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
        "ON CONFLICT (shipment_id, command_key) DO NOTHING RETURNING *",
        sh["id"], attempt_no, result, reason, note, next_contact_at, actor, command_key, fp)
    if att is None:  # race: cung command_key vao truoc -> replay
        ex = await conn.fetchrow(
            "SELECT * FROM shipment_delivery_attempts WHERE shipment_id=$1 AND command_key=$2", sh["id"], command_key)
        return await _attempt_replay(conn, sh, ex, fp)
    # cap nhat status tu trang thai HIEN TAI (in_transit) — khong dung hang so
    if result == "success":
        new_status = "delivered"
    elif attempt_no >= MAX_ATTEMPTS:
        new_status = "return_pending"           # het luot -> staff xu ly hoan (KHONG tu cong ton)
    else:
        new_status = "delivery_failed"
    await conn.execute("UPDATE shipments SET status=$2, version=version+1, updated_at=now() WHERE id=$1",
                       sh["id"], new_status)
    await audit_service.record(conn, actor_type="cli", action="shipment.attempt", actor_ref=actor,
                               entity_type="shipments", entity_id=str(sh["id"]),
                               after={"attempt_no": attempt_no, "result": result, "status": new_status})
    from app.services.fulfillment import notify as _n
    await _n.notify_shipment(conn, order_id, to_status=new_status, sh=dict(sh),
                             version=(sh["version"] + 1))
    return {"attempt": dict(att), "shipment_status": new_status, "attempts_used": attempt_no, "duplicate": False}
