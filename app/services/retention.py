"""Retention executor (I-B M3 Slice 6). Spec M3 §7.7; Directive §5-S6; docs/RETENTION-SCHEDULE.md.

Nguyên tắc:
  - Policy version hóa (`retention_policies`); APPLY chỉ khi status='approved' — dry-run với mọi status.
  - Legal hold override: customer/order đang hold (active) bị BỎ QUA (đếm skipped_hold), có audit.
  - Audit `retention_run_log` chỉ chứa số liệu + opaque refs — KHÔNG PII.
  - Restore/replay không tái sinh: policy là hàm hội tụ theo cutoff — dữ liệu quá hạn bị restore về
    sẽ bị xóa lại ở lần chạy kế (evidence m3_retention_test [6]).
  - KHÔNG chạy ngầm trong application startup (Directive §6): executor gọi tường minh
    (script/cron job riêng gate flag m3_retention_executor — job no-op khi flag OFF).

Category M3: raw_chat (RET-04: conversations/messages/escalations không hoạt động quá hạn),
deletion_requests (RET-09). Backup expiry (RET-06) = ops, ngoài executor — xem Schedule.
"""
from __future__ import annotations

import json

from app.config import settings


class RetentionError(Exception):
    pass


# F-M3-R1-02(1): action ĐƯỢC IMPLEMENT cho từng category — ngoài map này = fail-closed
# (action_not_implemented) TRƯỚC mọi mutation. anonymize/archive sẽ mở khi có handler thật.
SUPPORTED_ACTIONS: dict[str, set[str]] = {
    "raw_chat": {"delete"},
    "deletion_requests": {"delete"},
}


async def _counts_raw_chat(conn, cutoff_days: int, respect_hold: bool):
    """Conversation 'quá hạn' = không có message nào mới hơn cutoff (và tạo trước cutoff)."""
    hold_clause = (
        "AND NOT EXISTS (SELECT 1 FROM legal_holds h WHERE h.active AND h.customer_id = c.customer_id)"
        if respect_hold else "")
    rows = await conn.fetch(
        f"""SELECT c.id FROM conversations c
            WHERE COALESCE((SELECT max(m.created_at) FROM messages m WHERE m.conversation_id=c.id),
                           c.created_at) < now() - ($1 || ' days')::interval
            {hold_clause}""",
        str(cutoff_days))
    held = 0
    if respect_hold:
        held = await conn.fetchval(
            """SELECT count(*) FROM conversations c
               WHERE COALESCE((SELECT max(m.created_at) FROM messages m WHERE m.conversation_id=c.id),
                              c.created_at) < now() - ($1 || ' days')::interval
                 AND EXISTS (SELECT 1 FROM legal_holds h WHERE h.active AND h.customer_id=c.customer_id)""",
            str(cutoff_days))
    return [r["id"] for r in rows], held


async def _delete_raw_chat(conn, conv_ids: list[int]) -> dict:
    if not conv_ids:
        return {"messages_deleted": 0, "escalations_deleted": 0, "conversations_deleted": 0}
    m = await conn.execute("DELETE FROM messages WHERE conversation_id = ANY($1)", conv_ids)
    e = await conn.execute("DELETE FROM escalations WHERE conversation_id = ANY($1)", conv_ids)
    c = await conn.execute("DELETE FROM conversations WHERE id = ANY($1)", conv_ids)

    def _n(status):
        try:
            return int(status.split()[-1])
        except Exception:  # noqa: BLE001
            return 0
    return {"messages_deleted": _n(m), "escalations_deleted": _n(e), "conversations_deleted": _n(c)}


