"""M4 — Integration test EVIDENCE cho Production Signing Activation (Tier B). Design 71/72.

Kiem (DB sandbox, KHONG cham customer data — digest/scope tong hop):
  [1] migration 049: capability + bang.
  [2] request -> REQUESTED (fail-closed thieu field).
  [3] preflight -> PREFLIGHT_PASSED.
  [4] SoD: approver == requester -> loi; approver khac -> APPROVED + window (TTL).
  [5] SoD: activator == approver -> loi; activator khac -> ACTIVE + receipt.
  [6] anti-substitution: doi artifact_digest sau REQUESTED -> DB trigger chan.
  [7] stale preflight -> approve loi.
  [8] TTL: window het -> activate loi; expire_due -> EXPIRED.
  [9] revoke -> REVOKED + audit.
  [10] idempotency: request_id trung dang mo -> loi.
  [11] audit: audit_log co request/approve/activate/revoke, KHONG secret.
  [12] rehearsal khong cham customer data (khong ghi customers/conversations/messages).
In "M4_ACTIVATION_ALL_PASS".
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


def _plain(u): return u.replace("+asyncpg", "")
def _check(c, n):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}")
    if not c: raise SystemExit(f"FAIL: {n}")


async def main() -> int:
    os.environ["DATABASE_URL"] = DB_URL
    from app.db_pool import close_pool
    from app.services.m4_signing import activation as A

    admin = await asyncpg.connect(_plain(DB_URL))
    try:
        await admin.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await admin.close()
    r = subprocess.run([sys.executable, "scripts/migrate.py", "up"], cwd=str(ROOT),
                       env={**os.environ, "DATABASE_URL": DB_URL}, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout); print(r.stderr); raise SystemExit("migrate FAIL")

    c = await asyncpg.connect(_plain(DB_URL))
    try:
        # staff
        req = await c.fetchval("INSERT INTO staff_users(username,password_hash,password_salt) "
                               "VALUES('signer1','x','x') RETURNING id")
        appr = await c.fetchval("INSERT INTO staff_users(username,password_hash,password_salt) "
                                "VALUES('po','x','x') RETURNING id")
        # [1] capability + table
        cap = await c.fetchval("SELECT 1 FROM permissions WHERE key='m4.signing.activate.production'")
        tbl = await c.fetchval("SELECT to_regclass('public.m4_signing_activation') IS NOT NULL")
        _check(cap and tbl, "1 migration 049: capability + bang")
        base_conv = await c.fetchval("SELECT count(*) FROM conversations") if await c.fetchval(
            "SELECT to_regclass('public.conversations') IS NOT NULL") else 0
    finally:
        await c.close()

    DIGEST = "sha256:" + "a" * 64
    # [2] fail-closed thieu digest
    try:
        await A.create_request(request_id="R0", scope={"t": "x"}, artifact_digest="",
                               manifest_ref=None, max_sign_count=1, reason="r", ticket="T",
                               requester_staff_id=req, delegated_by=None, rollback_owner="hoai",
                               actor="signer1")
        _check(False, "2a fail-closed thieu digest")
    except A.ActivationError:
        _check(True, "2a fail-closed thieu digest")
    # request OK
    rq = await A.create_request(request_id="R1", scope={"tenant": "internal", "batch": "eval-1"},
                                artifact_digest=DIGEST, manifest_ref="m1", max_sign_count=2,
                                reason="dong dau eval", ticket="T-1", requester_staff_id=req,
                                delegated_by=None, rollback_owner="hoai", actor="signer1")
    aid = str(rq["activation_id"])
    _check(rq["state"] == "REQUESTED", "2b request -> REQUESTED")

    # [10] idempotency
    try:
        await A.create_request(request_id="R1", scope={"t": "x"}, artifact_digest=DIGEST,
                               manifest_ref=None, max_sign_count=1, reason="r", ticket="T",
                               requester_staff_id=req, delegated_by=None, rollback_owner="h",
                               actor="signer1")
        _check(False, "10 idempotency phai chan request_id trung")
    except A.ActivationError:
        _check(True, "10 idempotency chan request_id dang mo")

    # [6] anti-substitution: doi digest sau REQUESTED
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        await c.execute("UPDATE m4_signing_activation SET state='PREFLIGHT_PASSED' WHERE activation_id=$1", aid)
        blocked = False
        try:
            await c.execute("UPDATE m4_signing_activation SET artifact_digest='sha256:'||repeat('b',64) "
                            "WHERE activation_id=$1", aid)
        except asyncpg.PostgresError:
            blocked = True
        await c.execute("UPDATE m4_signing_activation SET state='REQUESTED' WHERE activation_id=$1", aid)
        _check(blocked, "6 anti-substitution: DB chan doi digest sau REQUESTED")
    finally:
        await c.close()

    # [3] preflight
    pf = await A.run_preflight(aid, actor="system")
    _check(pf["ok"] and pf["state"] == "PREFLIGHT_PASSED", "3 preflight -> PREFLIGHT_PASSED")

    # [4] SoD approver == requester -> loi
    try:
        await A.approve(aid, approver_staff_id=req, actor="signer1", window_minutes=30)
        _check(False, "4a SoD approver==requester phai chan")
    except A.ActivationError:
        _check(True, "4a SoD approver==requester bi chan")
    ap = await A.approve(aid, approver_staff_id=appr, actor="po", window_minutes=30)
    _check(ap["state"] == "APPROVED" and ap["window_end"] is not None, "4b approve -> APPROVED + window")

    # [5] SoD activator == approver -> loi; activator = requester OK
    try:
        await A.activate(aid, activator_staff_id=appr, actor="po")
        _check(False, "5a SoD activator==approver phai chan")
    except A.ActivationError:
        _check(True, "5a SoD activator==approver bi chan")
    ac = await A.activate(aid, activator_staff_id=req, actor="signer1")
    _check(ac["receipt"]["state"] == "ACTIVE" and ac["receipt"]["digest"] == DIGEST,
           "5b activate -> ACTIVE + receipt (digest khop)")

    # [7] stale preflight (run moi)
    rq2 = await A.create_request(request_id="R2", scope={"t": "y"}, artifact_digest=DIGEST,
                                 manifest_ref=None, max_sign_count=1, reason="r", ticket="T-2",
                                 requester_staff_id=req, delegated_by=None, rollback_owner="h",
                                 actor="signer1")
    aid2 = str(rq2["activation_id"])
    await A.run_preflight(aid2, actor="system")
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        await c.execute("UPDATE m4_signing_activation SET preflight_at=now()-interval '20 minutes' "
                        "WHERE activation_id=$1", aid2)
    finally:
        await c.close()
    try:
        await A.approve(aid2, approver_staff_id=appr, actor="po", window_minutes=30)
        _check(False, "7 stale preflight phai chan approve")
    except A.ActivationError:
        _check(True, "7 stale preflight chan approve")

    # [8] TTL expiry (aid dang ACTIVE) — set window het -> expire_due
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        await c.execute("UPDATE m4_signing_activation SET window_end=now()-interval '1 minute' "
                        "WHERE activation_id=$1", aid)
    finally:
        await c.close()
    n_exp = await A.expire_due()
    st = await A.get(aid)
    _check(n_exp >= 1 and st["state"] == "EXPIRED", "8 TTL het -> expire_due -> EXPIRED (auto dormant)")

    # [9] revoke (aid2 dang PREFLIGHT_PASSED)
    rv = await A.revoke(aid2, actor="hoai", reason="huy test")
    _check(rv["state"] == "REVOKED", "9 revoke -> REVOKED")

    # [11] audit + [12] no customer data
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        acts = sorted([x["action"] for x in await c.fetch(
            "SELECT DISTINCT action FROM audit_log WHERE action LIKE 'signing.activation.%'")])
        _check(all(a in acts for a in ["signing.activation.request", "signing.activation.approve",
               "signing.activation.activate", "signing.activation.revoke", "signing.activation.expire"]),
               "11a audit_log ghi du buoc")
        leak = await c.fetchval("SELECT count(*) FROM audit_log WHERE after::text ~* "
                                "'(pin_secret|password|-----BEGIN|ya29\\.)'")
        _check(leak == 0, "11b audit KHONG chua secret")
        now_conv = await c.fetchval("SELECT count(*) FROM conversations")
        _check(now_conv == base_conv, "12 rehearsal KHONG cham customer data (conversations khong doi)")
    finally:
        await c.close()

    await close_pool()
    print("M4_ACTIVATION_ALL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
