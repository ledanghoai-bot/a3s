"""M7 Conversational Fulfillment dashboard API (CA Directive 272 §4). Bo sung cho /dashboard/fulfillment (M6):
hoi thoai/step + timeout/reminder, route source + quote snapshot, QR/instruction preview tu snapshot, hang doi
staff_attention (resolve co RBAC/audit), provider events (SePay test) + quote log, retry route-quote (2 pha: GHN goi
NGOAI tx), resume hoi thoai sau khi staff xu ly. KHONG auto-refund/outgoing/shipment creation.
"""
from __future__ import annotations

import json

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import require_active_session, require_permission
from app.config import settings
from app.services.fulfillment import attention as att
from app.services.fulfillment import conversation as fc
from app.services.fulfillment import route_operation as rops
from app.services.fulfillment import shipment_service as ship
from app.services.payment import payment_service as pay
from app.services.payment import vietqr as vq

router = APIRouter(prefix="/dashboard/fulfillment", tags=["m7-fulfillment"],
                   dependencies=[Depends(require_active_session)])


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _actor(staff: dict) -> str:
    return staff.get("username") or f"staff:{staff.get('id')}"


def _map_err(e: Exception) -> HTTPException:
    msg = str(e)
    return HTTPException(status_code=409 if "version conflict" in msg else 400, detail=msg)


