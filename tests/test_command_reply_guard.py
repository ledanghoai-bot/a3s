"""Unit tests reply_guard + deterministic confirmation (I-B M1 Slice 6). Spec §6.4, §10.4."""
from app.services.command import reply_guard
from app.services.command.receipt import order_confirmation_line

R_OK = {
    "outcome": "succeeded",
    "resource": {"type": "order", "id": 123, "display_id": "#123"},
    "result": {"status": "new", "sku": "3S-100G", "quantity": 1,
               "unit_price_vnd": 170000, "total_vnd": 170000},
}


def test_order_confirmation_line_exact():
    assert (order_confirmation_line("#123", 1, "3S-100G", 170000)
            == "Đơn #123 đã được ghi nhận: 1 × 3S-100G, tổng 170.000đ.")


def test_append_adds_deterministic_line():
    out = reply_guard.append_receipt_lines("Dạ em chốt đơn cho anh nhé.", [R_OK])
    assert "Đơn #123 đã được ghi nhận: 1 × 3S-100G, tổng 170.000đ." in out
    assert out.startswith("Dạ em chốt đơn")


def test_append_skips_when_display_id_already_in_reply():
    # LLM da noi dung ma don -> khong bom lap
    out = reply_guard.append_receipt_lines("Đã tạo đơn #123 cho anh.", [R_OK])
    assert out.count("#123") == 1


def test_append_skips_non_succeeded_and_none():
    rejected = {"outcome": "rejected", "error_code": "insufficient_stock"}
    assert reply_guard.append_receipt_lines("reply", [rejected]) == "reply"
    assert reply_guard.append_receipt_lines("reply", None) == "reply"


def test_append_multiple_orders():
    r2 = {"outcome": "succeeded", "resource": {"display_id": "#124"},
          "result": {"sku": "3S-100G", "quantity": 2, "total_vnd": 340000}}
    out = reply_guard.append_receipt_lines("ok", [R_OK, r2])
    assert "#123" in out and "#124" in out


def test_append_order_id_boundary_not_prefix():
    # FINDING 3: order #12 KHÔNG bị bỏ sót chỉ vì reply chứa số dài hơn '#123'
    r12 = {"outcome": "succeeded", "resource": {"display_id": "#12"},
           "result": {"sku": "3S-100G", "quantity": 1, "total_vnd": 170000}}
    out = reply_guard.append_receipt_lines("Đơn #123 của khách khác đã xong.", [r12])
    assert "Đơn #12 đã được ghi nhận" in out          # #12 vẫn được bơm (không nhầm #123)
    out2 = reply_guard.append_receipt_lines("Đã tạo #12 cho anh.", [r12])
    assert "#12 đã được ghi nhận" not in out2          # #12 xuất hiện đúng token -> bỏ qua


def test_finalize_customer_reply_neutral_when_order_created():
    # CR-08: order đã commit -> reply tức thì TRUNG TÍNH; nội dung LLM bịa (mã đơn/tổng tiền sai)
    # KHÔNG tới khách. Xác nhận chính thức đi qua durable receipt.
    fabricated = "Đơn #999 đã tạo thành công, tổng 5.000.000đ cho anh nhé!"
    out = reply_guard.finalize_customer_reply(fabricated, order_created=True)
    assert out == reply_guard.NEUTRAL_ORDER_REPLY
    assert "#999" not in out and "5.000.000" not in out
    # chưa tạo đơn -> giữ nguyên reply LLM
    kept = reply_guard.finalize_customer_reply("Dạ anh cần thêm thông tin gì ạ?", order_created=False)
    assert kept == "Dạ anh cần thêm thông tin gì ạ?"


def test_shadow_evaluate():
    assert reply_guard.shadow_evaluate(False, [])["consistent"] is True      # khong claim -> ok
    assert reply_guard.shadow_evaluate(True, [123])["consistent"] is True    # claim + receipt -> ok
    s = reply_guard.shadow_evaluate(True, [])                                # claim + KHONG receipt
    assert s["consistent"] is False and s["has_receipt"] is False
