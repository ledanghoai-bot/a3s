"""Intent/Risk Router (Knowledge Base V2 - M3, Bat 3).

Phan loai 1 tin nhan khach thanh {intent, route, requires_handoff,
requires_tool, allowed_domains}, dung dung "Decision Logic" + "Routing Rules"
da dinh nghia san trong skills/conversation/SKL-CON-001.md (KHONG tu bia logic
moi):

    IF co van de an toan, khieu nai hoac su co don hang
      -> Tam dung muc tieu ban hang, uu tien xu ly/handoff.
    ELSE IF khach yeu cau du lieu dong (gia/ton kho/van chuyen/dat hang)
      -> Goi Tool truoc khi tra loi.
    ELSE IF cau hoi cu the va co Knowledge phu hop
      -> Tra loi truc tiep (route=knowledge).
    ELSE IF khach yeu cau tu van
      -> Need Discovery + Recommendation (route=knowledge, domain sales).
    ELSE
      -> Lam ro bang 1 cau hoi ngan (route=clarification).

QUAN TRONG - test thuc te phat hien: khach Viet Nam RAT hay go khong dau
("gia bao nhieu" thay vi "giá bao nhiêu") tren Messenger/Telegram, dac biet
tren mobile. Regex khop tu co dau don thuan se BO SOT phan lon tin nhan thuc
te. Giai phap: CHUAN HOA BO DAU ca text dau vao LAN pattern truoc khi so
khop (thay vi viet character-class thu cong cho tung tu nhu handoff.py cu -
kho bao tri, de sot).

MVP (Bat 3 dau tien): phan loai bang TU KHOA/regex (khong goi LLM) - du de
demo dung pattern voi cac truong hop RO RANG. Nang cap len LLM-based
classification cho cac truong hop mo ho la buoc tiep theo, ngoai pham vi Bat
3 (xem ISSUES-VI.md).

CHUA tich hop vao orchestrator.py/bot production - module doc lap, test qua
scripts/kb_router_test.py.
"""

import re
import unicodedata
from dataclasses import dataclass, field


def _strip_diacritics(text: str) -> str:
    """Bo dau tieng Viet + chuyen thuong, dung chung cho ca text dau vao lan
    pattern - dam bao so khop dung du khach go co dau hay khong dau."""
    text = text.lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def _kw_re(*keywords: str) -> re.Pattern:
    """Tao 1 regex OR tu danh sach tu khoa DA CO DAU (viet tu nhien de doc) -
    tu dong bo dau khi bien dich, dung ket hop voi _strip_diacritics() tren
    text dau vao luc match."""
    stripped = [_strip_diacritics(kw) for kw in keywords]
    # \b o hai dau moi tu khoa - tranh khop nham substring (bug thuc te da
    # gap: "hong" (tu "hỏng" bo dau) khop nham BEN TRONG "khong" (tu
    # "không" bo dau) neu khong co ranh gioi tu).
    return re.compile("|".join(r"\b" + re.escape(kw) + r"\b" for kw in stripped))


def _gap(word1: str, word2: str, max_gap: int = 25) -> str:
    """Tra ve PATTERN (chua compile) cho phep word1 ... word2 cach nhau boi
    noi dung bat ky (toi da max_gap ky tu, non-greedy) - dung cho cau co
    danh tu chen giua dong tu va tu hoi.

    BUG THUC TE 18/7: _kw_re("pha the nao") ONLY khop cum lien ke - cau that
    "Pha CA PHE 3S the nao?" co danh tu chen giua nen KHONG khop, bi phan
    loai nham thanh 'unclear'. _gap() giai quyet bang khoang trong linh hoat.
    """
    return re.escape(_strip_diacritics(word1)) + r".{0,%d}?" % max_gap + re.escape(_strip_diacritics(word2))


def _gap_re(*pairs: tuple[str, str], extra_exact: tuple[str, ...] = ()) -> re.Pattern:
    """Ghep nhieu cap (word1, word2) qua _gap() + cac tu khoa EXACT don le
    (extra_exact, dung _kw_re nhu cu) thanh 1 regex OR duy nhat."""
    parts = [r"\b" + _gap(w1, w2) + r"\b" for w1, w2 in pairs]
    parts += [r"\b" + re.escape(_strip_diacritics(kw)) + r"\b" for kw in extra_exact]
    return re.compile("|".join(parts))


