"""I-B M4-S0 — PII detector cuc bo (rule/regex thuan, KHONG model, KHONG vendor).

Phat hien phone / name / address / national_id / bank_account + phan loai
sensitive disclosure (D2) trong tin nhan khach tieng Viet.

Nguyen tac:
- Fold dau o CA HAI PHIA (van ban + tu dien) qua normalize.fold — giu offset 1:1
  (bai hoc CLAUDE.md §6: khong bo dau mot phia; test ca co dau lan khong dau).
- PIISpan CHI luu offset + metadata, KHONG luu plaintext gia tri => span/result
  serialize/log an toan PII. Ai co van ban goc thi tu cat theo offset (S1 se dung
  cho Slot Store; S0 shadow chi dem).
- Ham detect() co the raise binh thuong — viec nuot loi la trach nhiem cua
  shadow.shadow_scan (containment o bien, khong giau loi trong lo giua).
"""

import re
from dataclasses import dataclass, field

from app.services.pii.normalize import fold, nfc
from app.services.pii.taxonomy import (
    Confidence,
    ReasonCode,
    RiskClass,
    SensitiveCategory,
    SlotType,
)

# ---------------------------------------------------------------------------
# Tu dien (TAT CA o dang da fold — so khop tren ban fold cua van ban)
# ---------------------------------------------------------------------------

# Ho VN pho bien (fold). LUU Y dong am voi tu thuong: "le", "la", "do", "ho",
# "ly", "lam", "mai", "dao", "ta", "vu" — vi vay ho CHI duoc tinh khi dung sau
# name-cue hoac mo dau chuoi viet hoa (xem _detect_names), khong match tro troi.
_SURNAMES = {
    "nguyen", "tran", "le", "pham", "hoang", "huynh", "phan", "vu", "vo",
    "dang", "bui", "do", "ho", "ngo", "duong", "ly", "dinh", "truong", "lam",
    "mai", "trinh", "dao", "doan", "luong", "luu", "ta", "thai", "chau", "cao",
    "kieu", "quach", "tang", "tong", "vuong", "phung", "dam", "han", "quan",
}

# Cum dia danh nhieu tu de nham thanh ten nguoi (fold) — chan o _detect_names.
_PLACE_BLOCKLIST = {"ho chi minh", "phan thiet", "vung tau", "chau doc", "cao bang"}

# Name cue (fold), sap theo do dai giam dan de regex an cum dai nhat truoc.
_NAME_CUES = sorted(
    [
        "ten day du la", "ten nguoi nhan la", "nguoi nhan ten la", "ten minh la",
        "ten em la", "ten anh la", "ten chi la", "ten toi la", "nguoi nhan la",
        "nguoi nhan ten", "nguoi dat la", "ten la", "minh la", "em la", "anh la",
        "chi la", "toi la", "gui cho", "giao cho", "ship cho", "dat cho",
        "nguoi nhan", "ten",
    ],
    key=len,
    reverse=True,
)
_NAME_CUE_RE = re.compile(r"\b(?:" + "|".join(re.escape(c) for c in _NAME_CUES) + r")\b")
# Cue "yeu": mot minh no chua du tin cay -> doi hoi ho VN hoac viet hoa moi tinh.
_WEAK_CUES = {"ten", "nguoi nhan", "gui cho", "giao cho", "ship cho", "dat cho"}

# Token KHONG THE la ten (fold) — cat chuoi token sau cue. Gom tu chuc nang,
# danh tu vai tro, tu domain ca phe hay gap ngay sau cue.
_NAME_STOPWORDS = {
    "nhe", "nha", "a", "aj", "add", "gium", "dum", "giup", "voi", "o", "tai",
    "so", "sdt", "dt", "dien", "thoai", "dia", "chi", "giao", "ship", "gui",
    "den", "toi", "va", "con", "la", "khong", "chua", "duoc", "dc", "ok",
    "order", "don", "hang", "muon", "can", "dat", "mua", "nhan", "nguoi", "khach",
    "quen", "moi", "cu", "ca", "phe", "cafe", "coffee", "goi", "hop", "tui",
    "ban", "minh", "em", "anh", "chi", "co", "chu", "bac", "ong", "ba",
    "nhan vien", "shipper", "cho", "ne", "day", "do", "ay", "luon", "lun",
    "gap", "som", "truoc", "sau", "ngay", "mai", "nay",
}

