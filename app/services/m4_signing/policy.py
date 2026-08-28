"""M4-9 — Policy / preflight engine (read-only, fail-closed).

Cac check chay TRUOC khi cho phep chuyen buoc. Nguyen tac:
- fail-closed: bat ky loi/khong chac chan nao -> check FAIL (khong "gia dinh dat").
- server-side: window/scope/quota enforce o day + DB, KHONG tin client.
- read-only: khong mutation nao; khong start signer; khong cham secret.

Preflight tra ve dict co cau truc de UI hien va de ghi evidence:
  {"ok": bool, "checks": [{"name","passed","detail"}...], "evaluated_at": iso}
"""
from __future__ import annotations

import datetime as _dt

from app.db_pool import get_pool
from app.services.m4_signing import run_store

# Preflight "tuoi" trong bao lau (giay) truoc khi coi la stale — buoc sau phai chay lai.
PREFLIGHT_FRESHNESS_SECONDS = 15 * 60


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


async def _capture_is_off() -> tuple[bool, str]:
    """Dormant prerequisite: capture phai OFF. Fail-closed -> coi nhu KHONG dat khi loi."""
    try:
        from app.services.pii.stage0p_control import read_capture_enabled
    except Exception as exc:  # module chua san sang -> fail-closed
        return False, f"khong nap duoc stage0p_control: {type(exc).__name__}"
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            enabled = await read_capture_enabled(conn)
    except Exception as exc:
        return False, f"loi doc capture flag: {type(exc).__name__}"
    if enabled:
        return False, "capture dang ON — production khong dormant"
    return True, "capture OFF (dormant)"


def _check_window(run: dict) -> tuple[bool, str]:
    start = run.get("window_start")
    end = run.get("window_end")
    if start is None or end is None:
        return False, "thieu window_start/window_end"
    now = _now()
    if now < start:
        return False, f"chua toi window (bat dau {start.isoformat()})"
    if now >= end:
        return False, f"da qua window (ket thuc {end.isoformat()})"
    return True, f"trong window ({start.isoformat()} .. {end.isoformat()})"


async def _check_quota(run: dict) -> tuple[bool, str]:
    counts = await run_store.attempt_counts(run["run_id"])
    sts = counts.get("sts", 0)
    sign = counts.get("sign", 0)
    if sts >= run["quota_sts"]:
        return False, f"quota STS da het ({sts}/{run['quota_sts']})"
    if sign >= run["quota_sign"]:
        return False, f"quota sign da het ({sign}/{run['quota_sign']})"
    return True, f"quota con (STS {sts}/{run['quota_sts']}, sign {sign}/{run['quota_sign']})"


def _check_scope(run: dict) -> tuple[bool, str]:
    scope = run.get("scope") or {}
    if not isinstance(scope, dict) or not scope:
        return False, "scope rong — phai khai bao pham vi"
    # Production run bat buoc phai co data_boundary tuong minh.
    if run.get("run_kind") == "production":
        db = run.get("data_boundary") or {}
        if not db:
            return False, "production run thieu data_boundary"
    return True, "scope hop le"


async def run_preflight(run_id: str) -> dict:
    """Chay toan bo check read-only. Fail-closed: 1 check fail -> ok=False."""
    run = await run_store.get_run(run_id)
    if run is None:
        return {"ok": False, "checks": [{"name": "run_exists", "passed": False,
                                         "detail": "run khong ton tai"}],
                "evaluated_at": _now().isoformat()}

    checks: list[dict] = []

    ok_w, d_w = _check_window(run)
    checks.append({"name": "window", "passed": ok_w, "detail": d_w})

    ok_s, d_s = _check_scope(run)
    checks.append({"name": "scope", "passed": ok_s, "detail": d_s})

    ok_q, d_q = await _check_quota(run)
    checks.append({"name": "quota", "passed": ok_q, "detail": d_q})

    ok_c, d_c = await _capture_is_off()
    checks.append({"name": "dormant_capture_off", "passed": ok_c, "detail": d_c})

    ok = all(c["passed"] for c in checks)
    result = {"ok": ok, "checks": checks, "evaluated_at": _now().isoformat()}
    # Ghi attempt preflight (ledger) — dung ca khi fail (bang chung da chay).
    await run_store.record_attempt(
        run_id, "preflight", "ok" if ok else "failed",
        {"checks": [{"name": c["name"], "passed": c["passed"]} for c in checks]},
    )
    return result


def is_preflight_fresh(run: dict, events: list[dict]) -> tuple[bool, str]:
    """Kiem preflight gan nhat con "tuoi" khong (chong stale khi sang buoc ceremony/execute)."""
    last = None
    for ev in events:
        if ev["event_type"] == "preflight_pass":
            last = ev["created_at"]
    if last is None:
        return False, "chua co preflight PASS"
    age = (_now() - last).total_seconds()
    if age > PREFLIGHT_FRESHNESS_SECONDS:
        return False, f"preflight stale ({int(age)}s > {PREFLIGHT_FRESHNESS_SECONDS}s)"
    return True, f"preflight con tuoi ({int(age)}s)"
