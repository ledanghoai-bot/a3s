"""I-B M4-S0: unit test PII detector (AC-M4 nen tang; Directive §9).

Thuan logic — khong DB/Redis/HTTP. Moi nhom co ca case CO DAU va KHONG DAU
(bai hoc CLAUDE.md §6). Gia tri PII trong test la so/ten BIA (synthetic).
"""

import pytest

from app.services.pii.detector import detect
from app.services.pii.normalize import fold, nfc
from app.services.pii.taxonomy import Confidence, RiskClass, SensitiveCategory, SlotType


def _slots(text, slot_type):
    return [s for s in detect(text).spans if s.slot_type == slot_type]


class TestNormalize:
    def test_fold_giu_do_dai_va_offset(self):
        s = nfc("Cà Mau — Đường Lê Lợi")
        assert len(fold(s)) == len(s)
        assert fold(s) == "ca mau — duong le loi"

    def test_fold_dong_nhat_hai_phia(self):
        # cung mot tu co dau/khong dau fold ve cung chuoi
        assert fold(nfc("Phường")) == fold(nfc("phuong"))


class TestPhone:
    @pytest.mark.parametrize("num", [
        "0912345678", "0912 345 678", "0912.345.678", "0912-345-678",
        "+84912345678", "+84 912 345 678", "84912345678", "(+84)912345678",
        "09 1234 5678", "0356789012", "0789012345",
    ])
    def test_cac_dinh_dang_di_dong(self, num):
        spans = _slots(f"sđt của mình là {num} nhé", SlotType.PHONE)
        assert len(spans) == 1
        assert spans[0].confidence == Confidence.HIGH

    def test_khong_dau_va_co_dinh(self):
        assert len(_slots("lien he 0987654321 gap", SlotType.PHONE)) == 1
        landline = _slots("số bàn 02838123456 nhé", SlotType.PHONE)
        assert len(landline) == 1 and landline[0].confidence == Confidence.MEDIUM

    def test_hai_so_trong_mot_tin(self):
        assert len(_slots("goi 0912345678 hoac 0356789012", SlotType.PHONE)) == 2

    def test_offset_tro_dung_gia_tri(self):
        text = nfc("gọi mình qua 0912.345.678 nha")
        span = _slots(text, SlotType.PHONE)[0]
        assert text[span.start:span.end] == "0912.345.678"

    @pytest.mark.parametrize("text", [
        "giá 120000 đồng",  # 6 so — khong phai phone
        "tổng 1.250.000đ",  # tien co dau cham
        "đơn A123 tới đâu",  # ma don
        "năm 2026 hết hạn",
    ])
    def test_khong_bat_nham_so_thuong(self, text):
        assert detect(text).spans == []


