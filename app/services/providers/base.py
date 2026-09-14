"""Provider-neutral contracts (M7). Carrier quote + incoming bank transfer signal."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

QUOTE_OK = "ok"
QUOTE_REQUIRED = "quote_required"     # fail-closed: moi loi/mo ho -> staff quote


@dataclass(frozen=True)
class QuoteRequest:
    order_id: int
    province_code: str
    ward_code: str
    weight_g: int
    length_cm: int
    width_cm: int
    height_cm: int
    insurance_value_vnd: int = 0

    def fingerprint(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class QuoteResult:
    status: str                              # ok | quote_required
    provider: str
    reason: str = ""
    fee_vnd: int | None = None
    breakdown: dict[str, Any] = field(default_factory=dict)
    leadtime_days: int | None = None
    eta_text: str | None = None
    provider_ref: str | None = None
    request_fingerprint: str = ""
    service_id: int | None = None
    service_type_id: int | None = None
    http_status: int | None = None
    duration_ms: int | None = None
    carrier_ids: dict[str, Any] = field(default_factory=dict)   # to_district_id/to_ward_code da resolve (khong secret)

    def snapshot(self) -> dict[str, Any]:
        """JSON luu vao shipments.quote_snapshot (khong secret)."""
        return {
            "provider": self.provider, "status": self.status, "reason": self.reason, "fee_vnd": self.fee_vnd,
            "breakdown": self.breakdown, "leadtime_days": self.leadtime_days, "eta_text": self.eta_text,
            "provider_ref": self.provider_ref, "request_fingerprint": self.request_fingerprint,
            "service_id": self.service_id, "service_type_id": self.service_type_id,
            "carrier_ids": self.carrier_ids,
        }


class CarrierQuoteProvider(Protocol):
    name: str

    async def quote(self, conn, req: QuoteRequest) -> QuoteResult: ...


@dataclass(frozen=True)
class IncomingTransfer:
    """Su kien tien VAO da chuan hoa (provider-neutral). amount la so nguyen VND."""
    provider: str
    provider_event_id: str
    direction: str                 # in | out | unknown
    account_number: str | None
    amount_vnd: int | None
    content: str
    reference: str | None
    occurred_at: str | None        # ISO string tu provider (khong parse strict)
    gateway: str | None
    payload_hash: str
    raw_minimal: dict[str, Any]    # ban luu (khong secret)


def payload_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