def _jsonb(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:  # noqa: BLE001
            return v
    return v


# ============================ Attention queue ============================
@router.get("/attention")
async def attention_list(limit: int = 200) -> list[dict]:
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await att.list_open(conn, limit=limit)
        for r in rows:
            r["detail"] = _jsonb(r.get("detail"))
        return rows
    finally:
        await conn.close()


@router.post("/attention/{attention_id}/resolve")
async def attention_resolve(attention_id: int, body: dict,
                            staff: dict = Depends(require_permission("fulfillment.attention_resolve"))) -> dict:
    note = body.get("note")
    if not isinstance(note, str) or not note.strip():
        raise HTTPException(status_code=422, detail="thieu note (ly do/ket qua xu ly)")
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            row = await att.resolve(conn, attention_id, resolved_by=_actor(staff), note=note)
        if row is None:
            raise HTTPException(status_code=404, detail="attention khong ton tai hoac da resolved")
        row["detail"] = _jsonb(row.get("detail"))
        return row
    finally:
        await conn.close()


# ============================ Conversation detail / resume ============================
@router.get("/orders/{order_id}/conversation")
async def conversation_detail(order_id: int) -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        c = await fc.get(conn, order_id)
        events = [dict(r) for r in await conn.fetch(
            "SELECT id, command_key, source, from_step, to_step, detail, reply_text, created_at "
            "FROM fulfillment_conversation_events WHERE order_id=$1 ORDER BY id", order_id)]
        for e in events:
            e["detail"] = _jsonb(e.get("detail"))
        sh = await conn.fetchrow(
            "SELECT routing_source, routing_version, routing_province_code, routing_ward_code, routing_reason, "
            "routed_at, quote_provider, quote_snapshot, quoted_at, fee_status, delivery_fee_vnd, eta_text, version "
            "FROM shipments WHERE order_id=$1", order_id)
        shd = dict(sh) if sh else None
        if shd:
            shd["quote_snapshot"] = _jsonb(shd.get("quote_snapshot"))
        instr = await conn.fetchrow(
            "SELECT id, bank_snapshot, account_number_snapshot, holder_snapshot, transfer_content, amount_vnd, is_test, "
            "bin_snapshot, qr_payload, qr_version, instruction_version, created_at FROM payment_instructions "
            "WHERE order_id=$1 ORDER BY id DESC LIMIT 1", order_id)
        instr_d = dict(instr) if instr else None
        if instr_d and instr_d.get("qr_payload"):
            instr_d["qr_svg_data_uri"] = vq.svg_data_uri(instr_d["qr_payload"])
            try:
                d = vq.decode(instr_d["qr_payload"])
                instr_d["qr_decoded"] = {"bin": d.bin_code, "account": d.account_number, "amount_vnd": d.amount_vnd,
                                         "content": d.add_info, "crc_ok": d.crc_ok}
            except vq.VietQRError as e:
                instr_d["qr_decoded"] = {"error": str(e)}
        attn = [dict(r) for r in await conn.fetch(
            "SELECT id, reason, detail, status, created_at, resolved_at, resolved_by, resolution_note "
            "FROM staff_attention WHERE order_id=$1 ORDER BY id", order_id)]
        for a in attn:
            a["detail"] = _jsonb(a.get("detail"))
        pev = [dict(r) for r in await conn.fetch(
            "SELECT id, provider, provider_event_id, mode, processing_state, match_reason, received_at, processed_at, "
            "payment_event_id FROM provider_events WHERE order_id=$1 ORDER BY id", order_id)]
        qlog = [dict(r) for r in await conn.fetch(
            "SELECT id, provider, status, http_status, duration_ms, request_fingerprint, created_at "
            "FROM provider_quote_log WHERE order_id=$1 ORDER BY id DESC LIMIT 10", order_id)]
        return {"conversation": c, "events": events, "routing": shd, "instruction": instr_d, "attention": attn,
                "provider_events": pev, "quote_log": qlog,
                "flags": {"conversational": settings.m7_conversational_fulfillment, "ghn": settings.m7_ghn_quote,
                          "sepay_test": settings.m7_sepay_test_connector}}
    finally:
        await conn.close()


@router.post("/orders/{order_id}/shipment/route-quote")
async def route_quote(order_id: int, body: dict | None = None,
                      staff: dict = Depends(require_permission("shipment.manage"))) -> dict:
    """Retry dinh tuyen + bao phi (2 pha: GHN HTTP NGOAI tx). Khong doi hoi thoai; staff resume rieng.
    CA 276-01: SERVER-SIDE idempotency BAT BUOC. `body.command_key` (non-empty) -> receipt ben vung
    `fulfillment_route_operations`: request dau claim ATOMIC truoc khi goi GHN; double-click/retry/dong thoi cung key
    -> in_flight/replay (GHN goi DUNG 1 lan, apply 1 lan); cung key khac payload -> conflict (409); crash-recovery qua
    lease + provider_result da ghi (retry KHONG goi GHN lan hai). Self/manual deterministic khong goi GHN."""
    ck = (body or {}).get("command_key")
    if not isinstance(ck, str) or not ck.strip():
        raise HTTPException(status_code=422, detail="thieu command_key (idempotency key tu client)")
    conn = await asyncpg.connect(_db_url())
    try:
        out = await rops.execute(conn, order_id, actor=_actor(staff), command_key=ck.strip())
        row = dict(out["shipment"]) if out.get("shipment") else {}
        if "quote_snapshot" in row:
            row["quote_snapshot"] = _jsonb(row.get("quote_snapshot"))
        row["duplicate"] = out["duplicate"]
        row["op_state"] = out["op_state"]
        return row
    except rops.RouteOpConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except rops.RouteOpInFlight as e:
        raise HTTPException(status_code=409, detail=str(e))
    except rops.RouteOpAmbiguous as e:
        # CA 277-01: provider ket qua khong chac chan -> da chuyen staff, KHONG tu goi lai (at-most-once).
        raise HTTPException(status_code=409, detail=str(e))
    except ship.ShipmentError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/orders/{order_id}/conversation/resume")
async def conversation_resume(order_id: int, staff: dict = Depends(require_permission("shipment.manage"))) -> dict:
    """Sau khi staff xu ly (phi/dia chi/tai khoan): dua hoi thoai staff_attention -> routing de worker gui lai tong tien
    (dung quote hien tai; quote thu cong duoc giu nguyen)."""
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            out = await fc.resume(conn, order_id, actor=_actor(staff))
        if out is None:
            raise HTTPException(status_code=400, detail="hoi thoai khong o staff_attention hoac khong ton tai")
        return out
    except fc.AttentionOpenError as e:
        # CA 275-04: con open attention -> phai Resolve truoc khi Resume (fail-closed).
        raise HTTPException(status_code=409, detail=str(e))
    finally:
        await conn.close()


@router.post("/orders/{order_id}/payment/instruction-qr")
async def instruction_qr(order_id: int, body: dict, staff: dict = Depends(require_active_session)) -> dict:
    """Tao/tra instruction bat bien co VietQR (command_key idempotent; regenerate = command_key moi -> version moi)."""
    ck = body.get("command_key")
    if not isinstance(ck, str) or not ck.strip():
        raise HTTPException(status_code=422, detail="thieu command_key (idempotency key tu client)")
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            row = await pay.generate_instruction(conn, order_id, actor=_actor(staff), command_key=ck.strip())
        if row.get("qr_payload"):
            row["qr_svg_data_uri"] = vq.svg_data_uri(row["qr_payload"])
        return row
    except pay.PaymentError as e:
        raise _map_err(e)
    finally:
        await conn.close()


# ============================ Provider events / routing config ============================
@router.get("/provider-events")
async def provider_events(limit: int = 100, state: str | None = None,
                          staff: dict = Depends(require_permission("provider.events_view"))) -> list[dict]:
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            "SELECT id, provider, provider_event_id, mode, processing_state, match_reason, order_id, payment_id, "
            "payment_event_id, received_at, processed_at, attempts, last_error, "
            "raw->>'transferAmount' AS amount, raw->>'content' AS content, raw->>'transferType' AS direction "
            "FROM provider_events WHERE ($1::text IS NULL OR processing_state=$1) ORDER BY id DESC LIMIT $2",
            state, limit)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


@router.get("/routing/allowlist")
async def routing_allowlist() -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        vers = [dict(r) for r in await conn.fetch(
            "SELECT version, effective_from, effective_to, dataset_version, note, created_by FROM delivery_routing_versions "
            "ORDER BY version")]
        wards = [dict(r) for r in await conn.fetch(
            "SELECT routing_version, province_code, ward_code, ward_name, source_note FROM delivery_self_wards "
            "ORDER BY routing_version, ward_code")]
        from app.services.fulfillment import routing as _r
        return {"active_version": await _r.active_version(conn), "versions": vers, "wards": wards}
    finally:
        await conn.close()
