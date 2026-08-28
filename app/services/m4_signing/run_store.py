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

import datetime as _dt
import json
import re
from typing import Any

from app.db_pool import get_pool


def _parse_ts(v: str | _dt.datetime | None) -> _dt.datetime | None:
    """Chuyen ISO string (ke ca hau to 'Z') -> datetime cho asyncpg timestamptz."""
    if v is None or isinstance(v, _dt.datetime):
        return v
    s = str(v).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return _dt.datetime.fromisoformat(s)

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

# Tiered model (Review 64). Tier A = evidence_batch/synthetic (single-operator, HMAC eval).
# Tier B = production (Ed25519-KMS + SoD + ceremony). Cap routine do CA chot.
ROUTINE_BATCH_CAP = 260   # bang cap eval hien tai; vuot -> escalate Tier B
ROUTINE_QUOTA_CAP = 5     # STS/sign moi loai; vuot -> escalate Tier B
TIER_A_KINDS = frozenset({"synthetic_rehearsal", "evidence_batch"})
VALID_KINDS = frozenset({"synthetic_rehearsal", "production", "evidence_batch"})


def _evaluate_escalation(run_kind: str, *, scope: dict, data_boundary: dict,
                         quota_sts: int, quota_sign: int) -> tuple[str, list[str]]:
    """Auto-escalate Tier A -> production (fail-closed) neu bat ky trigger §4 policy.

    Tra (final_run_kind, flags). Chi escalate Tier A; production giu nguyen. "Khong khai/khong
    chac" khong tu ha xuong Tier A: caller phai KHAI TUONG MINH evidence_batch moi vao Tier A.
    """
    if run_kind not in TIER_A_KINDS:
        return run_kind, []
    flags: list[str] = []
    db = data_boundary or {}
    if db.get("non_repudiation") or db.get("external_delivery") or db.get("legal"):
        flags.append("non_repudiation_or_external")
    if db.get("unmasked_pii") or db.get("pii_outside_eval"):
        flags.append("pii_outside_scope")
    if db.get("cross_tenant"):
        flags.append("cross_tenant")
    if db.get("retention_beyond_run"):
        flags.append("retention_beyond_run")
    try:
        batch_size = int(scope.get("batch_size", 0) or 0)
    except (TypeError, ValueError):
        batch_size = 0
    if batch_size > ROUTINE_BATCH_CAP:
        flags.append(f"batch_over_cap({batch_size}>{ROUTINE_BATCH_CAP})")
    if quota_sts > ROUTINE_QUOTA_CAP or quota_sign > ROUTINE_QUOTA_CAP:
        flags.append(f"quota_over_routine(sts={quota_sts},sign={quota_sign})")
    if flags:
        return "production", flags
    return run_kind, flags

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


_JSONB_RUN_COLS = ("scope", "data_boundary", "public_metadata")


def _hydrate_run(row) -> dict:
    """asyncpg tra jsonb duoi dang str -> decode ve dict cho cac cot JSON cua run."""
    d = dict(row)
    for col in _JSONB_RUN_COLS:
        if isinstance(d.get(col), str):
            try:
                d[col] = json.loads(d[col])
            except (ValueError, TypeError):
                d[col] = {}
    return d


def _hydrate_json(rows, col: str = "detail") -> list[dict]:
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get(col), str):
            try:
                d[col] = json.loads(d[col])
            except (ValueError, TypeError):
                d[col] = {}
        out.append(d)
    return out


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
    purpose: str | None = None,
) -> dict:
    """Tao run moi o state CREATED. Fail neu con run active cung run_kind.

    Tiered (Review 64): Tier A (evidence_batch/synthetic) single-operator; production ep SoD.
    Auto-escalate: Tier A co trigger §4 -> buoc production (fail-closed), ghi escalation_flags.
    """
    scope = scope or {}
    data_boundary = data_boundary or {}
    _assert_no_secret(scope, "scope")
    _assert_no_secret(data_boundary, "data_boundary")
    if run_kind not in VALID_KINDS:
        raise RunStoreError("run_kind khong hop le")
    # Auto-escalate Tier A -> production neu co trigger.
    run_kind, esc_flags = _evaluate_escalation(
        run_kind, scope=scope, data_boundary=data_boundary,
        quota_sts=quota_sts, quota_sign=quota_sign)
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
                   quota_sts, quota_sign, data_boundary, created_by, state,
                   purpose, escalation_flags)
                VALUES ($1,$2,$3::jsonb,$4,$5,$6,$7,$8::jsonb,$9,'CREATED',$10,$11::jsonb)
                RETURNING run_id, state, run_kind, created_at
                """,
                run_kind, change_ticket, json.dumps(scope),
                _parse_ts(window_start), _parse_ts(window_end),
                quota_sts, quota_sign, json.dumps(data_boundary), created_by,
                purpose, json.dumps(esc_flags),
            )
            await _write_event(
                conn, row["run_id"], "created", None, "CREATED",
                actor_staff_id=created_by, reason=change_ticket,
                detail={"run_kind": run_kind, "escalated": bool(esc_flags),
                        "escalation_flags": esc_flags},
            )
    return dict(row)


async def get_run(run_id: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM m4_signing_run WHERE run_id = $1", run_id)
    return _hydrate_run(row) if row else None


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
    return _hydrate_json(rows, "detail")


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
            # SoD CHI ap cho production (Tier B). Tier A (evidence_batch/synthetic) single-operator:
            # operator duoc tu approve canary (Review 64). Voi production:
            is_production = row["run_kind"] == "production"
            if is_production:
                # (a) chong same-person khi ca hai da set
                if operator is not None and approver is not None and operator == approver:
                    raise SoDViolation("SoD production: approver phai khac operator")
                # (b) execute yeu cau ca hai non-NULL + khac (defense-in-depth cung DB CHECK)
                if event == "execute_start" and (operator is None or approver is None
                                                 or operator == approver):
                    raise SoDViolation(
                        "SoD production: execute yeu cau ca operator lan approver (khac nhau)")

            new_meta = None
            if public_metadata is not None:
                existing = row["public_metadata"]
                if isinstance(existing, str):
                    try:
                        existing = json.loads(existing)
                    except (ValueError, TypeError):
                        existing = {}
                merged = dict(existing or {})
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
    return _hydrate_run(updated)


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
