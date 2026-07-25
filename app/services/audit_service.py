"""Audit foundation (I-B M0.3).

Hai nhom (CA-REVIEW-IMPL-M0 §5):
- Nhom A — FAIL-CLOSED: `record(conn=...)` dung CHINH connection cua transaction dang mo, nen
  audit_log insert + business mutation commit/rollback CUNG nhau. Loi ghi audit -> vo transaction
  -> mutation rollback. Dung cho sensitive mutation (staff CRUD, role/permission, refund, ...).
- Nhom B — BEST-EFFORT: `record_best_effort()` tu mo connection rieng + nuot loi. CHI dung cho
  telemetry/diagnostic khong phai business (vd login failure).

Redaction (CA §10.2): before/after loc bo secret/PII thua truoc khi luu.
Append-only theo convention (khong ham update/delete o day). Cot before/after la JSONB.
"""
import json

import asyncpg

from app.config import settings

_SENSITIVE_KEYS = {
    # credential/secret
    "password", "password_hash", "password_salt", "new_password", "old_password",
    "current_password", "token", "session_token", "authorization", "secret", "app_secret",
    "page_access_token", "otp", "card", "cvv", "api_key", "private_key",
    # PII (CA-REVIEW-M0-DEV-002 §8: phone/email/address + nested)
    "phone", "phone_clean", "sdt", "so_dien_thoai", "mobile",
    "email", "e_mail",
    "address", "dia_chi", "diachi", "shipping_address",
    "psid", "external_id",
}


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _redact_value(v):
    """Redact DE QUY: dict -> loc key nhay cam; list -> tung phan tu; scalar giu nguyen.
    Xu ly payload long nhau (CA-REVIEW-M0-DEV-002 §8)."""
    if isinstance(v, dict):
        return {
            k: ("***REDACTED***" if k.lower() in _SENSITIVE_KEYS else _redact_value(val))
            for k, val in v.items()
        }
    if isinstance(v, (list, tuple)):
        return [_redact_value(x) for x in v]
    return v


def _redact(d: dict | None) -> str | None:
    """Tra ve JSON string da redact (hoac None). Loc key nhay cam (credential+PII) o MOI cap."""
    if d is None:
        return None
    return json.dumps(_redact_value(d), ensure_ascii=False, default=str)


async def record(
    conn,
    actor_type: str,
    action: str,
    *,
    actor_ref: str | None = None,
    actor_staff_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Nhom A (fail-closed). `conn` PHAI la connection cua transaction dang mo cua mutation."""
    await conn.execute(
        "INSERT INTO audit_log(actor_type,actor_ref,actor_staff_id,action,entity_type,entity_id,"
        "before,after,reason,request_id,correlation_id) "
        "VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9,$10,$11)",
        actor_type, actor_ref, actor_staff_id, action, entity_type, entity_id,
        _redact(before), _redact(after), reason, request_id, correlation_id,
    )


async def record_best_effort(actor_type: str, action: str, **kwargs) -> None:
    """Nhom B (telemetry). Tu mo connection, nuot loi — KHONG dung cho sensitive mutation."""
    try:
        conn = await asyncpg.connect(_db_url())
        try:
            await record(conn, actor_type, action, **kwargs)
        finally:
            await conn.close()
    except Exception as e:  # noqa: BLE001 - telemetry khong duoc lam vo flow chinh
        print(f"[audit] best-effort record loi (bo qua): {e}")
