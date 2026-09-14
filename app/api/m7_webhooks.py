"""M7-C0 provider webhook — SePay TEST MODE (CA Directive 272 §3.5). Xac thuc -> ghi ben vung -> tra nhanh; xu ly domain
o worker (provider_ingest.run_once). Flag m7_sepay_test_connector TAT -> 404 (endpoint khong ton tai). Live KHONG mo
(sepay_live_enabled la gate FINANCIAL rieng C1 — neu bat trong candidate nay van bi tu choi 503).
"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.services.payment import provider_ingest
from app.services.providers import sepay

router = APIRouter(prefix="/webhooks", tags=["m7-webhooks"])
MAX_BODY = 64 * 1024


@router.post("/sepay")
async def sepay_webhook(request: Request, authorization: str | None = Header(default=None)) -> dict:
    if not settings.m7_sepay_test_connector:
        raise HTTPException(status_code=404, detail="not found")
    if settings.sepay_live_enabled:
        # C1 chua duoc CA qualify/PO apply: fail-closed, khong nhan tin hieu live trong candidate nay.
        raise HTTPException(status_code=503, detail="sepay live mode not authorized (C1 gate)")
    if not sepay.verify_test_auth(authorization, settings.sepay_test_api_key):
        raise HTTPException(status_code=403, detail="invalid webhook auth")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(status_code=413, detail="payload too large")
    try:
        ev = sepay.parse_envelope(raw)
    except sepay.SepayError as e:
        raise HTTPException(status_code=400, detail=str(e))
    conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
    try:
        async with conn.transaction():
            row_id, created, conflict = await provider_ingest.ingest(conn, ev, mode="test")
    finally:
        await conn.close()
    # CA 274-01: cung event ID khac payload -> conflict (fail-closed, da ghi last_error cho staff).
    return {"success": True, "event_id": row_id, "duplicate": not created, "conflict": conflict}