class TestName:
    def test_cue_ho_viet_hoa(self):
        spans = _slots("tên mình là Nguyễn Văn An", SlotType.NAME)
        assert len(spans) == 1 and spans[0].confidence == Confidence.HIGH

    def test_cue_thuong_khong_dau(self):
        # khong dau + viet thuong: van bat nho ho VN sau cue
        assert len(_slots("ten minh la nguyen thi thu ha", SlotType.NAME)) == 1

    def test_danh_xung_khong_chan_ten(self):
        spans = _slots("giao cho chị Lan nhé shop", SlotType.NAME)
        assert len(spans) == 1

    def test_hai_nguoi_mot_tin(self):
        spans = _slots("giao cho chị Lan, người đặt là Nguyễn Văn An", SlotType.NAME)
        assert len(spans) == 2

    def test_ho_viet_hoa_khong_cue(self):
        assert len(_slots("Nguyễn Văn An", SlotType.NAME)) == 1

    @pytest.mark.parametrize("text", [
        "tp hồ chí minh còn ship không",  # dia danh, khong phai ten
        "đường Nguyễn Trãi kẹt xe",  # ten duong, khong phai ten nguoi
        "mình là khách quen nhé",  # danh tu vai tro sau cue
    ])
    def test_khong_bat_nham(self, text):
        assert _slots(text, SlotType.NAME) == []

    # --- F-A12-02: dong am gia sau khi bo dau (CLAUDE.md muc 6) -------------------
    # "minh"/"anh"/"mai"/"chi" nam trong _NAME_STOPWORDS vi la dai tu/tu noi, nhung SAU KHI fold()
    # chung trung voi am tiet TEN RIENG rat pho bien -> ten bi cat cut giua chung.
    @pytest.mark.parametrize("text,expected", [
        ("tên mình là Hoàng Minh Tuấn", "Hoàng Minh Tuấn"),   # "Minh" vs dai tu "mình"
        ("tên mình là Vũ Đức Anh", "Vũ Đức Anh"),             # "Anh"  vs dai tu "anh"
        ("tên mình là Phan Thị Mai", "Phan Thị Mai"),         # "Mai"  vs "ngày mai"
        ("tên mình là Đặng Quỳnh Anh", "Đặng Quỳnh Anh"),
        ("em là Hoàng Minh Tuấn ạ", "Hoàng Minh Tuấn"),
    ])
    def test_ten_nhieu_am_tiet_khong_bi_cat_boi_stopword_dong_am(self, text, expected):
        spans = _slots(text, SlotType.NAME)
        assert len(spans) == 1
        assert text[spans[0].start:spans[0].end] == expected

    @pytest.mark.parametrize("text", [
        "mình là khách quen nhé",   # "minh" la dai tu THUONG -> van phai bi chan
        "anh cần thêm 2 hộp nhé",   # "anh" dai tu THUONG
        "mai giao giúp mình nhé",   # "mai" = ngay mai, THUONG
    ])
    def test_stopword_viet_thuong_van_bi_chan(self, text):
        # Chi mien stopword khi token VIET HOA va dang giua cum ten - khong noi long cho tu thuong.
        assert _slots(text, SlotType.NAME) == []


class TestAddress:
    def test_day_du_co_dau(self):
        spans = _slots("giao về số 12 đường Lê Lợi, phường 5, quận 3, TPHCM", SlotType.ADDRESS)
        assert len(spans) == 1 and spans[0].confidence == Confidence.HIGH

    def test_day_du_khong_dau_viet_thuong(self):
        assert len(_slots("giao ve so 12 duong le loi phuong 5 quan 3 tphcm",
                          SlotType.ADDRESS)) == 1

    def test_so_nha_cong_duong_don_le(self):
        spans = _slots("123 duong Nguyen Trai", SlotType.ADDRESS)
        assert len(spans) == 1 and spans[0].confidence == Confidence.MEDIUM

    def test_hai_dia_chi_mot_tin(self):
        text = ("giao sáng ở số 12 đường Lê Lợi quận 3, chiều chuyển về "
                "45 ngõ 78 phố Huế Hà Nội giúp mình")
        assert len(_slots(text, SlotType.ADDRESS)) == 2

    # --- F-A12-02: ranh gioi span dia chi ----------------------------------------
    # Metric gate la `exact_span_match` (start/end khop TUYET DOI), nen lech bien bi tinh CA
    # false-positive LAN false-negative. 3 nhom duoi day la loi bien that do chan doan
    # PHASE1B-M4-DETECTOR-DIAGNOSIS-1-VI.md tim ra tren manifest rehearsal.
    @pytest.mark.parametrize("text,expected", [
        # (a) duoi: ten rieng sau tu khoa hanh chinh phai duoc nuot
        ("giao về 78/9 đường Quang Trung, phường 10, quận Gò Vấp nhé shop",
         "78/9 đường Quang Trung, phường 10, quận Gò Vấp"),
        ("giao về số 9, thôn Đoài, xã Phú Minh, huyện Sóc Sơn nhé shop",
         "số 9, thôn Đoài, xã Phú Minh, huyện Sóc Sơn"),
        # (b) duoi: CHU SO sau tu khoa hanh chinh ("quận 3") - _WORD_RE loai chu so nen truoc day mat
        ("giao về 9 đường Nguyễn Huệ, phường Bến Nghé, quận 1 nhé shop",
         "9 đường Nguyễn Huệ, phường Bến Nghé, quận 1"),
        ("giao về 88 đường Lý Thường Kiệt, phường 7, quận 11 nhé shop",
         "88 đường Lý Thường Kiệt, phường 7, quận 11"),
        # (c) dau: SO NHA TRAN truoc tu khoa duong
        ("giao về 45 đường Nguyễn Trãi, phường 7, quận Thanh Xuân, Hà Nội nhé shop",
         "45 đường Nguyễn Trãi, phường 7, quận Thanh Xuân, Hà Nội"),
        # (d) duoi: cum dia danh sau dau phay cuoi ("..., Hai Bà Trưng")
        ("giao về 34 ngõ 78 phố Huế, phường Ngô Thì Nhậm, Hai Bà Trưng nhé shop",
         "34 ngõ 78 phố Huế, phường Ngô Thì Nhậm, Hai Bà Trưng"),
    ])
    def test_ranh_gioi_span_dung_tuyet_doi(self, text, expected):
        spans = _slots(text, SlotType.ADDRESS)
        assert len(spans) == 1
        assert text[spans[0].start:spans[0].end] == expected

    def test_duoi_cau_viet_thuong_khong_bi_nuot(self):
        # Tin hieu dung la HOA/THUONG: "nhé shop"/"giúp mình" viet thuong -> phai nam NGOAI span.
        text = "giao về 12 đường Lê Lợi, quận 1 giúp mình nhé"
        spans = _slots(text, SlotType.ADDRESS)
        assert len(spans) == 1
        assert text[spans[0].start:spans[0].end] == "12 đường Lê Lợi, quận 1"

    @pytest.mark.parametrize("text", [
        "ship Cà Mau được không?",  # ten tinh don le = hoi vung giao
        "tp hồ chí minh còn ship trong ngày không",  # tp + tinh = dia danh
        "quán gần phố đi bộ không shop",  # "quán"~"quận", "phố" homograph
        "đà nẵng đường xa vậy phí ship nhiêu",  # street+province khong so
        "cà phê này chua quá",  # bay "chua"/"chưa" — khong lien quan dia chi
    ])
    def test_khong_bat_nham_dia_danh_dong_am(self, text):
        assert _slots(text, SlotType.ADDRESS) == []


