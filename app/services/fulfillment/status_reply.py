"""M6 customer status reply (CA Directive 265 §4.1/§4.4). Bot doc trang thai DA COMMIT cua shipment/payment
va tra text TAT DINH — KHONG de model tu nhan "da thanh toan". Read-only. None -> khong co don M6-tracked ->
caller fall-through hanh vi cu (handoff)."""
from __future__ import annotations

from app.services.payment.payment_service import transfer_content


def _vnd(n: int | None) -> str:
    return "-" if n is None else f"{n:,}".replace(",", ".") + "đ"


_SHIP = {
    None: "đang được chuẩn bị",
    "pending_prep": "đang được chuẩn bị",
    "ready_to_ship": "đã sẵn sàng để giao",
    "in_transit": "đang được giao",
    "delivered": "đã giao thành công",
    "delivery_failed": "giao chưa thành công, bộ phận giao hàng sẽ liên hệ lại",
    "return_pending": "đang được xử lý hoàn",
}


def format_status(row: dict) -> str:
    oid = row["id"]
    parts = [f"Dạ đơn #{oid} của anh/chị hiện {_SHIP.get(row.get('ship_status'), 'đang được xử lý')}"]
    if row.get("ship_status") == "in_transit":
        extra = []
        if row.get("carrier"):
            extra.append(f"đơn vị {row['carrier']}")
        if row.get("tracking_text"):
            extra.append(f"mã {row['tracking_text']}")
        if extra:
            parts.append(" (" + ", ".join(extra) + ")")
        if row.get("eta_text"):
            parts.append(f". Dự kiến: {row['eta_text']}")
    parts.append(".")

    # Phi giao — unknown != 0
    if row.get("fee_status") == "quoted":
        parts.append(f" Phí giao: {_vnd(row.get('delivery_fee_vnd'))}.")
    elif row.get("fee_status") in ("quote_required", "unknown"):
        parts.append(" Phí giao nhân viên sẽ báo cụ thể.")

    # Thanh toan — TAT DINH theo committed status (khong noi da thanh toan neu chua confirmed/reconciled)
    method, pstat = row.get("method"), row.get("pay_status")
    if method == "COD":
        pmap = {"awaiting": "Thanh toán: COD — thu tiền khi giao.",
                "collected": "Đã thu tiền COD, đang đối soát.",
                "reconciled": "Đã thanh toán (COD đã đối soát)."}
        parts.append(" " + pmap.get(pstat, "Thanh toán: COD."))
    elif method == "BANK_TRANSFER":
        pmap = {"awaiting": f"Thanh toán: chuyển khoản (nội dung: {transfer_content(oid)}).",
                "reported": "Anh/chị đã báo chuyển khoản, shop đang kiểm tra.",
                "confirmed": "Đã nhận thanh toán chuyển khoản."}
        parts.append(" " + pmap.get(pstat, "Thanh toán: chuyển khoản."))
    if row.get("amount_due_vnd") is not None:
        parts.append(f" Số tiền: {_vnd(row['amount_due_vnd'])}.")
    return "".join(parts)


async def order_status_reply(psid: str) -> str | None:
    """Tra text trang thai don M6-tracked gan nhat cua khach (theo psid). None neu khong co."""
    from app.db_pool import acquire, release
    conn = await acquire()
    try:
        cid = await conn.fetchval("SELECT id FROM customers WHERE psid=$1", psid)
        if not cid:
            return None
        row = await conn.fetchrow(
            "SELECT o.id, o.status AS order_status, s.status AS ship_status, s.carrier, s.tracking_text, "
            "s.eta_text, s.delivery_fee_vnd, s.fee_status, p.method, p.status AS pay_status, p.amount_due_vnd "
            "FROM orders o LEFT JOIN shipments s ON s.order_id=o.id LEFT JOIN payments p ON p.order_id=o.id "
            "WHERE o.customer_id=$1 AND (s.id IS NOT NULL OR p.id IS NOT NULL) "
            "ORDER BY o.created_at DESC LIMIT 1", cid)
        return format_status(dict(row)) if row else None
    finally:
        await release(conn)
