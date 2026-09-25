"""CA Directive 396 §2 (F1): khach HOI THOI GIAN GIAO / thoi diem shop ban giao -> tra loi TAT DINH tu shipment da
commit (KHONG de LLM tu tao ETA, KHONG hua "bao lai" suong).

- ETA: shipment `quoted` + co ETA that -> tra `shipments.eta_text` o moi trang thai chua giao xong.
  Chua co ETA (chua quote / quote_required / unknown / placeholder) -> mo staff_attention(reason='eta_question')
  + admin notify THAT (cung transaction) roi moi noi "da chuyen nhan vien".
- Ban giao: chua co lich ban giao thuc -> cau van hanh thong thuong (KHONG phai SLA/cam ket gio lay hang).
- Chi ap dung khi khach co DON MO hop le (khong huy, chua giao xong). Khong co -> None (fall-through luong cu).

So khop: GIU DAU + bien the khong dau trong cung regex, co ranh gioi tu (CLAUDE.md §6: "giao dien" khong phai
giao hang; "bao lau thi pha duoc" khong phai hoi giao).
"""
from __future__ import annotations

import re
import unicodedata

from app.services.fulfillment import attention as _att

ETA_REASON = "eta_question"

# Tu hoi thoi diem / khoang thoi gian.
_WHEN = (r"(?:bao\s*l[aâ]u|khi\s*n[aà]o|bao\s*gi[oờ]|m[aấ]y\s*(?:ng[aà]y|h[oô]m|b[uữ]a)|l[uú]c\s*n[aà]o"
         r"|ch[uừ]ng\s*n[aà]o|h[oô]m\s*n[aà]o|ng[aà]y\s*n[aà]o|m[aấ]y\s*gi[oờ])")
# Hanh dong giao / nhan hang (phia khach). "giao dien"/"giao dich" loai tru; "nhan duoc tien" (hoi thanh toan) loai tru; KHONG gom "co hang" (hoi ton kho).
_DELIVER = (r"(?:giao(?!\s*(?:di[eệ]n|d[iị]ch))|nh[aậ]n\s*(?:[đd][uư][oợ]c\s*)?h[aà]ng"
            r"|nh[aậ]n\s*[đd][uư][oợ]c(?!\s*ti[eề]n)|t[oớ]i\s*n[oơ]i|[đd][eế]n\s*n[oơ]i|v[eề]\s*(?:t[oớ]i|[đd][eế]n)"
            r"|ship\s*t[oớ]i|ship\s*[đd][eế]n)")
# Shop ban giao / gui hang di (phia shop).
_HANDOVER = (r"(?:b[aà]n\s*giao|g[uử]i\s*(?:h[aà]ng|[đd]i|[đd][oơ]n)|ship\s*[đd]i|xu[aấ]t\s*(?:h[aà]ng|kho)"
             r"|[đd][oó]ng\s*(?:g[oó]i|h[aà]ng)|l[aấ]y\s*h[aà]ng|g[uử]i\s*cho\s*(?:ghn|b[eê]n\s*giao))")

_ETA_DIRECT_RE = re.compile(
    r"\b(?:th[oờ]i\s*gian\s*(?:giao|nh[aậ]n\s*h[aà]ng|ship)|d[uự]\s*ki[eế]n\s*(?:giao|nh[aậ]n|t[oớ]i)|eta)\b",
    re.IGNORECASE)
_ETA_PAIR_RE = re.compile(rf"(?:\b{_WHEN}\b.*\b{_DELIVER}\b|\b{_DELIVER}\b.*\b{_WHEN}\b)", re.IGNORECASE)
_HANDOVER_RE = re.compile(rf"(?:\b{_WHEN}\b.*\b{_HANDOVER}\b|\b{_HANDOVER}\b.*\b{_WHEN}\b)", re.IGNORECASE)
# Cau KHANG DINH ("bao lau cung duoc", "khi nao giao cung duoc") -> khong phai hoi.
_NOT_QUESTION_RE = re.compile(
    r"\b(?:bao\s*l[aâ]u|khi\s*n[aà]o|l[uú]c\s*n[aà]o|bao\s*gi[oờ]|m[aấ]y\s*ng[aà]y)\b[^?.!\n]{0,20}?"
    r"\bc[uũ]ng\s*(?:[đd][uư][oợ]c|ok|kh[oô]ng\s*sao)\b", re.IGNORECASE)