class TestHighRiskSlots:
    def test_cccd_12_so_khong_phai_phone(self):
        r = detect("CCCD của tôi là 079123456789 nhé")
        assert r.count(SlotType.NATIONAL_ID) == 1
        assert r.count(SlotType.PHONE) == 0
        assert r.risk_class == RiskClass.D2

    def test_stk_cue_thang_prefix_di_dong(self):
        # "stk 09..." la so tai khoan du trung prefix di dong
        r = detect("chuyen khoan toi stk 0912345678 dung khong")
        assert r.count(SlotType.BANK_ACCOUNT) == 1
        assert r.count(SlotType.PHONE) == 0


class TestSensitiveAndRisk:
    @pytest.mark.parametrize("text,cat", [
        ("mình bị tiểu đường uống được không", SensitiveCategory.HEALTH),
        ("em dang mang thai co uong duoc khong", SensitiveCategory.HEALTH),
        ("nhận hàng cần CMND không", SensitiveCategory.IDENTITY_DOC),
    ])
    def test_sensitive_d2(self, text, cat):
        r = detect(text)
        assert cat in r.sensitive_categories
        assert r.risk_class == RiskClass.D2

    def test_risk_d1_khi_chi_co_pii_co_ban(self):
        assert detect("sđt 0912345678").risk_class == RiskClass.D1

    def test_risk_d0_khi_sach(self):
        r = detect("cho mình 2 gói 500g nhé")
        assert r.spans == [] and r.risk_class == RiskClass.D0

    def test_input_rong(self):
        assert detect("").spans == []
        assert detect("   ").risk_class == RiskClass.D0


class TestSpanSafety:
    def test_span_khong_chua_plaintext(self):
        span = _slots("sđt 0912345678", SlotType.PHONE)[0]
        d = span.as_safe_dict()
        assert "0912345678" not in str(d)
        assert set(d) == {"slot_type", "confidence", "reason", "length"}
        # repr dataclass chi co offset/enum — khong co gia tri
        assert "0912345678" not in repr(span)
