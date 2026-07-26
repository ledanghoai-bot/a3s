"""Retry classifier + backoff/jitter (I-B M1). Spec §9.2, §8.2.

Thuan tuy, rng injectable -> unit-testable (assert jitter bounds). Worker (Slice 5) dung module nay.
Khong tuyen bo exactly-once; day la chinh sach at-least-once + dead-letter.
"""
from __future__ import annotations

import random

# Outcome classes (classify_http)
DELIVERED = "delivered"
RETRYABLE = "retryable"
TERMINAL = "terminal"
UNKNOWN = "unknown"

# §9.2 defaults
BASE_SECONDS = 30
CAP_SECONDS = 6 * 3600           # 6h
MAX_ATTEMPTS = 8                 # ~24h tong
RETRY_AFTER_CAP_SECONDS = 24 * 3600
CONNECT_TIMEOUT = 3.0
TOTAL_TIMEOUT = 10.0

_RETRYABLE_STATUS = {408, 425, 429}
_TERMINAL_STATUS = {400, 401, 403, 404, 422}
_CREDENTIAL_ALERT_STATUS = {401, 403}


def classify_http(status: int) -> tuple[str, bool]:
    """Tra (outcome, credential_alert) tu HTTP status.
    2xx -> delivered; 408/425/429/5xx -> retryable; 400/401/403/404/422 -> terminal
    (401/403 kem credential alert). 4xx khac (khong liet ke) -> terminal an toan (khong retry mu)."""
    if 200 <= status < 300:
        return DELIVERED, False
    if status in _TERMINAL_STATUS:
        return TERMINAL, status in _CREDENTIAL_ALERT_STATUS
    if status in _RETRYABLE_STATUS or 500 <= status < 600:
        return RETRYABLE, False
    return TERMINAL, False


def classify_exception(is_timeout: bool) -> str:
    """Provider timeout -> UNKNOWN (§8.2: khong coi la failed ngay, reconcile roi retry).
    Network error khac -> RETRYABLE."""
    return UNKNOWN if is_timeout else RETRYABLE


def should_retry(attempt_no: int, outcome: str) -> bool:
    """Con retry khong: RETRYABLE/UNKNOWN va chua het max attempts."""
    return outcome in (RETRYABLE, UNKNOWN) and attempt_no < MAX_ATTEMPTS


def backoff_seconds(attempt_no: int, retry_after: float | None = None,
                    rng=random.random) -> float:
    """Full jitter exponential backoff. attempt_no >= 1.
    Retry-After hop le duoc uu tien nhung cap 24h. Nguoc lai: uniform[0, min(cap, base*2^(n-1)))."""
    if retry_after is not None and retry_after > 0:
        return min(float(retry_after), float(RETRY_AFTER_CAP_SECONDS))
    exp = min(CAP_SECONDS, BASE_SECONDS * (2 ** (max(1, attempt_no) - 1)))
    return rng() * float(exp)
