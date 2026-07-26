"""Deterministic order confirmation + structured/shadow guard (I-B M1 Slice 6). Spec §6.4, §10.4.

- append_receipt_lines: bom dong xac nhan DETERMINISTIC (order#/tong) tu committed receipt vao reply
  cua LLM — LLM co the noi truoc, nhung so tien/ma don/outcome sau commit lay tu day (khong de LLM viet lai).
- shadow_evaluate: buoc 2 rollout marker->structured (§10.4): moi 'claim da tao don' phai co receipt id.
  Orchestrator log tin hieu nay (shadow) truoc khi bo hoan toan marker matching.
Thuan tuy -> unit-testable, khong DB/LLM.
"""
from __future__ import annotations

from app.services.command.receipt import order_confirmation_line


def append_receipt_lines(reply: str, receipt_dicts: list[dict] | None) -> str:
    """Them dong xac nhan deterministic cho moi receipt succeeded (bo qua neu reply da chua ma don)."""
    lines: list[str] = []
    for rd in receipt_dicts or []:
        if rd.get("outcome") != "succeeded":
            continue
        resource = rd.get("resource") or {}
        result = rd.get("result") or {}
        disp = resource.get("display_id")
        if not disp or disp in reply:
            continue
        lines.append(order_confirmation_line(
            disp, result.get("quantity"), result.get("sku"), result.get("total_vnd")))
    if not lines:
        return reply
    return (reply.rstrip() + "\n\n" + "\n".join(lines)).strip()


def shadow_evaluate(reply_claims_order: bool, order_ids) -> dict:
    """Doi chieu shadow: neu reply 'claim da tao don' thi PHAI co receipt/order id backing.
    consistent=False => nghi bia (marker guard hien huu van chan; day la tin hieu evidence gate)."""
    has_receipt = bool(order_ids)
    return {
        "claims_order": reply_claims_order,
        "has_receipt": has_receipt,
        "consistent": (not reply_claims_order) or has_receipt,
    }
