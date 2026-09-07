"""M5 order-intent fingerprints + state model (CA Directive 223 + Amendment 224).

Fingerprint TAT DINH, KHONG PII (mot chieu). Dung lam SEMANTIC identity cho intent/idempotency thay vi
resolution-UUID ngau nhien (§5). verified_resolution_id van duoc persist rieng cho audit/binding.

Phan nay la logic THUAN (khong cham DB) -> test bang fixture. Wiring vao order path + DB state machine
o buoc sau.
"""
from __future__ import annotations

import hashlib

from app.services.address.acceptance_gate import normalize

# State machine (Amendment 224 §2). OPEN = chua terminal.
STATES = (
    "COLLECTING", "ADDRESS_CHECK", "NEEDS_CLARIFICATION", "READY_TO_COMMIT",
    "COMMITTING", "COMMITTED", "RETRYING", "REJECTED", "CANCELLED", "ESCALATED", "EXPIRED",
)
OPEN_STATES = frozenset({"COLLECTING", "ADDRESS_CHECK", "NEEDS_CLARIFICATION", "READY_TO_COMMIT",
                         "COMMITTING", "RETRYING"})
TERMINAL_STATES = frozenset({"COMMITTED", "REJECTED", "CANCELLED", "ESCALATED", "EXPIRED"})

# Transition hop le (Amendment 224 §4): (from -> {to,...}). Ngoai bang = fail-closed.
ALLOWED_TRANSITIONS = {
    "COLLECTING": {"ADDRESS_CHECK", "CANCELLED", "ESCALATED", "EXPIRED"},
    "ADDRESS_CHECK": {"NEEDS_CLARIFICATION", "READY_TO_COMMIT", "CANCELLED", "ESCALATED", "EXPIRED"},
    "NEEDS_CLARIFICATION": {"ADDRESS_CHECK", "CANCELLED", "ESCALATED", "EXPIRED"},
    "READY_TO_COMMIT": {"COMMITTING", "ADDRESS_CHECK", "CANCELLED", "ESCALATED", "EXPIRED"},
    "COMMITTING": {"COMMITTED", "RETRYING", "REJECTED"},
    "RETRYING": {"COMMITTING", "REJECTED"},
    # terminal states: khong transition ra (except khong co).
}


def can_transition(frm: str, to: str) -> bool:
    """True neu transition hop le. Terminal -> khong ra duoc (fail-closed: khong reopen)."""
    return to in ALLOWED_TRANSITIONS.get(frm, frozenset())


def _h(*parts: str) -> str:
    """sha256 mot chieu tren cac phan da normalize (join bang | de tranh nhap nhang bien)."""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def verified_address_fingerprint(dataset_version: str, province_code: str, ward_code: str,
                                 delivery_detail: str | None) -> str:
    """Semantic identity dia chi DA VERIFY (Amendment 224 §5): dataset_version + province_code + ward_code
    + hash mot chieu cua delivery-detail da normalize (so nha/duong — de phan biet vi tri KHAC trong CUNG
    phuong). TAT DINH: cung dia chi (qua bien the chinh ta/viet tat sau khi verify) -> cung fingerprint.
    KHONG chua raw address. district_code khong bat buoc (v2 co topology 2-tier province->ward)."""
    detail_h = _h(normalize(delivery_detail or ""))
    return _h("addr-v1", dataset_version or "", province_code or "", ward_code or "", detail_h)


def order_fingerprint(*, sku: str, quantity, customer_name: str, phone: str,
                      address_fp: str | None) -> str:
    """Canonical order fingerprint (§5): SKU + quantity + contact da normalize + verified-address
    fingerprint. Cung don (noi dung + dia chi da verify) -> cung fingerprint qua cac luot xac nhan ->
    idempotent. Doi bat ky truong -> fingerprint khac -> intent/version moi. phone chi giu chu so."""
    phone_digits = "".join(c for c in (phone or "") if c.isdigit())
    return _h("order-v1", normalize(sku or ""), str(quantity), normalize(customer_name or ""),
              phone_digits, address_fp or "")
