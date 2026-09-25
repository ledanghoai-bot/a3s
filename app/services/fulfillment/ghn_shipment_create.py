"""CA Directive 393 — GHN shipment create: MOT lifecycle chung cho 2 entry point (Bot | Dashboard Staff).

    prepared ──(worker, gate ON, revalidate OK)──> dispatching ──created──> succeeded (provider evidence)
        │                                              ├─rejected (4xx/code!=200)──> failed_terminal (+attention)
        │                                              ├─retryable (chua gui / 429 / 5xx)──> failed_retryable
        │                                              │        └─(truoc retry: DOI SOAT client_order_code)
        │                                              └─unknown (timeout/mat response)──> unknown_reconciliation_required
        └─(huy don / staff huy truoc dispatch)──> cancelled_before_dispatch

- Bot va Dashboard KHONG goi provider: chi `prepare` (1 transaction, idempotent theo (source, command_key), 1 operation
  active / order). Provider CHI chay trong worker `run_dispatch_once`, sau gate TACH theo source + revalidate lai toan bo
  dieu kien (fingerprint snapshot phai khop) — gate OFF -> dung TRUOC HTTP, ghi gate_blocked_reason (audit 1 lan).
- Snapshot request BAT BIEN (trigger 073): recipient/dia chi map/pickup/khoi luong-kich thuoc/quote/payment/policy/
  config revision. Adapter chi doc snapshot; credential resolve luc gui, khong luu.
- Timeout/mat response KHONG blind retry: -> unknown_reconciliation_required + staff attention. Moi retry create PHAI
  doi soat bang client_order_code truoc.
- Huy don: truoc dispatch -> cancelled_before_dispatch (khong HTTP); sau dispatch/succeeded -> KHONG gia vo huy GHN:
  giu state, huy thuong bi chan (can order.cancel.exception) + staff attention (cancel_cascade).
- Tao van don KHONG phai xac nhan thanh toan; khong doi SePay/inventory/map/quote rules/guard 20 kg.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.services import audit_service
from app.services.command import repository as cmd_repo

POLICY_VERSION = "ghn_create_policy_v1"
SNAPSHOT_SCHEMA = "ghn_create_snapshot_v1"
# Policy v1 (PO co the doi qua version moi): shop tra phi GHN (payment_type_id=1), khach tra tong (hang + phi giao)
# qua COD; khong cho xem hang. BANK_TRANSFER chi du dieu kien khi tien DA xac nhan. Quote hieu luc 24h.
POLICY = {"payment_type_id": 1, "required_note": "KHONGCHOXEMHANG", "quote_validity_hours": 24,
          "max_attempts": 4, "backoff_s": (60, 300, 900), "lease_s": 120,
          "cod_payment_states": ("awaiting",), "transfer_payment_states": ("confirmed", "reconciled")}

PREPARED, DISPATCHING, SUCCEEDED = "prepared", "dispatching", "succeeded"
FAILED_RETRYABLE, FAILED_TERMINAL = "failed_retryable", "failed_terminal"
UNKNOWN, CANCELLED_BEFORE = "unknown_reconciliation_required", "cancelled_before_dispatch"
ACTIVE_STATES = (PREPARED, DISPATCHING, SUCCEEDED, FAILED_RETRYABLE, UNKNOWN)
PRE_DISPATCH_STATES = (PREPARED, FAILED_RETRYABLE)
DISPATCHED_STATES = (DISPATCHING, UNKNOWN, SUCCEEDED)
SOURCES = ("bot", "dashboard")
ATTENTION_REASON = "shipment_create"
ORDER_OK_STATUSES = ("new", "confirmed", "processing", "ready_for_fulfillment")
_PHONE_RE = re.compile(r"^(0|\+84)(3|5|7|8|9)\d{8}$")


class ShipmentCreateError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 409, blockers: list | None = None):
        super().__init__(message)
        self.code, self.message, self.http_status, self.blockers = code, message, http_status, blockers or []


def gate_enabled(source: str) -> bool:
    return bool(settings.ghn_shipment_create_bot_enabled if source == "bot"
                else settings.ghn_shipment_create_dashboard_enabled)


def fingerprint(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
                          .encode("utf-8")).hexdigest()


def client_order_code(order_id: int, op_id: int) -> str:
    """Correlation tat dinh tu operation id (khong PII). <= 50 ky tu."""
    return f"A3S-{int(order_id)}-{int(op_id)}"


def mask_code(code: str | None) -> str | None:
    if not code:
        return code
    return code if len(code) <= 6 else f"{code[:4]}…{code[-3:]}"


def _mask_phone(p: str | None) -> str:
    s = "".join(ch for ch in str(p or "") if ch.isdigit())
    return ("***" + s[-3:]) if len(s) >= 3 else "***"


# ------------------------------------------------------------------ eligibility (dung CHUNG bot/dashboard/worker)
async def _integration(conn, mode: str) -> dict | None:
    row = await conn.fetchrow(
        "SELECT id, config_revision, config_public FROM integrations WHERE provider='ghn' AND mode=$1 AND enabled "
        "AND archived_at IS NULL", mode)
    if not row:
        return None
    cp = row["config_public"]
    if isinstance(cp, str):
        cp = json.loads(cp)
    return {"id": row["id"], "config_revision": row["config_revision"], "config": cp or {}}


async def evaluate(conn, order_id: int, *, source: str, exclude_op_id: int | None = None) -> dict:
    """Danh gia dieu kien + dung snapshot. Tra {eligible, blockers, warnings, snapshot, fingerprint}. KHONG ghi gi,
    KHONG goi provider, KHONG giai ma secret."""
    from app.services.fulfillment import fallback_quote as _fb
    from app.services.fulfillment import routing as _r
    from app.services.fulfillment import shipment_service as _sh
    from app.services.fulfillment import shipping_policy as _sp
    from app.services.providers import ghn as _ghn

    blockers: list[str] = []
    warnings: list[str] = []
    out = {"eligible": False, "blockers": blockers, "warnings": warnings, "snapshot": None, "fingerprint": None,
           "policy_version": POLICY_VERSION}
    if source not in SOURCES:
        blockers.append("source_invalid")
        return out
    o = await conn.fetchrow(
        "SELECT o.id, o.status, o.total_vnd, o.shipping_name, o.shipping_phone, o.shipping_address, o.customer_id, "
        "c.channel AS customer_channel FROM orders o JOIN customers c ON c.id=o.customer_id WHERE o.id=$1", order_id)
    if o is None:
        blockers.append("order_not_found")
        return out
    if o["status"] in ("cancelled", "cancelled_by_exception"):
        blockers.append("order_cancelled")
    elif o["status"] not in ORDER_OK_STATUSES:
        blockers.append(f"order_status_{o['status']}")
    if source == "bot" and o["customer_channel"] not in ("telegram_customer", "messenger"):
        blockers.append("customer_not_messaging")
    name, phone = (o["shipping_name"] or "").strip(), (o["shipping_phone"] or "").strip()
    if not name or not phone:
        blockers.append("recipient_incomplete")
    elif not _PHONE_RE.match(phone):
        blockers.append("recipient_phone_invalid")
    active = await conn.fetchval(
        "SELECT id FROM ghn_shipment_create_operations WHERE order_id=$1 AND state = ANY($2::text[]) "
        "AND ($3::bigint IS NULL OR id <> $3)", order_id, list(ACTIVE_STATES), exclude_op_id)
    if active:
        blockers.append("operation_active")
    open_att = [r["reason"] for r in await conn.fetch(
        "SELECT reason FROM staff_attention WHERE order_id=$1 AND status='open'", order_id)]
    if open_att:
        blockers.append("staff_attention_open")
        if "refund_required" in open_att or "order_cancel_exception" in open_att:
            blockers.append("refund_or_exception_pending")

    route = await _r.resolve_for_order(conn, order_id)
    if route.source == _r.SELF_DELIVERY:
        blockers.append("self_delivery")
    elif route.source != _r.GHN:
        blockers.append("route_manual_review")
    weight = await _sh._order_weight(conn, order_id)
    req = None
    if weight is None:
        blockers.append("weight_missing")
    elif _sp.is_heavy(weight):
        blockers.append("heavy_goods")
    elif route.source == _r.GHN:
        req, req_reason, _d = await _fb.build_ghn_request(conn, order_id, route, weight)
        if req is None:
            blockers.append(f"packing_{req_reason}")

    sh = await conn.fetchrow("SELECT * FROM shipments WHERE order_id=$1", order_id)
    qsnap = {}
    if sh is None:
        blockers.append("shipment_missing")
    else:
        if sh["status"] not in ("pending_prep", "ready_to_ship"):
            blockers.append(f"shipment_status_{sh['status']}")
        qsnap = sh["quote_snapshot"] or {}
        if isinstance(qsnap, str):
            qsnap = json.loads(qsnap)
        fee = qsnap.get("fee") or {}
        if sh["fee_status"] != "quoted" or sh["quote_provider"] != "ghn" or sh["quote_source"] == "fallback_policy" \
                or fee.get("status") != "ok":
            blockers.append("quote_not_ghn_api_ok")
        elif req is not None and fee.get("request_fingerprint") != req.fingerprint():
            blockers.append("quote_stale")
        if sh["quoted_at"] is None or (datetime.now(timezone.utc) - sh["quoted_at"]
                                       > timedelta(hours=POLICY["quote_validity_hours"])):
            blockers.append("quote_expired")

    mode = str(settings.ghn_active_mode or "").strip()
    integ = await _integration(conn, mode) if mode in _ghn.MODES else None
    addr = None
    if integ is None:
        blockers.append("ghn_not_configured")
    else:
        cfgp = integ["config"]
        if not cfgp.get("from_district_id") or not cfgp.get("from_ward_code") or \
                (cfgp.get("base_url") or "").rstrip("/") != _ghn.BASE_BY_MODE[mode]:
            blockers.append("ghn_not_configured")
        elif route.province_code and route.ward_code:
            addr = await _ghn.address_lookup(conn, route.province_code, route.ward_code,
                                             map_version=int(cfgp.get("address_map_version") or 1), mode=mode)
            if addr is None:
                blockers.append("address_unmapped")

    pay = await conn.fetchrow("SELECT id, method, status, version, amount_due_vnd, amount_received_vnd "
                              "FROM payments WHERE order_id=$1", order_id)
    if pay is None:
        blockers.append("payment_missing")
    elif pay["amount_due_vnd"] is None:
        blockers.append("payment_amount_unknown")
    elif pay["method"] == "COD":
        if pay["status"] not in POLICY["cod_payment_states"] or int(pay["amount_received_vnd"] or 0) != 0:
            blockers.append(f"payment_cod_state_{pay['status']}")
    elif pay["method"] == "BANK_TRANSFER":
        if pay["status"] not in POLICY["transfer_payment_states"]:
            blockers.append("payment_not_confirmed")
    else:
        blockers.append("payment_method_unknown")

    if blockers:
        return out
    snap_addr = await conn.fetchrow("SELECT street_text, ward_name, district_name, province_name "
                                    "FROM order_address_snapshot WHERE order_id=$1", order_id)
    parts = [snap_addr[k] for k in ("street_text", "ward_name", "district_name", "province_name")] if snap_addr else []
    address_text = ", ".join(p for p in parts if p) or (o["shipping_address"] or "").strip()
    if not address_text:
        blockers.append("recipient_address_missing")
        return out
    items = [{"name": r["name"], "quantity": int(r["quantity"]), "weight_g": int(r["shipping_weight_g"] or 0)}
             for r in await conn.fetch("SELECT p.name, oi.quantity, p.shipping_weight_g FROM order_items oi "
                                       "JOIN products p ON p.id=oi.product_id WHERE oi.order_id=$1 ORDER BY oi.id",
                                       order_id)]
    cfgp = integ["config"]
    cod = int(pay["amount_due_vnd"]) if pay["method"] == "COD" else 0
    snapshot = {
        "schema": SNAPSHOT_SCHEMA, "policy_version": POLICY_VERSION,
        "order": {"id": o["id"], "status": o["status"], "total_vnd": o["total_vnd"]},
        "recipient": {"name": name, "phone": phone, "address_text": address_text},
        "address": {"province_code": route.province_code, "ward_code": route.ward_code,
                    "carrier_district_id": addr["carrier_district_id"], "carrier_ward_code": addr["carrier_ward_code"],
                    "map_version": int(cfgp.get("address_map_version") or 1), "mode": mode,
                    "routing_version": route.version},
        "pickup": {"from_district_id": cfgp.get("from_district_id"), "from_ward_code": cfgp.get("from_ward_code"),
                   "integration_id": integ["id"], "config_revision": integ["config_revision"], "mode": mode},
        "parcel": {"weight_g": int(weight), "length_cm": req.length_cm, "width_cm": req.width_cm,
                   "height_cm": req.height_cm, "insurance_value_vnd": 0,
                   "service_type_id": _ghn.service_type_for_weight(int(weight), int(cfgp.get("light_max_g") or 20000))},
        "quote": {"fee_vnd": sh["delivery_fee_vnd"], "request_fingerprint": (qsnap.get("fee") or {}).get(
                      "request_fingerprint"), "quoted_at": sh["quoted_at"].isoformat(), "eta_text": sh["eta_text"],
                  "shipment_id": sh["id"], "shipment_version": sh["version"]},
        "payment": {"method": pay["method"], "status": pay["status"], "version": pay["version"],
                    "amount_due_vnd": int(pay["amount_due_vnd"]), "cod_amount_vnd": cod},
        "items": items,
        "policy": {"payment_type_id": POLICY["payment_type_id"], "required_note": POLICY["required_note"]},
    }
    if cod >= 3_000_000:
        warnings.append("cod_amount_high")
    if not items:
        warnings.append("no_items")
    out.update(eligible=True, snapshot=snapshot, fingerprint=fingerprint(snapshot))
    return out


def redacted_preview(ev: dict) -> dict:
    """Ban preview cho UI/audit: SDT mask, khong token."""
    s = ev.get("snapshot")
    if not s:
        return {k: ev[k] for k in ("eligible", "blockers", "warnings", "fingerprint", "policy_version")}
    s2 = json.loads(json.dumps(s))
    s2["recipient"]["phone"] = _mask_phone(s["recipient"]["phone"])
    return {"eligible": ev["eligible"], "blockers": ev["blockers"], "warnings": ev["warnings"],
            "fingerprint": ev["fingerprint"], "policy_version": ev["policy_version"], "snapshot": s2}


# ------------------------------------------------------------------ prepare (entry point chung)
def _op_view(op) -> dict:
    d = dict(op)
    d.pop("request_snapshot", None)
    d["client_order_code_masked"] = mask_code(d.pop("client_order_code", None))
    for k in ("provider_result",):
        if isinstance(d.get(k), str):
            d[k] = json.loads(d[k])
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


async def prepare(conn, order_id: int, *, source: str, command_key: str, actor: str, staff_id: int | None = None,
                  customer_id: int | None = None, confirm_fingerprint: str | None = None,
                  note: str | None = None) -> dict:
    """Tao operation `prepared` (TRONG transaction caller). Idempotent (source, command_key): replay tra receipt cu,
    KHONG tao operation/provider effect thu 2. confirm_fingerprint BAT BUOC = fingerprint hien hanh (xac nhan tren
    dung du lieu da xem). KHONG goi provider."""
    if source not in SOURCES:
        raise ShipmentCreateError("source_invalid", "source phai bot|dashboard", 422)
    if not isinstance(command_key, str) or not command_key.strip() or len(command_key) > 200:
        raise ShipmentCreateError("command_key_invalid", "command_key bat buoc (1-200 ky tu)", 422)
    if source == "dashboard" and not staff_id:
        raise ShipmentCreateError("staff_required", "Dashboard bat buoc Staff ID", 403)
    if source == "bot" and not customer_id:
        raise ShipmentCreateError("customer_required", "Bot bat buoc customer", 403)
    if note is not None and len(note.strip()) > 500:
        raise ShipmentCreateError("note_too_long", "ghi chu toi da 500 ky tu", 422)
    ck = command_key.strip()
    ex = await conn.fetchrow("SELECT * FROM ghn_shipment_create_operations WHERE source=$1 AND command_key=$2",
                             source, ck)
    if ex is not None:
        if ex["order_id"] != order_id:
            raise ShipmentCreateError("idempotency_conflict", "command_key da dung cho don khac", 409)
        return {"operation": _op_view(ex), "duplicate": True}
    await conn.execute("SELECT 1 FROM orders WHERE id=$1 FOR UPDATE", order_id)   # serialize voi huy/prepare khac
    ev = await evaluate(conn, order_id, source=source)
    if not ev["eligible"]:
        raise ShipmentCreateError("not_eligible", "Don chua du dieu kien tao van don GHN", 409, ev["blockers"])
    if not confirm_fingerprint or confirm_fingerprint != ev["fingerprint"]:
        raise ShipmentCreateError("confirmation_stale",
                                  "Du lieu don/dia chi/phi/phuong thuc da thay doi so voi luc xac nhan — xem lai", 409)
    snap = ev["snapshot"]
    op_id = await conn.fetchval("SELECT nextval(pg_get_serial_sequence('ghn_shipment_create_operations','id'))")
    row = await conn.fetchrow(
        "INSERT INTO ghn_shipment_create_operations (id, order_id, shipment_id, source, initiator_staff_id, "
        "initiator_customer_id, command_key, request_fingerprint, mode, integration_id, config_revision, "
        "client_order_code, state, policy_version, request_snapshot, note, max_attempts) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'prepared',$13,$14::jsonb,$15,$16) RETURNING *",
        op_id, order_id, snap["quote"]["shipment_id"], source, staff_id if source == "dashboard" else None,
        customer_id if source == "bot" else None, ck, ev["fingerprint"], snap["pickup"]["mode"],
        snap["pickup"]["integration_id"], snap["pickup"]["config_revision"], client_order_code(order_id, op_id),
        POLICY_VERSION, json.dumps(snap), (note or "").strip() or None, POLICY["max_attempts"])
    await audit_service.record(
        conn, "staff" if source == "dashboard" else "customer", "shipment.ghn_create.prepare", actor_ref=actor,
        actor_staff_id=staff_id if source == "dashboard" else None, entity_type="ghn_shipment_create_operations",
        entity_id=str(op_id), after={"order_id": order_id, "source": source, "command_key": ck,
                                     "fingerprint": ev["fingerprint"], "mode": snap["pickup"]["mode"],
                                     "config_revision": snap["pickup"]["config_revision"],
                                     "policy_version": POLICY_VERSION, "state": PREPARED,
                                     "gate_enabled": gate_enabled(source)})
    return {"operation": _op_view(row), "duplicate": False}


# ------------------------------------------------------------------ helpers ghi state
async def _audit(conn, op, action: str, after: dict, *, actor: str = "worker:ghn_create") -> None:
    await audit_service.record(conn, "system", action, actor_ref=actor, entity_type="ghn_shipment_create_operations",
                               entity_id=str(op["id"]), after={"order_id": op["order_id"], "source": op["source"],
                                                                **after})


async def _attempt(conn, op_id: int, attempt_no: int, kind: str, res, *, actor: str, outcome: str | None = None) -> None:
    await conn.execute(
        "INSERT INTO ghn_shipment_create_attempts (operation_id, attempt_no, kind, outcome, http_status, error_class, "
        "retry_after_s, duration_ms, response_redacted, actor) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10) "
        "ON CONFLICT (operation_id, attempt_no, kind) DO NOTHING",
        op_id, attempt_no, kind, outcome or res.outcome, getattr(res, "http_status", None),
        (getattr(res, "error_class", "") or None), getattr(res, "retry_after_s", None),
        getattr(res, "duration_ms", None), json.dumps(getattr(res, "result", {}) or {}), actor)


async def _open_attention(conn, op, why: str, extra: dict | None = None) -> None:
    from app.services.fulfillment import attention as _att
    await _att.open_attention(conn, op["order_id"], reason=ATTENTION_REASON,
                              detail={"operation_id": op["id"], "why": why, "state": op["state"],
                                      "client_order_code": mask_code(op["client_order_code"]), **(extra or {})},
                              created_by="worker:ghn_create")


async def _set_state(conn, op, state: str, **cols) -> dict:
    sets, args = ["state=$2", "updated_at=now()"], [op["id"], state]
    for k, v in cols.items():
        args.append(v)
        sets.append(f"{k}=${len(args)}" + ("::jsonb" if k == "provider_result" else ""))
    if state in (FAILED_TERMINAL, CANCELLED_BEFORE):
        sets.append("terminal_at=now()")
    row = await conn.fetchrow(f"UPDATE ghn_shipment_create_operations SET {', '.join(sets)} WHERE id=$1 RETURNING *",
                              *args)
    return dict(row)


async def _succeed(conn, op, res, *, actor: str) -> dict:
    op2 = await _set_state(conn, op, SUCCEEDED, provider_order_code=res.order_code, succeeded_at=datetime.now(timezone.utc),
                           provider_result=json.dumps(res.result or {}), lease_owner=None, lease_expires_at=None,
                           last_error_class=None, last_http_status=res.http_status)
    # Provider evidence -> ghi hang/ma van don vao shipment (KHONG doi shipment.status: ban giao do staff/van hanh).
    await conn.execute("UPDATE shipments SET carrier='GHN', tracking_text=$2, version=version+1, updated_at=now() "
                       "WHERE order_id=$1 AND status IN ('pending_prep','ready_to_ship')", op["order_id"], res.order_code)
    await _audit(conn, op2, "shipment.ghn_create.succeeded",
                 {"provider_order_code": res.order_code, "http_status": res.http_status}, actor=actor)
    cust = await conn.fetchrow("SELECT c.psid, c.channel FROM orders o JOIN customers c ON c.id=o.customer_id "
                               "WHERE o.id=$1", op["order_id"])
    if cust and cust["channel"] in ("telegram_customer", "messenger") and cust["psid"]:
        await cmd_repo.insert_outbox(
            conn, command_id=None, event_type="shipment.ghn_created.notify", event_version=1,
            destination=cust["channel"], dedupe_key=f"ghn_created:{op['id']}",
            payload={"customer_ref": cust["psid"], "order_id": op["order_id"],
                     "text": f"Dạ đơn #{op['order_id']} đã được tạo vận đơn GHN (mã {res.order_code}). "
                             "Shop sẽ báo anh/chị khi hàng được bàn giao cho GHN ạ."},
            max_attempts=8)
    return op2


# ------------------------------------------------------------------ provider cfg (resolve LUC GUI, khong luu)
async def _create_cfg(conn, op) -> tuple[dict | None, str]:
    from app.services.providers import ghn as _ghn
    from app.services.settings import integrations as _S
    mode = str(settings.ghn_active_mode or "").strip()
    if mode != op["mode"]:
        return None, "mode_changed"
    integ = await _integration(conn, mode)
    if integ is None or integ["id"] != op["integration_id"] or integ["config_revision"] != op["config_revision"]:
        return None, "config_changed"
    try:
        lc = await _S.load_active_config(conn, "ghn", mode)
    except Exception:  # noqa: BLE001
        return None, "config_load_error"
    if lc.get("source") != "database":
        return None, "config_not_database"
    cp = lc.get("config") or {}
    base = (cp.get("base_url") or "").rstrip("/")
    token = (lc.get("secrets") or {}).get("token") or ""
    if base != _ghn.BASE_BY_MODE[mode] or not token or not cp.get("shop_id"):
        return None, "ghn_not_configured"
    return {"base": base, "token": token, "shop_id": str(cp.get("shop_id")),
            "timeout": float(cp.get("timeout_seconds") or 8.0)}, ""


# ------------------------------------------------------------------ worker
async def run_dispatch_once(*, provider_factory=None, limit: int = 10, op_ids: list[int] | None = None) -> dict:
    """Cron: xu ly operation den han. provider_factory(cfg) -> provider (injectable test). op_ids: gioi han tap
    operation (test/van hanh co pham vi). Tra thong ke."""
    from app.db_pool import acquire, release
    stats = {"picked": 0, "gate_blocked": 0, "created": 0, "retryable": 0, "rejected": 0, "unknown": 0,
             "cancelled": 0, "terminal": 0, "http_calls": 0}
    conn = await acquire()
    try:
        ids = [r["id"] for r in await conn.fetch(
            "SELECT id FROM ghn_shipment_create_operations WHERE (state='prepared' "
            "OR (state='failed_retryable' AND (next_attempt_at IS NULL OR next_attempt_at <= now())) "
            "OR (state='dispatching' AND lease_expires_at < now())) AND ($2::bigint[] IS NULL OR id = ANY($2)) "
            "ORDER BY id LIMIT $1", limit, op_ids)]
        for op_id in ids:
            stats["picked"] += 1
            try:
                await _dispatch_one(conn, op_id, provider_factory=provider_factory, stats=stats)
            except Exception as e:  # noqa: BLE001 — 1 operation loi khong chan operation khac
                from app.services.safe_log import safe_exc
                print(f"[ghn_create] op {op_id} loi: {safe_exc(e)}")
    finally:
        await release(conn)
    return stats


async def _dispatch_one(conn, op_id: int, *, provider_factory, stats: dict) -> None:
    from app.services.providers.ghn_create import GhnCreateProvider
    owner = uuid.uuid4().hex
    async with conn.transaction():
        oid = await conn.fetchval("SELECT order_id FROM ghn_shipment_create_operations WHERE id=$1", op_id)
        ostatus = await conn.fetchval("SELECT status FROM orders WHERE id=$1 FOR UPDATE", oid)   # lock order TRUOC
        op = dict(await conn.fetchrow("SELECT * FROM ghn_shipment_create_operations WHERE id=$1 FOR UPDATE", op_id))
        if op["state"] == DISPATCHING:
            if op["lease_expires_at"] and op["lease_expires_at"] >= datetime.now(timezone.utc):
                return
            # worker chet giua chung: request CO THE da toi GHN -> KHONG gui lai, bat buoc doi soat
            op2 = await _set_state(conn, op, UNKNOWN, lease_owner=None, lease_expires_at=None,
                                   last_error_class="lease_expired")
            await conn.execute(
                "INSERT INTO ghn_shipment_create_attempts (operation_id, attempt_no, kind, outcome, error_class, actor) "
                "VALUES ($1,$2,'create','lease_expired','lease_expired','worker:ghn_create') "
                "ON CONFLICT DO NOTHING", op_id, max(op["attempt_count"], 1))
            await _open_attention(conn, op2, "lease_expired_unknown")
            await _audit(conn, op2, "shipment.ghn_create.unknown", {"why": "lease_expired"})
            stats["unknown"] += 1
            return
        if op["state"] not in PRE_DISPATCH_STATES:
            return
        if not gate_enabled(op["source"]):
            if op["gate_blocked_reason"] != "gate_off":
                op2 = await _set_state(conn, op, op["state"], gate_blocked_reason="gate_off")
                await _audit(conn, op2, "shipment.ghn_create.gate_blocked", {"gate": f"ghn_shipment_create_{op['source']}"
                                                                              "_enabled", "http_call": False})
            stats["gate_blocked"] += 1
            return
        if ostatus in ("cancelled", "cancelled_by_exception"):
            op2 = await _set_state(conn, op, CANCELLED_BEFORE, terminal_reason="order_cancelled")
            await _audit(conn, op2, "shipment.ghn_create.cancelled_before_dispatch", {"why": "order_cancelled"})
            stats["cancelled"] += 1
            return
        if op["attempt_count"] >= op["max_attempts"]:
            op2 = await _set_state(conn, op, FAILED_TERMINAL, terminal_reason="max_attempts")
            await _open_attention(conn, op2, "max_attempts")
            await _audit(conn, op2, "shipment.ghn_create.failed_terminal", {"why": "max_attempts"})
            stats["terminal"] += 1
            return
        ev = await evaluate(conn, op["order_id"], source=op["source"], exclude_op_id=op_id)
        if not ev["eligible"] or ev["fingerprint"] != op["request_fingerprint"]:
            why = "revalidation_blocked" if not ev["eligible"] else "snapshot_changed"
            op2 = await _set_state(conn, op, FAILED_TERMINAL, terminal_reason=why)
            await _open_attention(conn, op2, why, {"blockers": ev["blockers"][:8]})
            await _audit(conn, op2, "shipment.ghn_create.failed_terminal", {"why": why, "blockers": ev["blockers"][:8]})
            stats["terminal"] += 1
            return
        cfg, cfg_err = await _create_cfg(conn, op)
        if cfg is None:
            op2 = await _set_state(conn, op, FAILED_TERMINAL, terminal_reason=cfg_err)
            await _open_attention(conn, op2, cfg_err)
            await _audit(conn, op2, "shipment.ghn_create.failed_terminal", {"why": cfg_err})
            stats["terminal"] += 1
            return
        needs_reconcile = op["state"] == FAILED_RETRYABLE
        attempt_no = op["attempt_count"] + 1
        op = await _set_state(conn, op, DISPATCHING, lease_owner=owner, attempt_count=attempt_no,
                              lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=POLICY["lease_s"]),
                              dispatched_at=op["dispatched_at"] or datetime.now(timezone.utc), gate_blocked_reason=None)
    # ---------------- NGOAI transaction: HTTP ----------------
    provider = provider_factory(cfg) if provider_factory else GhnCreateProvider(cfg)
    snapshot = op["request_snapshot"]
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    lookup = None
    if needs_reconcile:
        stats["http_calls"] += 1
        try:
            lookup = await provider.lookup(op["client_order_code"])
        except Exception:  # noqa: BLE001
            from app.services.providers.ghn_create import UNKNOWN as _U
            from app.services.providers.ghn_create import ProviderOutcome
            lookup = ProviderOutcome(_U, error_class="lookup_exception")
    res = None
    if lookup is None or lookup.outcome == "not_found":
        stats["http_calls"] += 1
        try:
            res = await provider.create(snapshot, op["client_order_code"])
        except Exception:  # noqa: BLE001 — khong ro request da toi GHN chua -> unknown
            from app.services.providers.ghn_create import UNKNOWN as _U
            from app.services.providers.ghn_create import ProviderOutcome
            res = ProviderOutcome(_U, error_class="create_exception")
    await _record_outcome(conn, op_id, owner, attempt_no, lookup, res, stats)


async def _record_outcome(conn, op_id: int, owner: str, attempt_no: int, lookup, res, stats: dict) -> None:
    async with conn.transaction():
        oid = await conn.fetchval("SELECT order_id FROM ghn_shipment_create_operations WHERE id=$1", op_id)
        await conn.execute("SELECT 1 FROM orders WHERE id=$1 FOR UPDATE", oid)
        op = dict(await conn.fetchrow("SELECT * FROM ghn_shipment_create_operations WHERE id=$1 FOR UPDATE", op_id))
        if op["state"] != DISPATCHING or op["lease_owner"] != owner:
            print(f"[ghn_create] op {op_id} mat quyen so huu truoc khi ghi ket qua — bo qua (doi soat sau)")
            return
        actor = "worker:ghn_create"
        if lookup is not None:
            await _attempt(conn, op_id, attempt_no, "reconcile", lookup, actor=actor)
            if lookup.outcome == "found":
                await _succeed(conn, op, lookup, actor=actor)
                stats["created"] += 1
                return
            if lookup.outcome != "not_found":
                op2 = await _set_state(conn, op, UNKNOWN, lease_owner=None, lease_expires_at=None,
                                       last_error_class=lookup.error_class or "reconcile_unknown",
                                       last_http_status=lookup.http_status)
                await _open_attention(conn, op2, "reconcile_unknown")
                await _audit(conn, op2, "shipment.ghn_create.unknown", {"why": "reconcile_unknown"})
                stats["unknown"] += 1
                return
        await _attempt(conn, op_id, attempt_no, "create", res, actor=actor)
        if res.outcome == "created":
            await _succeed(conn, op, res, actor=actor)
            stats["created"] += 1
        elif res.outcome == "rejected":
            op2 = await _set_state(conn, op, FAILED_TERMINAL, terminal_reason=res.error_class, lease_owner=None,
                                   lease_expires_at=None, last_error_class=res.error_class,
                                   last_http_status=res.http_status)
            await _open_attention(conn, op2, "provider_rejected", {"error_class": res.error_class})
            await _audit(conn, op2, "shipment.ghn_create.failed_terminal", {"why": "provider_rejected",
                                                                             "error_class": res.error_class})
            stats["rejected"] += 1
        elif res.outcome == "retryable":
            if attempt_no >= op["max_attempts"]:
                op2 = await _set_state(conn, op, FAILED_TERMINAL, terminal_reason="max_attempts", lease_owner=None,
                                       lease_expires_at=None, last_error_class=res.error_class,
                                       last_http_status=res.http_status)
                await _open_attention(conn, op2, "max_attempts", {"error_class": res.error_class})
                await _audit(conn, op2, "shipment.ghn_create.failed_terminal", {"why": "max_attempts"})
                stats["terminal"] += 1
                return
            bo = POLICY["backoff_s"]
            delay = max(bo[min(attempt_no - 1, len(bo) - 1)], int(res.retry_after_s or 0))
            op2 = await _set_state(conn, op, FAILED_RETRYABLE, lease_owner=None, lease_expires_at=None,
                                   next_attempt_at=datetime.now(timezone.utc) + timedelta(seconds=delay),
                                   last_error_class=res.error_class, last_http_status=res.http_status)
            await _audit(conn, op2, "shipment.ghn_create.retry_scheduled",
                         {"error_class": res.error_class, "delay_s": delay, "retry_after_s": res.retry_after_s})
            stats["retryable"] += 1
        else:  # unknown -> KHONG blind retry
            op2 = await _set_state(conn, op, UNKNOWN, lease_owner=None, lease_expires_at=None,
                                   last_error_class=res.error_class, last_http_status=res.http_status)
            await _open_attention(conn, op2, "create_unknown", {"error_class": res.error_class})
            await _audit(conn, op2, "shipment.ghn_create.unknown", {"why": "create_unknown",
                                                                     "error_class": res.error_class})
            stats["unknown"] += 1


# ------------------------------------------------------------------ staff actions
async def reconcile(conn, op_id: int, *, staff_id: int, actor: str, provider_factory=None) -> dict:
    """Staff doi soat (read-only lookup theo client_order_code). Gate Dashboard OFF -> chan truoc HTTP."""
    from app.services.providers.ghn_create import GhnCreateProvider
    if not settings.ghn_shipment_create_dashboard_enabled:
        raise ShipmentCreateError("gate_off", "Gate tao van don GHN (dashboard) dang tat — khong goi provider", 409)
    async with conn.transaction():
        op = await conn.fetchrow("SELECT * FROM ghn_shipment_create_operations WHERE id=$1 FOR UPDATE", op_id)
        if op is None:
            raise ShipmentCreateError("not_found", "operation khong ton tai", 404)
        if op["state"] not in (UNKNOWN, FAILED_RETRYABLE):
            raise ShipmentCreateError("state_invalid", f"khong doi soat duoc o trang thai {op['state']}", 409)
        cfg, err = await _create_cfg(conn, op)
        if cfg is None:
            raise ShipmentCreateError(err, "cau hinh GHN khong con khop snapshot", 409)
    provider = provider_factory(cfg) if provider_factory else GhnCreateProvider(cfg)
    try:
        lk = await provider.lookup(op["client_order_code"])
    except Exception:  # noqa: BLE001
        from app.services.providers.ghn_create import ProviderOutcome
        lk = ProviderOutcome("unknown", error_class="lookup_exception")
    async with conn.transaction():
        await conn.execute("SELECT 1 FROM orders WHERE id=$1 FOR UPDATE", op["order_id"])
        op = dict(await conn.fetchrow("SELECT * FROM ghn_shipment_create_operations WHERE id=$1 FOR UPDATE", op_id))
        if op["state"] not in (UNKNOWN, FAILED_RETRYABLE):
            return {"operation": _op_view(op), "lookup": lk.outcome, "changed": False}
        n = await conn.fetchval("SELECT count(*) FROM ghn_shipment_create_attempts WHERE operation_id=$1 "
                                "AND kind='reconcile'", op_id)
        await _attempt(conn, op_id, int(n) + 1, "reconcile", lk, actor=actor)
        if lk.outcome == "found":
            op2 = await _succeed(conn, op, lk, actor=actor)
        elif lk.outcome == "not_found":
            # GHN noi ro KHONG co van don -> cho phep dispatch lai (worker se doi soat lan nua truoc create)
            op2 = await _set_state(conn, op, FAILED_RETRYABLE, next_attempt_at=datetime.now(timezone.utc),
                                   last_error_class="reconciled_not_found")
            await _audit(conn, op2, "shipment.ghn_create.reconciled_not_found", {"staff_id": staff_id}, actor=actor)
        else:
            op2 = op
        if lk.outcome in ("found", "not_found"):
            for a in await conn.fetch("SELECT id FROM staff_attention WHERE order_id=$1 AND status='open' "
                                      "AND reason=$2", op["order_id"], ATTENTION_REASON):
                from app.services.fulfillment import attention as _att
                await _att.resolve(conn, a["id"], resolved_by=actor, note=f"doi soat GHN: {lk.outcome}")
    return {"operation": _op_view(op2), "lookup": lk.outcome, "changed": lk.outcome in ("found", "not_found")}


async def abandon(conn, op_id: int, *, staff_id: int, actor: str, note: str) -> dict:
    """Staff dung operation: truoc dispatch -> cancelled_before_dispatch; unknown -> failed_terminal (staff da
    kiem tra tren GHN khong co van don). KHONG goi provider. Ghi chu bat buoc."""
    if not note or not note.strip() or len(note.strip()) > 500:
        raise ShipmentCreateError("note_required", "ghi chu bat buoc (1-500 ky tu)", 422)
    await conn.execute("SELECT 1 FROM orders WHERE id=(SELECT order_id FROM ghn_shipment_create_operations "
                       "WHERE id=$1) FOR UPDATE", op_id)
    op = await conn.fetchrow("SELECT * FROM ghn_shipment_create_operations WHERE id=$1 FOR UPDATE", op_id)
    if op is None:
        raise ShipmentCreateError("not_found", "operation khong ton tai", 404)
    op = dict(op)
    if op["state"] in PRE_DISPATCH_STATES:
        to = CANCELLED_BEFORE
    elif op["state"] == UNKNOWN:
        to = FAILED_TERMINAL
    else:
        raise ShipmentCreateError("state_invalid", f"khong dung duoc o trang thai {op['state']}", 409)
    op2 = await _set_state(conn, op, to, terminal_reason=f"staff_abandon: {note.strip()[:200]}", lease_owner=None,
                           lease_expires_at=None)
    await audit_service.record(conn, "staff", "shipment.ghn_create.abandon", actor_ref=actor, actor_staff_id=staff_id,
                               entity_type="ghn_shipment_create_operations", entity_id=str(op_id),
                               after={"order_id": op["order_id"], "from": op["state"], "to": to}, reason=note.strip())
    return {"operation": _op_view(op2)}


async def list_for_order(conn, order_id: int) -> list[dict]:
    ops = []
    for op in await conn.fetch("SELECT * FROM ghn_shipment_create_operations WHERE order_id=$1 ORDER BY id DESC",
                               order_id):
        v = _op_view(op)
        v["attempts"] = [
            {k: (x[k].isoformat() if isinstance(x[k], datetime) else x[k]) for k in
             ("attempt_no", "kind", "outcome", "http_status", "error_class", "retry_after_s", "duration_ms", "actor",
              "created_at")}
            for x in await conn.fetch("SELECT * FROM ghn_shipment_create_attempts WHERE operation_id=$1 "
                                      "ORDER BY id", op["id"])]
        ops.append(v)
    return ops


# ------------------------------------------------------------------ huy don (goi tu cancel_cascade)
async def on_order_cancel(conn, order_id: int, *, reason: str, actor: str, can_exception: bool) -> dict | None:
    """Trong transaction huy (order da FOR UPDATE). Truoc dispatch -> cancelled_before_dispatch (khong HTTP).
    Da dispatch/succeeded/unknown -> KHONG gia vo huy GHN: huy thuong bi chan (CancelBlocked) tru order.cancel.exception
    (khi do giu nguyen operation, caller mo attention order_cancel_exception)."""
    from app.services.fulfillment.cancel_cascade import CancelBlocked
    op = await conn.fetchrow("SELECT * FROM ghn_shipment_create_operations WHERE order_id=$1 "
                             "AND state = ANY($2::text[]) FOR UPDATE", order_id, list(ACTIVE_STATES))
    if op is None:
        return None
    op = dict(op)
    if op["state"] in PRE_DISPATCH_STATES:
        op2 = await _set_state(conn, op, CANCELLED_BEFORE, terminal_reason=f"order_cancelled: {reason[:200]}",
                               lease_owner=None, lease_expires_at=None)
        await _audit(conn, op2, "shipment.ghn_create.cancelled_before_dispatch", {"why": "order_cancelled"},
                     actor=actor)
        return {"operation_id": op["id"], "from": op["state"], "to": CANCELLED_BEFORE}
    if not can_exception:
        raise CancelBlocked("ghn_shipment_dispatched",
                            f"Van don GHN da gui/tao ({op['state']}) — can quyen order.cancel.exception", 409)
    return {"operation_id": op["id"], "from": op["state"], "to": op["state"], "kept": "provider_state_kept"}