async def run_retention(conn, *, rule_id: str, version: int, dry_run: bool = True,
                        actor: str = "system") -> dict:
    """Chạy 1 policy. dry_run=True -> chỉ đếm, không mutation. Trả report (không PII)."""
    pol = await conn.fetchrow(
        "SELECT data_category, action, retention_period_days, respect_legal_hold, status "
        "FROM retention_policies WHERE rule_id=$1 AND version=$2", rule_id, version)
    if pol is None:
        raise RetentionError(f"policy_not_found:{rule_id}v{version}")
    if not dry_run and pol["status"] != "approved":
        raise RetentionError(f"policy_not_approved:{rule_id}v{version}:{pol['status']}")

    category = pol["data_category"]
    if category not in SUPPORTED_ACTIONS:
        raise RetentionError(f"category_not_implemented:{category}")
    # F-M3-R1-02(1): FAIL-CLOSED theo action TRƯỚC mọi mutation — approved không cho phép executor
    # đổi hành động PO đã duyệt (anonymize/archive chưa implement -> lỗi rõ ràng, không DELETE nhầm).
    if pol["action"] not in SUPPORTED_ACTIONS[category]:
        raise RetentionError(f"action_not_implemented:{category}:{pol['action']}")

    days = pol["retention_period_days"]
    counts: dict = {"candidates": 0}
    # F-M3-R1-02(4): mutation + run-log trong MỘT transaction boundary — không có chuyện xóa
    # thành công nhưng mất audit record (log lỗi -> rollback toàn bộ, kể cả dry-run count log).
    async with conn.transaction():
        if category == "raw_chat":
            # F-M3-R1-02(2): legal hold theo customer — linkable, enforce khi respect_legal_hold.
            conv_ids, held = await _counts_raw_chat(conn, days, pol["respect_legal_hold"])
            counts["candidates"] = len(conv_ids)
            counts["skipped_hold"] = held
            counts["legal_hold_semantics"] = (
                "customer_linked_enforced" if pol["respect_legal_hold"] else "policy_disabled")
            if not dry_run:
                counts.update(await _delete_raw_chat(conn, conv_ids))
        elif category == "deletion_requests":
            # F-M3-R1-02(2): semantics tường minh — bản ghi deletion_request KHÔNG còn link tới
            # customer (psid đã cắt khi xóa), legal hold per-customer/order KHÔNG áp được lên
            # category này. KHÔNG báo skipped_hold=0 gây hiểu nhầm; khai báo not-linkable.
            counts["legal_hold_semantics"] = "not_applicable_no_customer_link"
            if dry_run:
                counts["candidates"] = await conn.fetchval(
                    "SELECT count(*) FROM data_deletion_requests "
                    "WHERE requested_at < now() - ($1 || ' days')::interval", str(days))
            else:
                res = await conn.execute(
                    "DELETE FROM data_deletion_requests "
                    "WHERE requested_at < now() - ($1 || ' days')::interval", str(days))
                try:
                    counts["deleted"] = int(res.split()[-1])
                except Exception:  # noqa: BLE001
                    counts["deleted"] = 0
                counts["candidates"] = counts["deleted"]

        run_id = await conn.fetchval(
            "INSERT INTO retention_run_log (rule_id, version, dry_run, counts, actor, finished_at) "
            "VALUES ($1,$2,$3,$4::jsonb,$5, now()) RETURNING run_id",
            rule_id, version, dry_run, json.dumps(counts), actor)
    return {"run_id": str(run_id), "rule_id": rule_id, "version": version,
            "dry_run": dry_run, "counts": counts}


async def run_all_approved(conn, *, dry_run: bool = True, actor: str = "system") -> list[dict]:
    """Chạy mọi policy approved (bản mới nhất mỗi rule). Dùng bởi cron job (flag-gated) / script."""
    if not settings.m3_retention_executor and not dry_run:
        return [{"skipped": "flag_off"}]
    rules = await conn.fetch(
        "SELECT DISTINCT ON (rule_id) rule_id, version FROM retention_policies "
        "WHERE status='approved' ORDER BY rule_id, version DESC")
    out = []
    for r in rules:
        out.append(await run_retention(conn, rule_id=r["rule_id"], version=r["version"],
                                       dry_run=dry_run, actor=actor))
    return out
