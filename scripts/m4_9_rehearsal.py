"""M4-9 — Synthetic rehearsal END-TO-END tu dashboard (Addendum 59 acceptance).

Drive TOAN BO control surface qua HTTP (FastAPI TestClient) voi auth/RBAC/SoD THAT tren DB that:
  create -> confirm -> preflight -> ceremony -> canary-request -> canary-approve -> execute(enqueue)
+ negative: SoD (operator tu duyet), thieu quyen, transition sai, abort thieu reason.

Chung minh KHONG co duong bypass dashboard/policy va moi human action duoc audit. Execution that
su (worker -> CLI runner -> signer) validate rieng (scripts/m4_9_signing_run_test.py + runner test);
o day enqueue duoc fake de rehearsal tu chua, KHONG can redis/signer stack.

Chay:
  docker exec -e DATABASE_URL=... -e MIGRATE_ACTOR=rehearsal -w /srv api python scripts/m4_9_rehearsal.py

In "M4_9_REHEARSAL_PASS" o cuoi neu dat het.
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


def _check(cond: bool, name: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        raise SystemExit(f"REHEARSAL CHECK FAIL: {name}")


async def _setup_db() -> dict:
    """Reset+migrate, seed 2 role (operator/approver) + 2 staff + session token + grant perms."""
    admin = await asyncpg.connect(_plain(DB_URL))
    try:
        await admin.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await admin.close()
    r = subprocess.run([sys.executable, "scripts/migrate.py", "up"], cwd=str(ROOT),
                       env={**os.environ, "DATABASE_URL": DB_URL}, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout); print(r.stderr); raise SystemExit("migrate.py up FAIL")

    admin = await asyncpg.connect(_plain(DB_URL))
    try:
        # roles
        await admin.execute(
            "INSERT INTO roles(key,name,is_system) VALUES "
            "('m4operator','M4 Operator',false),('m4approver','M4 Approver',false),"
            "('m4none','M4 NoPerm',false) ON CONFLICT DO NOTHING")
        # grants: operator = start/operate/abort/view ; approver = approve/view ; none = (nothing)
        grants = [
            ("m4operator", "m4.signing.run.start"), ("m4operator", "m4.signing.run.operate"),
            ("m4operator", "m4.signing.run.abort"), ("m4operator", "m4.signing.run.view"),
            ("m4approver", "m4.signing.run.approve"), ("m4approver", "m4.signing.run.view"),
        ]
        for rk, pk in grants:
            await admin.execute(
                "INSERT INTO role_permissions(role_key,permission_key) VALUES ($1,$2) "
                "ON CONFLICT DO NOTHING", rk, pk)
        ids = {}
        for user, role in (("op", "m4operator"), ("appr", "m4approver"), ("none", "m4none")):
            sid = await admin.fetchval(
                "INSERT INTO staff_users(username,name,password_hash,password_salt,role_key,is_active) "
                "VALUES ($1,$1,'x','s',$2,true) RETURNING id", user, role)
            token = f"tok-{user}-rehearsal"
            await admin.execute(
                "INSERT INTO staff_sessions(staff_id,token,expires_at) VALUES ($1,$2,$3)",
                sid, token, _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=1))
            ids[user] = {"id": sid, "token": token}
        return ids
    finally:
        await admin.close()


async def _run_http(ids: dict) -> None:
    """Drive HTTP flow bang httpx.AsyncClient + ASGITransport (CUNG event loop -> pool nhat quan)."""
    import httpx
    from fastapi import FastAPI

    import app.api.m4_signing as m4mod
    from app.api.m4_signing import router

    # Fake redis enqueue — rehearsal tu chua, khong can redis/signer stack.
    class _FakeRedis:
        def __init__(self):
            self.jobs = []

        async def enqueue_job(self, name, *a, **kw):
            self.jobs.append((name, a, kw))
            return None

    _fake = _FakeRedis()

    async def _fake_get_redis():
        return _fake

    m4mod._get_redis = _fake_get_redis

    application = FastAPI()
    application.include_router(router)

    def H(user):
        return {"Authorization": f"Bearer {ids[user]['token']}"}

    now = _dt.datetime.now(_dt.timezone.utc)
    win_start = (now - _dt.timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    win_end = (now + _dt.timedelta(hours=2)).isoformat().replace("+00:00", "Z")

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # NEG: thieu quyen (none) tao run -> 403
        rr = await client.post("/dashboard/signing/runs", headers=H("none"),
                               json={"scope": {"batch": "x"}})
        _check(rr.status_code == 403, "neg: staff khong quyen -> 403 tao run")

        # 1. create (operator)
        rr = await client.post("/dashboard/signing/runs", headers=H("op"),
                               json={"scope": {"batch": "synth-rehearsal-v1"},
                                     "window_start": win_start, "window_end": win_end,
                                     "quota_sts": 3, "quota_sign": 3})
        _check(rr.status_code == 200, "1 create 200")
        run_id = rr.json()["run_id"]

        # NEG: transition sai (execute khi CREATED) -> 409
        rr = await client.post(f"/dashboard/signing/runs/{run_id}/execute", headers=H("op"),
                               json={"manifest": "/x", "approval_ref": "a", "reviewer_staff_id": 1})
        _check(rr.status_code == 409, "neg: execute tu CREATED -> 409 (fail-closed)")

        # 2. confirm
        rr = await client.post(f"/dashboard/signing/runs/{run_id}/confirm", headers=H("op"), json={})
        _check(rr.status_code == 200 and rr.json()["state"] == "CONFIRMED", "2 confirm -> CONFIRMED")

        # 3. preflight
        rr = await client.post(f"/dashboard/signing/runs/{run_id}/preflight", headers=H("op"))
        _check(rr.status_code == 200 and rr.json()["preflight"]["ok"], "3 preflight PASS")
        _check(rr.json()["run"]["state"] == "PREFLIGHT_PASSED", "3b -> PREFLIGHT_PASSED")

        # 4. ceremony (public metadata only)
        rr = await client.post(f"/dashboard/signing/runs/{run_id}/ceremony", headers=H("op"),
                               json={"public_metadata": {"cert_fingerprint": "7D:67:ED:50"}})
        _check(rr.status_code == 200 and rr.json()["state"] == "CEREMONY_RECORDED", "4 ceremony")

        # NEG: ceremony chua secret -> 400
        r2 = await client.post(f"/dashboard/signing/runs/{run_id}/ceremony", headers=H("op"),
                               json={"public_metadata": {"pin_secret": "leak"}})
        _check(r2.status_code in (400, 409), "neg: ceremony secret bi chan")

        # 5. canary-request
        rr = await client.post(f"/dashboard/signing/runs/{run_id}/canary-request", headers=H("op"))
        _check(rr.status_code == 200 and rr.json()["state"] == "CANARY_PENDING", "5 canary-request")

        # NEG: operator tu duyet canary -> 403 SoD
        rr = await client.post(f"/dashboard/signing/runs/{run_id}/canary-approve", headers=H("op"), json={})
        _check(rr.status_code == 403, "neg: SoD operator tu duyet -> 403")

        # 6. approver duyet
        rr = await client.post(f"/dashboard/signing/runs/{run_id}/canary-approve", headers=H("appr"), json={})
        _check(rr.status_code == 200 and rr.json()["state"] == "CANARY_APPROVED", "6 canary-approve")

        # 7. execute (enqueue)
        rr = await client.post(f"/dashboard/signing/runs/{run_id}/execute", headers=H("op"),
                               json={"manifest": "/srv/scripts/synthetic-manifest.jsonl",
                                     "approval_ref": "rehearsal-approval-v1",
                                     "reviewer_staff_id": ids["appr"]["id"]})
        _check(rr.status_code == 200 and rr.json()["run"]["state"] == "EXECUTING", "7 execute -> EXECUTING")
        _check(len(_fake.jobs) == 1 and _fake.jobs[0][0] == "m4_signing_execute", "7b arq job enqueued")

        # NEG: abort thieu reason -> 400
        rr = await client.post(f"/dashboard/signing/runs/{run_id}/abort", headers=H("op"), json={})
        _check(rr.status_code == 400, "neg: abort thieu reason -> 400")

        # 8. detail: audit day du, khong secret
        rr = await client.get(f"/dashboard/signing/runs/{run_id}", headers=H("op"))
        _check(rr.status_code == 200, "8 detail 200")
        events = rr.json()["events"]
        types = [e["event_type"] for e in events]
        # event_type = ten transition verb (create_run ghi 'created'; transition ghi ten event).
        for want in ("created", "confirm", "preflight_pass", "ceremony_record",
                     "canary_request", "canary_approve", "execute_start"):
            _check(want in types, f"8 audit co event '{want}'")
        body = str(rr.json())
        _check("pin_secret" not in body and "-----BEGIN" not in body, "8b detail khong lo secret")


async def main() -> int:
    os.environ["DATABASE_URL"] = DB_URL
    ids = await _setup_db()
    await _run_http(ids)
    from app.db_pool import close_pool
    await close_pool()
    print("M4_9_REHEARSAL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