# Phone cue (fold) — dung cho day so khong ro prefix.
_PHONE_CUES = ("sdt", "so dien thoai", "dien thoai", "phone", "zalo", "lien he",
               "hotline", "goi", "so may", "dt")
_NID_CUES = ("cmnd", "cccd", "can cuoc", "chung minh", "ho chieu", "passport")
_BANK_CUES = ("stk", "so tai khoan", "tai khoan", "so the")
# F-NUM-02: cue cho thay day so la MA DON/MA GIAO DICH — KHONG phai giay to tuy than. Ap dung DUY
# NHAT cho nhanh fallback "12 so khong cue" (xem `_detect_numeric_slots`), nen cue CCCD/CMND tuong
# minh van thang (khach noi "cccd 0790..." thi van la national_id du cau co chu "don hang").
#
# Cac chuoi o day la dang DA FOLD (bo dau, chu thuong) vi `_has_cue` so khop tren `folded` — nho do
# "đơn hàng"/"Đơn Hàng"/"DON HANG" deu quy ve "don hang", khong can liet ke bien the hoa/dau.
_NID_EXCLUSION_CUES = ("don hang", "ma don", "ma giao dich", "order", "transaction")

# Thanh phan dia chi (fold). "pho" dong am "phở" (fold ca hai = "pho") — chap nhan
# vi 1 thanh phan don le KHONG bao gio tao span (can >=2 hoac so nha + duong).
_STREET_KW_RE = re.compile(
    r"\b(?:duong|pho|ngo|hem|ngach|kiet|khu pho|khu do thi|kdc|chung cu|"
    r"toa nha|toa|block|lo|ap|thon|xom|to)\b"
)
# Tu khoa hanh chinh DONG AM voi tu thuong sau khi fold ("quận"~"quán",
# "xã"~"xa" xa xoi, "phường"~"phương") — bai hoc CLAUDE.md §6. Vi vay:
# 1) regex chi bat KEYWORD (group 1), phan sau kiem rieng;
# 2) chi tinh la thanh phan dia chi khi ngay sau keyword la CHU SO hoac CHU HOA
#    (tren ban NFC goc): "quận 3", "phường Yên Hòa" ✓ — "quán gần", "xa vậy" ✗.
_ADMIN_KW_RE = re.compile(
    r"\b(phuong|quan|huyen|xa|thi tran|thi xa|thanh pho|tp)\b\.?\s*(?=[\w])"
)
_HOUSE_NUM_RE = re.compile(r"\b(?:so nha|so)\s*\d+\w*|\b\d+[a-z]?(?:/\d+\w*)+")
# F-A12-02 (chan doan ...DIAGNOSIS-1-VI.md loi 2.2): SO NHA TRAN ngay truoc tu khoa duong
# ("45 duong Nguyen Trai") khong khop `_HOUSE_NUM_RE` (nhanh 1 doi tu "so", nhanh 2 doi gach cheo)
# nen span bat dau tu "duong" va MAT so nha.
#
# CO Y khong them so nay vao `_HOUSE_NUM_RE`: lam vay bien no thanh 1 THANH PHAN doc lap, keo theo
# 2 tac dung phu that su da xay ra khi thu:
#   - `test_so_nha_cong_duong_don_le`: "123 duong Nguyen Trai" tu MEDIUM bi day len HIGH (2 thanh
#     phan -> multi), trong khi house+street don thuan von chi la bang chung YEU;
#   - `test_hai_dia_chi_mot_tin`: them 1 thanh phan o dau dia chi thu 2 lam khoang cach giua 2 cum
#     lot xuong duoi `_ADDR_CLUSTER_GAP` -> 2 dia chi bi GOP thanh 1.
# Vi vay so nha chi duoc dung de NOI BIEN (mo rong `start` lui lai), KHONG tinh la thanh phan/bang
# chung, KHONG anh huong cluster hay confidence.
_LEADING_HOUSE_NUM_RE = re.compile(r"(?:^|(?<=[\s,;:(]))(\d+[a-z]?)\s+$")
_NUM_STREET_RE = re.compile(r"\b\d+[a-z]?\s+(?:duong|pho|ngo|hem|ngach)\s+[\w]")

