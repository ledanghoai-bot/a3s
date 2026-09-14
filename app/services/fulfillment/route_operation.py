"""M7 route/quote server-side idempotency receipt (CA Review 276 blocker 276-01).

Endpoint route-quote goi GHN (HTTP) NGOAI transaction roi apply quote -> double-click/retry/dong thoi co the goi
GHN nhieu lan + apply nhieu lan. Receipt `fulfillment_route_operations` (migration 066) lam contract idempotency:

  - `claim` (trong tx): request DAU claim quyen thuc thi ATOMIC (INSERT ON CONFLICT). Cung key/cung payload dang
    xu ly -> in_flight; da xong -> replay; cung key/khac payload -> conflict. Lease het han -> takeover (crash recovery).
  - `record_provider` (trong tx): OWNER ghi ket qua GHN NGAY sau khi goi (state -> provider_recorded) => retry sau
    crash KHONG goi GHN lan hai (recover tu ket qua da ghi).
  - `mark_done` (trong tx): OWNER apply xong -> state done + luu result_payload de replay.

GHN HTTP luon NGOAI transaction (khong giu DB tx qua HTTP). Chi OWNER (owner_token) moi record/apply.
`execute` = orchestration day du cho endpoint (lazy-import conversation.prepare_ghn_quote + shipment_service.route_and_quote
de tranh circular import); provider injectable cho test dem so lan goi GHN.
"""
from __future__ import annotations

import hashlib
import json
import uuid

ACTION = "route_quote"
DEFAULT_LEASE_SECONDS = 60


class RouteOpConflict(Exception):
    """Cung command_key nhung fingerprint khac (payload khac) — fail-closed, khong tra nham ket qua cu."""


class RouteOpInFlight(Exception):
    """Thao tac cung command_key dang xu ly (chua terminal) — client thu lai sau; KHONG goi provider lan hai."""


def fingerprint(order_id: int, action: str = ACTION) -> str:
    """CA 276-01: fingerprint on-dinh cua payload logic (order_id + action). Cung command_key khac payload -> conflict."""
    raw = f"{action}|{order_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_owner_token() -> str:
    return uuid.uuid4().hex


def _compact(row: dict) -> dict:
    """Ket qua cuoi rut gon JSON-safe (khong datetime) de luu result_payload + replay/audit."""
    return {"shipment_id": row.get("id"), "order_id": row.get("order_id"),
            "routing_source": row.get("routing_source"), "routing_version": row.get("routing_version"),
            "fee_status": row.get("fee_status"), "delivery_fee_vnd": row.get("delivery_fee_vnd"),
            "quote_provider": row.get("quote_provider"), "version": row.get("version"),
            "attention_reason": row.get("attention_reason")}


def _deserialize_quote(snap):
    """Dung lai QuoteResult tu provider_result da luu (recover: apply KHONG goi GHN lai). None -> None (self/manual)."""
    if not snap:
        return None
    if isinstance(snap, str):  # asyncpg tra jsonb dang str
        snap = json.loads(snap)
    from app.services.providers.base import QuoteResult
    return QuoteResult(
        status=snap.get("status", "quote_required"), provider=snap.get("provider", "ghn"),
        reason=snap.get("reason", ""), fee_vnd=snap.get("fee_vnd"), breakdown=snap.get("breakdown") or {},
        leadtime_days=snap.get("leadtime_days"), eta_text=snap.get("eta_text"),
        provider_ref=snap.get("provider_ref"), request_fingerprint=snap.get("request_fingerprint", ""),
        service_id=snap.get("service_id"), service_type_id=snap.get("service_type_id"),
        carrier_ids=snap.get("carrier_ids") or {})


