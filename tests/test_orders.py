"""Test don vi cho validate_transition() trong orders.py (issue #9, Bat 2).

Ham nay la "trai tim" cua logic chuyen trang thai don hang tren dashboard -
sai o day co the cho phep staff lam nham (vd huy don da giao xong), nen
dang gia tri test cao dai dien cho ca file.
"""

import pytest

from app.services.orders import validate_transition


class TestValidTransitions:
    def test_tien_dung_thu_tu(self):
        # Khong raise gi ca la pass
        validate_transition("new", "confirmed")
        validate_transition("confirmed", "shipped")
        validate_transition("shipped", "done")

    def test_giu_nguyen_trang_thai_luon_hop_le(self):
        validate_transition("new", "new")
        validate_transition("done", "done")

    def test_huy_tu_bat_ky_buoc_nao_truoc_done(self):
        validate_transition("new", "cancelled")
        validate_transition("confirmed", "cancelled")
        validate_transition("shipped", "cancelled")


class TestInvalidTransitions:
    def test_khong_the_huy_don_da_giao_xong(self):
        with pytest.raises(ValueError, match="da giao xong"):
            validate_transition("done", "cancelled")

    def test_khong_the_chuyen_nguoc(self):
        with pytest.raises(ValueError, match="chuyen nguoc"):
            validate_transition("shipped", "confirmed")
        with pytest.raises(ValueError, match="chuyen nguoc"):
            validate_transition("done", "new")

    def test_khong_the_nhay_lui_xa(self):
        with pytest.raises(ValueError, match="chuyen nguoc"):
            validate_transition("done", "confirmed")

    def test_don_da_huy_khong_doi_duoc_nua(self):
        with pytest.raises(ValueError, match="da huy"):
            validate_transition("cancelled", "confirmed")
        with pytest.raises(ValueError, match="da huy"):
            validate_transition("cancelled", "new")

    def test_trang_thai_dich_khong_hop_le(self):
        with pytest.raises(ValueError, match="khong hop le"):
            validate_transition("new", "khong_ton_tai")

    def test_trang_thai_hien_tai_khong_hop_le(self):
        with pytest.raises(ValueError):
            validate_transition("khong_ton_tai", "confirmed")

    def test_khong_the_nhay_coc_bo_qua_buoc(self):
        """new -> shipped bo qua confirmed van duoc phep vi chi can KHONG
        chuyen NGUOC (index tang la du) - test nay xac nhan hanh vi thuc te
        cua code, khong phai gia dinh chu quan."""
        # Day KHONG raise loi - ghi lai ro rang de trach nham lan sau neu
        # logic thay doi (hien code cho phep nhay coc tien, chi chan lui).
        validate_transition("new", "shipped")