# Tinh/thanh (fold, kem ten goi thong dung). Ten tinh don le KHONG phai dia chi
# (khach hoi "ship Ca Mau duoc khong" chi la cau hoi vung giao) — chi la 1 thanh
# phan gop vao cluster.
_PROVINCES = [
    "ha noi", "tp hcm", "tphcm", "hcm", "sai gon", "ho chi minh", "da nang",
    "can tho", "hai phong", "ca mau", "bac lieu", "soc trang", "kien giang",
    "an giang", "dong thap", "tien giang", "ben tre", "vinh long", "tra vinh",
    "hau giang", "long an", "tay ninh", "binh duong", "dong nai", "vung tau",
    "ba ria", "da lat", "lam dong", "nha trang", "khanh hoa", "binh thuan",
    "phan thiet", "quang nam", "hoi an", "hue", "quang ngai", "binh dinh",
    "quy nhon", "gia lai", "pleiku", "dak lak", "buon ma thuot", "dak nong",
    "kon tum", "nghe an", "ha tinh", "thanh hoa", "nam dinh", "thai binh",
    "hai duong", "hung yen", "bac ninh", "bac giang", "quang ninh", "ha long",
    "thai nguyen", "phu tho", "lao cai", "sapa", "yen bai", "son la",
    "dien bien", "hoa binh", "ninh binh", "ha nam", "phu yen", "tuy hoa",
    "ninh thuan", "quang tri", "quang binh", "dong hoi", "cao bang",
    "lang son", "tuyen quang", "ha giang", "bac kan", "lai chau",
    "binh phuoc", "my tho", "rach gia", "chau doc", "phu quoc", "vinh",
]
_PROVINCE_RE = re.compile(r"\b(?:" + "|".join(re.escape(p) for p in _PROVINCES) + r")\b")

# Sensitive disclosure (D2) — fold ca hai phia.
_SENSITIVE_KW: dict[SensitiveCategory, tuple[str, ...]] = {
    SensitiveCategory.HEALTH: (
        "tieu duong", "huyet ap", "mang thai", "co bau", "co thai",
        "cho con bu", "di ung", "tim mach", "benh tim", "dau da day",
        "trao nguoc", "ung thu", "mat ngu", "kho ngu", "dong kinh",
        "tram cam", "roi loan lo au", "suy than", "gan nhiem mo", "mo mau",
        "cholesterol", "dang dieu tri", "dang uong thuoc", "bac si dan",
        "tuyen giap", "hen suyen", "benh nen",
    ),
    SensitiveCategory.IDENTITY_DOC: (
        "cmnd", "cccd", "can cuoc cong dan", "can cuoc", "ho chieu",
        "passport", "ma so thue",
    ),
    SensitiveCategory.FINANCE: (
        "so tai khoan", "stk", "tai khoan ngan hang", "so the",
        "the tin dung", "chuyen khoan toi so",
    ),
}
_SENSITIVE_RE = {
    cat: re.compile(r"\b(?:" + "|".join(re.escape(k) for k in kws) + r")\b")
    for cat, kws in _SENSITIVE_KW.items()
}

# Day so ung vien: cho phep khoang trang/cham/gach/ngoac giua cac cum so.
_DIGITRUN_RE = re.compile(r"(?<![\d/])\+?\(?\+?\d[\d .\-()]{6,18}\d(?![\d])")
_VN_MOBILE_RE = re.compile(r"^0[35789]\d{8}$")
_VN_LANDLINE_RE = re.compile(r"^02\d{8,9}$")

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Khoang cach toi da (ky tu) giua 2 thanh phan dia chi de gop chung 1 cluster.
# 20 du cho "duong X..., phuong Y" nhung tach duoc 2 dia chi trong cung 1 tin.
_ADDR_CLUSTER_GAP = 20
# Cua so nhin lui tim cue cho day so (phone/nid/bank).
_CUE_WINDOW = 30