# --- Tu khoa theo tung nhom, dung theo "Routing Rules" trong SKL-CON-001 ---
# Viet co dau cho de doc/bao tri - _kw_re() tu bo dau luc bien dich.

_GREETING_RE = _kw_re(
    "chào", "hi", "hello", "alo", "xin chào",
    # Cum tu THU HUT CHU Y (khong mang noi dung cau hoi cu the) - dung theo
    # bang nhan dien danh xung trong system_prompt.md cu (a=anh, c=chi, e=em):
    # khach nhan tin "e oi"/"shop oi" chi de mo dau, chua co gi de route that
    # su - xu ly gan giong greeting (dap lai hoi "co gi em/shop giup duoc")
    # thay vi hoi lai lam ro nhu 'unclear' (phan hoi anh Hoai 18/7).
    "shop ơi", "em ơi", "e ơi", "a ơi", "c ơi", "anh ơi", "chị ơi",
)
_COMPLAINT_RE = _kw_re(
    "khiếu nại", "hoàn tiền", "không hài lòng", "thất vọng", "tệ quá",
    "lỗi sản phẩm", "lỗi đơn", "hỏng", "giao sai", "thiếu hàng",
    "chưa nhận được", "bực mình",
)
_HEALTH_SAFETY_RE = _kw_re(
    "dị ứng", "an toàn", "sức khỏe", "có bầu", "mang thai", "tim mạch",
    "dạ dày", "triệu chứng", "tác dụng phụ", "bác sĩ",
)
_DYNAMIC_INFO_RE = _kw_re(
    "giá", "tồn kho", "còn hàng", "vận chuyển", "ship", "phí giao",
    "khuyến mãi", "giao hàng", "bao nhiêu tiền", "bao nhiêu 1",
)
_ORDER_RE = _kw_re("đặt hàng", "đặt mua", "mua ngay", "chốt đơn", "order", "đặt")
_CONSULTATION_RE = _kw_re("tư vấn", "nên chọn", "nên mua loại nào", "gợi ý giúp")

# --- Cac pattern sau dung _gap_re() thay vi _kw_re() thuong - cho phep
# danh tu chen giua dong tu/tinh tu va tu hoi (bug thuc te 18/7, xem
# docstring _gap()) ---
_BREWING_RE = _gap_re(
    ("pha", "thế nào"), ("pha", "sao"), ("pha", "kiểu"),
    extra_exact=("cách pha", "nấu"),
)
_TASTE_RE = _gap_re(
    ("vị", "đắng"), ("có", "đắng"), ("vị", "ra sao"),
    extra_exact=("hương vị", "ngon không"),
)
_COMPARE_RE = _gap_re(("khác", "gì"), ("so", "với"))
_B2B_RE = _kw_re("sỉ", "đại lý", "hợp tác", "số lượng lớn", "nhập sỉ")
_PRODUCT_RE = _gap_re(
    ("là", "gì"),
    extra_exact=("sản xuất", "nguyên liệu", "thành phần"),
)

# Domain duoc phep truy hoi Knowledge Base cho tung intent (dung filter
# allowed_domains cua search_kb() trong app/services/kb_retrieval.py).
_INTENT_DOMAINS: dict[str, list[str]] = {
    "greeting": [],
    "product_understanding": ["product", "brand"],
    "evaluate_taste": ["product", "faq"],
    "compare": ["product", "faq"],
    "learn_brewing": ["faq", "product"],
    "seek_recommendation": ["sales", "product", "faq"],
    "ask_for_consultation": ["sales", "customer_service"],
    "ask_dynamic_information": [],  # di qua Tool, khong qua Knowledge
    "order": [],  # di qua Tool
    "request_support": ["faq", "customer_service"],
    "complaint": [],  # di qua human handoff, khong retrieval
    "health_safety": [],  # di qua human handoff/safety response
    "b2b_inquiry": ["sales"],
}


