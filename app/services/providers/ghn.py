"""GHN carrier adapter — M7-B READ-ONLY quote/leadtime/master-data (CA Directive 272 §3.4).

- Endpoint staging mac dinh (dev-online-gateway); KHONG create/update/cancel shipment, KHONG tao van don.
- Token/ShopId server-side (settings). Timeout huu han, retry gioi han + jitter chi cho loi mang/5xx; KHONG retry
  validation/mapping error. Moi loi -> QuoteResult(quote_required) (fail-closed), KHONG raise ra luong bot.
- Address adapter co version: (province_code, ward_code) chinh phu -> carrier_address_map (status matched) ->
  to_district_id/to_ward_code GHN. Thieu/ambiguous -> quote_required.
- Service type theo hop dong: weight <= GHN_LIGHT_MAX_G -> service_type_id 2 (hang nhe), nguoc lai 5 (hang nang).
- Snapshot: request fingerprint, fee total + breakdown, leadtime, timestamp -> provider_quote_log (append-only) +
  shipments.quote_snapshot (o shipment_service).
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.services.providers.base import (
    QUOTE_OK,
    QUOTE_REQUIRED,
    QuoteRequest,
    QuoteResult,
)
from app.services.safe_log import safe_exc

PROVIDER = "ghn"
STAGING_BASE = "https://dev-online-gateway.ghn.vn/shiip/public-api"
PROD_BASE = "https://online-gateway.ghn.vn/shiip/public-api"
MODES = ("staging", "production")
BASE_BY_MODE = {"staging": STAGING_BASE, "production": PROD_BASE}
SERVICE_TYPE_LIGHT = 2
SERVICE_TYPE_HEAVY = 5
_RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


def _cfg() -> dict[str, Any]:
    return {
        "enabled": bool(settings.m7_ghn_quote),
        "base": (settings.ghn_base_url or STAGING_BASE).rstrip("/"),
        "token": settings.ghn_token or "",
        "shop_id": settings.ghn_shop_id or "",
        "from_district_id": settings.ghn_from_district_id,
        "from_ward_code": settings.ghn_from_ward_code or "",
        "timeout": float(settings.ghn_timeout_seconds or 8.0),
        "retries": int(settings.ghn_max_retries or 2),
        "light_max_g": int(settings.ghn_light_max_g or 20000),
        "map_version": int(settings.ghn_address_map_version or 1),
    }


def _unconfigured(base: dict, source: str, mode: str | None = None) -> dict:
    """Cfg fail-closed: thieu/lech token-shop-pickup-mode -> quote() tra ghn_not_configured (khong HTTP)."""
    return {**base, "token": "", "shop_id": "", "from_district_id": None, "from_ward_code": "", "source": source,
            "mode": mode}


async def resolve_quote_cfg(conn) -> dict[str, Any]:
    """CA Directive 345 §2A: cfg quote GHN theo loader D305 (DB authoritative khi settings_integrations_enabled).
    CA Directive 357 §2.1: mode active (settings.ghn_active_mode) phai TUONG MINH 'staging'|'production' — khong suy
    doan tu token/URL/ShopId; moi luc chi MOT mode.
    - m7_ghn_quote OFF -> cfg env (enabled=False -> quote() tra ghn_disabled), KHONG doc/giai ma secret.
    - mode khong hop le -> fail-closed NGAY (khong cham DB/secret).
    - module OFF -> env (baseline).
    - module ON: integration ghn cua DUNG mode active, enabled + day du -> config DB + token giai ma TRONG PHAM VI
      request; khong co record -> fail-closed; decrypt loi/thieu secret/base_url khong khop endpoint ghim cua mode
      -> fail-closed (ghn_not_configured). Token khong log/cache/snapshot."""
    base = _cfg()
    mode = str(getattr(settings, "ghn_active_mode", "") or "").strip()
    if not base["enabled"]:
        return {**base, "source": "disabled", "mode": mode}
    if mode not in MODES:                       # CA 357: mode phai TUONG MINH hop le, khong doan
        return _unconfigured(base, "mode_invalid", mode)
    if not settings.settings_integrations_enabled:
        return {**base, "source": "env", "mode": mode}
    from app.services.settings import integrations as _S
    try:
        lc = await _S.load_active_config(conn, PROVIDER, mode)
    except Exception:  # noqa: BLE001 — decrypt/invalid -> fail closed, KHONG fallback env
        return _unconfigured(base, "db_error", mode)
    if lc["source"] == "env":
        return {**base, "source": "env", "mode": mode}
    if lc["source"] != "database":
        return _unconfigured(base, "none", mode)
    cp = lc["config"] or {}
    b = (cp.get("base_url") or "").rstrip("/")
    if b != BASE_BY_MODE[mode]:                 # endpoint phai khop DUNG mode active
        return _unconfigured(base, "base_mode_mismatch", mode)
    mr = cp.get("max_retries")
    return {"enabled": True, "base": b, "token": (lc.get("secrets") or {}).get("token") or "",
            "shop_id": str(cp.get("shop_id") or ""), "from_district_id": cp.get("from_district_id"),
            "from_ward_code": cp.get("from_ward_code") or "", "timeout": float(cp.get("timeout_seconds") or 8.0),
            "retries": int(mr if mr is not None else 2), "light_max_g": int(cp.get("light_max_g") or 20000),
            "map_version": int(cp.get("address_map_version") or 1), "source": "database", "mode": mode}


def service_type_for_weight(weight_g: int, light_max_g: int) -> int:
    return SERVICE_TYPE_LIGHT if weight_g <= light_max_g else SERVICE_TYPE_HEAVY


def default_dims_cm(weight_g: int) -> tuple[int, int, int]:
    """Kich thuoc goi mac dinh theo bang trong luong (hop dong noi bo, snapshot vao request). Ca phe say lanh dong
    goi nho: <=1kg 20x15x10; <=5kg 30x25x20; con lai 40x30x30. Staff co the quote manual neu khac."""
    if weight_g <= 1000:
        return 20, 15, 10
    if weight_g <= 5000:
        return 30, 25, 20
    return 40, 30, 30


def _headers(cfg: dict, with_shop: bool = True) -> dict[str, str]:
    h = {"Content-Type": "application/json", "Token": cfg["token"]}
    if with_shop and cfg["shop_id"]:
        h["ShopId"] = str(cfg["shop_id"])
    return h


def _redact(d: dict | None) -> dict:
    if not d:
        return {}
    return {k: v for k, v in d.items() if k.lower() not in ("token", "shopid", "shop_id", "authorization")}


async def _post(cfg: dict, path: str, body: dict, *, retries: int) -> tuple[int | None, dict | None, str, int]:
    """POST co retry gioi han + jitter. Tra (http_status, json, error_class, duration_ms). Khong raise."""
    url = f"{cfg['base']}{path}"
    t0 = time.perf_counter()
    last_err, last_status, last_json = "", None, None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(cfg["timeout"], connect=3.0)) as client:
                resp = await client.post(url, headers=_headers(cfg), json=body)
            last_status = resp.status_code
            try:
                last_json = resp.json()
            except Exception:  # noqa: BLE001
                last_json = None
            if resp.status_code in _RETRYABLE_HTTP and attempt < retries:
                await asyncio.sleep(0.2 * (2 ** attempt) + random.uniform(0, 0.2))
                continue
            return last_status, last_json, "", int((time.perf_counter() - t0) * 1000)
        except httpx.TimeoutException:
            last_err = "timeout"
        except httpx.HTTPError as e:  # noqa: BLE001
            last_err = type(e).__name__
        if attempt < retries:
            await asyncio.sleep(0.2 * (2 ** attempt) + random.uniform(0, 0.2))
    return last_status, last_json, last_err or "error", int((time.perf_counter() - t0) * 1000)


async def _log(conn, *, order_id: int | None, fp: str, request: dict, response: dict | None, status: str,
               http_status: int | None, duration_ms: int | None) -> None:
    try:
        await conn.execute(
            "INSERT INTO provider_quote_log (provider, order_id, request_fingerprint, request, response, status, "
            "http_status, duration_ms) VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7,$8)",
            PROVIDER, order_id, fp, json.dumps(_redact(request)),
            json.dumps(response) if response is not None else None, status, http_status, duration_ms)
    except Exception as e:  # noqa: BLE001 — log khong duoc lam vo quote
        print(f"[ghn] quote log skipped: {safe_exc(e)}")


async def address_lookup(conn, province_code: str, ward_code: str, *, map_version: int,
                         mode: str = "staging") -> dict | None:
    """Adapter dia chi co version + MODE (CA 357: map staging/production tach hoan toan).
    Chi 'matched' moi dung; ambiguous/manual/unmatched -> None (fail-closed)."""
    row = await conn.fetchrow(
        "SELECT carrier_province_id, carrier_district_id, carrier_ward_code, status, method, confidence "
        "FROM carrier_address_map WHERE provider=$1 AND mode=$2 AND map_version=$3 AND province_code=$4 "
        "AND ward_code=$5", PROVIDER, mode, map_version, province_code, ward_code)
    if not row or row["status"] != "matched" or not row["carrier_district_id"] or not row["carrier_ward_code"]:
        return None
    return dict(row)


def _leadtime_days(data: dict | None) -> int | None:
    """leadtime = unix ts du kien giao -> so ngay tu now (lam tron len)."""
    try:
        ts = int((data or {}).get("leadtime"))
    except Exception:  # noqa: BLE001
        return None
    now = int(datetime.now(timezone.utc).timestamp())
    return max(1, -(-(ts - now) // 86400)) if ts > now else 1


class GhnQuoteProvider:
    name = PROVIDER

    def __init__(self, cfg: dict | None = None, post=None):
        self.cfg = cfg or _cfg()
        self._post = post or _post   # inject de test/replay fixture

    async def quote(self, conn, req: QuoteRequest) -> QuoteResult:
        cfg = self.cfg
        fp = req.fingerprint()
        base = dict(provider=PROVIDER, request_fingerprint=fp)
        from app.services.fulfillment import shipping_policy as _sp
        if _sp.is_heavy(req.weight_g):   # CA 354 (phong thu): >20 kg -> KHONG HTTP, KHONG provider_quote_log
            return QuoteResult(status=QUOTE_REQUIRED, reason=_sp.HEAVY_GOODS_REASON, **base)
        if not cfg["enabled"]:
            return QuoteResult(status=QUOTE_REQUIRED, reason="ghn_disabled", **base)
        if not cfg["token"] or not cfg["shop_id"] or not cfg["from_district_id"] or not cfg["from_ward_code"]:
            await _log(conn, order_id=req.order_id, fp=fp, request={"reason": "not_configured"}, response=None,
                       status="skipped", http_status=None, duration_ms=None)
            return QuoteResult(status=QUOTE_REQUIRED, reason="ghn_not_configured", **base)
        if req.weight_g <= 0 or min(req.length_cm, req.width_cm, req.height_cm) <= 0:
            return QuoteResult(status=QUOTE_REQUIRED, reason="invalid_weight_or_dims", **base)
        addr = await address_lookup(conn, req.province_code, req.ward_code, map_version=cfg["map_version"],
                                    mode=cfg.get("mode") or "staging")
        if addr is None:
            await _log(conn, order_id=req.order_id, fp=fp, request={"reason": "address_unmapped",
                       "province_code": req.province_code, "ward_code": req.ward_code,
                       "map_version": cfg["map_version"], "mode": cfg.get("mode")}, response=None, status="skipped",
                       http_status=None, duration_ms=None)
            return QuoteResult(status=QUOTE_REQUIRED, reason="address_unmapped", **base)
        stype = service_type_for_weight(req.weight_g, cfg["light_max_g"])
        body = {
            "from_district_id": int(cfg["from_district_id"]), "from_ward_code": str(cfg["from_ward_code"]),
            "service_type_id": stype, "to_district_id": int(addr["carrier_district_id"]),
            "to_ward_code": str(addr["carrier_ward_code"]), "weight": int(req.weight_g),
            "length": int(req.length_cm), "width": int(req.width_cm), "height": int(req.height_cm),
            "insurance_value": int(req.insurance_value_vnd or 0),
        }
        status, js, err, dur = await self._post(cfg, "/v2/shipping-order/fee", body, retries=cfg["retries"])
        carrier_ids = {"to_district_id": body["to_district_id"], "to_ward_code": body["to_ward_code"],
                       "service_type_id": stype, "map_version": cfg["map_version"]}
        if err or status is None:
            await _log(conn, order_id=req.order_id, fp=fp, request=body, response={"error": err},
                       status="timeout" if err == "timeout" else "error", http_status=status, duration_ms=dur)
            return QuoteResult(status=QUOTE_REQUIRED, reason=f"ghn_{err}", http_status=status, duration_ms=dur,
                               carrier_ids=carrier_ids, **base)
        data = (js or {}).get("data") if isinstance(js, dict) else None
        if status != 200 or not isinstance(js, dict) or js.get("code") != 200 or not isinstance(data, dict):
            await _log(conn, order_id=req.order_id, fp=fp, request=body, response=js if isinstance(js, dict) else
                       {"raw": str(js)[:300]}, status="error", http_status=status, duration_ms=dur)
            return QuoteResult(status=QUOTE_REQUIRED, reason=f"ghn_http_{status}_code_{(js or {}).get('code') if isinstance(js, dict) else 'na'}",
                               http_status=status, duration_ms=dur, carrier_ids=carrier_ids, **base)
        total = data.get("total")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            await _log(conn, order_id=req.order_id, fp=fp, request=body, response=js, status="error",
                       http_status=status, duration_ms=dur)
            return QuoteResult(status=QUOTE_REQUIRED, reason="ghn_schema_total", http_status=status,
                               duration_ms=dur, carrier_ids=carrier_ids, **base)
        # Leadtime (best-effort; loi -> None, KHONG lam quote that bai)
        lt_days = None
        lt_body = {"from_district_id": body["from_district_id"], "from_ward_code": body["from_ward_code"],
                   "to_district_id": body["to_district_id"], "to_ward_code": body["to_ward_code"],
                   "service_type_id": stype}
        lts, ltj, lterr, _ = await self._post(cfg, "/v2/shipping-order/leadtime", lt_body, retries=0)
        if not lterr and lts == 200 and isinstance(ltj, dict) and ltj.get("code") == 200:
            lt_days = _leadtime_days(ltj.get("data"))
        breakdown = {k: data.get(k) for k in ("service_fee", "insurance_fee", "pick_station_fee", "coupon_value",
                                                "r2s_fee", "document_return", "double_check", "cod_fee",
                                                "pick_remote_areas_fee", "deliver_remote_areas_fee", "cod_failed_fee")
                     if k in data}
        await _log(conn, order_id=req.order_id, fp=fp, request=body,
                   response={"fee": data, "leadtime": (ltj or {}).get("data") if isinstance(ltj, dict) else None},
                   status="ok", http_status=status, duration_ms=dur)
        eta = f"khoảng {lt_days} ngày (GHN)" if lt_days else "GHN sẽ báo thời gian giao"
        return QuoteResult(status=QUOTE_OK, fee_vnd=int(total), breakdown=breakdown, leadtime_days=lt_days,
                           eta_text=eta, provider_ref=None, service_type_id=stype, http_status=status,
                           duration_ms=dur, carrier_ids=carrier_ids, reason="ok", **base)


# ---------------- Master data ----------------
# CA Directive 345 §2B: snapshot master-data chi qua tool van hanh co pham vi + hard cap
# (app/services/providers/ghn_master_data.py + scripts/ghn_g1_prep.py). Ham quet toan quoc cu da go (F2).
