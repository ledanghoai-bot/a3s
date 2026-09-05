"""M5 Gate C — fulfillment completeness policy (CA Directive 179 §4).

Mot address chi duoc dung downstream (bind/quote/fulfillment) khi co it nhat province + ward hop le (hierarchy/
effective range/dataset version da duoc resolver verify). Province-only = INCOMPLETE: phuc vu informational lookup
nhung KHONG duoc confirmation response hoac staff action bien thanh fulfillment-ready neu chua co ward hop le.
Fail-closed.
"""
from __future__ import annotations


class CompletenessError(Exception):
    """Fail-closed: address chua du province+ward de fulfillment."""


def is_complete(province_code, ward_code) -> bool:
    """Fulfillment-complete = co ca province_code va ward_code (khong rong)."""
    return bool(province_code and str(province_code).strip()) and bool(ward_code and str(ward_code).strip())


def assert_fulfillment_ready(resolution: dict) -> None:
    """Raise CompletenessError neu resolution chua du province+ward (province-only -> informational only)."""
    if not is_complete(resolution.get("province_code"), resolution.get("ward_code")):
        raise CompletenessError(
            f"address INCOMPLETE (province={resolution.get('province_code')}, ward={resolution.get('ward_code')}) "
            "— chi informational; can province+ward hop le truoc khi fulfillment (Gate C §4)")
