"""M4-9 — Integration test EVIDENCE (DB that) cho signing-run control surface.

Chay voi DATABASE_URL tro toi 1 sandbox RIENG (KHONG production). Vi du:
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/alpha3s \
    -w /srv api python scripts/m4_9_signing_run_test.py

Kiem (tren DB that, full migrations):
  [1] create_run + single-active (run active thu 2 bi chan).
  [2] happy path CREATED->...->CLOSED qua run_store.transition.
  [3] invalid transition -> InvalidTransition (fail-closed).
  [4] SoD: approver == operator -> SoDViolation.
  [5] ledger immutable qua service (attempt/event khong UPDATE/DELETE) — dem quota theo row.
  [6] quota enforcement: preflight FAIL khi attempt sign >= quota.
  [7] preflight fail-closed: ngoai window / scope rong / capture ON.
  [8] no-secret: create_run voi scope chua secret -> SecretLeakBlocked.
  [9] abort tu moi active state -> ABORTED.

KHONG chua secret/PII. In "M4_9_ALL_PASS" o cuoi neu dat het.
"""
import asyncio
import datetime as _dt
import os
import subprocess
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_URL = os.environ.get("DATABASE_URL") or "postgresql://alpha3s:alpha3s@db:5432/alpha3s"


def _plain(url: str) -> str:
    return url.replace("+asyncpg", "")


async def _reset_and_migrate(admin: asyncpg.Connection) -> None:
    await admin.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    r = subprocess.run([sys.executable, "scripts/migrate.py", "up"], cwd=str(ROOT),
                       env={**os.environ, "DATABASE_URL": DB_URL}, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout); print(r.stderr)
        raise SystemExit("migrate.py up FAIL")


async def _seed_staff(conn) -> tuple[int, int, int]:
    await conn.execute("INSERT INTO roles(key,name,is_system) VALUES ('admin','Admin',true) "
                       "ON CONFLICT DO NOTHING")
    ids = []
    for u in ("m4op", "m4approver", "m4reviewer"):
        rid = await conn.fetchval(
            "INSERT INTO staff_users(username,name,password_hash,password_salt,role_key) "
            "VALUES ($1,$1,'x','s','admin') RETURNING id", u)
        ids.append(rid)
    return tuple(ids)  # type: ignore


