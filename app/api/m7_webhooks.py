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
from app.services.settings import crypto as _settings_crypto
from app.services.settings import integrations as _settings

router = APIRouter(prefix="/webhooks", tags=["m7-webhooks"])
MAX_BODY = 64 * 1024


@router.post("/sepay")
async def sepay_webhook(request: Request, authorization: str | None = Header(default=None)) -> dict:
    # CA 316-01 §5: connector-OFF -> 404 TRUOC auth (khong cham DB/secret).
    if not settings.m7_sepay_test_connector:
        raise HTTPException(status_code=404, detail="not found")
    if settings.sepay_live_enabled:
        # C1 chua duoc CA qualify/PO apply: fail-closed, khong nhan tin hieu live trong candidate nay.
        raise HTTPException(status_code=503, detail="sepay live mode not authorized (C1 gate)")
    conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
    try:
        # CA 316-01: api_key theo PRECEDENCE loader D305 (DB authoritative khi module ON) — KHONG chi env.
        # Thieu secret/decrypt loi/no-record fail-closed -> reject 403 (khong leak plaintext/ciphertext).
        try:
            key = await _settings.resolve_sepay_test_key(conn)
        except (_settings.SettingsError, _settings_crypto.ConfigCryptoError):
            raise HTTPException(status_code=403, detail="invalid webhook auth")
        if not key or not sepay.verify_test_auth(authorization, key):
            raise HTTPException(status_code=403, detail="invalid webhook auth")
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise HTTPException(status_code=413, detail="payload too large")
        try:
            ev = sepay.parse_envelope(raw)
        except sepay.SepayError as e:
            raise HTTPException(status_code=400, detail=str(e))
        async with conn.transaction():
            row_id, created, conflict = await provider_ingest.ingest(conn, ev, mode="test")
    finally:
        await conn.close()
    # CA 275-02: cung event ID khac payload -> conflict fail-closed (row -> error, attention mo). success=False.
    return {"success": not conflict, "event_id": row_id, "duplicate": not created, "conflict": conflict}
