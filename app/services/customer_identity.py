"""CA Directive 387 §5 + PO Record 386 — identity khach TUONG MINH theo kenh + ChatID bat buoc.

- Kenh LUON do caller truyen tuong minh (listener/webhook/command envelope/API Dashboard). KHONG suy kenh tu tien to psid.
- psid (khoa cu, UNIQUE) giu nguyen quy uoc luu tru theo tung kenh; external_chat_id = ChatID that cua kenh do.
- Ho so khach (customers.name/phone/address) la CHU TAI KHOAN: tao lan dau, KHONG bi ghi de boi nguoi nhan cua cac don
  sau (nguoi nhan luu o orders.shipping_*).
- Dashboard: identity noi bo channel='dashboard', ChatID = 'dashboard:<staff_id>:<uuid>' (unique, khong doan duoc);
  KHONG bao gio gui bot/outbox toi identity nay.
"""
from __future__ import annotations

import uuid

CHANNELS = ("telegram_customer", "messenger", "dashboard")
MESSAGING_CHANNELS = ("telegram_customer", "messenger")
_TG_PREFIX = "tg:"


class IdentityError(ValueError):
    pass


def external_chat_id(channel: str, psid: str) -> str:
    """ChatID that cua KENH DA BIET (khong dung de doan kenh). Telegram luu psid 'tg:<chat_id>' -> chat_id."""
    if channel not in CHANNELS:
        raise IdentityError(f"channel khong hop le: {channel!r}")
    if not psid:
        raise IdentityError("thieu psid/ChatID")
    if channel == "telegram_customer":
        if not psid.startswith(_TG_PREFIX) or len(psid) <= len(_TG_PREFIX):
            raise IdentityError("psid Telegram phai co dang 'tg:<chat_id>' (quy uoc listener)")
        return psid[len(_TG_PREFIX):]
    return psid


def new_dashboard_identity(staff_id: int) -> str:
    """ChatID noi bo cho don Dashboard: namespace + staff tao don + nonce (Record 386)."""
    if not isinstance(staff_id, int) or isinstance(staff_id, bool) or staff_id <= 0:
        raise IdentityError("staff_id bat buoc (so nguyen duong) cho identity Dashboard")
    return f"dashboard:{staff_id}:{uuid.uuid4().hex}"


async def get_existing(conn, psid: str) -> int | None:
    return await conn.fetchval("SELECT id FROM customers WHERE psid=$1", psid) if psid else None


async def ensure_customer(conn, *, channel: str, psid: str, name: str | None = None, phone: str | None = None,
                          address: str | None = None) -> int:
    """Tao khach neu chua co (kenh + ChatID tuong minh). Da co -> tra id, KHONG ghi de ten/SDT/dia chi.
    An toan dong thoi: ON CONFLICT (psid) DO NOTHING roi SELECT."""
    existing = await get_existing(conn, psid)
    if existing is not None:
        return existing
    chat = external_chat_id(channel, psid)
    cid = await conn.fetchval(
        "INSERT INTO customers (psid, channel, external_chat_id, name, phone, address) VALUES ($1,$2,$3,$4,$5,$6) "
        "ON CONFLICT (psid) DO NOTHING RETURNING id", psid, channel, chat, name, phone, address)
    if cid is None:
        cid = await conn.fetchval("SELECT id FROM customers WHERE psid=$1", psid)
    return cid


async def require_existing(conn, psid: str) -> int:
    """Duong staff (ghi chu/pause/price override) KHONG co nguon su that ve kenh -> khach phai ton tai san."""
    cid = await get_existing(conn, psid)
    if cid is None:
        raise IdentityError("khach chua ton tai (duong staff khong tao identity moi)")
    return cid
