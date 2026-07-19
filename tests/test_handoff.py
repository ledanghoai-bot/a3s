"""Test don vi cho cac ham logic THUAN (khong cham DB) trong handoff.py
(issue #9, Bat 2 - CI thuc su co gia tri, khong con la placeholder).
"""

from app.services.handoff import is_valid_identifier, wants_human


class TestIsValidIdentifier:
    def test_ma_kh_ngan_thuan_so_hop_le(self):
        assert is_valid_identifier("4") is True
        assert is_valid_identifier("42") is True
        assert is_valid_identifier("  7  ") is True  # tu strip khoang trang

    def test_sender_id_telegram_hop_le(self):
        assert is_valid_identifier("tg:5913051767") is True

    def test_sender_id_manual_hop_le(self):
        assert is_valid_identifier("manual:a1b2c3d4e5f6") is True

    def test_chuoi_rong_khong_hop_le(self):
        assert is_valid_identifier("") is False
        assert is_valid_identifier("   ") is False

    def test_go_nham_cum_bot_hien_thi_khong_hop_le(self):
        """Bug thuc te 16/7: staff go nguyen 'Ma KH: 4' thay vi chi go '4'."""
        assert is_valid_identifier("Ma") is False
        assert is_valid_identifier("Ma KH: 4") is False
        assert is_valid_identifier("khach") is False

    def test_manual_sender_id_hoa_khong_hop_le(self):
        """Regex chi chap nhan hex thuong (0-9a-f) - hex hoa se bi tu choi."""
        assert is_valid_identifier("manual:A1B2C3") is False

    def test_tg_sender_id_khong_phai_so_khong_hop_le(self):
        assert is_valid_identifier("tg:abc") is False


class TestWantsHuman:
    def test_cac_cum_tu_chuan_kich_hoat(self):
        assert wants_human("cho em gap nhan vien voi") is True
        assert wants_human("toi muon gap nguoi that") is True
        assert wants_human("chuyen nhan vien giup em") is True
        assert wants_human("goi nhan vien ra day") is True
        assert wants_human("cho gap admin duoc khong") is True
        assert wants_human("em muon gap quan ly") is True

    def test_khong_phan_biet_hoa_thuong(self):
        assert wants_human("Gap Nhan Vien gap") is True
        assert wants_human("GAP NGUOI THAT") is True

    def test_cau_hoi_binh_thuong_khong_kich_hoat(self):
        assert wants_human("gia bao nhieu 1 hu") is False
        assert wants_human("cho hoi cach pha") is False
        assert wants_human("hu 100g con hang khong") is False

    def test_chuoi_rong_khong_kich_hoat(self):
        assert wants_human("") is False