@dataclass
class PIISpan:
    """Mot vung PII: CHI offset (tren ban NFC) + metadata — KHONG chua gia tri."""

    slot_type: SlotType
    start: int
    end: int
    confidence: Confidence
    reason: ReasonCode

    def as_safe_dict(self) -> dict:
        """Dang an toan de log/metrics: khong co cach nao suy nguoc plaintext."""
        return {
            "slot_type": self.slot_type.value,
            "confidence": self.confidence.value,
            "reason": self.reason.value,
            "length": self.end - self.start,
        }


@dataclass
class DetectionResult:
    spans: list[PIISpan] = field(default_factory=list)
    sensitive_categories: list[SensitiveCategory] = field(default_factory=list)
    risk_class: RiskClass = RiskClass.D0

    def count(self, slot: SlotType) -> int:
        return sum(1 for s in self.spans if s.slot_type == slot)


def _has_cue(folded: str, pos: int, cues: tuple[str, ...]) -> bool:
    window = folded[max(0, pos - _CUE_WINDOW):pos]
    return any(re.search(r"\b" + re.escape(c) + r"\b", window) for c in cues)


def _overlaps(spans: list[PIISpan], start: int, end: int) -> bool:
    return any(s.start < end and start < s.end for s in spans)


# ---------------------------------------------------------------------------
# Phone / national_id / bank_account (tren day so)
# ---------------------------------------------------------------------------

def _detect_numeric_slots(text_nfc: str, folded: str, spans: list[PIISpan]) -> None:
    for m in _DIGITRUN_RE.finditer(folded):
        raw = m.group(0)
        cleaned = re.sub(r"[ .\-()]", "", raw)
        if cleaned.startswith("+84"):
            cleaned = "0" + cleaned[3:]
        elif cleaned.startswith("84") and len(cleaned) >= 11:
            cleaned = "0" + cleaned[2:]
        start, end = m.start(), m.end()
        if _overlaps(spans, start, end):
            continue

        # 1) CMND/CCCD: uu tien truoc phone (12 so de nham thanh "so dien thoai").
        #
        # F-NUM-01/F-NUM-02 (dap PHASE1B-M4-NUMERIC-SLOT-COLLISION-REVIEW-VI.md): nhanh 12 so nay
        # TRUOC DAY nuot MOI day 12 chu so va `continue` ngay, nen:
        #   - "STK 710001234567" (so tai khoan 12 so, CO cue bank) bi gan `national_id` va khong
        #     bao gio toi duoc nhanh bank ben duoi -> bank fn + nid fp (F-NUM-01);
        #   - "don hang 079000012345" (ma don 12 so) thanh `national_id` MEDIUM -> nid fp (F-NUM-02).
        #
        # THU TU UU TIEN moi (quyet dinh duoc, khong mo ho — CA yeu cau policy ro rang):
        #   1. co cue CCCD/CMND        -> national_id HIGH   (khach noi ro la giay to)
        #   2. co cue tai chinh        -> bank_account HIGH  (khach noi ro la tai khoan)
        #   3. co cue don hang/giao dich -> KHONG gan slot nao (loai tru tuong minh)
        #   4. khong cue nao           -> national_id MEDIUM (GIU fallback — CA chon huong (ii) de
        #                                 khong lam tut recall khi khach chi gui so CCCD tran)
        # Buoc 1 dat TRUOC buoc 2 la co y: neu cau co CA HAI cue thi cue giay to thang.
        if cleaned.isdigit() and len(cleaned) == 12:
            if _has_cue(folded, start, _NID_CUES):
                spans.append(PIISpan(SlotType.NATIONAL_ID, start, end,
                                     Confidence.HIGH, ReasonCode.NID_CUE_DIGITS))
                continue
            if _has_cue(folded, start, _BANK_CUES):
                spans.append(PIISpan(SlotType.BANK_ACCOUNT, start, end,
                                     Confidence.HIGH, ReasonCode.BANK_CUE_DIGITS))
                continue
            if _has_cue(folded, start, _NID_EXCLUSION_CUES):
                # Ma don/ma giao dich: KHONG phai PII danh tinh -> khong gan slot, va cung khong
                # de roi xuong cac nhanh duoi (phone) vi 12 so khong khop dinh dang phone VN.
                continue
            spans.append(PIISpan(SlotType.NATIONAL_ID, start, end,
                                 Confidence.MEDIUM, ReasonCode.NID_12_DIGITS))
            continue
        if cleaned.isdigit() and len(cleaned) == 9 and _has_cue(folded, start, _NID_CUES):
            spans.append(PIISpan(SlotType.NATIONAL_ID, start, end,
                                 Confidence.MEDIUM, ReasonCode.NID_CUE_DIGITS))
            continue

        # 2) STK: cue tai chinh thang prefix (vi "stk 0912..." la so tai khoan).
        if cleaned.isdigit() and 6 <= len(cleaned) <= 16 and _has_cue(folded, start, _BANK_CUES):
            spans.append(PIISpan(SlotType.BANK_ACCOUNT, start, end,
                                 Confidence.HIGH, ReasonCode.BANK_CUE_DIGITS))
            continue

        # 3) Phone di dong/co dinh VN.
        if _VN_MOBILE_RE.match(cleaned):
            spans.append(PIISpan(SlotType.PHONE, start, end,
                                 Confidence.HIGH, ReasonCode.PHONE_VALID_VN_MOBILE))
            continue
        if _VN_LANDLINE_RE.match(cleaned):
            spans.append(PIISpan(SlotType.PHONE, start, end,
                                 Confidence.MEDIUM, ReasonCode.PHONE_VALID_VN_LANDLINE))
            continue

        # 4) Day 9-11 so khong prefix hop le nhung co cue lien he -> LOW.
        if cleaned.isdigit() and 9 <= len(cleaned) <= 11 and _has_cue(folded, start, _PHONE_CUES):
            spans.append(PIISpan(SlotType.PHONE, start, end,
                                 Confidence.LOW, ReasonCode.PHONE_DIGITRUN_WITH_CUE))


