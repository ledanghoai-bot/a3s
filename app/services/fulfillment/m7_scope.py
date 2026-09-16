"""M7 PO/Tester conversational scope gate (CA Directive 286).

M7-specific scope control, ĐỘC LẬP với M5 Gate E full-scope (KHÔNG dùng gate_e_fullscope_* làm M7 scope). 3 trạng thái:
  - `off`    : không tạo/tiến M7 conversation nào.
  - `tester` : CHỈ customer_id nằm trong M7 tester allowlist mới vào M7.
  - `public` : reserved/LOCKED — chưa được phép (treat như off, fail-closed).

Master switch = `settings.m7_conversational_fulfillment`. M7 chỉ chạy khi **master ON VÀ scope cho phép customer hiện tại**.

Allowlist fail-closed (CA Review 289 §2 / Directive 286 §1): allowlist rỗng -> 0 enrolled (valid); nhưng nếu có BẤT KỲ
token không rỗng nào KHÔNG phải positive canonical integer (`[1-9][0-9]*`), toàn bộ config bị coi là INVALID -> allowlist
rỗng, KHÔNG ai eligible (không "bỏ token rác nhưng giữ token đúng"). Mọi entry point (order-create hook, orchestrator
handle_customer_text, worker cron routing/due, resume/retry) PHẢI gọi cùng `m7_enabled_for()`. Readback chỉ
count/hash/valid-flag — KHÔNG PSID/phone/secret/raw value.
"""
from __future__ import annotations

import hashlib
import re

from app.config import settings

_STATES = ("off", "tester", "public")
# Positive canonical integer: không dấu, không leading zero, chỉ chữ số. "01"/"+1"/"1.0"/"2x"/"-5"/"0" đều KHÔNG canonical.
_CANON_ID = re.compile(r"^[1-9][0-9]*$")


def _parse_allowlist(csv: str | None) -> tuple[bool, set[int]]:
    """Return (valid, ids). Token rỗng (dấu phẩy thừa/khoảng trắng) được bỏ qua như separator. Bất kỳ token KHÔNG rỗng
    nào không phải positive canonical integer -> config INVALID: trả (False, set()) — fail-closed toàn bộ (CA 289-01).
    Allowlist rỗng hợp lệ -> (True, set()): valid config, 0 enrolled. Duplicate/whitespace hợp lệ -> canonical dedupe set."""
    ids: set[int] = set()
    for tok in (csv or "").split(","):
        t = tok.strip()
        if not t:
            continue  # separator artifact (vd "1,,2" hoặc trailing comma) — không phải giá trị malformed
        if not _CANON_ID.match(t):
            return False, set()  # bất kỳ token rác nào -> toàn bộ allowlist rỗng, fail-closed
        ids.add(int(t))
    return True, ids


def scope() -> str:
    """Scope hiệu lực: off|tester|public. Malformed/khác -> 'off' (fail-closed)."""
    s = (settings.m7_conversational_scope or "off").strip().lower()
    return s if s in _STATES else "off"


def tester_ids() -> set[int]:
    """Effective allowlist (canonical dedupe). Config malformed -> set rỗng (fail-closed)."""
    return _parse_allowlist(settings.m7_tester_customer_ids)[1]


def allowlist_valid() -> bool:
    """True <=> allowlist parse được toàn bộ (rỗng cũng là valid). False <=> có token rác -> fail-closed."""
    return _parse_allowlist(settings.m7_tester_customer_ids)[0]


def m7_enabled_for(customer_id: int | None) -> bool:
    """True <=> master ON VÀ scope=tester VÀ allowlist VALID VÀ customer nằm trong allowlist.
    off/public(locked)/allowlist-malformed/allowlist-rỗng -> False (fail-closed).
    Đây là HÀM DUY NHẤT quyết định eligibility — dùng ở MỌI entry point M7."""
    if not settings.m7_conversational_fulfillment:  # master switch
        return False
    if scope() != "tester":
        return False  # off hoặc public (locked) -> không ai
    valid, ids = _parse_allowlist(settings.m7_tester_customer_ids)
    if not valid:
        return False  # CA 289-01: malformed config -> 0 enrolled, không kích hoạt M7
    return customer_id is not None and int(customer_id) in ids


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
    """Read-only scope readback per container (CA 286 §3 + 289-01): master/scope/allowlist_valid/count+hash —
    KHÔNG lộ ID/PSID/raw value. allowlist_valid=False => config malformed, 0 enrolled."""
    valid, ids = _parse_allowlist(settings.m7_tester_customer_ids)
    h = hashlib.sha256(",".join(str(i) for i in sorted(ids)).encode("utf-8")).hexdigest()[:12] if ids else ""
    return {"master": bool(settings.m7_conversational_fulfillment), "scope": scope(),
            "allowlist_valid": valid, "tester_count": len(ids), "tester_hash": h}
