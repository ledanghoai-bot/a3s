"""Test don vi cho cac ham logic THUAN trong tools.py (issue #9, Bat 2):
regex validate SDT va tinh gia theo bac so luong - KHONG cham DB.
"""

from app.services.tools import PHONE_RE, _unit_price_for_quantity


class TestPhoneRegex:
    def test_so_dien_thoai_hop_le_dau_0(self):
        for prefix in ["03", "05", "07", "08", "09"]:
            phone = prefix + "12345678"
            assert PHONE_RE.match(phone), f"{phone} phai hop le"

    def test_so_dien_thoai_hop_le_dau_84(self):
        assert PHONE_RE.match("+84912345678")
        assert PHONE_RE.match("+84312345678")

    def test_so_dau_khong_hop_le(self):
        """Dau so 01,02,04,06 khong ton tai o VN (theo quy hoach hien tai)."""
        assert not PHONE_RE.match("0112345678")
        assert not PHONE_RE.match("0212345678")
        assert not PHONE_RE.match("0412345678")

    def test_thieu_thua_chu_so(self):
        assert not PHONE_RE.match("091234567")  # thieu 1 so
        assert not PHONE_RE.match("09123456789")  # thua 1 so

    def test_khong_phai_so(self):
        assert not PHONE_RE.match("khong co so dien thoai")
        assert not PHONE_RE.match("")


class TestUnitPriceForQuantity:
    TIERS = [
        {"min_qty": 1, "unit_price_vnd": 170000},
        {"min_qty": 5, "unit_price_vnd": 160000},
        {"min_qty": 20, "unit_price_vnd": 140000},
    ]

    def test_khop_bac_thap_nhat(self):
        assert _unit_price_for_quantity(self.TIERS, 1) == 170000
        assert _unit_price_for_quantity(self.TIERS, 4) == 170000

    def test_khop_bac_giua(self):
        assert _unit_price_for_quantity(self.TIERS, 5) == 160000
        assert _unit_price_for_quantity(self.TIERS, 19) == 160000

    def test_khop_bac_cao_nhat(self):
        assert _unit_price_for_quantity(self.TIERS, 20) == 140000
        assert _unit_price_for_quantity(self.TIERS, 1000) == 140000  # >100 van tinh dung gia bac, chan so luong nam o cho khac (MAX_AUTO_QUANTITY)

    def test_khong_co_bac_nao_khop_tra_ve_none(self):
        """Vd danh sach bac gia rong hoac tat ca bac deu co min_qty > quantity -
        ham phai tra None de create_order/search_products fallback ve price_vnd."""
        assert _unit_price_for_quantity([], 5) is None
        higher_tiers = [{"min_qty": 100, "unit_price_vnd": 130000}]
        assert _unit_price_for_quantity(higher_tiers, 5) is None
