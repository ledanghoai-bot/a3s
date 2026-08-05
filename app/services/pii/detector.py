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
        if cleaned.isdigit() and len(cleaned) == 12:
            if _has_cue(folded, start, _NID_CUES):
                spans.append(PIISpan(SlotType.NATIONAL_ID, start, end,
                                     Confidence.HIGH, ReasonCode.NID_CUE_DIGITS))
            else:
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
        if fold(nfc(tok)) in _NAME_STOPWORDS:
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
        start = cluster[0][0]
        end = max(c[1] for c in cluster)
        # keo end het "tu" dang do (vd admin regex chi an 1 ky tu sau keyword)
        tail = _WORD_RE.match(folded, end - 1)
        if tail:
            end = max(end, tail.end())
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
