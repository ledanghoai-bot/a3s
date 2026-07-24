"""Test don vi cho guard CHONG BIA DON trong orchestrator (ham logic thuan
`_reply_claims_order_created`). Guard nay money-critical: chan viec bot bao khach
"da tao don / ma don #..." khi khong co create_order thanh cong trong luot -
loi that da gap (bot tu che "Ma don #3" ma khong goi tool nen DB khong co don).
"""

from app.services.orchestrator import _reply_claims_order_created


class TestReplyClaimsOrderCreated:
    def test_bat_duoc_cau_bia_don_that(self):
        """Chinh xac cau bot da bia trong su co that."""
        reply = "Đơn hàng thứ 2 đã được tạo thành công! - Mã đơn: #3 - 12 hũ - 1.920.000đ"
        assert _reply_claims_order_created(reply) is True

    def test_bat_duoc_cac_bien_the_xac_nhan_don(self):
        for reply in [
            "Đơn của anh đã được tạo, mã đơn #5",
            "Dạ đặt hàng thành công rồi ạ",
            "Em đã lên đơn thành công cho chị",
            "Đơn hàng đã được tạo, giao trong 3 ngày",
        ]:
            assert _reply_claims_order_created(reply) is True, reply

    def test_khong_bat_nham_cau_tu_van_binh_thuong(self):
        for reply in [
            "Còn hàng anh nhé, giá 170.000đ/hũ, anh cho em xin tên và SĐT",
            "Dạ 3S Coffee có 1 sản phẩm là hũ 100g anh nhé",
            "Anh muốn đặt bao nhiêu hũ để em tư vấn giá ạ?",
            "Em xác nhận lại thông tin trước khi lên đơn nhé",
        ]:
            assert _reply_claims_order_created(reply) is False, reply

    def test_khong_phan_biet_hoa_thuong(self):
        assert _reply_claims_order_created("MÃ ĐƠN: #9") is True
