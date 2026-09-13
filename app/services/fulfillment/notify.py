"""M6 customer notification (CA Directive 265 §4.4). Qua transactional outbox co san (insert_outbox),
template TAT DINH — KHONG de model tu nhan da thanh toan. Event gan order identity + dedupe_key (effective-once,
retry khong tao logical event trung). command_id=None (M6 event trong allowlist CHECK migration 064).

Best-effort: chi enqueue khi resolve duoc kenh khach (telegram_customer/messenger). Order origin dashboard/
khong co kenh bot -> skip (khong loi). insert_outbox nam trong CUNG transaction voi state change (atomic).
"""
from __future__ import annotations

from app.services.command import repository as cmd_repo
from app.services.payment.payment_service import transfer_content

MAX_ATTEMPTS = 8
_CUSTOMER_DEST = {"telegram_customer", "messenger"}


async def _customer(conn, order_id: int):
    """Tra (destination_channel, psid) neu order co kenh khach bot; None neu khong (skip notify)."""
    row = await conn.fetchrow(
        "SELECT o.origin_channel, cu.psid FROM orders o JOIN customers cu ON cu.id=o.customer_id WHERE o.id=$1",
        order_id)
    if not row or row["origin_channel"] not in _CUSTOMER_DEST or not row["psid"]:
        return None
    return row["origin_channel"], row["psid"]


async def _enqueue(conn, order_id: int, *, event_type: str, dedupe_key: str, text: str) -> None:
    who = await _customer(conn, order_id)
    if not who:
        return
    dest, psid = who
    await cmd_repo.insert_outbox(
        conn, command_id=None, event_type=event_type, event_version=1, destination=dest,
        dedupe_key=dedupe_key, payload={"customer_ref": psid, "order_id": order_id, "text": text},
        max_attempts=MAX_ATTEMPTS)


async def notify_shipment(conn, order_id: int, *, to_status: str, sh: dict) -> None:
    """Thong bao khach khi shipment doi trang thai (handover/delivered/failed). dedupe theo (order, status)."""
    if to_status == "in_transit":
        extra = ""
        bits = []
        if sh.get("carrier"):
            bits.append(f"đơn vị {sh['carrier']}")
        if sh.get("tracking_text"):
            bits.append(f"mã {sh['tracking_text']}")
        if bits:
            extra = " (" + ", ".join(bits) + ")"
        eta = f" Dự kiến: {sh['eta_text']}." if sh.get("eta_text") else ""
        await _enqueue(conn, order_id, event_type="shipment.handover.notify",
                       dedupe_key=f"shipment_handover:{order_id}",
                       text=f"Dạ đơn #{order_id} của anh/chị đang được giao{extra}.{eta}")
    elif to_status == "delivered":
        await _enqueue(conn, order_id, event_type="shipment.delivered.notify",
                       dedupe_key=f"shipment_delivered:{order_id}",
                       text=f"Dạ đơn #{order_id} đã giao thành công. Cảm ơn anh/chị đã tin dùng 3S Coffee ạ!")
    elif to_status in ("delivery_failed", "return_pending"):
        await _enqueue(conn, order_id, event_type="shipment.failed.notify",
                       dedupe_key=f"shipment_failed:{order_id}:{to_status}",
                       text=(f"Dạ đơn #{order_id} giao chưa thành công, bộ phận giao hàng sẽ liên hệ lại "
                             "với anh/chị ạ."))


async def notify_payment(conn, order_id: int, *, kind: str, new_status: str) -> None:
    """Thong bao khach khi payment tien trien. check_request (khach bao chuyen khoan -> ack shop kiem tra);
    confirmed (transfer confirmed / COD reconciled -> shop da nhan tien)."""
    if kind == "customer_reported":
        await _enqueue(conn, order_id, event_type="payment.check_request.notify",
                       dedupe_key=f"payment_check:{order_id}",
                       text=(f"Dạ shop đã nhận thông tin chuyển khoản đơn #{order_id} (nội dung "
                             f"{transfer_content(order_id)}), đang kiểm tra và sẽ xác nhận với anh/chị ạ."))
    elif (kind == "shop_confirmed_received" and new_status == "confirmed") or \
         (kind == "reconciled" and new_status == "reconciled"):
        await _enqueue(conn, order_id, event_type="payment.confirmed.notify",
                       dedupe_key=f"payment_confirmed:{order_id}",
                       text=f"Dạ shop đã xác nhận nhận thanh toán đơn #{order_id}. Cảm ơn anh/chị ạ!")
