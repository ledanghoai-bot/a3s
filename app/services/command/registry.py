"""Command type/version registry (I-B M1). Spec §4.2, §6.1.

M1 chi mo mot command: order.create v1 (AI + dashboard bot/manual). Registry la noi khai bao:
- validate payload (structural + phone/quantity — business stock/product o service layer);
- hash-field extraction (business-relevant, normalized) cho request_hash;
- stored-payload allowlist (masked phone, KHONG address raw) cho cot request_payload.
Foundation dung lai cho M2-M6 (them command khac vao REGISTRY).
"""
from __future__ import annotations

import re
from typing import Any

from app.services.command import errors
from app.services.command.hashing import canonical_hash
from app.services.command.redaction import mask_phone

ORDER_CREATE = "order.create"
ORDER_CREATE_VERSION = 1

# Khop tools.PHONE_RE (M0) — giu nhat quan dinh dang SDT VN.
PHONE_RE = re.compile(r"^(0|\+84)(3|5|7|8|9)\d{8}$")

REGISTRY: set[tuple[str, int]] = {
    (ORDER_CREATE, ORDER_CREATE_VERSION),
}


def is_registered(command_type: str, version: int) -> bool:
    return (command_type, version) in REGISTRY


def require_registered(command_type: str, version: int) -> None:
    if not is_registered(command_type, version):
        raise errors.unknown_command(command_type, version)


def _clean_phone(phone: str) -> str:
    return str(phone).replace(" ", "").replace("-", "")


def validate_order_create_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalize input tho cho order.create. Raise CommandError (422) khi invalid.
    KHONG kiem tra product/stock o day (thuoc transaction service — can row lock)."""
    if not isinstance(payload, dict):
        raise errors.CommandError(errors.INVALID_ENVELOPE, "payload phai la object.")
    name = (payload.get("customer_name") or "").strip()
    address = (payload.get("address") or "").strip()
    sku = (payload.get("sku") or "").strip()
    phone_raw = payload.get("phone") or ""
    qty = payload.get("quantity")

    if not name:
        raise errors.CommandError(errors.INVALID_ENVELOPE, "Thieu ten nguoi nhan.")
    if not address:
        raise errors.CommandError(errors.INVALID_ENVELOPE, "Thieu dia chi giao.")
    if not sku:
        raise errors.CommandError(errors.INVALID_ENVELOPE, "Thieu sku.")
    if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
        raise errors.CommandError(errors.INVALID_QUANTITY, "So luong phai la so nguyen > 0.")
    phone = _clean_phone(phone_raw)
    if not PHONE_RE.match(phone):
        raise errors.CommandError(errors.INVALID_PHONE, "So dien thoai khong hop le (can so VN).")

    normalized: dict[str, Any] = {
        "customer_name": name,
        "phone": phone,
        "address": address,
        "sku": sku,
        "quantity": qty,
    }
    # Optional: unit_price_vnd -> staff-priced (manual path); absent -> system-priced (AI/bot).
    unit_price = payload.get("unit_price_vnd")
    if unit_price is not None:
        if not isinstance(unit_price, int) or isinstance(unit_price, bool) or unit_price <= 0:
            raise errors.CommandError(errors.INVALID_ENVELOPE, "unit_price_vnd phai la so nguyen > 0.")
        normalized["unit_price_vnd"] = unit_price
    # Optional: psid -> customer key + override lookup (AI/bot). KHONG di vao stored_payload (PII).
    psid = payload.get("psid")
    if psid:
        normalized["psid"] = str(psid)
    return normalized


def order_create_hash_input(normalized: dict[str, Any]) -> dict[str, Any]:
    """Business-relevant fields cho request_hash (da normalize). Bao gom phone/address de phan
    biet y dinh don khac nhau — chi di vao sha256 (mot chieu), KHONG luu raw. unit_price_vnd
    (neu staff-priced) cung la mot phan y dinh -> vao hash. psid KHONG vao hash (scope da phan biet)."""
    hi = {
        "sku": normalized["sku"],
        "quantity": normalized["quantity"],
        "customer_name": normalized["customer_name"],
        "phone": normalized["phone"],
        "address": normalized["address"],
    }
    if "unit_price_vnd" in normalized:
        hi["unit_price_vnd"] = normalized["unit_price_vnd"]
    return hi


def order_create_stored_payload(normalized: dict[str, Any]) -> dict[str, Any]:
    """Allowlist luu vao request_payload (§7.4): masked phone, KHONG address/psid raw."""
    stored = {
        "sku": normalized["sku"],
        "quantity": normalized["quantity"],
        "customer_name": normalized["customer_name"],
        "phone_masked": mask_phone(normalized["phone"]),
        "pricing_mode": "staff" if "unit_price_vnd" in normalized else "system",
    }
    if "unit_price_vnd" in normalized:
        stored["unit_price_vnd"] = normalized["unit_price_vnd"]
    return stored


def compute_request_hash(command_type: str, version: int, hash_input: dict[str, Any]) -> str:
    """sha256 canonical JSON tren (command_type, version, business payload da normalize). §6.1."""
    return canonical_hash({
        "command_type": command_type,
        "command_version": version,
        "payload": hash_input,
    })
