"""Entity Extraction (Buoc 6, NLU-INTEGRATION-GUIDE.md) - trich xuat entity
nhe tu message hien tai bang regex/tu khoa (khong dung ML NER, MVP don gian).

Entity MVP theo dung guide: product, quantity, unit, location, taste_preference,
brewing_method, temperature, order_id, payment_method, health_context.

HO TRO (co the trich xuat that): quantity, unit, order_id, payment_method,
health_context, temperature.

CHUA HO TRO (can du lieu/gazetteer chua co, KHONG doan bua):
- location: can danh sach dia danh Viet Nam (tinh/thanh pho/quan huyen) -
  chua co nguon du lieu nay trong datasets/nlu/.
- product: can danh sach SKU/ten san pham chuan hoa - co the lay tu
  products.py nhung chua noi day de giu module doc lap don gian.
- taste_preference, brewing_method: mo ho hon, can nhieu tu khoa hon de
  chinh xac, de danh gia sau khi co du lieu that.

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
    ):
        if result:
            entities[name] = result
    return entities