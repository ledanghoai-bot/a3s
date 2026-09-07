"""M5 order-intent fingerprints + state model (CA Directive 223 + Amendment 224).

Fingerprint TAT DINH, KHONG PII (mot chieu). Dung lam SEMANTIC identity cho intent/idempotency thay vi
resolution-UUID ngau nhien (§5). verified_resolution_id van duoc persist rieng cho audit/binding.

Phan nay la logic THUAN (khong cham DB) -> test bang fixture. Wiring vao order path + DB state machine
o buoc sau.
"""
from __future__ import annotations

import hashlib
import re

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


# --- Canonical delivery-detail extraction (CA Review 225-06) ---
# Bo cac thanh phan hanh chinh DA RESOLVE (ten canonical + dang bare + prefix/viet tat) khoi dia chi
# free-text -> chi con so nha/duong. TAT DINH: cung vi tri qua bien the chinh ta/viet tat (P./Phuong,
# co/khong dau) -> cung detail -> cung fingerprint (case 17). Khac so nha/duong cung phuong -> khac
# detail (case 16). KHONG chua ten hanh chinh -> fingerprint on dinh khi dataset doi ten cap tren.
_ADMIN_LEADING = ("thanh pho", "thi xa", "thi tran", "tinh", "quan", "huyen", "phuong", "xa",
                  "tp", "tx", "tt")
# Token CHAC CHAN hanh chinh, an toan bo sau khi da go ten (KHONG go token da nghia nhu thanh/pho/thi/
# tran/h/x/t vi co the la ten duong).
_ADMIN_DROP_TOKENS = frozenset({"phuong", "quan", "huyen", "xa", "tinh", "p", "q", "tp", "tx", "tt", "kp"})


def _strip_leading_admin(nn: str) -> str:
    """'phuong ea kao' -> 'ea kao'; 'tinh dak lak' -> 'dak lak'. Tra nguyen neu khong co prefix."""
    for pre in _ADMIN_LEADING:
        if nn.startswith(pre + " "):
            return nn[len(pre) + 1:]
    return nn


def canonical_delivery_detail(address: str | None, province_name: str | None = None,
                              ward_name: str | None = None, district_name: str | None = None) -> str:
    """Trich delivery-detail canonical tu dia chi free-text + ten hanh chinh DA RESOLVE (server-side).
    Dung LAM delivery_detail cho verified_address_fingerprint (thay raw address) -> fingerprint semantic
    canonical (CA 225-06). Chi goi khi da co ten canonical tu resolver (khong doan mo)."""
    n = normalize(address or "")
    phrases: list[str] = []
    for nm in (province_name, district_name, ward_name):
        if not nm:
            continue
        nn = normalize(nm)
        phrases.append(nn)
        bare = _strip_leading_admin(nn)
        if bare and bare != nn:
            phrases.append(bare)
    for ph in sorted(set(phrases), key=len, reverse=True):
        n = re.sub(r"\b" + re.escape(ph) + r"\b", " ", n)
    toks = [t for t in re.split(r"[^a-z0-9]+", n) if t and t not in _ADMIN_DROP_TOKENS]
    return " ".join(toks).strip()


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
