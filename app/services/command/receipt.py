"""Deterministic receipt + customer template (I-B M1). Spec §6.4.

Receipt duoc dung TU command_executions.result_payload (committed truth) — KHONG qua LLM.
LLM co the them cau chuyen tiep TRUOC action, nhung khong duoc viet lai so tien/ma don/outcome
sau commit (§6.4, §10.4). Template versioned de doi chieu evidence marker replacement (§10.4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CUSTOMER_TEMPLATE_VERSION = 1

# Outcomes (§6.4)
SUCCEEDED = "succeeded"
REJECTED = "rejected"
IN_PROGRESS = "in_progress"


def format_vnd(n: int) -> str:
    """170000 -> '170.000đ' (dinh dang VN: dau cham phan cach nghin, hau to đ)."""
    return f"{int(n):,}".replace(",", ".") + "đ"


def order_confirmation_line(display_id, quantity, sku, total_vnd) -> str:
    """Template deterministic DUY NHAT cho xac nhan don (customer-facing + reply guard dung chung).
    Vd: 'Đơn #123 đã được ghi nhận: 1 × 3S-100G, tổng 170.000đ.'"""
    return (f"Đơn {display_id} đã được ghi nhận: "
            f"{quantity} × {sku}, tổng {format_vnd(total_vnd)}.")


@dataclass
class CommandReceipt:
    receipt_id: str
    command_id: str
    command_type: str
    command_version: int
    outcome: str
    committed_at: str | None
    correlation_id: str
    duplicate: bool = False
    resource: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "receipt_id": self.receipt_id,
            "command_id": self.command_id,
            "command_type": self.command_type,
            "command_version": self.command_version,
            "outcome": self.outcome,
            "committed_at": self.committed_at,
            "correlation_id": self.correlation_id,
            "duplicate": self.duplicate,
        }
        if self.resource is not None:
            d["resource"] = self.resource
        if self.result is not None:
            d["result"] = self.result
        if self.error_code is not None:
            d["error_code"] = self.error_code
        return d


def build_order_create_receipt(
    *, command_id: str, correlation_id: str, outcome: str,
    result_payload: dict[str, Any] | None, committed_at: str | None,
    duplicate: bool = False, error_code: str | None = None,
) -> CommandReceipt:
    """Dung receipt cho order.create tu result_payload da commit. resource/result CHI lay tu
    du lieu persisted, khong tu input tho."""
    resource = None
    result = None
    if outcome == SUCCEEDED and result_payload is not None:
        oid = result_payload.get("order_id")
        resource = {"type": "order", "id": oid, "display_id": f"#{oid}"}
        result = {
            "status": result_payload.get("status"),
            "sku": result_payload.get("sku"),
            "quantity": result_payload.get("quantity"),
            "unit_price_vnd": result_payload.get("unit_price_vnd"),
            "total_vnd": result_payload.get("total_vnd"),
        }
        if "backordered" in result_payload:  # M2 PO-change: đơn giữ do thiếu hàng (chờ topup)
            result["backordered"] = result_payload["backordered"]
    return CommandReceipt(
        receipt_id=f"cmd_{command_id}",
        command_id=command_id,
        command_type="order.create",
        command_version=1,
        outcome=outcome,
        committed_at=committed_at,
        correlation_id=correlation_id,
        duplicate=duplicate,
        resource=resource,
        result=result,
        error_code=error_code,
    )


def customer_message(receipt: CommandReceipt) -> str:
    """Text deterministic gui khach — chi tu committed result. Template v1.
    Vd: 'Đơn #123 đã được ghi nhận: 1 × 3S-100G, tổng 170.000đ.'"""
    if receipt.outcome != SUCCEEDED or not receipt.result or not receipt.resource:
        # Khong bao gio tu bia so tien/ma don khi chua succeeded.
        return "Yêu cầu của bạn đang được xử lý."
    r = receipt.result
    return order_confirmation_line(
        receipt.resource.get("display_id"), r.get("quantity"), r.get("sku"), r.get("total_vnd")
    )


def staff_summary(receipt: CommandReceipt) -> dict[str, Any]:
    """Tom tat cho staff detail view (da la du lieu committed, khong PII day du)."""
    return {
        "receipt_id": receipt.receipt_id,
        "outcome": receipt.outcome,
        "resource": receipt.resource,
        "result": receipt.result,
        "committed_at": receipt.committed_at,
        "duplicate": receipt.duplicate,
        "correlation_id": receipt.correlation_id,
    }
