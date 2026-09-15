"""M7 PO/Tester conversational scope gate (CA Directive 286).

M7-specific scope control, ĐỘC LẬP với M5 Gate E full-scope (KHÔNG dùng gate_e_fullscope_* làm M7 scope). 3 trạng thái:
  - `off`    : không tạo/tiến M7 conversation nào.
  - `tester` : CHỈ customer_id nằm trong M7 tester allowlist mới vào M7.
  - `public` : reserved/LOCKED — chưa được phép (treat như off, fail-closed).

Master switch = `settings.m7_conversational_fulfillment`. M7 chỉ chạy khi **master ON VÀ scope cho phép customer hiện tại**.
Allowlist rỗng/malformed -> fail-closed (0 enrolled). Mọi entry point (order-create hook, orchestrator handle_customer_text,
worker cron routing/due, resume/retry) PHẢI gọi cùng `m7_enabled_for()`. Readback chỉ count/hash — KHÔNG PSID/phone/secret.
"""
from __future__ import annotations

import hashlib

from app.config import settings

_STATES = ("off", "tester", "public")


def _parse_ids(csv: str | None) -> set[int]:
    """Parse canonical CSV customer_id: trim, dedupe, BỎ token không hợp lệ (không phải int, <=0). Rỗng -> set rỗng."""
    out: set[int] = set()
    for tok in (csv or "").split(","):
        t = tok.strip()
        if not t:
            continue
        try:
            n = int(t)
        except (ValueError, TypeError):
            continue  # reject invalid token (fail-closed, không nạp rác)
        if n > 0:
            out.add(n)
    return out


def scope() -> str:
    """Scope hiệu lực: off|tester|public. Malformed/khác -> 'off' (fail-closed)."""
    s = (settings.m7_conversational_scope or "off").strip().lower()
    return s if s in _STATES else "off"


def tester_ids() -> set[int]:
    return _parse_ids(settings.m7_tester_customer_ids)


def m7_enabled_for(customer_id: int | None) -> bool:
    """True <=> master ON VÀ scope cho phép customer này. off/public(locked)/allowlist-rỗng -> False (fail-closed).
    Đây là HÀM DUY NHẤT quyết định eligibility — dùng ở MỌI entry point M7."""
    if not settings.m7_conversational_fulfillment:  # master switch
        return False
    sc = scope()
    if sc == "tester":
        return customer_id is not None and int(customer_id) in tester_ids()
    return False  # off hoặc public (locked) -> không ai


async def enabled_for_psid(conn, psid: str | None) -> bool:
    """Tiện ích cho entry point chỉ có psid (orchestrator): map psid -> internal customer_id rồi check eligibility.
    psid không map được customer -> False (fail-closed)."""
    if not settings.m7_conversational_fulfillment:
        return False
    if not psid:
        return False
    cid = await conn.fetchval("SELECT id FROM customers WHERE psid=$1", psid)
    return m7_enabled_for(cid)


def readback() -> dict:
    """Read-only scope readback per container (CA 286 §3): master/scope/allowlist count+hash — KHÔNG lộ ID/PSID."""
    ids = tester_ids()
    h = hashlib.sha256(",".join(str(i) for i in sorted(ids)).encode("utf-8")).hexdigest()[:12] if ids else ""
    return {"master": bool(settings.m7_conversational_fulfillment), "scope": scope(),
            "tester_count": len(ids), "tester_hash": h}