async def claim(conn, order_id: int, *, command_key: str, request_fingerprint: str, owner_token: str,
                action: str = ACTION, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> dict:
    """Claim quyen thuc thi ATOMIC. Tra {kind, op} voi kind:
       owner            -> request nay so huu (moi hoac takeover lease het han); goi provider + apply.
       recover_provider -> provider_result da ghi (owner cu crash sau khi goi GHN) -> apply KHONG goi GHN lai.
       replay           -> da done -> tra result_payload cu.
       replay_failed    -> da failed -> tra error_code cu.
       in_flight        -> owner khac dang xu ly (lease con hieu luc) -> thu lai sau.
       conflict         -> cung key khac fingerprint.
    Goi TRONG transaction cua caller."""
    row = await conn.fetchrow(
        "INSERT INTO fulfillment_route_operations (order_id, action, command_key, request_fingerprint, state, "
        "owner_token, lease_expires_at) VALUES ($1,$2,$3,$4,'claimed',$5, now() + make_interval(secs => $6)) "
        "ON CONFLICT (order_id, action, command_key) DO NOTHING RETURNING *",
        order_id, action, command_key, request_fingerprint, owner_token, lease_seconds)
    if row is not None:
        return {"kind": "owner", "op": dict(row)}
    # Da ton tai -> lock + kiem tra (lease_active tinh phia DB de tranh clock-skew).
    ex = await conn.fetchrow(
        "SELECT *, (lease_expires_at > now()) AS lease_active FROM fulfillment_route_operations "
        "WHERE order_id=$1 AND action=$2 AND command_key=$3 FOR UPDATE", order_id, action, command_key)
    if ex is None:  # race hiem: bi xoa giua chung -> coi nhu in_flight (an toan)
        return {"kind": "in_flight", "op": None}
    if ex["request_fingerprint"] != request_fingerprint:
        return {"kind": "conflict", "op": dict(ex)}
    st = ex["state"]
    if st == "done":
        return {"kind": "replay", "op": dict(ex)}
    if st == "failed":
        return {"kind": "replay_failed", "op": dict(ex)}
    # provider_recorded/claimed: chi TAKEOVER khi lease HET HAN (owner cu presumed crashed). Con lease -> in_flight
    # (owner dang lam viec) — tranh hai request cung apply gay version conflict + receipt ket ngang provider_recorded.
    if ex["lease_active"]:
        return {"kind": "in_flight", "op": dict(ex)}
    upd = await conn.fetchrow(
        "UPDATE fulfillment_route_operations SET owner_token=$2, lease_expires_at=now()+make_interval(secs => $3), "
        "attempts=attempts+1, updated_at=now() WHERE id=$1 RETURNING *", ex["id"], owner_token, lease_seconds)
    return {"kind": "recover_provider" if st == "provider_recorded" else "owner", "op": dict(upd)}


async def record_provider(conn, op_id: int, *, provider: str | None, provider_result: dict | None,
                          expected_owner: str) -> dict | None:
    """OWNER ghi ket qua provider (claimed -> provider_recorded). Tra None neu mat quyen so huu (owner khac takeover)."""
    row = await conn.fetchrow(
        "UPDATE fulfillment_route_operations SET state='provider_recorded', provider=$2, provider_result=$3::jsonb, "
        "updated_at=now() WHERE id=$1 AND owner_token=$4 AND state='claimed' RETURNING *",
        op_id, provider, json.dumps(provider_result) if provider_result is not None else None, expected_owner)
    return dict(row) if row else None


async def mark_done(conn, op_id: int, *, result_payload: dict, expected_owner: str) -> dict | None:
    """OWNER apply xong -> done + luu result_payload. Tra None neu mat quyen so huu."""
    row = await conn.fetchrow(
        "UPDATE fulfillment_route_operations SET state='done', result_payload=$2::jsonb, updated_at=now() "
        "WHERE id=$1 AND owner_token=$3 AND state IN ('claimed','provider_recorded') RETURNING *",
        op_id, json.dumps(result_payload), expected_owner)
    return dict(row) if row else None


async def mark_failed(conn, op_id: int, *, error_code: str, expected_owner: str) -> dict | None:
    row = await conn.fetchrow(
        "UPDATE fulfillment_route_operations SET state='failed', error_code=$2, updated_at=now() "
        "WHERE id=$1 AND owner_token=$3 AND state IN ('claimed','provider_recorded') RETURNING *",
        op_id, error_code, expected_owner)
    return dict(row) if row else None


async def execute(conn, order_id: int, *, actor: str, command_key: str, provider=None,
                  lease_seconds: int = DEFAULT_LEASE_SECONDS) -> dict:
    """Orchestration day du cho endpoint route-quote. Tra {"shipment", "duplicate", "op_state", "kind"}.
    Raise RouteOpConflict / RouteOpInFlight / ShipmentError. `provider` injectable de test dem so lan goi GHN.
    GHN HTTP luon NGOAI transaction; chi OWNER goi + apply; recover dung provider_result da ghi (KHONG goi GHN lai)."""
    from app.services.fulfillment import conversation as _fc
    from app.services.fulfillment import shipment_service as _sh

    if not isinstance(command_key, str) or not command_key.strip():
        raise _sh.ShipmentError("thieu command_key (idempotency)")
    command_key = command_key.strip()
    fp = fingerprint(order_id)
    owner = new_owner_token()

    async with conn.transaction():
        c = await claim(conn, order_id, command_key=command_key, request_fingerprint=fp, owner_token=owner,
                        lease_seconds=lease_seconds)
    kind = c["kind"]
    if kind == "conflict":
        raise RouteOpConflict("command_key da dung cho payload khac — tu choi (idempotency mismatch)")
    if kind == "in_flight":
        raise RouteOpInFlight("thao tac route-quote cung command_key dang xu ly — thu lai sau")
    if kind == "replay":
        row = await _sh.get_shipment(conn, order_id)
        return {"shipment": row, "duplicate": True, "op_state": "done", "kind": kind}
    if kind == "replay_failed":
        raise _sh.ShipmentError(c["op"].get("error_code") or "route_quote that bai truoc do")

    op = c["op"]
    owner = op["owner_token"]  # takeover/recover cap nhat owner_token -> dung dung token cua row

    if kind == "recover_provider":
        ghn_res = _deserialize_quote(op.get("provider_result"))
    else:  # owner -> goi GHN NGOAI tx
        try:
            ghn_res = await _fc.prepare_ghn_quote(conn, order_id, provider=provider)
        except Exception as e:  # noqa: BLE001 — loi provider khong duoc giu lease vinh vien
            async with conn.transaction():
                await mark_failed(conn, op["id"], error_code="provider_error", expected_owner=owner)
            raise _sh.ShipmentError(f"loi goi provider quote: {e}") from e
        prov_name = ghn_res.provider if ghn_res is not None else "none"
        async with conn.transaction():
            rec = await record_provider(conn, op["id"], provider=prov_name,
                                        provider_result=(ghn_res.snapshot() if ghn_res is not None else None),
                                        expected_owner=owner)
        if rec is None:
            raise RouteOpInFlight("thao tac bi request khac tiep quan (record) — thu lai sau")

    async with conn.transaction():
        row = await _sh.route_and_quote(conn, order_id, actor=actor, ghn_result=ghn_res)
        done = await mark_done(conn, op["id"], result_payload=_compact(row), expected_owner=owner)
    if done is None:
        raise RouteOpInFlight("thao tac bi request khac tiep quan (apply) — thu lai sau")
    return {"shipment": row, "duplicate": False, "op_state": "done", "kind": kind}
