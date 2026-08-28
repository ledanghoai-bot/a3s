"""M4-9 — State machine + ledger store cho signing run (bang m4_signing_run*).

Nguon su that cua trang thai run nam o DB. Module nay:
- dinh nghia transition HOP LE (fail-closed: transition la giá trị allowlist, khong suy dien);
- ghi event + attempt vao ledger BAT BIEN (append-only, migration 046 chan UPDATE/DELETE);
- ep SoD (approver != operator) o ca service layer lan DB constraint;
- KHONG cho 2 run active song song (partial unique index + advisory lock khi execute).

KHONG chua secret/PIN/private key/token/customer data. Cot JSON (scope/public_metadata/detail)
duoc kiem "no-secret" o ca service (`_assert_no_secret`) lan DB CHECK.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.db_pool import get_pool

# --- State machine -----------------------------------------------------------
# Transition hop le: {from_state: {event: to_state}}. Bat ky cap (state,event) khong co o day
# la BAT HOP LE -> raise InvalidTransition (fail-closed, khong "doan" state ke tiep).
TRANSITIONS: dict[str, dict[str, str]] = {
    "CREATED": {"confirm": "CONFIRMED", "abort": "ABORTED"},
    "CONFIRMED": {"preflight_pass": "PREFLIGHT_PASSED", "preflight_fail": "ABORTED",
                  "abort": "ABORTED"},
    "PREFLIGHT_PASSED": {"ceremony_record": "CEREMONY_RECORDED", "abort": "ABORTED"},
    "CEREMONY_RECORDED": {"canary_request": "CANARY_PENDING", "abort": "ABORTED"},
    "CANARY_PENDING": {"canary_approve": "CANARY_APPROVED", "abort": "ABORTED"},
    "CANARY_APPROVED": {"execute_start": "EXECUTING", "abort": "ABORTED"},
    "EXECUTING": {"execute_success": "CLOSED", "execute_fail": "FAILED", "abort": "ABORTED"},
    # terminal states: khong con transition
    "CLOSED": {},
    "ABORTED": {},
    "FAILED": {},
}
TERMINAL_STATES = frozenset({"CLOSED", "ABORTED", "FAILED"})

# Cac pattern secret hien nhien — chan o service layer TRUOC khi cham DB (defense-in-depth).
_SECRET_RE = re.compile(
    r"(pin_secret|private[_ ]?key|\btoken\b|password|-----BEGIN|ya29\.)", re.IGNORECASE
)


class RunStoreError(Exception):
    """Loi nghiep vu store (khong leak chi tiet nhay cam)."""


class InvalidTransition(RunStoreError):
    pass


class SoDViolation(RunStoreError):
    pass


class SecretLeakBlocked(RunStoreError):
    pass


class ActiveRunExists(RunStoreError):
    pass


def _assert_no_secret(obj: Any, where: str) -> None:
    """Chan secret hien nhien lot vao payload JSON tu dashboard."""
    if obj is None:
        return
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    if _SECRET_RE.search(text):
        raise SecretLeakBlocked(f"Payload {where} chua chuoi giong secret — tu choi ghi")


async def create_run(
    *,
    created_by: int,
    run_kind: str = "synthetic_rehearsal",
    change_ticket: str | None = None,
    scope: dict | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    quota_sts: int = 3,
    quota_sign: int = 3,
    data_boundary: dict | None = None,
) -> dict:
    """Tao run moi o state CREATED. Fail neu con run active cung run_kind."""
    scope = scope or {}
    data_boundary = data_boundary or {}
    _assert_no_secret(scope, "scope")
    _assert_no_secret(data_boundary, "data_boundary")
    if run_kind not in ("synthetic_rehearsal", "production"):
        raise RunStoreError("run_kind khong hop le")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchval(
                "SELECT run_id FROM m4_signing_run "
                "WHERE run_kind = $1 AND state NOT IN ('CLOSED','ABORTED','FAILED') LIMIT 1",
                run_kind,
            )
            if existing is not None:
                raise ActiveRunExists(f"Da co run active ({run_kind}); dong no truoc")
            row = await conn.fetchrow(
                """
                INSERT INTO m4_signing_run
                  (run_kind, change_ticket, scope, window_start, window_end,
                   quota_sts, quota_sign, data_boundary, created_by, state)
                VALUES ($1,$2,$3::jsonb,$4::timestamptz,$5::timestamptz,$6,$7,$8::jsonb,$9,'CREATED')
                RETURNING run_id, state, run_kind, created_at
                """,
                run_kind, change_ticket, json.dumps(scope), window_start, window_end,
                quota_sts, quota_sign, json.dumps(data_boundary), created_by,
            )
            await _write_event(
                conn, row["run_id"], "created", None, "CREATED",
                actor_staff_id=created_by, reason=change_ticket, detail={"run_kind": run_kind},
            )
    return dict(row)


async def get_run(run_id: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM m4_signing_run WHERE run_id = $1", run_id)
    return dict(row) if row else None


async def list_runs(limit: int = 50) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT run_id, state, run_kind, change_ticket, created_by, operator_staff_id, "
            "approver_staff_id, terminal_reason, created_at, updated_at "
            "FROM m4_signing_run ORDER BY created_at DESC LIMIT $1",
            limit,
        )
    return [dict(r) for r in rows]


async def list_events(run_id: str) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT event_type, from_state, to_state, actor_staff_id, reason, detail, created_at "
            "FROM m4_signing_run_event WHERE run_id = $1 ORDER BY created_at",
            run_id,
        )
    return [dict(r) for r in rows]


async def attempt_counts(run_id: str) -> dict[str, int]:
    """Dem attempt theo kind — dem theo SO ROW ledger, khong the reset."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT attempt_kind, count(*) AS n FROM m4_signing_run_attempt "
            "WHERE run_id = $1 GROUP BY attempt_kind",
            run_id,
        )
    return {r["attempt_kind"]: r["n"] for r in rows}


