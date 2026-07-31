"""I-B M4 Stage 0P — helper DUNG CHUNG boi cac evidence script (kill_test.py/sampling_test.py) de
khoi dong/dung `app.services.pii.stage0p_signing_service` nhu 1 TIEN TRINH RIENG THAT SU
(F-M4-0P-T10-02) — khong phai app code, CHI cho muc dich test/evidence.

Tien trinh con nhan 2 khoa (`M4_SAMPLE_KEY_B64`/`M4_TRANSCRIPT_HMAC_KEY_B64`) qua MOI TRUONG CUA
CHINH NO — tien trinh cha (script test, dong vai "collector") KHONG BAO GIO dat 2 bien nay trong
`os.environ`/`settings` cua CHINH no, chung minh collector process THAT SU khong giu khoa."""

import asyncio
import base64
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def start_signing_service(*, socket_path: str) -> tuple[asyncio.subprocess.Process, bytes, bytes]:
    """Khoi dong tien trinh signing service, tra ve (process, sample_key_bytes, hmac_key_bytes).
    Cho toi khi socket THAT SU xuat hien truoc khi tra ve (khong doan thoi gian sleep co dinh)."""
    sample_key = os.urandom(32)
    hmac_key = os.urandom(32)
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    env = os.environ.copy()
    env["STAGE0P_SIGNING_SOCKET"] = socket_path
    env["M4_SAMPLE_KEY_B64"] = base64.b64encode(sample_key).decode()
    env["M4_TRANSCRIPT_HMAC_KEY_B64"] = base64.b64encode(hmac_key).decode()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.services.pii.stage0p_signing_service",
        cwd=str(ROOT), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    deadline = time.monotonic() + 5.0
    while not os.path.exists(socket_path):
        if proc.returncode is not None:
            out = await proc.stdout.read()
            raise RuntimeError(
                f"signing service thoat som (exit={proc.returncode}): {out.decode(errors='replace')}")
        if time.monotonic() > deadline:
            proc.terminate()
            raise RuntimeError("signing service khong tao socket trong 5s")
        await asyncio.sleep(0.05)
    return proc, sample_key, hmac_key


async def stop_signing_service(proc: asyncio.subprocess.Process, socket_path: str) -> None:
    if proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
    if os.path.exists(socket_path):
        os.unlink(socket_path)
