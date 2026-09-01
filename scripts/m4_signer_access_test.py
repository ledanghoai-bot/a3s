"""M4 — Integration test Signer Access workflow (Directive 91). DB sandbox + Redis + LocalDev.

Kiem (synthetic, KHONG customer data): submit fail-closed; idempotency; digest-lock; preflight that;
SoD approver==requester chan; approve -> ACTIVE + temp role grant + activation window lien ket;
PERMISSION RESOLUTION: requester co m4.signing.run.* qua temp grant; REHEARSAL grant KHONG cap quyen;
already-has-role -> khong cap temp; close -> revoke role + terminal activation -> perms mat;
stale preflight chan; expire_due -> EXPIRED + revoke; revoke; audit no-secret.
In "M4_SIGNER_ACCESS_ALL_PASS".
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB_URL = os.environ.get("DATABASE_URL") or "postgresql://alpha3s:alpha3s@db:5432/alpha3s"


def _plain(u):
    return u.replace("+asyncpg", "")


def _check(c, n):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}")
    if not c:
        raise SystemExit(f"FAIL: {n}")


async def _seed_registry(conn):
    from app.services.pii.signing_backend import LocalDevBackend
    b = LocalDevBackend(key_id="m4-transcript-ed25519-localdev")
    await conn.execute(
        "INSERT INTO m4_stage0p_transcript_public_keys(key_id,key_version,algorithm,public_key) "
        "VALUES('m4-transcript-ed25519-localdev',$1,'Ed25519',$2) ON CONFLICT DO NOTHING",
        b.key_version(), b.public_key_raw())


async def main() -> int:
    os.environ["DATABASE_URL"] = DB_URL
    from app.db_pool import close_pool
    from app.services import permission_service
    from app.services.m4_signing import signer_access as SA

    admin = await asyncpg.connect(_plain(DB_URL))
    try:
        await admin.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await admin.close()
    r = subprocess.run([sys.executable, "scripts/migrate.py", "up"], cwd=str(ROOT),
                       env={**os.environ, "DATABASE_URL": DB_URL}, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("migrate FAIL")

    DIGEST = "sha256:" + "a" * 64
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        signer = await c.fetchval("INSERT INTO staff_users(username,password_hash,password_salt) "
                                  "VALUES('signer1','x','x') RETURNING id")
        po = await c.fetchval("INSERT INTO staff_users(username,password_hash,password_salt) "
                              "VALUES('po','x','x') RETURNING id")
        await _seed_registry(c)
        # [1] migration objects
        t1 = await c.fetchval("SELECT to_regclass('public.m4_signer_access_request') IS NOT NULL")
        t2 = await c.fetchval("SELECT to_regclass('public.m4_temp_signer_role_grant') IS NOT NULL")
        p = await c.fetchval("SELECT count(*) FROM permissions WHERE key LIKE 'm4.signer_access.%'")
        _check(t1 and t2 and p == 3, "1 migration 051: 2 bang + 3 perm")
    finally:
        await c.close()

    async def perms_of(staff_id):
        cc = await asyncpg.connect(_plain(DB_URL))
        try:
            return (await permission_service.load_staff_authz(cc, staff_id))["permissions"]
        finally:
            await cc.close()

    # [2] submit fail-closed
    try:
        await SA.submit(request_id="", scope={"t": "x"}, artifact_digest=DIGEST, ticket="T",
                        reason="r", rollback_owner="h", requester_staff_id=signer, window_minutes=30,
                        actor="signer1")
        _check(False, "2 fail-closed thieu request_id")
    except SA.SignerAccessError:
        _check(True, "2 fail-closed thieu request_id")

    # [3] submit OK
    req = await SA.submit(request_id="R1", scope={"tenant": "internal"}, artifact_digest=DIGEST,
                          ticket="T-1", reason="ky eval", rollback_owner="hoai",
                          requester_staff_id=signer, window_minutes=30, actor="signer1")
    _check(req["state"] == "SUBMITTED", "3 submit -> SUBMITTED")

    # [4] idempotency
    try:
        await SA.submit(request_id="R1", scope={"t": "x"}, artifact_digest=DIGEST, ticket="T",
                        reason="r", rollback_owner="h", requester_staff_id=signer, window_minutes=30,
                        actor="signer1")
        _check(False, "4 idempotency phai chan")
    except SA.SignerAccessError:
        _check(True, "4 idempotency chan request_id trung")

    # [5] digest lock (anti-substitution) — DB trigger
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        await c.execute("UPDATE m4_signer_access_request SET state='PREFLIGHT_PASSED' WHERE request_id='R1'")
        blocked = False
        try:
            await c.execute("UPDATE m4_signer_access_request SET artifact_digest='sha256:'||repeat('b',64) WHERE request_id='R1'")
        except asyncpg.PostgresError:
            blocked = True
        await c.execute("UPDATE m4_signer_access_request SET state='SUBMITTED' WHERE request_id='R1'")
        _check(blocked, "5 digest lock: DB chan doi digest sau SUBMITTED")
    finally:
        await c.close()

    # [6] preflight that -> PREFLIGHT_PASSED
    pf = await SA.run_preflight("R1", actor="system")
    _check(pf["ok"] and pf["state"] == "PREFLIGHT_PASSED", "6 preflight that -> PREFLIGHT_PASSED")

    # [7] SoD approver==requester chan
    try:
        await SA.approve("R1", approver_staff_id=signer, actor="signer1")
        _check(False, "7 SoD approver==requester phai chan")
    except SA.SignerAccessError:
        _check(True, "7 SoD approver==requester bi chan (Addendum 90)")

    # [8] perms TRUOC approve: signer chua co run.*
    before = await perms_of(signer)
    _check("m4.signing.run.start" not in before, "8 truoc approve: signer chua co run.*")

    # [9] approve -> ACTIVE + temp grant + activation window
    ap = await SA.approve("R1", approver_staff_id=po, actor="po")
    _check(ap["state"] == "ACTIVE" and ap["activation_id"] and ap["window_end"], "9 approve -> ACTIVE + window + activation_id")

    # [10] PERMISSION RESOLUTION: signer GIO co m4.signing.run.* qua temp grant
    after = await perms_of(signer)
    _check({"m4.signing.run.start", "m4.signing.run.operate"}.issubset(after),
           "10 temp grant cap m4.signing.run.* cho signer (permission resolution)")

    # [11] activation window lien ket la APPROVED + window
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        actrow = await c.fetchrow("SELECT state, window_end FROM m4_signing_activation WHERE activation_id=$1", ap["activation_id"])
        _check(actrow["state"] == "APPROVED" and actrow["window_end"] is not None, "11 activation window APPROVED + TTL")
        grow = await c.fetchrow("SELECT valid_until, is_rehearsal FROM m4_temp_signer_role_grant WHERE request_id='R1'")
        _check(grow["valid_until"] is not None and grow["is_rehearsal"] is False, "11b temp grant valid_until + not rehearsal")
    finally:
        await c.close()

    # [12] close -> revoke role + terminal activation -> perms MAT
    cl = await SA.close("R1", actor="po", staff_id=po)
    _check(cl["state"] == "CLOSED", "12 close -> CLOSED")
    gone = await perms_of(signer)
    _check("m4.signing.run.start" not in gone, "12b sau close: temp perms MAT (revoked)")
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        arow = await c.fetchval("SELECT state FROM m4_signing_activation WHERE activation_id=$1", ap["activation_id"])
        rrow = await c.fetchval("SELECT revoked_at IS NOT NULL FROM m4_temp_signer_role_grant WHERE request_id='R1'")
        _check(arow == "CLOSED" and rrow, "12c activation CLOSED + grant revoked")
    finally:
        await c.close()

    # [13] REHEARSAL grant KHONG cap quyen that
    r2 = await SA.submit(request_id="R2", scope={"t": "reh"}, artifact_digest=DIGEST, ticket="T-2",
                         reason="rehearsal", rollback_owner="h", requester_staff_id=signer,
                         window_minutes=30, is_rehearsal=True, actor="signer1")
    await SA.run_preflight("R2", actor="system")
    await SA.approve("R2", approver_staff_id=po, actor="po")
    reh_perms = await perms_of(signer)
    _check("m4.signing.run.start" not in reh_perms, "13 REHEARSAL grant KHONG cap m4.signing.run.* (an toan)")
    await SA.revoke("R2", actor="po", reason="huy rehearsal", staff_id=po)

    # [14] stale preflight chan approve
    r3 = await SA.submit(request_id="R3", scope={"t": "y"}, artifact_digest=DIGEST, ticket="T-3",
                         reason="r", rollback_owner="h", requester_staff_id=signer, window_minutes=30,
                         actor="signer1")
    await SA.run_preflight("R3", actor="system")
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        await c.execute("UPDATE m4_signer_access_request SET preflight_at=now()-interval '20 minutes' WHERE request_id='R3'")
    finally:
        await c.close()
    try:
        await SA.approve("R3", approver_staff_id=po, actor="po")
        _check(False, "14 stale preflight phai chan")
    except SA.SignerAccessError:
        _check(True, "14 stale preflight chan approve")

    # [15] expire_due -> EXPIRED + revoke role
    r4 = await SA.submit(request_id="R4", scope={"t": "z"}, artifact_digest=DIGEST, ticket="T-4",
                         reason="r", rollback_owner="h", requester_staff_id=signer, window_minutes=30,
                         actor="signer1")
    await SA.run_preflight("R4", actor="system")
    await SA.approve("R4", approver_staff_id=po, actor="po")
    _check("m4.signing.run.start" in await perms_of(signer), "15a R4 active: signer co perms")
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        await c.execute("UPDATE m4_signer_access_request SET window_end=now()-interval '1 minute' WHERE request_id='R4'")
    finally:
        await c.close()
    n_exp = await SA.expire_due()
    st = await SA.get("R4")
    _check(n_exp >= 1 and st["state"] == "EXPIRED", "15 expire_due -> EXPIRED (auto-revoke worker)")
    _check("m4.signing.run.start" not in await perms_of(signer), "15b sau expire: perms MAT")

    # [16] already-has-role -> KHONG cap temp grant moi
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        staff2 = await c.fetchval("INSERT INTO staff_users(username,password_hash,password_salt,role_key) "
                                  "VALUES('signer2','x','x','m4_signing_operator') RETURNING id")
    finally:
        await c.close()
    r5 = await SA.submit(request_id="R5", scope={"t": "q"}, artifact_digest=DIGEST, ticket="T-5",
                         reason="r", rollback_owner="h", requester_staff_id=staff2, window_minutes=30,
                         actor="signer2")
    await SA.run_preflight("R5", actor="system")
    await SA.approve("R5", approver_staff_id=po, actor="po")
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        n_grant = await c.fetchval("SELECT count(*) FROM m4_temp_signer_role_grant WHERE request_id='R5'")
        _check(n_grant == 0, "16 already-has-role: KHONG cap temp grant moi (chi issue window)")
    finally:
        await c.close()

    # [17] audit no-secret
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        acts = sorted({x["action"] for x in await c.fetch(
            "SELECT DISTINCT action FROM audit_log WHERE action LIKE 'signer_access.%'")})
        _check(all(a in acts for a in ["signer_access.submit", "signer_access.approve",
               "signer_access.provision_role", "signer_access.close", "signer_access.expire"]),
               "17a audit ghi du buoc (incl provision_role)")
        leak = await c.fetchval("SELECT count(*) FROM audit_log WHERE after::text ~* '(pin_secret|password|-----BEGIN|ya29\\.)'")
        _check(leak == 0, "17b audit KHONG secret")
    finally:
        await c.close()

    await close_pool()
    print("M4_SIGNER_ACCESS_ALL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
