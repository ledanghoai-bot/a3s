"""Canonical JSON + sha256 (I-B M1). Spec §6.1.

Canonical JSON: UTF-8, sort keys, khong whitespace, so o dang chuan. Dung de tinh
request_hash on-dinh (cung input business -> cung hash) phuc vu idempotency conflict
detection (§6.2 cung key + khac hash -> 409). Thuan tuy, khong side effect -> unit-testable.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    """Serialize on-dinh: sort_keys + compact separators + ensure_ascii=False (UTF-8).

    Python json render int nhu int, khong ep float -> so nguyen VND giu nguyen dang.
    KHONG dung cho payload chua float tien te (M1 dung int VND)."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_hash(obj: Any) -> str:
    """sha256 cua canonical JSON — 64 hex ky tu (khop char(64) cot request_hash)."""
    return sha256_hex(canonical_json(obj))
