"""M7 route/quote server-side idempotency receipt (CA Review 276 blocker 276-01 + Review 277 blocker 277-01/02).

Endpoint route-quote goi GHN (HTTP) NGOAI transaction roi apply quote -> double-click/retry/dong thoi co the goi
GHN nhieu lan + apply nhieu lan. Receipt `fulfillment_route_operations` (migration 066+067) lam contract idempotency
AT-MOST-ONCE provider request:

  State machine: claimed -> provider_started -> provider_recorded -> done   (hoac -> failed)
  - `claim` (trong tx): request DAU claim ATOMIC (INSERT ON CONFLICT). Cung key/khac fingerprint -> conflict;
    da done -> replay (ket qua BAT BIEN da luu, 277-02); da failed -> replay_failed.
  - `mark_provider_started` (trong tx): OWNER ghi state BEN VUNG 'provider_started' + tag provider ('ghn'|'none')
    TRUOC khi goi HTTP (277-01). Chi 'claimed' (chua bat dau provider) moi duoc takeover-goi-provider.
  - `record_provider` (trong tx): OWNER ghi ket qua GHN (provider_started -> provider_recorded) => retry sau crash
    KHONG goi GHN lan hai.
  - `mark_done` (trong tx): OWNER apply xong -> done + luu result_payload BAT BIEN.

  Takeover khi lease HET HAN (owner presumed crashed):
  - 'claimed' -> owner (chua goi provider, an toan re-run).
  - 'provider_started' provider='ghn' -> AMBIGUOUS (provider CO THE da nhan request): KHONG tu goi lai, chuyen staff
    (mo attention reconciliation), receipt -> failed. Uu tien production stability + at-most-once.
  - 'provider_started' provider='none' (self/manual, khong goi external) -> an toan re-run (reset claimed, owner).
  - 'provider_recorded' -> recover_provider: apply KHONG goi provider lai.
  Con lease -> in_flight (owner dang lam). HTTP keo dai qua lease KHONG tao owner thu hai goi provider (provider_started
  khong takeover-goi-provider).

GHN HTTP luon NGOAI transaction. `execute` = orchestration cho endpoint (lazy-import de tranh circular); provider
injectable cho test dem so lan goi GHN.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

ACTION = "route_quote"
DEFAULT_LEASE_SECONDS = 60


class RouteOpConflict(Exception):
    """Cung command_key nhung fingerprint khac (payload khac) — fail-closed, khong tra nham ket qua cu."""


class RouteOpInFlight(Exception):
    """Thao tac cung command_key dang xu ly (chua terminal) — client thu lai sau; KHONG goi provider lan hai."""


class RouteOpAmbiguous(Exception):
    """CA 277-01: provider da bat dau nhung ket qua KHONG chac chan (crash/lease-timeout giua chung). KHONG tu goi
    lai provider (at-most-once) — da chuyen staff reconcile. Retry cung key tra lai trang thai nay (idempotent)."""


def fingerprint(order_id: int, action: str = ACTION) -> str:
    """CA 276-01: fingerprint on-dinh cua payload logic (order_id + action). Cung command_key khac payload -> conflict."""
    raw = f"{action}|{order_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_owner_token() -> str:
    return uuid.uuid4().hex


def _serialize_row(row: dict) -> dict:
    """Ket qua command BAT BIEN, JSON-safe (datetime -> iso, jsonb -> dict). Luu result_payload + replay (277-02)."""
    out: dict = {}
    for k, v in dict(row).items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif k == "quote_snapshot" and isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except (ValueError, TypeError):
                out[k] = v
        else:
            out[k] = v
    return out


def _load_result(op: dict):
    """CA 277-02: replay tra CHINH XAC result_payload bat bien da luu (KHONG doc current shipment)."""
    rp = op.get("result_payload")
    if isinstance(rp, str):
        rp = json.loads(rp)
    return rp


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
    """Claim quyen thuc thi ATOMIC. Tra {kind, op}. kind: owner | recover_provider | ambiguous | replay |
    replay_failed | in_flight | conflict. Goi TRONG transaction cua caller (FOR UPDATE serialize takeover)."""
    row = await conn.fetchrow(
        "INSERT INTO fulfillment_route_operations (order_id, action, command_key, request_fingerprint, state, "
        "owner_token, lease_expires_at) VALUES ($1,$2,$3,$4,'claimed',$5, now() + make_interval(secs => $6)) "
        "ON CONFLICT (order_id, action, command_key) DO NOTHING RETURNING *",
        order_id, action, command_key, request_fingerprint, owner_token, lease_seconds)
    if row is not None:
        return {"kind": "owner", "op": dict(row)}
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
    if ex["lease_active"]:
        return {"kind": "in_flight", "op": dict(ex)}   # owner con lease -> dang lam viec

    # --- lease HET HAN: takeover theo state (owner presumed crashed) ---
    if st == "provider_started" and ex["provider"] == "ghn":
        # CA 277-01: provider GHN CO THE da nhan request -> AMBIGUOUS. KHONG tu goi lai; chuyen staff.
        upd = await conn.fetchrow(
            "UPDATE fulfillment_route_operations SET state='failed', error_code='provider_ambiguous', "
            "updated_at=now() WHERE id=$1 AND state='provider_started' RETURNING *", ex["id"])
        return {"kind": "ambiguous", "op": dict(upd) if upd else dict(ex)}
    if st == "provider_recorded":
        upd = await conn.fetchrow(
            "UPDATE fulfillment_route_operations SET owner_token=$2, lease_expires_at=now()+make_interval(secs => $3), "
            "attempts=attempts+1, updated_at=now() WHERE id=$1 RETURNING *", ex["id"], owner_token, lease_seconds)
        return {"kind": "recover_provider", "op": dict(upd)}
    # 'claimed' (chua goi provider) HOAC 'provider_started' provider='none' (self/manual, khong goi external) ->
    # an toan re-run: reset ve 'claimed', owner takeover.
    upd = await conn.fetchrow(
        "UPDATE fulfillment_route_operations SET state='claimed', owner_token=$2, "
        "lease_expires_at=now()+make_interval(secs => $3), attempts=attempts+1, updated_at=now() "
        "WHERE id=$1 RETURNING *", ex["id"], owner_token, lease_seconds)
    return {"kind": "owner", "op": dict(upd)}


async def mark_provider_started(conn, op_id: int, *, provider: str, expected_owner: str) -> dict | None:
    """OWNER ghi state BEN VUNG 'provider_started' + tag provider TRUOC khi goi HTTP (CA 277-01). None neu mat quyen."""
    row = await conn.fetchrow(
        "UPDATE fulfillment_route_operations SET state='provider_started', provider=$2, updated_at=now() "
        "WHERE id=$1 AND owner_token=$3 AND state='claimed' RETURNING *", op_id, provider, expected_owner)
    return dict(row) if row else None


async def record_provider(conn, op_id: int, *, provider_result: dict | None, expected_owner: str) -> dict | None:
    """OWNER ghi ket qua provider (provider_started -> provider_recorded). None neu mat quyen so huu."""
    row = await conn.fetchrow(
        "UPDATE fulfillment_route_operations SET state='provider_recorded', provider_result=$2::jsonb, "
        "updated_at=now() WHERE id=$1 AND owner_token=$3 AND state='provider_started' RETURNING *",
        op_id, json.dumps(provider_result) if provider_result is not None else None, expected_owner)
    return dict(row) if row else None


async def mark_done(conn, op_id: int, *, result_payload: dict, expected_owner: str) -> dict | None:
    """OWNER apply xong -> done + luu result_payload bat bien. None neu mat quyen so huu."""
    row = await conn.fetchrow(
        "UPDATE fulfillment_route_operations SET state='done', result_payload=$2::jsonb, updated_at=now() "
        "WHERE id=$1 AND owner_token=$3 AND state='provider_recorded' RETURNING *",
        op_id, json.dumps(result_payload), expected_owner)
    return dict(row) if row else None


async def mark_failed(conn, op_id: int, *, error_code: str, expected_owner: str) -> dict | None:
    row = await conn.fetchrow(
        "UPDATE fulfillment_route_operations SET state='failed', error_code=$2, updated_at=now() "
        "WHERE id=$1 AND owner_token=$3 AND state IN ('claimed','provider_started','provider_recorded') RETURNING *",
        op_id, error_code, expected_owner)
    return dict(row) if row else None


async def _open_ambiguous_attention(conn, order_id: int, command_key: str, actor: str) -> None:
    """CA 277-01: chuyen staff reconcile (idempotent). KHONG tu goi lai provider."""
    from app.services.fulfillment import attention as _att
    async with conn.transaction():
        await _att.open_attention(
            conn, order_id, reason="provider_error",
            detail={"reason": "route_quote_ambiguous", "command_key": command_key,
                    "note": "provider call ket qua khong chac chan (crash/lease-timeout) — reconcile thu cong, "
                            "KHONG tu goi lai (at-most-once)"},
            created_by=actor)


async def execute(conn, order_id: int, *, actor: str, command_key: str, provider=None,
                  lease_seconds: int = DEFAULT_LEASE_SECONDS) -> dict:
    """Orchestration cho endpoint route-quote. Tra {"shipment", "duplicate", "op_state", "kind"}.
    Raise RouteOpConflict / RouteOpInFlight / RouteOpAmbiguous / ShipmentError. `provider` injectable cho test."""
    from app.services.fulfillment import conversation as _fc
    from app.services.fulfillment import routing as _r
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
        # CA 277-02: tra CHINH XAC result_payload bat bien (KHONG doc current shipment).
        return {"shipment": _load_result(c["op"]), "duplicate": True, "op_state": "done", "kind": kind}
    if kind == "ambiguous":
        await _open_ambiguous_attention(conn, order_id, command_key, actor)
        raise RouteOpAmbiguous("route-quote khong chac chan (provider co the da nhan request) — da chuyen nhan vien "
                               "kiem tra, KHONG tu goi lai")
    if kind == "replay_failed":
        ec = c["op"].get("error_code")
        if ec == "provider_ambiguous":
            await _open_ambiguous_attention(conn, order_id, command_key, actor)
            raise RouteOpAmbiguous("route-quote khong chac chan — dang cho nhan vien kiem tra (KHONG tu goi lai)")
        raise _sh.ShipmentError(ec or "route_quote that bai truoc do")

    op = c["op"]
    owner = op["owner_token"]

    if kind == "recover_provider":
        ghn_res = _deserialize_quote(op.get("provider_result"))
    else:  # owner
        # Xac dinh co goi external provider khong (de tag provider_started -> phan biet ambiguous vs an toan re-run).
        route = await _r.resolve_for_order(conn, order_id)
        weight = await _sh._order_weight(conn, order_id)
        will_call_ghn = (route.source == _r.GHN and weight is not None)
        if will_call_ghn:
            # CA 341-01: prepare_ghn_quote KHONG goi provider khi thieu kich thuoc/x -> tag 'none' (khong phai ambiguous).
            from app.services.fulfillment import fallback_quote as _fb
            _req, _, _ = await _fb.build_ghn_request(conn, order_id, route, weight)
            will_call_ghn = _req is not None
        prov_tag = "ghn" if will_call_ghn else "none"
        # CA 277-01: ghi 'provider_started' BEN VUNG TRUOC khi goi HTTP.
        async with conn.transaction():
            ps = await mark_provider_started(conn, op["id"], provider=prov_tag, expected_owner=owner)
        if ps is None:
            raise RouteOpInFlight("thao tac bi request khac tiep quan (start) — thu lai sau")
        try:
            ghn_res = await _fc.prepare_ghn_quote(conn, order_id, provider=provider)
        except Exception as e:  # noqa: BLE001 — provider call raised -> ket qua khong chac chan -> AMBIGUOUS (at-most-once)
            async with conn.transaction():
                await mark_failed(conn, op["id"], error_code="provider_ambiguous", expected_owner=owner)
            await _open_ambiguous_attention(conn, order_id, command_key, actor)
            raise RouteOpAmbiguous(f"loi/khong chac chan khi goi provider quote ({e}) — da chuyen nhan vien, "
                                   "KHONG tu goi lai") from e
        async with conn.transaction():
            rec = await record_provider(conn, op["id"],
                                        provider_result=(ghn_res.snapshot() if ghn_res is not None else None),
                                        expected_owner=owner)
        if rec is None:
            raise RouteOpInFlight("thao tac bi request khac tiep quan (record) — thu lai sau")

    async with conn.transaction():
        row = await _sh.route_and_quote(conn, order_id, actor=actor, ghn_result=ghn_res)
        done = await mark_done(conn, op["id"], result_payload=_serialize_row(row), expected_owner=owner)
    if done is None:
        raise RouteOpInFlight("thao tac bi request khac tiep quan (apply) — thu lai sau")
    return {"shipment": row, "duplicate": False, "op_state": "done", "kind": kind}