# ---------------------------------------------------------------------------
# Name
# ---------------------------------------------------------------------------

# Danh xung di truoc ten ("giao cho CHI Lan") — BO QUA (khong tinh vao span,
# khong chan) khi dung ngay sau cue; van la stopword neu xuat hien giua chuoi.
_HONORIFICS = {"anh", "chi", "em", "co", "chu", "bac", "ong", "ba", "ban", "cau"}


def _name_tokens_after(text_nfc: str, folded: str, pos: int) -> list[tuple[str, int, int]]:
    """Lay toi da 4 token chu (khong so) lien tiep sau vi tri pos, dung khi gap
    stopword/dau cau; danh xung mo dau duoc bo qua. Tra (token_goc, start, end)."""
    tokens: list[tuple[str, int, int]] = []
    cursor = pos
    skipped_honorific = 0
    while skipped_honorific < 2:
        m = _WORD_RE.match(text_nfc, cursor) or _WORD_RE.search(text_nfc, cursor)
        if not m or m.start() > cursor + 2:
            break
        if fold(nfc(m.group(0))) in _HONORIFICS:
            cursor = m.end()
            skipped_honorific += 1
            continue
        break
    for _ in range(4):
        m = _WORD_RE.match(text_nfc, cursor) or _WORD_RE.search(text_nfc, cursor)
        if not m or m.start() > cursor + 2:  # cho phep toi da 2 ky tu trang
            break
        # dau cau giua chung -> het cum ten ("Lan, nguoi dat la..." dung o Lan)
        if any(ch in ",.;:!?()[]/\n" for ch in text_nfc[cursor:m.start()]):
            break
        tok = m.group(0)
        # F-A12-02 (chan doan ...DIAGNOSIS-1-VI.md loi 2.3) — DUNG lop bug tai phat nhieu nhat cua
        # du an (CLAUDE.md muc 6: "bo dau de so khop gay dong am gia").
        #
        # `_NAME_STOPWORDS` chua "minh"/"anh"/"mai"/"chi"... — sau khi fold() thi:
        #     "minh" = dai tu "mình"  VA  ten rieng "Minh"
        #     "anh"  = dai tu "anh"   VA  ten rieng "Anh"/"Ánh"
        #     "mai"  = "ngày mai"     VA  ten rieng "Mai"
        # nen "Hoang Minh Tuan" bi cat con "Hoang", "Vu Duc Anh" con "Vu Duc". Day la dong am o cap
        # TU HOAN CHINH — them `\b` KHONG cuu duoc (dung nhu CLAUDE.md da ghi).
        #
        # Cach tach: tin hieu HOA/THUONG trong ban NFC GOC. Dai tu/tu noi luon viet thuong ("mình",
        # "anh", "nhé"); ten rieng viet hoa ("Minh", "Anh", "Mai"). Chi mien stopword khi token VIET
        # HOA *va* da co it nhat 1 token truoc do (tuc dang giua 1 cum ten) — khong noi long cho
        # token DAU tien, de "minh la ..." / "anh oi" khong bi hieu nham thanh ten.
        if fold(nfc(tok)) in _NAME_STOPWORDS and not (tokens and tok[:1].isupper()):
            break
        tokens.append((tok, m.start(), m.end()))
        cursor = m.end()
    return tokens


