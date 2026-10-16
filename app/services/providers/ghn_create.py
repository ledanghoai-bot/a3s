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
D421 B1 (probe STAGING read-only/preview 16/10/2026, KHONG goi create): payload theo MA duoc chap nhan (ban theo ten
+ is_new_to_address -> TO_ADDRESS_CONFLICT) -> giu theo ma; thieu items+content -> 'Tên hàng hoá bắt buộc';
lookup = GET + query; 'khong ton tai' = HTTP 400/code 400/code_message null/message '... - Đơn hàng không tồn tại'.
Idempotency create theo client_order_code VAN CHUA verify (can create that tren staging — cam theo CA 422).
"""
from __future__ import annotations

import re
import time
import unicodedata
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

_NOT_FOUND_MSG = unicodedata.normalize("NFC", "Đơn hàng không tồn tại")
# Tran COD cua GHN (docs Tao don, D421 B1) — vuot -> blocker truoc khi goi provider.
COD_MAX_VND = 50_000_000

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


def _code_message_suffix(js: dict | None) -> str:
    """`code_message` GHN (vd TO_ADDRESS_CONFLICT, USER_ERR_COMMON) -> hau to error_class de staff biet sua gi.
    Chi giu [A-Z0-9_] (<=48 ky tu) — khong dua message tu do (co the chua PII/du lieu dau vao) vao error_class."""
    cm = (js or {}).get("code_message")
    if not isinstance(cm, str):
        return ""
    s = re.sub(r"[^A-Z0-9_]", "", cm.strip().upper())[:48]
    return f"_{s}" if s else ""


def is_lookup_not_found(http_status: int | None, js: dict | None) -> bool:
    """'Khong ton tai' CHAC CHAN cho detail-by-client-code (not_found -> state machine DUOC tao lai => phai chat).
    Hop dong quan sat tren staging (D421 B1, 16/10/2026): HTTP 400, code 400, data null, code_message null,
    message 'Lỗi gọi API: corev2_tenant_order_detail_by_client_order_code - Đơn hàng không tồn tại'.
    Chap nhan: code_message == ORDER_NOT_FOUND (theo docs) HOAC doan cuoi message (sau ' - ') == 'Đơn hàng không tồn
    tại' (NFC, GIU DAU — khong bo dau/khong substring). Moi truong hop khac -> unknown (staff doi soat)."""
    if http_status != 400 or not isinstance(js, dict) or js.get("code") != 400 or js.get("data"):
        return False
    if js.get("code_message") == "ORDER_NOT_FOUND":
        return True
    msg = unicodedata.normalize("NFC", str(js.get("message") or ""))
    return msg.rsplit(" - ", 1)[-1].strip() == _NOT_FOUND_MSG


def _retry_after(resp) -> int | None:
    v = resp.headers.get("Retry-After") if resp is not None else None
    if v is None:
        return None
    try:
        n = int(str(v).strip())
    except ValueError:
        return None   # dang HTTP-date: bo qua -> backoff mac dinh cua state machine
    return max(0, min(n, RETRY_AFTER_MAX_S))


async def _send_once(cfg: dict, path: str, body: dict | None, *, method: str = "POST",
                     params: dict | None = None) -> tuple[Any, dict | None, str, int]:
    """1 request (POST create | GET lookup), KHONG retry. Tra (resp|None, json|None, error_class, duration_ms).
    error_class: '' | 'connect' (chua gui) | 'timeout_read' | 'protocol' (co the da gui)."""
    headers = {"Content-Type": "application/json", "Token": cfg["token"]}
    if cfg.get("shop_id"):
        headers["ShopId"] = str(cfg["shop_id"])
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(cfg["timeout"], connect=3.0)) as client:
            resp = await client.request(method, f"{cfg['base']}{path}", headers=headers, params=params,
                                        json=body if method == "POST" else None)
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
            return ProviderOutcome(REJECTED, http_status=st,
                                   error_class=f"rejected_http_{st}_code_{gcode}{_code_message_suffix(js)}",
                                   duration_ms=dur)
        return ProviderOutcome(UNKNOWN, http_status=st, error_class=f"http_{st}", duration_ms=dur)

    async def lookup(self, client_order_code: str) -> ProviderOutcome:
        """Doi soat theo client_order_code (read-only). found | not_found | unknown (khong chac chan -> staff)."""
        # D421 B1 (probe staging): docs + thuc te = GET + query string (POST body KHONG phai hop dong).
        resp, js, err, dur = await self._send(self.cfg, DETAIL_BY_CLIENT_CODE_PATH, None, method="GET",
                                              params={"client_order_code": client_order_code})
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
        if is_lookup_not_found(st, js):
            return ProviderOutcome(NOT_FOUND, http_status=st, duration_ms=dur)
        return ProviderOutcome(UNKNOWN, http_status=st, error_class=f"lookup_http_{st}{_code_message_suffix(js)}",
                               duration_ms=dur, retry_after_s=_retry_after(resp) if st == 429 else None)
