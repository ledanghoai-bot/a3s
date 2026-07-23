"""Entity Extraction (Buoc 6, NLU-INTEGRATION-GUIDE.md) - trich xuat entity
nhe tu message hien tai bang regex/tu khoa (khong dung ML NER, MVP don gian).

Entity MVP theo dung guide: product, quantity, unit, location, taste_preference,
brewing_method, temperature, order_id, payment_method, health_context.

HO TRO (co the trich xuat that): quantity, unit, order_id, payment_method,
health_context, temperature, location (v1.1, 18/7), product (v1.1, 18/7 -
MVP chi nhan dien bien the kich thuoc nhu "100g"/"25kg", chua phai ten SKU
day du).

CHUA HO TRO (mo ho hon, can nhieu tu khoa hon de chinh xac):
- taste_preference, brewing_method.

BUG DONG AM da hoc duoc tu high_precision_rules.py (18/7) - AP DUNG LAI O DAY:
so khop tu khoa GIU NGUYEN DAU tieng Viet (khong bo dau) - vi du thuc te:
"ly" (don vi coc) va "lý" (trong "xu ly" = xu ly/process) deu thanh "ly" sau
khi bo dau, gay khop nham don vi "ly" trong cau khong lien quan gi toi coc.
Rieng quantity (chu so) va order_id (chu+so) khong nhay cam dau nen van
dung ban da bo dau cho 2 truong hop nay.
"""

import re
import unicodedata
from dataclasses import dataclass

_NUMBER_WORDS = {
    "một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5,
    "sáu": 6, "bảy": 7, "tám": 8, "chín": 9, "mười": 10,
}
_UNIT_WORDS = ["hũ", "túi", "thùng", "kg", "g", "gói", "ly"]
_PAYMENT_PHRASES = ["chuyển khoản", "tiền mặt", "mã qr", "quét qr", "cod"]
_HEALTH_PHRASES = ["mang thai", "cho con bú", "cao huyết áp", "bệnh tim", "uống thuốc"]

# Danh sach dia danh Viet Nam pho bien (thanh pho/tinh khach hay nhac khi
# hoi van chuyen) - dung TEN GOI ON DINH, khong phu thuoc thay doi dia gioi
# hanh chinh (vd sap nhap tinh) vi day la NHAN DIEN TEN GOI trong cau noi,
# khong phai xac thuc dia gioi hanh chinh chinh thuc.
_LOCATIONS = [
    "hà nội", "hồ chí minh", "sài gòn", "đà nẵng", "cần thơ", "hải phòng",
    "nha trang", "huế", "vũng tàu", "đà lạt", "buôn ma thuột", "quy nhơn",
    "biên hòa", "hạ long", "vinh", "thanh hóa", "nam định", "hải dương",
    "bắc ninh", "thái nguyên", "việt trì", "cà mau", "phú quốc", "sa pa",
    "hà giang", "lào cai", "điện biên", "sơn la", "tây ninh", "long an",
    "an giang", "bến tre", "cần giờ", "lý sơn", "côn đảo",
]


def strip_diacritics(text: str) -> str:
    text = text.lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


@dataclass
class Entity:
    value: str
    source: str  # "message" - hien tai chi ho tro rut tu cau hien tai,
    # chua doc conversation_state (Buoc 5, ngoai pham vi hien tai)


def _word_match(keyword: str, text_lower: str) -> bool:
    return bool(re.search(r"\b" + re.escape(keyword.lower()) + r"\b", text_lower, re.UNICODE))


def _extract_quantity(text_stripped: str) -> Entity | None:
    m = re.search(r"\b(\d+)\b", text_stripped)
    if m:
        return Entity(value=m.group(1), source="message")
    for word, num in _NUMBER_WORDS.items():
        if _word_match(strip_diacritics(word), text_stripped):
            return Entity(value=str(num), source="message")
    return None


def _extract_unit(text_lower: str) -> Entity | None:
    for unit in _UNIT_WORDS:
        if _word_match(unit, text_lower):
            return Entity(value=unit, source="message")
    return None


def _extract_order_id(text_stripped: str) -> Entity | None:
    m = re.search(r"\b([a-z]\d{2,})\b", text_stripped)
    if m:
        return Entity(value=m.group(1).upper(), source="message")
    m2 = re.search(r"\bdon\s+(\d{2,})\b", text_stripped)
    if m2:
        return Entity(value=m2.group(1), source="message")
    return None


def _extract_payment_method(text_lower: str) -> Entity | None:
    for phrase in _PAYMENT_PHRASES:
        if _word_match(phrase, text_lower):
            return Entity(value=phrase, source="message")
    return None


def _extract_health_context(text_lower: str) -> Entity | None:
    for phrase in _HEALTH_PHRASES:
        if _word_match(phrase, text_lower):
            return Entity(value=phrase, source="message")
    return None


def _extract_temperature(text_lower: str) -> Entity | None:
    m = re.search(r"\b(\d+)\s*độ\b", text_lower)
    if m:
        return Entity(value=f"{m.group(1)} do", source="message")
    if _word_match("nóng", text_lower):
        return Entity(value="nong", source="message")
    if _word_match("lạnh", text_lower):
        return Entity(value="lanh", source="message")
    return None


def _extract_location(text_lower: str) -> Entity | None:
    """So khop tren BAN DA BO DAU (ca text dau vao lan gazetteer) - BUG THUC
    TE phat hien (18/7): khach thuong go khong dau (vd "Ca Mau" thay vi
    "Cà Mau"), nhung gazetteer viet co dau -> khong khop neu so truc tiep
    tren text_lower (chi ha hoa/thuong, chua bo dau). Fix: bo dau CA 2 ben
    truoc khi so, tra ve dang co dau (canonical) du input khong dau."""
    text_stripped = strip_diacritics(text_lower)
    for loc in _LOCATIONS:
        loc_stripped = strip_diacritics(loc)
        if re.search(r"\b" + re.escape(loc_stripped) + r"\b", text_stripped, re.UNICODE):
            return Entity(value=loc, source="message")
    return None


_PRODUCT_SIZE_RE = re.compile(r"\b(\d+)\s*(g|kg)\b", re.IGNORECASE)


def _extract_product(text_lower: str) -> Entity | None:
    """MVP - chi nhan dien BIEN THE KICH THUOC (vd "100g", "25kg") theo dung
    cac SKU da xac nhan trong session nay (60g/100g/200g/25kg), CHUA phai
    ten SKU day du (vd "3S-100G") - can du lieu tu products.py de lam chinh
    xac hon, ngoai pham vi hien tai de giu module doc lap khong phu thuoc DB.
    """
    m = _PRODUCT_SIZE_RE.search(text_lower)
    if m:
        return Entity(value=f"{m.group(1)}{m.group(2)}", source="message")
    return None


def extract_entities(message: str) -> dict[str, Entity]:
    """Tra ve dict {ten_entity: Entity}. Chi cac entity TIM THAY moi co mat
    trong dict (khong co key voi value None)."""
    text_lower = message.strip().lower()
    text_stripped = strip_diacritics(message.strip())

    entities: dict[str, Entity] = {}
    for name, result in (
        ("quantity", _extract_quantity(text_stripped)),
        ("unit", _extract_unit(text_lower)),
        ("order_id", _extract_order_id(text_stripped)),
        ("payment_method", _extract_payment_method(text_lower)),
        ("health_context", _extract_health_context(text_lower)),
        ("temperature", _extract_temperature(text_lower)),
        ("location", _extract_location(text_lower)),
        ("product", _extract_product(text_lower)),
    ):
        if result:
            entities[name] = result
    return entities