@dataclass
class Route:
    intent: str
    route: str  # answer_without_retrieval / knowledge / tool / human / clarification
    requires_handoff: bool = False
    requires_tool: bool = False
    allowed_domains: list[str] = field(default_factory=list)
    reason: str = ""


def classify(message: str) -> Route:
    """Phan loai 1 tin nhan theo dung thu tu uu tien trong Decision Logic
    cua SKL-CON-001 - dung IF/ELIF theo dung thu tu, DUNG o dieu kien dau
    tien khop (khong doi tiep)."""
    text = _strip_diacritics(message.strip())

    # 1. An toan/khieu nai/su co don hang -> TAM DUNG ban hang, uu tien handoff
    if _HEALTH_SAFETY_RE.search(text):
        return Route(
            intent="health_safety", route="human", requires_handoff=True,
            reason="Cau hoi lien quan suc khoe/an toan - theo Decision Logic phai "
            "tam dung ban hang va uu tien xu ly/handoff, KHONG tu tu van y khoa.",
        )
    if _COMPLAINT_RE.search(text):
        return Route(
            intent="complaint", route="human", requires_handoff=True,
            reason="Khieu nai/su co don hang - theo Decision Logic phai tam dung "
            "ban hang va handoff cho nhan vien.",
        )

    # 2. Yeu cau du lieu dong -> goi Tool TRUOC khi tra loi
    if _ORDER_RE.search(text):
        return Route(
            intent="order", route="tool", requires_tool=True,
            reason="Khach san sang mua - chuyen nhanh sang quy trinh giao dich (Tool).",
        )
    if _DYNAMIC_INFO_RE.search(text):
        return Route(
            intent="ask_dynamic_information", route="tool", requires_tool=True,
            reason="Yeu cau du lieu dong (gia/ton kho/van chuyen) - PHAI goi Tool "
            "truoc khi tra loi, khong duoc tra loi tu Knowledge tinh.",
        )

    # 3. Chao hoi -> tra loi ngay, khong can retrieval
    if _GREETING_RE.search(text):
        return Route(
            intent="greeting", route="answer_without_retrieval",
            reason="Chao hoi don gian - khong can Tool/Knowledge.",
        )

    # 4. B2B -> phan loai domain, escalate that (neu can) xu ly o Tool layer
    if _B2B_RE.search(text):
        return Route(
            intent="b2b_inquiry", route="knowledge",
            allowed_domains=_INTENT_DOMAINS["b2b_inquiry"],
            reason="Cau hoi B2B/sỉ - tra loi tu Sales Knowledge, co the can "
            "escalate rieng neu so luong vuot nguong (xu ly o Tool layer, "
            "khong phai router nay).",
        )

    # 5. Cau hoi cu the co Knowledge phu hop -> tra loi truc tiep
    for intent, pattern in (
        ("learn_brewing", _BREWING_RE),
        ("evaluate_taste", _TASTE_RE),
        ("compare", _COMPARE_RE),
        ("product_understanding", _PRODUCT_RE),
    ):
        if pattern.search(text):
            return Route(
                intent=intent, route="knowledge",
                allowed_domains=_INTENT_DOMAINS[intent],
                reason=f"Cau hoi cu the thuoc intent '{intent}' - co Knowledge "
                "phu hop, tra loi truc tiep qua retrieval.",
            )

    # 6. Yeu cau tu van -> Need Discovery + Recommendation
    if _CONSULTATION_RE.search(text):
        return Route(
            intent="ask_for_consultation", route="knowledge",
            allowed_domains=_INTENT_DOMAINS["ask_for_consultation"],
            reason="Yeu cau tu van - can Need Discovery toi thieu truoc khi "
            "recommend (xu ly o Prompt Assembly/Conversation State, ngoai "
            "pham vi router nay).",
        )

    # 7. Khong khop gi ro rang -> lam ro bang 1 cau hoi ngan
    return Route(
        intent="unclear", route="clarification",
        reason="Khong khop ro rang voi intent nao - can hoi lai 1 cau ngan "
        "de lam ro truoc khi tra loi/retrieval.",
    )
