"""M4-9 full-stack rehearsal — minimal arq worker (torch-free).

Chi dang ky m4_signing_execute (KHONG import orchestrator/LLM nhu app.workers.tasks — tranh keo
torch vao rehearsal). Logic GIONG HET tasks.m4_signing_execute: goi cli_adapter.run_execute roi
chuyen state CLOSED/FAILED. Dung de chung minh duong worker->runner->signer THAT (tracked action #2).

Chay: arq scripts._m4_9_rehearsal_worker.WorkerSettings
Env can: DATABASE_URL, REDIS_URL + (runner) STAGE0P_REHEARSAL_OPERATOR_PIN/REVIEWER_PIN,
M4_STAGE0P_SIGNING_SOCKET, M4_SAMPLE_KEY_B64.
"""
import os
import sys
from pathlib import Path

from arq.connections import RedisSettings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def m4_signing_execute(ctx, payload: dict) -> dict:
    from app.services.m4_signing import cli_adapter, run_store
    run_id = payload["run_id"]
    try:
        result = await cli_adapter.run_execute(
            run_id, manifest=payload["manifest"], approval_ref=payload["approval_ref"],
            operator_staff_id=payload["operator_staff_id"],
            reviewer_staff_id=payload["reviewer_staff_id"],
        )
        if result.ok:
            await run_store.transition(run_id, "execute_success", actor_staff_id=None,
                                       reason="lifecycle success", detail=result.as_dict())
        else:
            reason = "CLEANUP_FAILED (nguy hiem)" if result.danger else "lifecycle failed"
            await run_store.transition(run_id, "execute_fail", actor_staff_id=None,
                                       reason=reason, detail=result.as_dict())
        # In stdout redacted de rehearsal doc bang chung (khong secret).
        print("[m4-9-worker] execute done ok=%s signal=%s" % (result.ok, result.signal))
        print(result.stdout_redacted[-2000:])
        return result.as_dict()
    except Exception as e:  # noqa: BLE001
        try:
            await run_store.transition(run_id, "execute_fail", actor_staff_id=None,
                                       reason=f"adapter loi: {type(e).__name__}")
        except Exception:  # noqa: BLE001
            pass
        print(f"[m4-9-worker] execute loi run={run_id}: {type(e).__name__}: {e}")
        raise


async def _on_shutdown(ctx) -> None:
    from app.db_pool import close_pool
    await close_pool()


class WorkerSettings:
    functions = [m4_signing_execute]
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    max_jobs = 2
    max_tries = 1  # rehearsal: khong retry — muon thay ket qua that ngay
    on_shutdown = _on_shutdown
