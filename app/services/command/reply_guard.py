"""Deterministic order confirmation + structured/shadow guard (I-B M1 Slice 6). Spec §6.4, §10.4.

- append_receipt_lines: bom dong xac nhan DETERMINISTIC (order#/tong) tu committed receipt vao reply
  cua LLM — LLM co the noi truoc, nhung so tien/ma don/outcome sau commit lay tu day (khong de LLM viet lai).
- shadow_evaluate: buoc 2 rollout marker->structured (§10.4): moi 'claim da tao don' phai co receipt id.
  Orchestrator log tin hieu nay (shadow) truoc khi bo hoan toan marker matching.
Thuan tuy -> unit-testable, khong DB/LLM.
"""
from __future__ import annotations

import re

from app.services.command.receipt import order_confirmation_line


def _display_in_reply(disp: str, reply: str) -> bool:
    """disp='#12' chỉ tính là 'đã có' khi xuất hiện như 1 token (không phải tiền tố của số dài hơn):
    tránh '#12' khớp nhầm '#123'/'#120' -> bỏ sót dòng xác nhận (bài học substring biên CLAUDE.md).
    FINDING 3 (adversarial self-review)."""
    return re.search(r"(?<!\d)" + re.escape(disp) + r"(?!\d)", reply) is not None


def append_receipt_lines(reply: str, receipt_dicts: list[dict] | None) -> str:
    """Them dong xac nhan deterministic cho moi receipt succeeded (bo qua neu reply da chua ma don)."""
    lines: list[str] = []
    for rd in receipt_dicts or []:
        if rd.get("outcome") != "succeeded":
            continue
        resource = rd.get("resource") or {}
        result = rd.get("result") or {}
        disp = resource.get("display_id")
        if not disp or _display_in_reply(disp, reply):
            continue
        lines.append(order_confirmation_line(
            disp, result.get("quantity"), result.get("sku"), result.get("total_vnd")))
    if not lines:
        return reply
    return (reply.rstrip() + "\n\n" + "\n".join(lines)).strip()


NEUTRAL_ORDER_REPLY = (
    "Dạ em đã ghi nhận yêu cầu đặt hàng của anh/chị. Xác nhận đơn (mã đơn, tổng tiền) "
    "sẽ được gửi tới anh/chị ngay sau ít phút ạ."
)


def finalize_customer_reply(llm_reply: str, order_created: bool) -> str:
    """CR-08: khi order ĐÃ commit, KHÔNG gửi nguyên văn reply LLM cho khách (LLM có thể nói sai mã
    đơn / số lượng / tổng tiền trước khi durable receipt tới). Trả câu TRUNG TÍNH, không khẳng định
    business effect; xác nhận CHÍNH THỨC (đúng committed data) đi qua durable receipt (outbox).
    Chưa tạo đơn -> giữ reply LLM (marker anti-fabrication guard riêng vẫn chặn claim bịa)."""
    return NEUTRAL_ORDER_REPLY if order_created else llm_reply


def shadow_evaluate(reply_claims_order: bool, order_ids) -> dict:
    """Doi chieu shadow: neu reply 'claim da tao don' thi PHAI co receipt/order id backing.
    consistent=False => nghi bia (marker guard hien huu van chan; day la tin hieu evidence gate)."""
    has_receipt = bool(order_ids)
    return {
        "claims_order": reply_claims_order,
        "has_receipt": has_receipt,
        "consistent": (not reply_claims_order) or has_receipt,
    }


# CA Directive 396 §2.2 (F1): cam cau HUA follow-up ("kiem tra va bao lai", "phan hoi lai"...) khi luot do KHONG tao
# escalation/attention that — khach cho mot loi hua khong co co che thuc hien (evidence don #254 msg 1813/1815).
# Giu dau + bien the khong dau, ranh gioi tu (CLAUDE.md §6).
_FOLLOWUP_PROMISE_RE = re.compile(
    r"\b(?:b[aá]o\s*l[aạ]i|ph[aả]n\s*h[oồ]i\s*(?:l[aạ]i|b[aạ]n|anh|ch[iị]|s[oớ]m|ngay)"
    r"|ki[eể]m\s*tra\s*(?:(?:v[aà]|r[oồ]i)\s*)?(?:b[aá]o|nh[aắ]n|g[uử]i)"
    r"|li[eê]n\s*h[eệ]\s*l[aạ]i|s[eẽ]\s*(?:b[aá]o|nh[aắ]n)\s*(?:l[aạ]i|cho|anh|ch[iị]|b[aạ]n|ngay)"
    r"|khi\s*n[aà]o\s*c[oó]\s*th[oô]ng\s*tin)\b",
    re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")

NO_PROMISE_OFFER = ("Nếu anh/chị cần, anh/chị nhắn \"gặp nhân viên\" để em chuyển nhân viên shop hỗ trợ "
                    "trực tiếp nhé ạ.")
NO_PROMISE_REPLY = ("Dạ phần này em chưa có thông tin chính xác để trả lời anh/chị ngay ạ. " + NO_PROMISE_OFFER)


def has_followup_promise(reply: str) -> bool:
    return bool(_FOLLOWUP_PROMISE_RE.search(reply or ""))


def strip_empty_promise(reply: str, escalated: bool) -> str:
    """Luot DA escalate that -> giu nguyen. Chua -> bo cau hua, them loi moi gap nhan vien (khong hua).
    Khong con noi dung -> NO_PROMISE_REPLY. Thuan tuy (unit-testable)."""
    if escalated or not has_followup_promise(reply):
        return reply
    kept = [s for s in _SENTENCE_SPLIT_RE.split(reply.strip()) if s.strip() and not has_followup_promise(s)]
    if not kept or len(" ".join(kept)) < 12:
        return NO_PROMISE_REPLY
    return (" ".join(kept).rstrip() + " " + NO_PROMISE_OFFER).strip()