def _detect_names(text_nfc: str, folded: str, spans: list[PIISpan]) -> None:
    # a) Theo cue: "ten la X", "minh la X", "giao cho chi X"...
    for m in _NAME_CUE_RE.finditer(folded):
        cue = m.group(0)
        tokens = _name_tokens_after(text_nfc, folded, m.end())
        if not tokens:
            continue
        start, end = tokens[0][1], tokens[-1][2]
        if _overlaps(spans, start, end):
            continue
        first_fold = fold(nfc(tokens[0][0]))
        capitalized = all(t[0][:1].isupper() for t in tokens)
        has_surname = first_fold in _SURNAMES
        strong_cue = cue not in _WEAK_CUES
        if has_surname and (capitalized or strong_cue):
            conf, reason = Confidence.HIGH, ReasonCode.NAME_CUE_SURNAME
        elif capitalized:
            conf, reason = Confidence.MEDIUM, ReasonCode.NAME_CUE_CAPITALIZED
        elif strong_cue:
            conf, reason = Confidence.LOW, ReasonCode.NAME_CUE_TOKENS
        else:
            continue  # cue yeu + khong ho + khong viet hoa -> khong du tin cay
        spans.append(PIISpan(SlotType.NAME, start, end, conf, reason))

    # b) Khong cue: chuoi viet hoa mo dau bang ho VN ("Nguyen Van An, 123 Le Loi").
    words = [(w.group(0), w.start(), w.end()) for w in _WORD_RE.finditer(text_nfc)]
    i = 0
    while i < len(words):
        tok, ws, we = words[i]
        if tok[:1].isupper() and fold(nfc(tok)) in _SURNAMES:
            group = [(tok, ws, we)]
            j = i + 1
            while (
                j < len(words)
                and words[j][0][:1].isupper()
                and words[j][1] - group[-1][2] <= 2
                and len(group) < 4
            ):
                group.append(words[j])
                j += 1
            if len(group) >= 2:
                g_start, g_end = group[0][1], group[-1][2]
                g_fold = fold(nfc(text_nfc[g_start:g_end]))
                prefix = folded[max(0, g_start - 12):g_start]
                is_place = g_fold in _PLACE_BLOCKLIST or re.search(
                    r"\b(?:tp|thanh pho|tinh|phuong|quan|huyen|duong|pho)\W*$", prefix
                )
                if not is_place and not _overlaps(spans, g_start, g_end):
                    spans.append(PIISpan(SlotType.NAME, g_start, g_end,
                                         Confidence.MEDIUM,
                                         ReasonCode.NAME_SURNAME_SEQUENCE))
            i = j
        else:
            i += 1


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------

_ADDR_TAIL_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)  # CHU hoac SO (khac _WORD_RE: loai chu so)