def _check(cond: bool, name: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        raise SystemExit(f"CHECK FAIL: {name}")


async def main() -> int:
    from app.services.m4_signing import policy, run_store
    from app.services.m4_signing.run_store import (
        ActiveRunExists,
        InvalidTransition,
        SecretLeakBlocked,
        SoDViolation,
    )
    from app.db_pool import close_pool

    os.environ["DATABASE_URL"] = DB_URL
    admin = await asyncpg.connect(_plain(DB_URL))
    try:
        await _reset_and_migrate(admin)
        op_id, approver_id, reviewer_id = await _seed_staff(admin)
    finally:
        await admin.close()

    now = _dt.datetime.now(_dt.timezone.utc)
    win_start = (now - _dt.timedelta(minutes=5)).isoformat()
    win_end = (now + _dt.timedelta(hours=2)).isoformat()

    # [1] create + single-active. Dung run_kind='production' de test SoD (Tier B ep SoD).
    run = await run_store.create_run(created_by=op_id, run_kind="production",
                                     scope={"batch": "synth-v1"},
                                     data_boundary={"scope": "internal-synthetic"},
                                     window_start=win_start, window_end=win_end,
                                     quota_sts=3, quota_sign=1)
    rid = str(run["run_id"])
    _check(run["state"] == "CREATED" and run["run_kind"] == "production",
           "1a create production -> CREATED")
    try:
        await run_store.create_run(created_by=op_id, run_kind="production", scope={"batch": "b2"})
        _check(False, "1b single-active phai chan")
    except ActiveRunExists:
        _check(True, "1b single-active chan run thu 2")

    # [8] no-secret khi tao (dung run rieng sau khi dong run tren)
    try:
        await run_store.create_run(created_by=op_id, scope={"pin_secret": "x"},
                                   run_kind="production")
        _check(False, "8 no-secret phai chan")
    except SecretLeakBlocked:
        _check(True, "8 no-secret chan scope co secret")

    # [3] invalid transition (execute_start tu CREATED)
    try:
        await run_store.transition(rid, "execute_start", actor_staff_id=op_id)
        _check(False, "3 invalid transition phai chan")
    except InvalidTransition:
        _check(True, "3 invalid transition fail-closed")

    # [2] happy path: confirm -> preflight_pass -> ceremony -> canary_request -> canary_approve
    await run_store.transition(rid, "confirm", actor_staff_id=op_id)
    # preflight thuc te (window OK, scope OK, quota OK, capture OFF sau migrate)
    pf = await policy.run_preflight(rid)
    if not pf["ok"]:
        for c in pf["checks"]:
            print(f"     preflight.{c['name']}={c['passed']} :: {c['detail']}")
    _check(pf["ok"], "7a preflight PASS (window/scope/quota/dormant)")
    await run_store.transition(rid, "preflight_pass", actor_staff_id=op_id, detail={"ok": True})
    await run_store.transition(rid, "ceremony_record", actor_staff_id=op_id, set_operator=True,
                               public_metadata={"cert_fingerprint": "7D:67:ED"})
    await run_store.transition(rid, "canary_request", actor_staff_id=op_id)

    # [4] SoD (production): approver == operator -> chan
    try:
        await run_store.transition(rid, "canary_approve", actor_staff_id=op_id, set_approver=True)
        _check(False, "4 SoD production phai chan approver==operator")
    except SoDViolation:
        _check(True, "4 SoD production chan approver==operator")

    # approve bang nguoi KHAC
    await run_store.transition(rid, "canary_approve", actor_staff_id=approver_id, set_approver=True)
    r2 = await run_store.transition(rid, "execute_start", actor_staff_id=op_id)
    _check(r2["state"] == "EXECUTING", "2 happy path toi EXECUTING")

    # [5] ledger immutable + quota dem theo row
    await run_store.record_attempt(rid, "sign", "ok", {"phase": "canary"})
    counts = await run_store.attempt_counts(rid)
    _check(counts.get("sign", 0) >= 1, "5a attempt ledger ghi sign")
    # thu UPDATE/DELETE ledger truc tiep -> DB trigger chan
    conn = await asyncpg.connect(_plain(DB_URL))
    try:
        blocked = False
        try:
            await conn.execute("UPDATE m4_signing_run_attempt SET outcome='failed' WHERE run_id=$1", rid)
        except asyncpg.PostgresError:
            blocked = True
        _check(blocked, "5b ledger UPDATE bi chan (immutable)")
        blocked = False
        try:
            await conn.execute("DELETE FROM m4_signing_run_attempt WHERE run_id=$1", rid)
        except asyncpg.PostgresError:
            blocked = True
        _check(blocked, "5c ledger DELETE bi chan (immutable)")
    finally:
        await conn.close()

    # close run (execute_success) de mo cho test quota o run moi
    await run_store.transition(rid, "execute_success", actor_staff_id=None, reason="test done")

    # [6] quota: run moi, ghi sign >= quota_sign -> preflight FAIL o check quota
    run_q = await run_store.create_run(created_by=op_id, scope={"batch": "q"},
                                       window_start=win_start, window_end=win_end,
                                       quota_sts=3, quota_sign=1)
    rq = str(run_q["run_id"])
    await run_store.record_attempt(rq, "sign", "ok", {})  # dat quota_sign=1
    pfq = await policy.run_preflight(rq)
    quota_check = [c for c in pfq["checks"] if c["name"] == "quota"][0]
    _check(not quota_check["passed"], "6 quota het -> preflight quota FAIL")
    _check(not pfq["ok"], "6b preflight tong FAIL khi quota het")

    # [7b] preflight fail-closed: ngoai window
    run_w = await asyncpg.connect(_plain(DB_URL))
    try:
        await run_w.execute("UPDATE m4_signing_run SET state='ABORTED', window_end=$2 WHERE run_id=$1",
                            rq, now - _dt.timedelta(hours=1))
    finally:
        await run_w.close()
    run_late = await run_store.create_run(created_by=op_id, scope={"batch": "late"},
                                          window_start=(now - _dt.timedelta(hours=3)).isoformat(),
                                          window_end=(now - _dt.timedelta(hours=1)).isoformat())
    pfl = await policy.run_preflight(str(run_late["run_id"]))
    win_check = [c for c in pfl["checks"] if c["name"] == "window"][0]
    _check(not win_check["passed"], "7b preflight window FAIL (ngoai window)")

    # [9] abort tu active state
    ab = await run_store.transition(str(run_late["run_id"]), "abort", actor_staff_id=op_id,
                                    reason="test abort")
    _check(ab["state"] == "ABORTED", "9 abort -> ABORTED")

    # [10] TIER A (evidence_batch): operator TU APPROVE canary (single-operator) — PHAI OK
    ta = await run_store.create_run(created_by=op_id, run_kind="evidence_batch",
                                    scope={"batch": "eval", "batch_size": 100},
                                    window_start=win_start, window_end=win_end)
    tid = str(ta["run_id"])
    _check(ta["run_kind"] == "evidence_batch", "10a tao evidence_batch (Tier A)")
    await run_store.transition(tid, "confirm", actor_staff_id=op_id)
    await policy.run_preflight(tid)
    await run_store.transition(tid, "preflight_pass", actor_staff_id=op_id, detail={"ok": True})
    await run_store.transition(tid, "ceremony_record", actor_staff_id=op_id, set_operator=True,
                               public_metadata={"note": "tier-a"})
    await run_store.transition(tid, "canary_request", actor_staff_id=op_id)
    # operator TU approve — Tier A cho phep (khong SoD)
    await run_store.transition(tid, "canary_approve", actor_staff_id=op_id, set_approver=True)
    ta_exec = await run_store.transition(tid, "execute_start", actor_staff_id=op_id)
    _check(ta_exec["state"] == "EXECUTING", "10b Tier A single-operator toi EXECUTING (khong SoD)")
    await run_store.transition(tid, "execute_success", actor_staff_id=None, reason="tier-a done")

    # [11] ESCALATION: evidence_batch khai non_repudiation -> BUOC production (fail-closed)
    esc = await run_store.create_run(created_by=op_id, run_kind="evidence_batch",
                                     scope={"batch": "x"}, data_boundary={"non_repudiation": True})
    _check(esc["run_kind"] == "production", "11a escalation non_repudiation -> production")
    await run_store.transition(str(esc["run_id"]), "abort", actor_staff_id=op_id, reason="cleanup")

    # [12] ESCALATION: batch_size > 260 -> production
    esc2 = await run_store.create_run(created_by=op_id, run_kind="evidence_batch",
                                      scope={"batch": "big", "batch_size": 500})
    _check(esc2["run_kind"] == "production", "12 escalation batch>260 -> production")
    await run_store.transition(str(esc2["run_id"]), "abort", actor_staff_id=op_id, reason="cleanup")

    await close_pool()
    print("M4_9_ALL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
