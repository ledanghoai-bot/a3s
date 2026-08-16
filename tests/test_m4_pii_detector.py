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


class TestNumericSlotPrecedence:
    """F-NUM-01/F-NUM-02 — thu tu uu tien cho day 12 chu so.

    Truoc correction, nhanh "12 so -> national_id" nuot MOI day 12 chu so va `continue` ngay, nen
    so tai khoan 12 so bi gan nham va ma don 12 so thanh false positive.

    Thu tu duoc CA chot (quyet dinh duoc, khong mo ho):
      1. cue CCCD/CMND        -> national_id HIGH
      2. cue tai chinh        -> bank_account HIGH
      3. cue don hang/giao dich -> khong gan slot nao
      4. khong cue            -> national_id MEDIUM (GIU fallback, huong (ii) CA chon)
    """

    # --- F-NUM-01: bank account 8-19 chu so, GOM length 12 ---
    @pytest.mark.parametrize("digits", [
        "71000123",          # 8
        "710001234",         # 9
        "7100012345",        # 10
        "71000123456",       # 11
        "710001234567",      # 12  <- chinh la ca bi gan nham truoc day
        "7100012345678",     # 13
        "71000123456789",    # 14
        "710001234567890",   # 15
        "7100012345678901",  # 16
    ])
    def test_bank_account_moi_do_dai(self, digits):
        spans = _slots(f"chuyen khoan toi STK {digits} nhe", SlotType.BANK_ACCOUNT)
        assert len(spans) == 1
        assert spans[0].confidence == Confidence.HIGH

    @pytest.mark.parametrize("digits", [
        "71234567890123456",    # 17
        "712345678901234567",   # 18
        "7123456789012345678",  # 19
    ])
    def test_bank_17_den_19_so_duoc_nhan(self, digits):
        """PO policy B: bank account 8-19 so.

        Truoc do 17-19 so CO cue `STK` bi silent miss (nhanh bank chan cung <= 16). PO khong chap
        nhan bo sot PII chi vi do dai, nen tran duoc nang len 19.

        Ban dau Dev khoa HANH VI CU lai bang test nay (assert khong nhan gi) theo dung chi dao CA
        "khong noi policy ngam". Khi PO chot policy B, chinh test do FAIL va buoc phai sua tuong
        minh — dung muc dich thiet ke: khong the doi hanh vi ma khong ai thay.
        """
        text = f"chuyen khoan toi STK {digits} nhe"
        spans = _slots(text, SlotType.BANK_ACCOUNT)
        assert len(spans) == 1
        assert text[spans[0].start:spans[0].end] == digits
        assert spans[0].confidence == Confidence.HIGH

    @pytest.mark.parametrize("text,expected", [
        ("STK 1234 5678 9012 34567 nhe", "1234 5678 9012 34567"),              # 17 so + khoang trang
        ("so tai khoan 1234-5678-9012-345678 nhe", "1234-5678-9012-345678"),   # 18 so + gach
        ("tai khoan 1234.5678.9012.3456789 nhe", "1234.5678.9012.3456789"),    # 19 so + cham
    ])
    def test_bank_17_den_19_so_co_dau_phan_tach(self, text, expected):
        """Directive doi 'at least one separator variation' cho moi length 17/18/19.

        Do duoc mot loi RIENG khi lam phan nay: noi rieng tran do dai (16->19) VAN CHUA DU, vi
        `_DIGITRUN_RE` con chan TONG SO KY TU THO o 20. '1234-5678-9012-345678' (18 so + 3 gach =
        21 ky tu) bi CAT thanh '1234-5678-9012'. Da noi `{6,18}` -> `{6,21}` (toi da 23 ky tu) de
        du cho 19 so + 4 dau phan tach.
        """
        spans = _slots(text, SlotType.BANK_ACCOUNT)
        assert len(spans) == 1
        assert text[spans[0].start:spans[0].end] == expected

    @pytest.mark.parametrize("text", [
        "ma giao dich 12345678901234567 da chuyen tien",
        "ma tham chieu chuyen khoan 123456789012345678 nhe",
        "noi dung chuyen khoan 1234567890123456789 da gui",
        "don hang 12345678901234567 thanh toan roi",
        "ma don 123456789012345678 da chuyen khoan",
        "order 1234567890123456789 paid",
        "transaction 12345678901234567 pending",
        "chuyen 123456789012345678 dong nhe",
        "hoa don 1234567890123456789 da thanh toan",
        "ma van don 12345678901234567 giao roi",
    ])
    def test_17_den_19_so_ngu_canh_tai_chinh_nhung_khong_phai_STK(self, text):
        """Dieu kien DO PRECISION cua viec noi tran (Directive: "khong duoc ne").

        Day la cac day 17-19 so nam trong ngu canh tai chinh/don hang nhung KHONG co cue trong
        `_BANK_CUES`, nen luat moi KHONG duoc phep kich hoat. Neu mot ngay nao do chung bi bat,
        nghia la viec noi tran da lam hong precision.
        """
        assert _slots(text, SlotType.BANK_ACCOUNT) == []
        assert _slots(text, SlotType.NATIONAL_ID) == []

    @pytest.mark.parametrize("text", [
        "chuyen khoan toi STK 710001234567 nhe",
        "stk 710001234567 vietcombank nhe",
        "STK 710001234567",
        "so tai khoan 710001234567 nhe",
        "tai khoan 710 001 234 567 nhe",   # co khoang trang
    ])
    def test_bank_12_so_khong_con_bi_gan_national_id(self, text):
        assert len(_slots(text, SlotType.BANK_ACCOUNT)) == 1
        assert _slots(text, SlotType.NATIONAL_ID) == []

    # --- national_id CO cue van phai thang ---
    @pytest.mark.parametrize("text", [
        "CCCD cua toi la 079000012345 nhe",
        "cccd cua toi la 079000012345 nhe",
        "can cuoc 079000012345 nhe shop",
        "CCCD cua toi la 079 000 012345 nhe",
        "CCCD cua toi la 079.000.012345 nhe",
    ])
    def test_national_id_co_cue(self, text):
        spans = _slots(text, SlotType.NATIONAL_ID)
        assert len(spans) == 1 and spans[0].confidence == Confidence.HIGH

    @pytest.mark.parametrize("text,expect_bank", [
        # Cue tham chieu GAN so hon cue tai chinh -> KHONG gan bank (day la ma GD/ma don).
        ("so tai khoan, ma giao dich 12345678901234567 nhe", False),
        ("STK va ma don 123456789012345678 nhe", False),
        # Cue tai chinh GAN hon -> van la so tai khoan that.
        ("ma giao dich cho STK 12345678901234567 nhe", True),
        # `ma tham chieu` gio nam trong tu vung loai tru (PO §1.3) va gan hon -> khong gan.
        ("tai khoan nhan tien, ma tham chieu 1234567890123456789 nhe", False),
    ])
    def test_conflict_bank_cue_va_reference_cue_THEO_POLICY_PO(self, text, expect_bank):
        """F-NUM-03: cue GAN NHAT co hieu luc thang (PO policy §1.1).

        TRUOC DAY test nay ten `..._HANH_VI_HIEN_TAI` va khoa hien trang SAI (3 ca dau deu ra bank,
        ca 4 silent miss) vi Dev khong duoc tu dat precedence. PO da quyet o
        `PHASE1B-M4-F-NUM-03-PO-POLICY-DECISION-AND-PR-PREPARATION-DIRECTIVE-VI.md`, nen ky vong
        doi theo — va doi TUONG MINH o day, dung nhu muc dich cua test cu.

        Luu y ca 4: truoc kia no "dung" chi vi cue `tai khoan` roi ngoai cua so 30, KHONG phai vi he
        thong hieu `ma tham chieu`. Gio no dung vi ly do THAT: `ma tham chieu` da nam trong tu vung
        loai tru va dung gan so hon.
        """
        got = _slots(text, SlotType.BANK_ACCOUNT)
        assert (len(got) == 1) is expect_bank

    def test_conflict_policy_nid_vs_bank_theo_PO_decision_B(self):
        """PO decision B (`...F-NUM-01-VS-F-NUM-03-PO-DECISION-VI.md`): trong CUNG MENH DE, cue GAN
        NHAT thang — ke ca khi cue kia la giay to tuy than.

        TRUOC DAY test nay ten `test_conflict_policy_nid_cue_thang_bank_cue` va khoa policy F-NUM-01
        ("cue giay to LUON thang"). Khi implement F-NUM-03, chinh test nay chuyen do va lam lo ra va
        cham giua hai policy deu co authority. Dev KHONG tu chon ben: giu policy cu + bao finding.
        PO sau do thu hoi ngoai le F-NUM-01 cho rieng cap national_id/bank_account.

        Day dung la muc dich cua mot test khoa policy: doi hanh vi thi phai doi test tuong minh, va
        viec doi test buoc phai co mot quyet dinh co ten di kem.
        """
        text = "CCCD va STK 079000012361 nhe"          # `STK` gan so hon `CCCD`
        assert len(_slots(text, SlotType.BANK_ACCOUNT)) == 1
        assert _slots(text, SlotType.NATIONAL_ID) == []

    # --- F-NUM-02: cue loai tru -> KHONG gan national_id ---
    @pytest.mark.parametrize("text", [
        "don hang 079000012352 toi chua shop",
        "đơn hàng 079000012353 giao chua",
        "ma don 079000012354 kiem tra giup",
        "mã đơn 079000012355 sao roi shop",
        "ma giao dich 079000012356 da chuyen",
        "mã giao dịch 079000012357 nhe",
        "order 079000012358 status the nao",
        "transaction 079000012359 pending",
        "ORDER 079000012360 chua toi",       # hoa - fold ve cung dang
        "Đơn Hàng 079000012361 dau roi",     # hoa + dau
    ])
    def test_ma_don_giao_dich_khong_phai_national_id(self, text):
        assert _slots(text, SlotType.NATIONAL_ID) == []

    def test_bare_12_so_van_giu_fallback_national_id(self):
        # CA chon huong (ii): GIU fallback de khong tut recall khi khach chi gui so CCCD tran.
        spans = _slots("079000012350 la so cua minh", SlotType.NATIONAL_ID)
        assert len(spans) == 1 and spans[0].confidence == Confidence.MEDIUM

    def test_cmnd_9_so_co_cue_van_hoat_dong(self):
        assert len(_slots("chung minh nhan dan 079000123 nhe", SlotType.NATIONAL_ID)) == 1

    # --- non-regression ---
    @pytest.mark.parametrize("text,slot", [
        ("lien he 0301234567 nhe shop", SlotType.PHONE),
        ("sdt cua minh 0912345678", SlotType.PHONE),
        ("lien he +84 301234567 nhe", SlotType.PHONE),
    ])
    def test_phone_khong_regression(self, text, slot):
        assert len(_slots(text, slot)) == 1

    def test_so_tien_van_khong_bi_bat(self):
        assert detect("chuyen 71000123456 dong nhe").spans == []


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