def _extend_start_over_house_number(folded: str, start: int,
                                    cluster: list[tuple[int, int, str]]) -> int:
    """F-A12-02: keo `start` lui lai qua SO NHA TRAN dung ngay truoc tu khoa duong.

    Chi ap dung khi thanh phan DAU cua cluster la "street" ("45 |duong Nguyen Trai" -> "|45 duong
    Nguyen Trai"). KHONG tao thanh phan moi nen khong doi cluster/confidence (xem chu thich o
    `_LEADING_HOUSE_NUM_RE` ve 2 regression that da gap khi lam theo huong kia)."""
    if not cluster or cluster[0][2] != "street":
        return start
    prefix = folded[max(0, start - 8):start]
    m = _LEADING_HOUSE_NUM_RE.search(prefix)
    if not m:
        return start
    return start - (len(prefix) - m.start(1))


def _extend_over_proper_nouns(text_nfc: str, end: int, *, max_tokens: int = 8) -> int:
    """F-A12-02: keo `end` qua cac token TEN RIENG (viet hoa) hoac CHU SO lien tiep ngay sau.

    Dung cho duoi cluster dia chi:
        "...quan| Go Vap nhe shop"                  -> keo qua "Go Vap",   dung truoc "nhe"
        "...quan| 3 nhe shop"                        -> keo qua "3",        dung truoc "nhe"
        "...phuong Ngo Thi Nham|, Hai Ba Trung nhe"  -> keo qua ca cum sau dau phay, dung truoc "nhe"

    Chi doc `text_nfc` GOC de con tin hieu HOA/THUONG — `folded` da mat tin hieu do (va mat dau),
    dung lop bay "bo dau gay dong am gia" ma CLAUDE.md canh bao.

    Quy tac dung: gap token THUONG dau tien thi dung ngay ("nhe shop", "gium em"...). Do do
    `max_tokens` rong rai cung an toan — ranh gioi THAT su la tin hieu hoa/thuong, khong phai bo dem.
    Cho phep bang qua DAU PHAY (dia chi VN hay viet "..., quan X, TP Y") nhung KHONG bang qua dau
    ket cau manh (`.;:!?` xuong dong) va toi da 1 dau phay lien tiep.

    Neu input viet thuong hoan toan (vd khong dau "phuong tan phong") thi khong keo gi -> giu
    nguyen hanh vi cu, khong noi rong false positive.
    """
    cursor = end
    for _ in range(max_tokens):
        m = _ADDR_TAIL_TOKEN_RE.search(text_nfc, cursor)
        if not m:
            break
        gap = text_nfc[cursor:m.start()]
        if len(gap) > 2 or any(ch in ".;:!?()[]\n" for ch in gap) or gap.count(",") > 1:
            break
        tok = m.group(0)
        if not (tok[:1].isupper() or tok.isdigit()):
            break  # token viet thuong -> da sang phan duoi cau, dung lai
        cursor = m.end()
    return max(end, cursor)


