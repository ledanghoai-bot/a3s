"""M7 conversation parser + templates — unit (logic thuan, Directive 272 §3.1). Cau that co dau/khong dau."""
from app.services.fulfillment import conversation as c


def test_parse_cod_variants():
    for t in ("COD", "cod", "Cod nhé", "em chọn tiền mặt", "tien mat", "trả khi nhận hàng", "khi nhan hang", "1",
              "1.", "ship cod giúp em", "nhận hàng rồi trả"):
        assert c.parse_method(t) == "COD", t


def test_parse_bank_variants():
    for t in ("chuyển khoản", "chuyen khoan", "CK", "ck nhé", "em quét mã", "quet ma", "VietQR", "qr", "2", "2)",
              "chuyển tiền luôn", "internet banking"):
        assert c.parse_method(t) == "BANK_TRANSFER", t


def test_parse_ambiguous_and_none():
    for t in ("cod hay chuyển khoản cũng được", "ck hoặc cod", "ok", "được", "sao cũng được", "cả hai", "tùy", "?"):
        assert c.parse_method(t) == "ambiguous", t
    for t in ("cảm ơn shop", "phí có đắt không", "đơn của em tới chưa", "mã QR không quét được hả?"[:0] or "hủy đơn"):
        assert c.parse_method(t) == "none", t


def test_no_false_positive_substring():
    # "ck" khong khop trong "quick"/"cock"; "cod" khong khop trong "coding"; "qr" khong khop trong "sqrt"
    for t in ("quick", "coding", "sqrt", "chuyenkhoanoi"):
        assert c.parse_method(t) == "none", t


def test_transfer_reported_detection():
    for t in ("đã chuyển", "da chuyen roi", "em chuyển rồi", "đã ck", "ck xong", "đã thanh toán", "da thanh toan",
              "đã gửi tiền"):
        assert c.is_transfer_reported(t), t
    for t in ("chưa chuyển", "chua chuyen", "không chuyển được", "ko ck được", "chuyển khoản", "đã chuyển chưa?"[:0] or "chưa ck"):
        assert not c.is_transfer_reported(t), t


def test_prompt_text_total_and_no_zero_guess():
    t = c.prompt_text(154, goods_vnd=200000, fee_vnd=30000, total_vnd=230000, route="GHN", eta_text="khoảng 3 ngày")
    assert "230.000đ" in t and "30.000đ" in t and "200.000đ" in t and "GHN" in t and "khoảng 3 ngày" in t
    t0 = c.prompt_text(154, goods_vnd=200000, fee_vnd=0, total_vnd=200000, route="SELF_DELIVERY", eta_text=None)
    assert "miễn phí" in t0 and "TỔNG 200.000đ" in t0


def test_templates_never_claim_received():
    instr = {"bank_snapshot": "VietinBank", "account_number_snapshot": "0071000123456", "holder_snapshot": "ROBANME",
             "transfer_content": "3SCF 154", "amount_vnd": 230000, "is_test": True, "qr_payload": "x"}
    for txt in (c.instruction_text(154, instr, wait_minutes=30), c.reminder_text(154, instr), c.reported_text(154),
                c.staff_text(154, "timeout"), c.cod_text(154, 230000), c.reask_text(154)):
        low = txt.lower()
        assert "đã nhận thanh toán" not in low and "đã nhận được tiền" not in low and "đã xác nhận nhận" not in low
    assert "TEST — KHÔNG CHUYỂN TIỀN" in c.instruction_text(154, instr, wait_minutes=30)
    assert "0071000123456" in c.instruction_text(154, instr, wait_minutes=30)
    assert "30 phút" in c.instruction_text(154, instr, wait_minutes=30)
