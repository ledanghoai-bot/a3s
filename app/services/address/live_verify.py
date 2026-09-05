"""M5 "Nửa A" — live address verify + auto-link (CA Directive 196). CUSTOMER-FACING, default-OFF.

Trong luong Telegram khach: LLM DE XUAT ten tinh/phuong (chi TEN, untrusted) -> resolver M5 verify tat dinh
vao dataset v2 (dataset la chan ly, LLM chi goi y) -> neu ket qua CHINH XAC `auto_verified` + du province+ward
+ traceable dataset active + owner la customer da xac thuc thi ghi customers.current_address_resolution_id
(resolution + pointer + audit trong MOT transaction). Non-auto (confirm/staff/failed) -> giu resolution/audit
lam bang chung, KHONG doi pointer.

Nguyen tac (Directive 196):
- LLM chi de xuat TEN; code/status/confidence/dataset/owner tu LLM bi bo qua (schema chi co 2 field ten).
- Customer identity derive SERVER-SIDE tu psid kenh da xac thuc (khong tin body/LLM).
- Idempotency + latest-event: idempotency_key theo (psid+event) -> replay tra ve resolution cu (khong doi
  pointer); relink chi khi event moi hon event cua resolution dang link (so message-id, khong tin timestamp).
- Loi bat NGOAI transaction (caller nuot) -> transaction hong khong bi tai dung; reply/don KHONG bao gio vo.
- KHONG migration, KHONG doi order free-text, Gate E + quote enforcement giu OFF.
"""
from __future__ import annotations

import re

from app.db_pool import acquire, release
from app.services import audit_service
from app.services.address import dataset_registry as reg
from app.services.address import resolver

_MAX_NAME = 120
_TRAILING_INT = re.compile(r"(\d+)(?!.*\d)")  # cum so cuoi cung trong chuoi


def _clean_name(v) -> str | None:
    """Chi nhan chuoi ten hop le (§3.3): str, strip, gioi han do dai. Khac -> None (bo qua an toan)."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or len(s) > _MAX_NAME:
        return None
    return s


def _band(conf) -> str:
    c = conf or 0.0
    return ">=0.95" if c >= 0.95 else ("0.80-<0.95" if c >= 0.80 else "<0.80")


def _msgnum(s: str | None) -> int:
    """Trich message-id (cum so cuoi) tu event/idempotency_key. Khong co -> -1."""
    if not s:
        return -1
    m = _TRAILING_INT.search(s)
    return int(m.group(1)) if m else -1


async def _link_eligible(conn, r: dict) -> bool:
    """§3.5: chi link khi auto_verified + du province+ward + traceable dataset active v2."""
    if r.get("status") != "auto_verified":
        return False
    if not (r.get("province_code") and r.get("ward_code")):
        return False
    active = await reg.get_active(conn)
    return bool(active) and r.get("dataset_version") == active


async def _is_latest(conn, cid: int, event_id: str) -> bool:
    """§3.9: relink chi khi event moi HON event cua resolution dang link (so message-id server-side)."""
    cur_rid = await conn.fetchval("SELECT current_address_resolution_id FROM customers WHERE id=$1", cid)
    if cur_rid is None:
        return True
    cur_key = await conn.fetchval("SELECT idempotency_key FROM address_resolution WHERE id=$1", cur_rid)
    return _msgnum(event_id) > _msgnum(cur_key)


async def verify_and_link(*, psid: str, channel: str | None, province_proposal, ward_proposal,
                          event_id: str) -> dict:
    """Verify de xuat + auto-link neu du dieu kien. Tra metrics an toan (route/band/linked) — KHONG raw
    address/customer. Co the raise (caller nuot NGOAI transaction). Flag da duoc caller kiem tra."""
    prov = _clean_name(province_proposal)
    ward = _clean_name(ward_proposal)
    if not prov:  # resolver fail-closed neu thieu province -> bo qua som, khong goi
        return {"skipped": "no_province_proposal"}
    conn = await acquire()
    try:
        cid = await conn.fetchval("SELECT id FROM customers WHERE psid=$1", psid)
        if cid is None:
            return {"skipped": "no_customer"}  # chua co customer de link (server-side identity)
        idem = f"lv:{psid}:{event_id}"
        linked = False
        async with conn.transaction():
            r = await resolver.resolve(
                conn, subject_type="customer", subject_id=str(cid), province=prov, ward=ward,
                actor=f"live-verify:{channel or 'telegram_customer'}", reason="telegram-live-verify",
                ticket=f"LIVEVERIFY:{event_id}", idempotency_key=idem)
            if await _link_eligible(conn, r) and await _is_latest(conn, cid, event_id):
                await conn.execute(
                    "UPDATE customers SET current_address_resolution_id=$2::uuid WHERE id=$1", cid, r["id"])
                await audit_service.record(
                    conn, actor_type="cli", action="address.autolink",
                    actor_ref=f"live-verify:{channel or 'telegram_customer'}",
                    entity_type="customers", entity_id=str(cid), before=None,
                    after={"resolution_id": r["id"], "status": r["status"],
                           "dataset_version": r["dataset_version"], "event": event_id},
                    reason="telegram-live-verify")
                linked = True
        return {"status": r["status"], "confidence_band": _band(r.get("confidence")),
                "linked": linked, "customer_id": cid}
    finally:
        await release(conn)
