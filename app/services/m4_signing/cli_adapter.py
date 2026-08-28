"""M4-9 — Adapter goi CLI runner (scripts/m4_stage0p_rehearsal_runner.py).

Boc CLI da co, KHONG viet lai logic ky. Nhiem vu:
- dung lenh + env (PIN lay tu MOI TRUONG SERVER-SIDE cua worker, KHONG tu request/dashboard);
- chay subprocess bat dong bo (arq worker), capture stdout/stderr;
- parse tin hieu PASS/FAIL: exit code + cac dong JSON log dac trung;
- REDACT moi chuoi giong secret truoc khi luu log vao evidence;
- ghi attempt vao ledger (dem quota).

Tin hieu (theo CLI contract):
  dry-run  : exit 0 + stdout chua "dry_run_ready"
  probe    : exit 0 + stdout chua "m4_signing_probe_ok"
  execute  : exit 0 + stdout chua "rehearsal_execute_succeeded" VA KHONG chua "CLEANUP_FAILED"
  nguy hiem: stdout chua "CLEANUP_FAILED" -> FAILED + alert rieng
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from app.services.m4_signing import run_store

_ROOT = Path(__file__).resolve().parents[3]
_RUNNER = _ROOT / "scripts" / "m4_stage0p_rehearsal_runner.py"

# Redaction: che moi chuoi giong secret trong log truoc khi luu.
_REDACT_RE = re.compile(
    r"(pin[_ ]?secret|private[_ ]?key|password|ya29\.[A-Za-z0-9_\-]+|-----BEGIN[^-]+-----)",
    re.IGNORECASE,
)
# Cac env chua secret — KHONG bao gio duoc log gia tri.
_SECRET_ENV_KEYS = {
    "STAGE0P_REHEARSAL_OPERATOR_PIN", "STAGE0P_REHEARSAL_REVIEWER_PIN",
    "STAGE0P_REHEARSAL_APPROVAL_PIN", "M4_SAMPLE_KEY_B64", "M4_TRANSCRIPT_HMAC_KEY_B64",
    "M4_SIGNING_AUTH_VERIFY_KEY_B64", "M4_SIGNING_PROBE_TOKEN", "DATABASE_URL",
}


def redact(text: str) -> str:
    return _REDACT_RE.sub("[REDACTED]", text)


class AdapterResult:
    def __init__(self, *, ok: bool, exit_code: int, signal: str,
                 stdout_redacted: str, stderr_redacted: str, danger: bool = False):
        self.ok = ok
        self.exit_code = exit_code
        self.signal = signal          # "dry_run_ready" | "probe_ok" | "execute_ok" | "fail" | "cleanup_failed"
        self.stdout_redacted = stdout_redacted
        self.stderr_redacted = stderr_redacted
        self.danger = danger          # True neu CLEANUP_FAILED

    def as_dict(self) -> dict:
        return {"ok": self.ok, "exit_code": self.exit_code, "signal": self.signal,
                "danger": self.danger}


def _worker_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Env cho subprocess: ke thua env worker (chua PIN/secret da provisioned server-side)
    + bo sung. KHONG nhan secret nao tu request/dashboard."""
    env = dict(os.environ)
    if extra:
        # Chi cho phep bo sung key KHONG nhay cam tu caller (an toan hoa).
        for k, v in extra.items():
            if k in _SECRET_ENV_KEYS:
                raise ValueError(f"adapter khong nhan secret env tu caller: {k}")
            env[k] = v
    return env


async def _run(argv: list[str], env: dict[str, str], timeout: float) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(_RUNNER), *argv,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", "TIMEOUT"
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _classify(exit_code: int, stdout: str, expect: str) -> tuple[bool, str, bool]:
    """Tra (ok, signal, danger). Fail-closed: chi PASS khi thay dung tin hieu."""
    danger = "CLEANUP_FAILED" in stdout
    if danger:
        return False, "cleanup_failed", True
    marker = {"dry_run": "dry_run_ready", "probe": "m4_signing_probe_ok",
              "execute": "rehearsal_execute_succeeded"}[expect]
    ok = exit_code == 0 and marker in stdout
    signal = {"dry_run": "dry_run_ready", "probe": "probe_ok",
              "execute": "execute_ok"}[expect] if ok else "fail"
    return ok, signal, False


async def run_dry_run(
    run_id: str, *, manifest: str, approval_ref: str,
    operator_staff_id: int, reviewer_staff_id: int, timeout: float = 120.0,
) -> AdapterResult:
    """Preflight-execute qua `run --dry-run` (KHONG ghi gi)."""
    argv = ["run", "--dry-run", "--manifest", manifest, "--approval-ref", approval_ref,
            "--operator-staff-id", str(operator_staff_id),
            "--reviewer-staff-id", str(reviewer_staff_id)]
    rc, out, err = await _run(argv, _worker_env(), timeout)
    ok, signal, danger = _classify(rc, out, "dry_run")
    await run_store.record_attempt(run_id, "preflight", "ok" if ok else "failed",
                                   {"signal": signal, "exit_code": rc})
    return AdapterResult(ok=ok, exit_code=rc, signal=signal,
                         stdout_redacted=redact(out), stderr_redacted=redact(err), danger=danger)


async def run_execute(
    run_id: str, *, manifest: str, approval_ref: str,
    operator_staff_id: int, reviewer_staff_id: int, timeout: float = 900.0,
) -> AdapterResult:
    """Full lifecycle qua `run` (execute). Ledger ghi attempt sign; CLEANUP_FAILED -> danger."""
    argv = ["run", "--manifest", manifest, "--approval-ref", approval_ref,
            "--operator-staff-id", str(operator_staff_id),
            "--reviewer-staff-id", str(reviewer_staff_id)]
    await run_store.record_attempt(run_id, "sign", "started", {"phase": "execute_begin"})
    rc, out, err = await _run(argv, _worker_env(), timeout)
    ok, signal, danger = _classify(rc, out, "execute")
    outcome = "ok" if ok else ("failed" if not danger else "failed")
    await run_store.record_attempt(run_id, "sign", outcome,
                                   {"signal": signal, "exit_code": rc, "danger": danger})
    return AdapterResult(ok=ok, exit_code=rc, signal=signal,
                         stdout_redacted=redact(out), stderr_redacted=redact(err), danger=danger)
