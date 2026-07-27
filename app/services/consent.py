"""Consent projection + suppression (I-B M3 Slice 3). Spec M3 §7.4; Scalffold §13.5, tests §13.19.

Ledger append-only (`consent_records`, migration 031). Projection = record mới nhất theo
`authority_revision` per (customer, purpose, channel-phù-hợp). Enforcement point đầu tiên cho mọi
outbound (dispatcher S5 gọi `check_permission`).

Quy tắc quyết định (spec §7.4):
  - P03 transactional (và P01/P02/P04 service mặc nhiên theo yêu cầu khách) KHÔNG bị chặn bởi
    opt-out marketing — chỉ bị chặn khi có denial TƯỜNG MINH đúng purpose đó.
  - P05 lifecycle / P06 marketing: cần granted còn hiệu lực; withdrawn/denied/expired/không có -> deny.
  - Complaint (captured_via='complaint') mở suppression: chặn P06 (promotion) bất kể granted trước đó,
    cho tới khi có record giải tỏa mới (revision cao hơn, captured_via='complaint_resolved').
  - Lỗi hạ tầng -> 'unavailable'; caller PHẢI fail-closed cho P05/P06 (spec: unavailable fail-closed).
Audit: caller lưu `decision_ref` (opaque), KHÔNG copy evidence body.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

PURPOSES_DEFAULT_ALLOW = {"P01_CONSULT", "P02_COMMERCE", "P03_TRANSACTIONAL", "P04_SUPPORT"}
PURPOSES_CONSENT_REQUIRED = {"P05_LIFECYCLE", "P06_MARKETING", "P08_CONTENT_INSIGHT",
                             "P09_UGC_PUBLICATION"}


@dataclass(frozen=True)
class PermissionDecision:
    decision: str      # allow | deny | unavailable
    reason_code: str
    decision_ref: str  # opaque — đưa vào outbound audit


async def record_consent(
    conn,
    *,
    customer_id: int,
    purpose_code: str,
    status: str,
    captured_via: str,
    policy_version: str,
    notice_version: str,
    channel: str = "any",
    evidence_ref: str | None = None,
    jurisdiction: str = "VN",
) -> dict:
    """Append record mới với authority_revision = max+1 (per customer/purpose/channel).
    Chạy trong transaction của caller; unique index chặn ghi đè revision (không timestamp-race)."""
    row = await conn.fetchrow(
        "INSERT INTO consent_records (customer_id, purpose_code, channel, policy_version, "
        "notice_version, status, captured_via, evidence_ref, withdrawn_at, jurisdiction, "
        "authority_system, authority_revision) "
        "SELECT $1,$2,$3,$4,$5,$6,$7,$8, CASE WHEN $6='withdrawn' THEN now() END, $9, 'alpha3s', "
        "  COALESCE((SELECT max(authority_revision) FROM consent_records "
        "            WHERE customer_id=$1 AND purpose_code=$2 AND channel=$3), 0) + 1 "
        "RETURNING consent_id, authority_revision, policy_version, notice_version",
        customer_id, purpose_code, channel, policy_version, notice_version, status,
        captured_via, evidence_ref, jurisdiction,
    )
    return dict(row)


async def record_complaint(conn, *, customer_id: int, evidence_ref: str | None,
                           policy_version: str, notice_version: str) -> dict:
    """Complaint mở suppression promotion (§13.19 #3): record P06 denied, captured_via='complaint'."""
    return await record_consent(
        conn, customer_id=customer_id, purpose_code="P06_MARKETING", status="denied",
        captured_via="complaint", policy_version=policy_version, notice_version=notice_version,
        evidence_ref=evidence_ref)


async def _latest(conn, customer_id: int, purpose_code: str, channel: str):
    """Record hiệu lực = revision cao nhất; channel cụ thể thắng 'any' khi cùng tồn tại
    (lấy revision cao nhất trong cả hai — opt-out 'any' phủ mọi channel cùng purpose)."""
    return await conn.fetchrow(
        "SELECT consent_id, status, captured_via, authority_revision, policy_version, notice_version "
        "FROM consent_records WHERE customer_id=$1 AND purpose_code=$2 AND channel IN ($3, 'any') "
        "ORDER BY authority_revision DESC, captured_at DESC LIMIT 1",
        customer_id, purpose_code, channel,
    )


async def check_permission(conn, *, customer_id: int, purpose_code: str,
                           channel: str = "any") -> PermissionDecision:
    """API spec §7.4: -> allow | deny | unavailable (+reason_code, decision_ref).
    KHÔNG raise cho lỗi hạ tầng — trả 'unavailable' để caller fail-closed (P05/P06)."""
    ref = str(uuid.uuid4())
    try:
        latest = await _latest(conn, customer_id, purpose_code, channel)
        if purpose_code in PURPOSES_DEFAULT_ALLOW:
            # Opt-out P06 KHÔNG chặn transactional; chỉ denial tường minh đúng purpose mới chặn.
            if latest is not None and latest["status"] in ("denied", "withdrawn"):
                return PermissionDecision("deny", "explicit_denial", ref)
            return PermissionDecision("allow", "service_default", ref)
        if purpose_code in PURPOSES_CONSENT_REQUIRED:
            if purpose_code == "P06_MARKETING":
                comp = await conn.fetchrow(
                    "SELECT captured_via FROM consent_records WHERE customer_id=$1 "
                    "AND purpose_code='P06_MARKETING' AND captured_via IN ('complaint','complaint_resolved') "
                    "ORDER BY authority_revision DESC, captured_at DESC LIMIT 1", customer_id)
                if comp is not None and comp["captured_via"] == "complaint":
                    return PermissionDecision("deny", "complaint_suppression", ref)
            if latest is None:
                return PermissionDecision("deny", "no_consent", ref)
            if latest["status"] == "granted":
                return PermissionDecision("allow", "granted", ref)
            return PermissionDecision("deny", f"status_{latest['status']}", ref)
        # Purpose ngoài registry hành vi (P07/P10/P11 không phải outbound-per-customer):
        return PermissionDecision("deny", "purpose_not_outbound", ref)
    except Exception:  # noqa: BLE001 — lỗi hạ tầng: KHÔNG đoán, trả unavailable (fail-closed ở caller)
        return PermissionDecision("unavailable", "infrastructure_error", ref)


async def consent_versions(conn, *, customer_id: int, purpose_code: str,
                           channel: str = "any") -> dict | None:
    """§13.19 #13: consent version truy xuất được (policy/notice version của record hiệu lực)."""
    latest = await _latest(conn, customer_id, purpose_code, channel)
    return dict(latest) if latest is not None else None
