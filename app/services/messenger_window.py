"""CA Review 414 §2 — chinh sach gui Messenger theo khung 24 gio (Send API standard messaging).

Meta chi cho Page gui tin thuong toi nguoi da nhan Page trong 24 gio qua. Tin outbox (bien nhan don, nhac thanh toan,
xac nhan thanh toan, hoi thoai M7...) co the phat sinh MUON -> truoc khi goi Send API phai kiem moc tin khach gan
nhat tu nguon DURABLE (bang messages, role='customer' — moi nhanh orchestrator deu ghi tin khach vao day) chu khong
tu Redis/RAM. Ngoai khung -> KHONG goi Send API (caller ket thuc event + mo staff attention).

Bien an toan: tin khach duoc ghi DB sau khi xu ly xong (tre vai giay toi ~1 phut so voi luc Meta nhan) va dong ho
server/Meta co the lech -> chi coi la TRONG khung khi tin gan nhat moi hon (24h - SAFETY_MARGIN). Thieu du lieu
(khong co tin khach nao) = ngoai khung (fail-closed: khong gui mu).
Khong dua vao message tag (chua co bang chung Meta chinh thuc ve tag con hieu luc — CA 414 §2).
"""
from __future__ import annotations

WINDOW_HOURS = 24
SAFETY_MARGIN_MINUTES = 10

_LAST_INBOUND_SQL = (
    "SELECT max(m.created_at) FROM messages m JOIN conversations c ON c.id = m.conversation_id "
    "JOIN customers cu ON cu.id = c.customer_id "
    "WHERE cu.psid = $1 AND cu.channel = 'messenger' AND m.role = 'customer'")


async def window_state(conn, customer_ref) -> dict:
    """-> {'open': bool, 'reason': 'within_window'|'outside_window'|'no_inbound'|'no_recipient',
           'age_minutes': int|None}. Tinh bang dong ho DB (now()) — khong phu thuoc dong ho worker."""
    if not isinstance(customer_ref, str) or not customer_ref:
        return {"open": False, "reason": "no_recipient", "age_minutes": None}
    row = await conn.fetchrow(
        f"SELECT last_at, (EXTRACT(EPOCH FROM (now() - last_at)) / 60)::int AS age_min, "
        f"last_at > now() - make_interval(hours => $2) + make_interval(mins => $3) AS inside "
        f"FROM ({_LAST_INBOUND_SQL}) AS t(last_at)",
        customer_ref, WINDOW_HOURS, SAFETY_MARGIN_MINUTES)
    if row is None or row["last_at"] is None:
        return {"open": False, "reason": "no_inbound", "age_minutes": None}
    if row["inside"]:
        return {"open": True, "reason": "within_window", "age_minutes": row["age_min"]}
    return {"open": False, "reason": "outside_window", "age_minutes": row["age_min"]}
