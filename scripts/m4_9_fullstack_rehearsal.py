"""M4-9 tracked action #2 — FULL-STACK rehearsal THAT: worker -> runner -> signer.

Chung minh duong execution that (khong chi enqueue): mot dashboard signing run di qua arq worker
THAT -> cli_adapter -> CLI runner -> signer socket (LocalDevBackend Ed25519, sandbox) -> full
lifecycle collector/label/seal/predict/evaluate + cleanup -> dormant. KHONG production data/cred.

Chay (postgres + redis reachable):
  docker run ... -e DATABASE_URL=... -e REDIS_URL=... -e MIGRATE_ACTOR=rehearsal python \
    scripts/m4_9_fullstack_rehearsal.py

Env sandbox (script tu set): APP_ENV=sandbox, M4_SIGNING_BACKEND=localdev,
M4_ALLOW_LOCALDEV_SIGNING=1, M4_LOCALDEV_SIGNING_SEED_B64=<32B b64>.

In "M4_9_FULLSTACK_PASS" o cuoi neu run toi CLOSED + dormant.
"""
import asyncio
import base64
import datetime as _dt
import os
import subprocess
import sys
import time
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

DB_URL = os.environ.get("DATABASE_URL") or "postgresql://alpha3s:alpha3s@db:5432/alpha3s"
REDIS_URL = os.environ.get("REDIS_URL") or "redis://redis:6379/0"
SOCKET = "/tmp/m4-9-sig/signing.sock"
MANIFEST = str(ROOT / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v2.jsonl")

# Sandbox localdev signing (guard fail-closed van chan production).
os.environ.setdefault("APP_ENV", "sandbox")
os.environ["M4_SIGNING_BACKEND"] = "localdev"
os.environ["M4_ALLOW_LOCALDEV_SIGNING"] = "1"
os.environ["M4_LOCALDEV_SIGNING_SEED_B64"] = base64.b64encode(b"s" * 32).decode()
os.environ["DATABASE_URL"] = DB_URL
os.environ["REDIS_URL"] = REDIS_URL


def _plain(url: str) -> str:
    return url.replace("+asyncpg", "")


def _check(cond: bool, name: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}", flush=True)
    if not cond:
        raise SystemExit(f"FULLSTACK CHECK FAIL: {name}")


async def _migrate_and_seed():
    admin = await asyncpg.connect(_plain(DB_URL))
    try:
        await admin.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await admin.close()
    r = subprocess.run([sys.executable, "scripts/migrate.py", "up"], cwd=str(ROOT),
                       env={**os.environ}, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout); print(r.stderr); raise SystemExit("migrate FAIL")

    from m4_stage0p_rehearsal_runner_test import _make_staff  # reuse pattern
    admin = await asyncpg.connect(_plain(DB_URL))
    try:
        # role admin cho dashboard perms (khong bat buoc cho run_store; run chi dung staff id)
        approval = await _make_staff(admin, username="fs_appr",
                                     permissions=["m4.stage0p.approve"], pin_secret="appr-pin")
        operator = await _make_staff(admin, username="fs_op",
                                     permissions=["m4.stage0p.operate"], pin_secret="op-pin")
        reviewer = await _make_staff(admin, username="fs_rev",
                                     permissions=["m4.stage0p.review", "m4.stage0p.evaluate"],
                                     pin_secret="rev-pin")
        return {"approval": approval, "operator": operator, "reviewer": reviewer}
    finally:
        await admin.close()


def _cli(*args, env_extra=None, timeout=120):
    env = {**os.environ, "DATABASE_URL": DB_URL, "REDIS_URL": REDIS_URL, **(env_extra or {})}
    return subprocess.run([sys.executable, "scripts/m4_stage0p_rehearsal_runner.py", *args],
                          cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=timeout)


async def main() -> int:
    from _stage0p_signing_service_helper import start_signing_service, stop_signing_service
    from app.db_pool import close_pool
    from app.services.m4_signing import policy, run_store

    ids = await _migrate_and_seed()

    # record-approval (approval staff)
    approval_ref = "fs-rehearsal-approval-v1"
    now = _dt.datetime.now(_dt.timezone.utc)
    r = _cli("record-approval", "--approval-staff-id", str(ids["approval"]),
             "--approval-ref", approval_ref,
             "--valid-from", (now - _dt.timedelta(minutes=5)).isoformat(),
             "--valid-until", (now + _dt.timedelta(hours=2)).isoformat(),
             env_extra={"STAGE0P_REHEARSAL_APPROVAL_PIN": "appr-pin"})
    _check(r.returncode == 0, "setup: record-approval")

    # start signer (localdev) — allowed_uid = uid hien tai (1-UID model)
    os.makedirs(os.path.dirname(SOCKET), exist_ok=True)
    proc, sample_key, hmac_key, auth_key = await start_signing_service(
        socket_path=SOCKET, allowed_uid=os.getuid())
    try:
        # provision-keys khop khoa signer
        r = _cli("provision-keys", env_extra={
            "M4_SAMPLE_KEY_B64": base64.b64encode(sample_key).decode(),
            "M4_TRANSCRIPT_HMAC_KEY_B64": base64.b64encode(hmac_key).decode(),
            "M4_SIGNING_AUTH_VERIFY_KEY_B64": base64.b64encode(auth_key).decode()})
        _check(r.returncode == 0, "setup: provision-keys")

        # publish public key localdev vao registry (khop signer: cung seed -> localdev:v1
        # deterministic). Migration 044 doi (key_id,key_version) co san truoc khi ghi chu ky.
        from app.services.pii.signing_backend import SIGNATURE_ALGORITHM, LocalDevBackend
        b = LocalDevBackend(app_env="sandbox")
        conn = await asyncpg.connect(_plain(DB_URL))
        try:
            await conn.execute(
                "INSERT INTO m4_stage0p_transcript_public_keys "
                "(key_id, key_version, algorithm, public_key) VALUES ($1,$2,$3,$4) "
                "ON CONFLICT DO NOTHING",
                b.key_id(), b.key_version(), SIGNATURE_ALGORITHM, b.public_key_raw())
        finally:
            await conn.close()
        _check(True, f"setup: publish localdev pubkey {b.key_id()}@{b.key_version()}")

        # tao run + drive toi CANARY_APPROVED (SoD: operator != approver)
        run = await run_store.create_run(created_by=ids["operator"], scope={"batch": "fullstack-v1"},
                                         window_start=(now - _dt.timedelta(minutes=5)).isoformat(),
                                         window_end=(now + _dt.timedelta(hours=2)).isoformat(),
                                         quota_sts=3, quota_sign=3)
        rid = str(run["run_id"])
        await run_store.transition(rid, "confirm", actor_staff_id=ids["operator"])
        pf = await policy.run_preflight(rid)
        _check(pf["ok"], "preflight PASS (dormant/window/scope/quota)")
        await run_store.transition(rid, "preflight_pass", actor_staff_id=ids["operator"],
                                   detail={"ok": True})
        await run_store.transition(rid, "ceremony_record", actor_staff_id=ids["operator"],
                                   set_operator=True, public_metadata={"cert_fingerprint": "SYNTH"})
        await run_store.transition(rid, "canary_request", actor_staff_id=ids["operator"])
        await run_store.transition(rid, "canary_approve", actor_staff_id=ids["approval"],
                                   set_approver=True)
        await run_store.transition(rid, "execute_start", actor_staff_id=ids["operator"])
        await close_pool()  # nhuong DB cho worker subprocess

        # start arq worker THAT (torch-free minimal) voi env runner can
        worker_env = {**os.environ,
                      "STAGE0P_REHEARSAL_OPERATOR_PIN": "op-pin",
                      "STAGE0P_REHEARSAL_REVIEWER_PIN": "rev-pin",
                      "M4_STAGE0P_SIGNING_SOCKET": SOCKET,
                      "M4_SAMPLE_KEY_B64": base64.b64encode(sample_key).decode()}
        wlog = open("/tmp/m4_9_worker.log", "w")
        worker = subprocess.Popen(
            [sys.executable, "-m", "arq", "scripts._m4_9_rehearsal_worker.WorkerSettings"],
            cwd=str(ROOT), env=worker_env, stdout=wlog, stderr=subprocess.STDOUT)

        # enqueue job
        from arq import create_pool
        from arq.connections import RedisSettings
        pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
        await pool.enqueue_job("m4_signing_execute", {
            "run_id": rid, "manifest": MANIFEST, "approval_ref": approval_ref,
            "operator_staff_id": ids["operator"], "reviewer_staff_id": ids["reviewer"]})
        print("  job enqueued; cho worker->runner->signer chay full lifecycle...", flush=True)

        # poll run state
        final = None
        deadline = time.time() + 240
        while time.time() < deadline:
            await asyncio.sleep(4)
            conn = await asyncpg.connect(_plain(DB_URL))
            try:
                st = await conn.fetchval("SELECT state FROM m4_signing_run WHERE run_id=$1", rid)
            finally:
                await conn.close()
            if st in ("CLOSED", "FAILED", "ABORTED"):
                final = st
                break
        worker.terminate()
        try:
            worker.wait(timeout=15)
        except Exception:  # noqa: BLE001
            worker.kill()

        print("  worker log (tail):", flush=True)
        try:
            print("\n".join(Path("/tmp/m4_9_worker.log").read_text().splitlines()[-12:]))
        except Exception:  # noqa: BLE001
            pass

        _check(final == "CLOSED", f"run toi CLOSED (thuc te: {final})")

        # Bang chung KY THAT = worker log 'rehearsal_execute_succeeded' (runner chi emit khi MOI
        # sample da duoc signer ky + record + verify TRUOC commit). Signatures/samples bi PURGE
        # o cleanup (CASCADE) — 0 sau lifecycle la DUNG dormant, khong phai thieu ky.
        wlog_text = Path("/tmp/m4_9_worker.log").read_text()
        _check("rehearsal_execute_succeeded" in wlog_text,
               "signer da ky full lifecycle (rehearsal_execute_succeeded)")
        # verify dormant + attempt ledger + purge
        conn = await asyncpg.connect(_plain(DB_URL))
        try:
            cap = await conn.fetchval("SELECT capture_enabled FROM m4_stage0p_control WHERE id=1")
            signs = await conn.fetchval(
                "SELECT count(*) FROM m4_signing_run_attempt WHERE run_id=$1 AND attempt_kind='sign'",
                rid)
            samples = await conn.fetchval("SELECT count(*) FROM m4_shadow_review_samples")
            sig_rows = await conn.fetchval("SELECT count(*) FROM m4_stage0p_transcript_signatures")
        finally:
            await conn.close()
        _check(cap is False, "dormant: capture OFF sau lifecycle")
        _check(signs >= 1, "M4-9 attempt ledger co sign")
        _check(samples == 0 and sig_rows == 0,
               f"dormant: sample/signature da purge (samples={samples}, sigs={sig_rows})")
    finally:
        await stop_signing_service(proc, SOCKET)

    print("M4_9_FULLSTACK_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