def _detect_addresses(text_nfc: str, folded: str, spans: list[PIISpan]) -> None:
    components: list[tuple[int, int, str]] = []
    province_hits = [(m.start(), m.end()) for m in _PROVINCE_RE.finditer(folded)]
    for kind, regex in (("house", _HOUSE_NUM_RE), ("street", _STREET_KW_RE)):
        for m in regex.finditer(folded):
            components.append((m.start(), m.end(), kind))
    for m in _ADMIN_KW_RE.finditer(folded):
        kw_end = m.end(1)
        # "tp/thanh pho + <ten tinh>" la MOT cach goi dia danh, khong phai
        # 2 thanh phan dia chi ("ship ve TP Ho Chi Minh?" khong phai dia chi).
        if any(0 <= ps - kw_end <= 3 for ps, _ in province_hits):
            continue
        # chong dong am: sau keyword la chu so/chu HOA (ban NFC goc) => "admin"
        # manh; nguoc lai ("phuong tan phong" go thuong khong dau) => "admin_weak"
        # — chi dung de NOI cluster, KHONG tinh vao quyet dinh multi (tranh FP
        # "quán gần phố đi bộ" nhung van bat dia chi khong dau du thanh phan).
        nxt = m.end()  # lookahead (?=[\w]) => vi tri ky tu ngay sau keyword+space
        ch = text_nfc[nxt] if nxt < len(text_nfc) else ""
        kind = "admin" if (ch.isdigit() or ch.isupper()) else "admin_weak"
        components.append((m.start(1), m.end(1), kind))
    components.extend((ps, pe, "province") for ps, pe in province_hits)
    components.sort()

    clusters: list[list[tuple[int, int, str]]] = []
    for comp in components:
        if clusters and comp[0] - clusters[-1][-1][1] <= _ADDR_CLUSTER_GAP:
            clusters[-1].append(comp)
        else:
            clusters.append([comp])

    for cluster in clusters:
        start = _extend_start_over_house_number(folded, cluster[0][0], cluster)
        end = max(c[1] for c in cluster)
        # keo end het "tu" dang do (vd admin regex chi an 1 ky tu sau keyword)
        tail = _WORD_RE.match(folded, end - 1)
        if tail:
            end = max(end, tail.end())
        # F-A12-02 (chan doan ...DIAGNOSIS-1-VI.md loi 2.1): thanh phan "admin" CHI la tu khoa
        # ("quan"/"huyen"/"xa"...), KHONG bao gom TEN RIENG dung sau, nen span cu ket thuc o
        # "...quan" va mat "Go Vap". Keo them cac tu VIET HOA (ban NFC GOC) hoac chu so ngay sau.
        #
        # Vi sao dung tin hieu VIET HOA thay vi danh sach tu: ten dia danh la tap mo (khong the liet
        # ke het), trong khi duoi cau thuong la tu thuong ("nhe shop", "gium em"). Doc tren text_nfc
        # GOC — KHONG dung `folded` — vi fold() da mat ca dau LAN thong tin hoa/thuong, dung lop bay
        # "bo dau gay dong am gia" ma CLAUDE.md canh bao.
        end = _extend_over_proper_nouns(text_nfc, end)
        strong = [c for c in cluster if c[2] != "admin_weak"]
        kinds = {c[2] for c in strong}
        digit_near = bool(re.search(r"\d", folded[max(0, start - 10):end + 20]))
        multi = len(strong) >= 2 and (
            len(kinds) >= 2 or "admin" in kinds or digit_near
        )
        # Cap yeu {street, province} ("da nang duong xa lam") de false positive:
        # doi hoi co CHU SO quanh cluster (dia chi giao hang thuc te co so nha).
        if multi and kinds == {"street", "province"} and not digit_near:
            multi = False
        if _overlaps(spans, start, end):
            continue
        if multi:
            spans.append(PIISpan(SlotType.ADDRESS, start, end,
                                 Confidence.HIGH, ReasonCode.ADDR_MULTI_COMPONENT))
        elif _NUM_STREET_RE.search(folded, max(0, start - 8), min(len(folded), end + 8)):
            spans.append(PIISpan(SlotType.ADDRESS, start, end,
                                 Confidence.MEDIUM, ReasonCode.ADDR_NUM_STREET))
        # 1 thanh phan don le (chi ten tinh / chi "duong") -> KHONG phai dia chi


# ---------------------------------------------------------------------------
# Sensitive disclosure + API chinh
# ---------------------------------------------------------------------------

def _detect_sensitive(folded: str) -> list[SensitiveCategory]:
    return [cat for cat, rx in _SENSITIVE_RE.items() if rx.search(folded)]


def detect(text: str) -> DetectionResult:
    """Quet PII tren 1 tin nhan. Thuan CPU (regex), khong I/O, co the raise —
    caller shadow_scan chiu trach nhiem containment."""
    result = DetectionResult()
    if not text or not text.strip():
        return result

    text_nfc = nfc(text)
    folded = fold(text_nfc)

    spans: list[PIISpan] = []
    _detect_numeric_slots(text_nfc, folded, spans)
    _detect_addresses(text_nfc, folded, spans)
    _detect_names(text_nfc, folded, spans)
    spans.sort(key=lambda s: s.start)
    result.spans = spans
    result.sensitive_categories = _detect_sensitive(folded)

    high_risk_slots = {SlotType.NATIONAL_ID, SlotType.BANK_ACCOUNT}
    if result.sensitive_categories or any(s.slot_type in high_risk_slots for s in spans):
        result.risk_class = RiskClass.D2
    elif spans:
        result.risk_class = RiskClass.D1
    return result
