"""M5 "Nửa A" — live address verify + auto-link (CA Directive 196, Review 197 corrections). CUSTOMER-FACING,
default-OFF.

Trong luong Telegram khach: LLM DE XUAT ten tinh/phuong (chi TEN, untrusted) -> resolver M5 verify tat dinh
vao dataset v2 (dataset la chan ly, LLM chi goi y) -> neu ket qua CHINH XAC `auto_verified` + du province+ward
+ traceable dataset active + owner la customer da xac thuc thi ghi customers.current_address_resolution_id
(resolution + pointer + audit trong MOT transaction, khoa hang customer FOR UPDATE de an toan concurrency).
Non-auto (confirm/staff/failed) -> giu resolution/audit lam bang chung, KHONG doi pointer.

Rang buoc (Directive 196 + Review 197):
- C2: CHI kenh Telegram khach + customer_id trong pilot allowlist (address_resolver_pilot_customer_ids, rong =
  khong ai). Channel/scope tu server, khong tin LLM/body/username.
- C3: BAT BUOC event id provider that dang 'tg:<so>' (khong fallback sender_id/timestamp/random) -> thieu/sai =
  skip, 0 side effect.
- C4: khoa customers FOR UPDATE trong tx truoc khi quyet latest-event + update pointer -> 2 event dong thoi khong
  ghi de nguoc; chi event moi hon (theo so message-id server-side) duoc link.
- LLM chi de xuat TEN; code/status/confidence/dataset/owner tu LLM bi bo qua (schema chi co 2 field ten).
- Loi bat NGOAI transaction (caller nuot) -> transaction hong khong bi tai dung; reply/don KHONG bao gio vo.
- KHONG migration, KHONG doi order free-text, Gate E + quote enforcement giu OFF.
"""
from __future__ import annotations

import re

from app.config import settings
from app.db_pool import acquire, release
from app.services import audit_service
from app.services.address import dataset_registry as reg
from app.services.address import resolver

TELEGRAM_CUSTOMER_CHANNEL = "telegram_customer"
_MAX_NAME = 120
_EVENT_RE = re.compile(r"^tg:(\d+)$")  # dinh dang event id Telegram that: 'tg:<message_id>'
_TRAILING_INT = re.compile(r"(\d+)$")  # so cuoi cua idempotency_key da luu = message-id


def _clean_name(v) -> str | None:
    """Chi nhan chuoi ten hop le (§3.3): str, strip, gioi han do dai. Khac -> None (bo qua an toan)."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or len(s) > _MAX_NAME:
        return None
    return s


def _event_seq(event_id) -> int | None:
    """Validate + trich so thu tu (message-id) tu event id Telegram 'tg:<so>'. Sai dang -> None (C3)."""
    if not isinstance(event_id, str):
        return None
    m = _EVENT_RE.match(event_id.strip())
    return int(m.group(1)) if m else None


def _band(conf) -> str:
    c = conf or 0.0
    return ">=0.95" if c >= 0.95 else ("0.80-<0.95" if c >= 0.80 else "<0.80")


def _pilot_scope() -> set[int]:
    out: set[int] = set()
    for tok in (settings.address_resolver_pilot_customer_ids or "").split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.add(int(tok))
    return out


async def _link_eligible(conn, r: dict) -> bool:
    """§3.5: chi link khi auto_verified + du province+ward + traceable dataset active v2."""
    if r.get("status") != "auto_verified":
        return False
    if not (r.get("province_code") and r.get("ward_code")):
        return False
    active = await reg.get_active(conn)
    return bool(active) and r.get("dataset_version") == active


async def verify_and_link(*, psid: str, channel: str | None, province_proposal, ward_proposal,
                          event_id) -> dict:
    """Verify de xuat + auto-link neu du dieu kien. Tra metrics an toan (route/band/linked) — KHONG raw
    address/customer/psid. Co the raise (caller nuot NGOAI transaction). Flag da duoc caller kiem tra."""
    # C3: bat buoc event id that (khong fallback) — thieu/sai -> skip
    seq = _event_seq(event_id)
    if seq is None:
        return {"skipped": "bad_event_id"}
    # C2: chi kenh Telegram khach
    if channel != TELEGRAM_CUSTOMER_CHANNEL:
        return {"skipped": "channel_not_eligible"}
    prov = _clean_name(province_proposal)
    ward = _clean_name(ward_proposal)
    if not prov:  # resolver fail-closed neu thieu province -> bo qua som
        return {"skipped": "no_province_proposal"}
    conn = await acquire()
    try:
        cid = await conn.fetchval("SELECT id FROM customers WHERE psid=$1", psid)
        if cid is None:
            return {"skipped": "no_customer"}  # server-side identity
        if cid not in _pilot_scope():  # C2: pilot allowlist (rong = khong ai)
            return {"skipped": "out_of_pilot_scope"}
        idem = f"lv:{psid}:{event_id}"
        linked = False
        async with conn.transaction():
            # C4: khoa hang customer -> serialize quyet dinh latest-event + update pointer giua cac event
            await conn.execute("SELECT id FROM customers WHERE id=$1 FOR UPDATE", cid)
            r = await resolver.resolve(
                conn, subject_type="customer", subject_id=str(cid), province=prov, ward=ward,
                actor=f"live-verify:{channel}", reason="telegram-live-verify",
                ticket=f"LIVEVERIFY:{event_id}", idempotency_key=idem)
            eligible = await _link_eligible(conn, r)
            if eligible:
                cur_rid = await conn.fetchval(
                    "SELECT current_address_resolution_id FROM customers WHERE id=$1", cid)
                cur_seq = -1
                if cur_rid is not None:
                    cur_key = await conn.fetchval(
                        "SELECT idempotency_key FROM address_resolution WHERE id=$1", cur_rid)
                    m = _TRAILING_INT.search(cur_key or "")
                    cur_seq = int(m.group(1)) if m else -1
                if seq > cur_seq:  # chi link khi event moi hon event dang link
                    await conn.execute(
                        "UPDATE customers SET current_address_resolution_id=$2::uuid WHERE id=$1", cid, r["id"])
                    await audit_service.record(
                        conn, actor_type="cli", action="address.autolink", actor_ref=f"live-verify:{channel}",
                        entity_type="customers", entity_id=str(cid), before=None,
                        after={"resolution_id": r["id"], "status": r["status"],
                               "dataset_version": r["dataset_version"], "event_seq": seq},
                        reason="telegram-live-verify")
                    linked = True
        # M5 upgrade (Directive 214 §6.C + Q2): tra resolution_id REQUEST-SCOPED + may_bind (server-owned).
        # may_bind = eligible (auto_verified + du province+ward + dataset active v2). Chi khi may_bind thi
        # orchestrator moi truyen verified_resolution_id xuong Gate E de bind (sua F2). resolution_id van
        # tra ve du non-may_bind (lam bang chung), nhung KHONG duoc bind.
        return {"status": r["status"], "confidence_band": _band(r.get("confidence")),
                "linked": linked, "customer_id": cid,
                "resolution_id": r["id"], "may_bind": bool(eligible)}
    finally:
        await release(conn)
