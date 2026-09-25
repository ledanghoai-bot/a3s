"""GHN shipment CREATE adapter — CA Directive 393 §4 (CANDIDATE, gate OFF; chua tung goi provider that).

Hop dong an toan:
- CHI nhan request_snapshot DA FREEZE (operation). Khong doc order/shipment/payment mutable luc gui. Credential (token,
  ShopId) lay tu cfg da resolve (loader D305/D357) TRONG PHAM VI request, KHONG vao snapshot/log.
- `client_order_code` tat dinh tu operation id -> correlation de doi soat (GHN detail-by-client-code).
- MOT HTTP moi lan goi, KHONG retry noi bo: retry/backoff/reconcile do state machine (ghn_shipment_create) quyet dinh.
- Phan loai ket qua create:
    created    : HTTP 200 + code 200 + data.order_code (provider evidence)
    rejected   : 4xx validation (tru 408/425/429) hoac 200 + code != 200 (GHN tu choi) -> terminal
    retryable  : request CHUA toi provider (connect error/connect timeout) HOAC 429/5xx co response ro rang
    unknown    : request CO THE da toi provider nhung khong co ket qua chac chan (read timeout, mat ket noi giua
                 chung, 200 thieu order_code, body khong doc duoc) -> KHONG blind retry, bat buoc doi soat
- 429: ton trong Retry-After (giay, gioi han). Khong log token/Authorization/PII/raw payload.

Provider-contract GAP (CHUA verify voi GHN that — nop CA): endpoint `/v2/shipping-order/create`, bo field bat buoc,
co/khong idempotency theo client_order_code, `/v2/shipping-order/detail-by-client-code` cho doi soat, API huy/label/
tracking/webhook — xem ho so submission Directive 393 §gap.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

PROVIDER = "ghn"
CREATE_PATH = "/v2/shipping-order/create"
DETAIL_BY_CLIENT_CODE_PATH = "/v2/shipping-order/detail-by-client-code"
RETRY_AFTER_MAX_S = 3600
_RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}
# Chi cac key nay duoc luu tu response (khong PII: ten/SDT/dia chi nguoi nhan, khong token).
_RESULT_KEYS = ("order_code", "sort_code", "trans_type", "total_fee", "expected_delivery_time", "status",
                "client_order_code")

CREATED, REJECTED, RETRYABLE, UNKNOWN = "created", "rejected", "retryable", "unknown"
FOUND, NOT_FOUND = "found", "not_found"


@dataclass
class ProviderOutcome:
    outcome: str
    http_status: int | None = None
    error_class: str = ""
    retry_after_s: int | None = None
    duration_ms: int | None = None
    order_code: str | None = None
    result: dict[str, Any] = field(default_factory=dict)     # redacted


def redact_result(data: Any) -> dict:
    if not isinstance(data, dict):
        return {}
    return {k: data.get(k) for k in _RESULT_KEYS if k in data}


def build_create_payload(snapshot: dict, client_order_code: str) -> dict:
    """Payload GHN create CHI tu snapshot bat bien (pure — test duoc, khong I/O)."""
    r, a, pk, pa, pay, pol = (snapshot["recipient"], snapshot["address"], snapshot["pickup"], snapshot["parcel"],
                              snapshot["payment"], snapshot["policy"])
    return {
        "client_order_code": client_order_code,
        "payment_type_id": int(pol["payment_type_id"]),
        "required_note": str(pol["required_note"]),
        "note": f"Don #{snapshot['order']['id']}",
        "to_name": r["name"], "to_phone": r["phone"], "to_address": r["address_text"],
        "to_ward_code": str(a["carrier_ward_code"]), "to_district_id": int(a["carrier_district_id"]),
        "from_district_id": int(pk["from_district_id"]), "from_ward_code": str(pk["from_ward_code"]),
        "weight": int(pa["weight_g"]), "length": int(pa["length_cm"]), "width": int(pa["width_cm"]),
        "height": int(pa["height_cm"]), "service_type_id": int(pa["service_type_id"]),
        "cod_amount": int(pay["cod_amount_vnd"]), "insurance_value": int(pa.get("insurance_value_vnd") or 0),
        "items": [{"name": it["name"], "quantity": int(it["quantity"]), "weight": int(it.get("weight_g") or 0)}
                  for it in snapshot["items"]],
    }


def _retry_after(resp) -> int | None:
    v = resp.headers.get("Retry-After") if resp is not None else None
    if v is None:
        return None
    try:
        n = int(str(v).strip())
    except ValueError:
        return None   # dang HTTP-date: bo qua -> backoff mac dinh cua state machine
    return max(0, min(n, RETRY_AFTER_MAX_S))


async def _send_once(cfg: dict, path: str, body: dict) -> tuple[Any, dict | None, str, int]:
    """1 POST, KHONG retry. Tra (resp|None, json|None, error_class, duration_ms). error_class:
    '' | 'connect' (chua gui) | 'timeout_read' | 'protocol' (co the da gui)."""
    headers = {"Content-Type": "application/json", "Token": cfg["token"]}
    if cfg.get("shop_id"):
        headers["ShopId"] = str(cfg["shop_id"])
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(cfg["timeout"], connect=3.0)) as client:
            resp = await client.post(f"{cfg['base']}{path}", headers=headers, json=body)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return None, None, "connect", int((time.perf_counter() - t0) * 1000)
    except httpx.TimeoutException:
        return None, None, "timeout_read", int((time.perf_counter() - t0) * 1000)
    except httpx.HTTPError:
        return None, None, "protocol", int((time.perf_counter() - t0) * 1000)
    try:
        js = resp.json()
    except Exception:  # noqa: BLE001
        js = None
    return resp, js if isinstance(js, dict) else None, "", int((time.perf_counter() - t0) * 1000)


class GhnCreateProvider:
    """Adapter tao van don. `send` injectable (test/mock) — cung chu ky _send_once."""
    name = PROVIDER

    def __init__(self, cfg: dict, send=None):
        self.cfg = cfg
        self._send = send or _send_once

    async def create(self, snapshot: dict, client_order_code: str) -> ProviderOutcome:
        body = build_create_payload(snapshot, client_order_code)
        resp, js, err, dur = await self._send(self.cfg, CREATE_PATH, body)
        if err == "connect":
            return ProviderOutcome(RETRYABLE, error_class="connect_not_sent", duration_ms=dur)
        if err:
            return ProviderOutcome(UNKNOWN, error_class=err, duration_ms=dur)
        st = resp.status_code
        data = (js or {}).get("data")
        if st == 200 and js is not None and js.get("code") == 200:
            code = (data or {}).get("order_code") if isinstance(data, dict) else None
            if isinstance(code, str) and code.strip():
                return ProviderOutcome(CREATED, http_status=st, duration_ms=dur, order_code=code.strip(),
                                       result=redact_result(data))
            return ProviderOutcome(UNKNOWN, http_status=st, error_class="ok_without_order_code", duration_ms=dur)
        if st in _RETRYABLE_HTTP:
            return ProviderOutcome(RETRYABLE, http_status=st, error_class=f"http_{st}", duration_ms=dur,
                                   retry_after_s=_retry_after(resp) if st == 429 else None)
        if st == 200 or 400 <= st < 500:
            gcode = js.get("code") if js else None
            return ProviderOutcome(REJECTED, http_status=st, error_class=f"rejected_http_{st}_code_{gcode}",
                                   duration_ms=dur)
        return ProviderOutcome(UNKNOWN, http_status=st, error_class=f"http_{st}", duration_ms=dur)

    async def lookup(self, client_order_code: str) -> ProviderOutcome:
        """Doi soat theo client_order_code (read-only). found | not_found | unknown (khong chac chan -> staff)."""
        resp, js, err, dur = await self._send(self.cfg, DETAIL_BY_CLIENT_CODE_PATH,
                                              {"client_order_code": client_order_code})
        if err:
            return ProviderOutcome(UNKNOWN, error_class=f"lookup_{err}", duration_ms=dur)
        st = resp.status_code
        data = (js or {}).get("data")
        if st == 200 and js is not None and js.get("code") == 200 and isinstance(data, dict):
            code = data.get("order_code")
            if isinstance(code, str) and code.strip() and data.get("client_order_code") in (None, client_order_code):
                return ProviderOutcome(FOUND, http_status=st, duration_ms=dur, order_code=code.strip(),
                                       result=redact_result(data))
            return ProviderOutcome(UNKNOWN, http_status=st, error_class="lookup_ok_mismatch", duration_ms=dur)
        # GAP: ma/HTTP GHN tra khi KHONG tim thay chua duoc xac nhan -> chi coi 'not_found' khi body noi ro.
        if js is not None and st in (200, 400, 404) and js.get("code") in (400, 404) and not data:
            msg = str(js.get("message") or "").lower()
            if "not found" in msg or "không tìm thấy" in msg or "khong tim thay" in msg:
                return ProviderOutcome(NOT_FOUND, http_status=st, duration_ms=dur)
        return ProviderOutcome(UNKNOWN, http_status=st, error_class=f"lookup_http_{st}", duration_ms=dur,
                               retry_after_s=_retry_after(resp) if st == 429 else None)
