"""M6 customer status reply — deterministic format tests (logic thuan). CA Directive 265 §4.4.
Bot KHONG duoc noi "da thanh toan" khi chua confirmed/reconciled."""
from app.services.fulfillment.status_reply import format_status


def _row(**kw):
    base = {"id": 42, "order_status": "confirmed", "ship_status": None, "carrier": None,
            "tracking_text": None, "eta_text": None, "delivery_fee_vnd": None, "fee_status": "unknown",
            "method": None, "pay_status": None, "amount_due_vnd": None}
    base.update(kw)
    return base


def test_in_transit_shows_carrier_tracking_eta():
    s = format_status(_row(ship_status="in_transit", carrier="GHN", tracking_text="ABC123",
                           eta_text="1–3 ngày"))
    assert "đang được giao" in s and "GHN" in s and "ABC123" in s and "1–3 ngày" in s


def test_delivered():
    assert "đã giao thành công" in format_status(_row(ship_status="delivered"))


def test_fee_quoted_shows_amount_quote_required_not_zero():
    s = format_status(_row(fee_status="quoted", delivery_fee_vnd=30000))
    assert "30.000đ" in s
    s2 = format_status(_row(fee_status="quote_required"))
    assert "nhân viên sẽ báo" in s2 and "0đ" not in s2   # unknown != 0


def test_cod_awaiting_not_paid():
    s = format_status(_row(method="COD", pay_status="awaiting", amount_due_vnd=230000))
    assert "thu tiền khi giao" in s and "đã thanh toán" not in s and "230.000đ" in s


def test_cod_collected_not_reconciled():
    s = format_status(_row(method="COD", pay_status="collected"))
    assert "đang đối soát" in s and "đã thanh toán" not in s


def test_cod_reconciled_paid():
    assert "Đã thanh toán" in format_status(_row(method="COD", pay_status="reconciled"))


def test_transfer_awaiting_shows_deterministic_content_not_paid():
    s = format_status(_row(id=99, method="BANK_TRANSFER", pay_status="awaiting"))
    assert "3SCF 99" in s and "Đã nhận thanh toán" not in s


def test_transfer_reported_not_confirmed():
    s = format_status(_row(method="BANK_TRANSFER", pay_status="reported"))
    assert "shop đang kiểm tra" in s and "Đã nhận thanh toán" not in s


def test_transfer_confirmed_paid():
    assert "Đã nhận thanh toán chuyển khoản" in format_status(_row(method="BANK_TRANSFER", pay_status="confirmed"))