async def record_attempt(
    run_id: str, attempt_kind: str, outcome: str, detail: dict | None = None
) -> None:
    """Ghi 1 attempt vao ledger bat bien. Dung cho quota enforcement (dem row)."""
    detail = detail or {}
    _assert_no_secret(detail, "attempt.detail")
    if attempt_kind not in ("sts", "sign", "preflight", "canary"):
        raise RunStoreError("attempt_kind khong hop le")
    if outcome not in ("started", "ok", "transient_failed", "failed"):
        raise RunStoreError("outcome khong hop le")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO m4_signing_run_attempt (run_id, attempt_kind, outcome, detail) "
            "VALUES ($1,$2,$3,$4::jsonb)",
            run_id, attempt_kind, outcome, json.dumps(detail),
        )


async def transition(
    run_id: str,
    event: str,
    *,
    actor_staff_id: int | None,
    reason: str | None = None,
    detail: dict | None = None,
    set_operator: bool = False,
    set_approver: bool = False,
    public_metadata: dict | None = None,
) -> dict:
    """Chuyen state theo allowlist TRANSITIONS. Atomic + ghi event. Fail-closed.

    - `set_operator`: gan actor lam operator (buoc ceremony/execute).
    - `set_approver`: gan actor lam approver (buoc canary approve) — ep SoD != operator.
    - `public_metadata`: merge vao run (buoc ceremony) — kiem no-secret.
    """
    detail = detail or {}
    _assert_no_secret(detail, "event.detail")
    if public_metadata is not None:
        _assert_no_secret(public_metadata, "public_metadata")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM m4_signing_run WHERE run_id = $1 FOR UPDATE", run_id
            )
            if row is None:
                raise RunStoreError("run khong ton tai")
            cur = row["state"]
            allowed = TRANSITIONS.get(cur, {})
            if event not in allowed:
                raise InvalidTransition(
                    f"Transition '{event}' khong hop le tu state '{cur}'"
                )
            to_state = allowed[event]

            operator = row["operator_staff_id"]
            approver = row["approver_staff_id"]
            if set_operator:
                operator = actor_staff_id
            if set_approver:
                approver = actor_staff_id
            # SoD: approver != operator (khi ca hai da xac dinh)
            if operator is not None and approver is not None and operator == approver:
                raise SoDViolation("SoD: nguoi approve canary phai khac operator")

            new_meta = None
            if public_metadata is not None:
                merged = dict(row["public_metadata"] or {})
                merged.update(public_metadata)
                new_meta = json.dumps(merged)

            await conn.execute(
                """
                UPDATE m4_signing_run
                   SET state = $2,
                       operator_staff_id = $3,
                       approver_staff_id = $4,
                       public_metadata = COALESCE($5::jsonb, public_metadata),
                       terminal_reason = CASE WHEN $2 IN ('CLOSED','ABORTED','FAILED')
                                              THEN $6 ELSE terminal_reason END,
                       updated_at = now()
                 WHERE run_id = $1
                """,
                run_id, to_state, operator, approver, new_meta, reason,
            )
            await _write_event(
                conn, run_id, event, cur, to_state,
                actor_staff_id=actor_staff_id, reason=reason, detail=detail,
            )
            updated = await conn.fetchrow("SELECT * FROM m4_signing_run WHERE run_id = $1", run_id)
    return dict(updated)


async def _write_event(
    conn, run_id, event_type, from_state, to_state, *, actor_staff_id, reason, detail
) -> None:
    await conn.execute(
        "INSERT INTO m4_signing_run_event "
        "(run_id, event_type, from_state, to_state, actor_staff_id, reason, detail) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)",
        run_id, event_type, from_state, to_state, actor_staff_id, reason,
        json.dumps(detail, ensure_ascii=False),
    )