class TestFNum03CueDistanceClause:
    """F-NUM-03 — cue gan nhat thang + quy tac menh de bat doi xung + tu vung loai tru.

    Policy: `PHASE1B-M4-F-NUM-03-PO-POLICY-DECISION-AND-PR-PREPARATION-DIRECTIVE-VI.md` §1.
    Thiet ke + so lieu do: `PHASE1B-M4-F-NUM-03-DESIGN-PROPOSAL-VI.md`.
    """

    # --- D1: cue GAN NHAT thang, khong phai thu tu `if` trong code ---
    @pytest.mark.parametrize("text,expect_bank", [
        ("so tai khoan, ma giao dich 12345678901234567 nhe", False),
        ("STK va ma don 123456789012345678 nhe", False),
        ("ma giao dich cho STK 12345678901234567 nhe", True),
        ("tai khoan nhan tien, ma tham chieu 1234567890123456789 nhe", False),
    ])
    def test_d1_cue_gan_nhat_quyet_dinh(self, text, expect_bank):
        assert (len(_slots(text, SlotType.BANK_ACCOUNT)) == 1) is expect_bank

    # --- D2: khong con vach dung 30 ky tu ---
    @pytest.mark.parametrize("text", [
        "stk 71000123456",
        "stk cua em o ngan hang ben do la 71000123456",
        "so tai khoan cua minh ben ngan hang ACB la 71000123456",
        "stk cua em o ngan hang ben do la 71000123456 khong dau cau nao",
    ])
    def test_d2_cue_xa_van_bat_duoc_trong_cua_so_80(self, text):
        assert len(_slots(text, SlotType.BANK_ACCOUNT)) == 1

    def test_d2_bien_cua_so_80_la_bien_THAT(self):
        """Kiem CA HAI phia cua bien, khong tin mot phia (bai hoc CLAUDE.md §6)."""
        assert len(_slots("stk " + "x" * 60 + " 71000123456", SlotType.BANK_ACCOUNT)) == 1
        assert _slots("stk " + "x" * 76 + " 71000123456", SlotType.BANK_ACCOUNT) == []

    # --- D2: quy tac menh de BAT DOI XUNG ---
    @pytest.mark.parametrize("text", [
        "so tai khoan cua minh, 71000123456",
        "stk cua em, vietcombank, 71000123456",
        "so tai khoan\n71000123456",
    ])
    def test_d2_cue_CUNG_nhom_duoc_vuot_dau_phay_va_xuong_dong(self, text):
        """Kieu viet rat pho bien cua nguoi Viet — cat hai chieu tai dau phay se lam mat cue nay.

        Ban thiet ke dau tien (cat hai chieu) hong dung 2 ca dau; ghi lai o day de khong ai
        'don dep' quy tac bat doi xung ma khong biet vi sao no bat doi xung.
        """
        assert len(_slots(text, SlotType.BANK_ACCOUNT)) == 1

    def test_d2_cue_CANH_TRANH_chi_co_hieu_luc_trong_menh_de_hien_tai(self):
        # `ma giao dich` o menh de truoc -> khong chan duoc `stk` o menh de nay.
        assert len(_slots("ma giao dich\nstk 71000123456", SlotType.BANK_ACCOUNT)) == 1

    # --- D3: tu vung loai tru mo rong (PO §1.3) ---
    @pytest.mark.parametrize("text", [
        "ma van don 1234567890123456 cua em dau roi",
        "ma tra cuu 079000012345 la gi",
        "ma hoa don 079000012346 shop oi",
    ])
    def test_d3_tu_vung_tham_chieu_khong_thanh_national_id(self, text):
        assert _slots(text, SlotType.NATIONAL_ID) == []

    def test_d3_khong_vo_hieu_hoa_bank_cue_GAN_HON(self):
        """Rang buoc PO §1.4: cue tham chieu KHONG duoc chan mot bank cue gan hon cung menh de."""
        assert len(_slots("ma tham chieu cho stk 71000123456", SlotType.BANK_ACCOUNT)) == 1

    # --- PO decision B: collision nid vs bank quyet bang KHOANG CACH trong cung menh de ---
    @pytest.mark.parametrize("text,expect", [
        ("CCCD va STK 079000012361 nhe", SlotType.BANK_ACCOUNT),   # `STK` gan hon
        ("stk cccd 079000012361", SlotType.NATIONAL_ID),           # `cccd` gan hon
    ])
    def test_collision_cung_menh_de_cue_gan_nhat_thang(self, text, expect):
        """PO decision B — thu hoi ngoai le F-NUM-01 cho rieng cap national_id/bank_account.

        Hai ca nay DOI XUNG nhau co y: cung mot cap cue, chi doi thu tu, va ket qua phai dao theo.
        Neu chi test mot chieu thi khong phan biet duoc 'cue gan nhat thang' voi 'mot loai luon
        thang loai kia'.
        """
        other = (SlotType.NATIONAL_ID if expect is SlotType.BANK_ACCOUNT
                 else SlotType.BANK_ACCOUNT)
        assert len(_slots(text, expect)) == 1
        assert _slots(text, other) == []

    def test_collision_KHONG_tran_qua_menh_de_khac(self):
        """Ranh gioi PO nhan manh: cue canh tranh o menh de khac KHONG duoc doi type so local.

        Neu quy tac bi ap xuyen menh de thi so thu 2 se bi keo ve `national_id` (do `cccd` dung
        dau cau), hoac so thu 1 bi keo ve `bank_account`.
        """
        text = "cccd 079012345678, stk 71000123456"
        nid = _slots(text, SlotType.NATIONAL_ID)
        bank = _slots(text, SlotType.BANK_ACCOUNT)
        assert len(nid) == 1 and text[nid[0].start:nid[0].end] == "079012345678"
        assert len(bank) == 1 and text[bank[0].start:bank[0].end] == "71000123456"

    def test_collision_khong_tran_nguoc_tu_menh_de_sau(self):
        """Chieu con lai: cue o menh de SAU cung khong duoc voi nguoc len so o menh de truoc."""
        text = "stk 71000123456, cccd 079012345678"
        bank = _slots(text, SlotType.BANK_ACCOUNT)
        nid = _slots(text, SlotType.NATIONAL_ID)
        assert len(bank) == 1 and text[bank[0].start:bank[0].end] == "71000123456"
        assert len(nid) == 1 and text[nid[0].start:nid[0].end] == "079012345678"

    # --- Doi chung: khong duoc pha cac loai khac ---
    @pytest.mark.parametrize("text", [
        "sdt cua minh la 0901234567 nhe shop",
        "so dien thoai lien he khi giao hang la 0901234567",
        "sdt minh day, 0901234567",
    ])
    def test_phone_khong_bi_anh_huong(self, text):
        assert len(_slots(text, SlotType.PHONE)) == 1

    def test_emoji_chen_giua_cue_va_so(self):
        """Emoji la ky tu ngoai BMP — kiem offset/cua so khong lech vi no."""
        assert len(_slots("stk 🌟 71000123456", SlotType.BANK_ACCOUNT)) == 1
