"""M4 — Integration test preflight THAT (Roadmap Buoc 1). DB sandbox + Redis + LocalDev backend.

Kiem (KHONG customer data, digest/scope tong hop):
  [A] Happy: localdev backend + registry seed + Redis + control not-frozen -> preflight PASS,
      4 check ha tang deu passed (kms_wif_health/cert_chain/clock_nonce_replay/no_conflicting_incident).
  [B] Freeze: m4_signing_control.signing_frozen=true -> preflight FAIL (no_conflicting_incident) -> REVOKED.
  [C] Registry absent: retire public key -> preflight FAIL (kms_wif_health) -> REVOKED.
  [D] Conflicting activation: mot activation ACTIVE khac -> preflight FAIL (no_conflicting_incident).
In "M4_PREFLIGHT_ALL_PASS".

Env bat buoc (do runner dat): DATABASE_URL, REDIS_URL, M4_SIGNING_BACKEND=localdev,
M4_ALLOW_LOCALDEV_SIGNING=1, M4_LOCALDEV_SIGNING_SEED_B64=<32B b64>, APP_ENV=development.
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
    pub = b.public_key_raw()
    ver = b.key_version()
    await conn.execute(
        "INSERT INTO m4_stage0p_transcript_public_keys(key_id,key_version,algorithm,public_key) "
        "VALUES('m4-transcript-ed25519-localdev',$1,'Ed25519',$2) ON CONFLICT DO NOTHING", ver, pub)
    return ver


async def _mk_request(A, req, digest, rid):
    r = await A.create_request(
        request_id=rid, scope={"tenant": "internal", "batch": "preflight"}, artifact_digest=digest,
        manifest_ref=None, max_sign_count=1, reason="preflight test", ticket="T-PF",
        requester_staff_id=req, delegated_by=None, rollback_owner="hoai", actor="signer1")
    return str(r["activation_id"])


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
        print(r.stdout, r.stderr)
        raise SystemExit("migrate FAIL")

    DIGEST = "sha256:" + "a" * 64
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        req = await c.fetchval("INSERT INTO staff_users(username,password_hash,password_salt) "
                               "VALUES('signer1','x','x') RETURNING id")
        appr = await c.fetchval("INSERT INTO staff_users(username,password_hash,password_salt) "
                                "VALUES('po','x','x') RETURNING id")
        ver = await _seed_registry(c)
        ctl_ok = await c.fetchval("SELECT signing_frozen=false FROM m4_signing_control WHERE id=1")
        _check(ctl_ok, "0 migration 050 control seeded not-frozen")
    finally:
        await c.close()

    # [A] Happy path -> PASS
    aid = await _mk_request(A, req, DIGEST, "PF-A")
    pf = await A.run_preflight(aid, actor="system")
    by = {x["name"]: x["passed"] for x in pf["checks"]}
    _check(pf["ok"] and pf["state"] == "PREFLIGHT_PASSED", "A preflight PASS")
    _check(by.get("kms_wif_health") and by.get("cert_chain") and by.get("clock_nonce_replay")
           and by.get("no_conflicting_incident"), "A ca 4 check ha tang passed (that, khong stub)")

    # [B] Freeze -> FAIL no_conflicting_incident -> REVOKED
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        await c.execute("UPDATE m4_signing_control SET signing_frozen=true, incident_ref='INC-1' WHERE id=1")
    finally:
        await c.close()
    aidB = await _mk_request(A, req, DIGEST, "PF-B")
    pfB = await A.run_preflight(aidB, actor="system")
    byB = {x["name"]: x["passed"] for x in pfB["checks"]}
    _check(not pfB["ok"] and pfB["state"] == "REVOKED" and not byB["no_conflicting_incident"],
           "B freeze -> preflight FAIL (no_conflicting_incident) -> REVOKED")
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        await c.execute("UPDATE m4_signing_control SET signing_frozen=false WHERE id=1")
    finally:
        await c.close()

    # [C] Registry retired -> FAIL kms_wif_health -> REVOKED
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        await c.execute("UPDATE m4_stage0p_transcript_public_keys SET retired_at=now() "
                        "WHERE key_id='m4-transcript-ed25519-localdev' AND key_version=$1", ver)
    finally:
        await c.close()
    aidC = await _mk_request(A, req, DIGEST, "PF-C")
    pfC = await A.run_preflight(aidC, actor="system")
    byC = {x["name"]: x["passed"] for x in pfC["checks"]}
    _check(not pfC["ok"] and not byC["kms_wif_health"],
           "C registry retired -> preflight FAIL (kms_wif_health)")
    # tra lai registry cho [D]
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        await c.execute("UPDATE m4_stage0p_transcript_public_keys SET retired_at=NULL "
                        "WHERE key_id='m4-transcript-ed25519-localdev' AND key_version=$1", ver)
    except asyncpg.PostgresError:
        # bang bat bien co the chan un-retire; seed lai key_version khac
        await c.execute("INSERT INTO m4_stage0p_transcript_public_keys(key_id,key_version,algorithm,public_key) "
                        "SELECT 'm4-transcript-ed25519-localdev','localdev:v1','Ed25519',public_key "
                        "FROM m4_stage0p_transcript_public_keys WHERE key_version=$1 ON CONFLICT DO NOTHING", ver)
    finally:
        await c.close()

    # [D] Conflicting ACTIVE activation -> FAIL no_conflicting_incident
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        await c.execute("INSERT INTO m4_signing_activation(request_id,scope,artifact_digest,state,"
                        "requester_staff_id,approver_staff_id) VALUES('PF-OTHER','{}'::jsonb,$1,'ACTIVE',$2,$3)",
                        DIGEST, req, appr)
    finally:
        await c.close()
    aidD = await _mk_request(A, req, DIGEST, "PF-D")
    pfD = await A.run_preflight(aidD, actor="system")
    byD = {x["name"]: x["passed"] for x in pfD["checks"]}
    _check(not byD["no_conflicting_incident"], "D conflicting ACTIVE -> FAIL no_conflicting_incident")

    # [E] rehearsal khong cham customer data (khong bang conversations bi ghi)
    c = await asyncpg.connect(_plain(DB_URL))
    try:
        has_conv = await c.fetchval("SELECT to_regclass('public.conversations') IS NOT NULL")
        nconv = await c.fetchval("SELECT count(*) FROM conversations") if has_conv else 0
        _check(nconv == 0, "E khong cham customer data (conversations rong)")
    finally:
        await c.close()

    await close_pool()
    print("M4_PREFLIGHT_ALL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