# eta_text KHONG phai ETA that (placeholder) -> coi nhu chua co ETA.
_ETA_PLACEHOLDERS = ("GHN sẽ báo thời gian giao", "sẽ xác nhận sau khi kiểm tra địa chỉ")
_DONE_SHIP = ("delivered", "cancelled", "return_pending")
_CANCELLED_ORDER = ("cancelled", "cancelled_by_exception")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").strip()


def classify(text: str) -> str | None:
    """'handover' | 'eta' | None. Handover xet TRUOC ("khi nao ban giao" chua 'giao')."""
    t = _norm(text)
    if not t or _NOT_QUESTION_RE.search(t):
        return None
    if _HANDOVER_RE.search(t):
        return "handover"
    if _ETA_DIRECT_RE.search(t) or _ETA_PAIR_RE.search(t):
        return "eta"
    return None


def has_real_eta(row: dict) -> bool:
    eta = (row.get("eta_text") or "").strip()
    return row.get("fee_status") == "quoted" and bool(eta) and eta not in _ETA_PLACEHOLDERS


def _is_ghn(row: dict) -> bool:
    return row.get("quote_provider") == "ghn" and row.get("quote_source") != "fallback_policy"


def eta_text_reply(row: dict) -> str:
    oid, eta = row["order_id"], row["eta_text"].strip()
    if row.get("ship_status") == "in_transit":
        return f"Dạ đơn #{oid} đã được bàn giao cho đơn vị vận chuyển, dự kiến giao {eta} ạ."
    if _is_ghn(row):
        return f"Dạ đơn #{oid} dự kiến giao {eta}, tính từ khi bên GHN nhận hàng từ shop ạ."
    return f"Dạ đơn #{oid} dự kiến giao: {eta} ạ."


def no_eta_reply(order_id: int) -> str:
    return (f"Dạ đơn #{order_id} hiện chưa báo phí giao hàng được nên em chưa có thời gian giao chính xác. "
            "Em đã chuyển nhân viên shop kiểm tra, nhân viên sẽ nhắn anh/chị ạ.")


def handover_reply(row: dict) -> str:
    oid = row["order_id"]
    if row.get("ship_status") == "in_transit":
        return eta_text_reply(row) if has_real_eta(row) else f"Dạ đơn #{oid} đã được bàn giao cho đơn vị vận chuyển ạ."
    base = ("Dạ thông thường bên em bàn giao trong ngày làm việc, hoặc ngày làm việc kế tiếp nếu đơn đặt ngoài giờ ạ.")
    if _is_ghn(row):
        base += " Thời gian GHN giao sẽ được tính từ lúc GHN nhận hàng."
    return base


async def open_order_row(conn, psid: str) -> dict | None:
    """Don MO gan nhat cua khach: khong huy, shipment (neu co) chua giao xong/huy."""
    row = await conn.fetchrow(
        "SELECT o.id AS order_id, o.status AS order_status, s.status AS ship_status, s.fee_status, s.eta_text, "
        "s.quote_provider, s.quote_source "
        "FROM orders o JOIN customers c ON c.id=o.customer_id LEFT JOIN shipments s ON s.order_id=o.id "
        "WHERE c.psid=$1 AND o.status <> ALL($2::text[]) ORDER BY o.created_at DESC, o.id DESC LIMIT 1",
        psid, list(_CANCELLED_ORDER))
    if row is None or row["ship_status"] in _DONE_SHIP:
        return None
    return dict(row)


async def handle(conn, psid: str, text: str, *, actor: str = "m7:eta") -> str | None:
    """Goi TRONG transaction (orchestrator). None -> khong phai cau hoi giao/ban giao HOAC khong co don mo."""
    kind = classify(text)
    if kind is None:
        return None
    row = await open_order_row(conn, psid)
    if row is None:
        return None
    if kind == "handover":
        return handover_reply(row)
    if has_real_eta(row):
        return eta_text_reply(row)
    # Chua co ETA that -> escalate THAT truoc (attention + admin notify cung tx), roi moi noi "da chuyen nhan vien".
    await _att.open_attention(conn, row["order_id"], reason=ETA_REASON,
                              detail={"why": "customer_eta_question", "fee_status": row.get("fee_status"),
                                      "ship_status": row.get("ship_status")}, created_by=actor)
    return no_eta_reply(row["order_id"])
