"""I-B M4 Stage 0P — helper DUNG CHUNG boi cac evidence script (kill_test.py/sampling_test.py/
signing_service_test.py) de khoi dong/dung `app.services.pii.stage0p_signing_service` nhu 1 TIEN
TRINH RIENG THAT SU (F-M4-0P-T10-02) — khong phai app code, CHI cho muc dich test/evidence.

Tien trinh con nhan 2 khoa (`M4_SAMPLE_KEY_B64`/`M4_TRANSCRIPT_HMAC_KEY_B64`) qua MOI TRUONG CUA
CHINH NO (tien trinh cha (script test, dong vai "collector") KHONG BAO GIO dat 2 bien nay trong
`os.environ`/`settings` cua CHINH no, chung minh collector process THAT SU khong giu khoa.

REV12 (F-M4-0P-T11-02): `run_signing_service()` gio tu choi khoi dong neu thu muc cha cua socket
KHONG PHAI 1 thu muc RIENG mode 0700 (vd `/tmp` mode 1777 se bi tu choi) — helper nay TU TAO thu
muc do (khong con de caller tu chiu trach nhiem truyen 1 duong dan `/tmp/....sock` truc tiep)."""

import asyncio
import base64
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def start_signing_service(
        *, socket_path: str,
        allowed_uid: int | None = None) -> tuple[asyncio.subprocess.Process, bytes, bytes]:
    """Khoi dong tien trinh signing service, tra ve (process, sample_key_bytes, hmac_key_bytes).
    Cho toi khi socket THAT SU xuat hien truoc khi tra ve (khong doan thoi gian sleep co dinh).

    `allowed_uid`: neu duoc truyen, ghi de `STAGE0P_SIGNING_ALLOWED_UID` cho tien trinh con — dung
    cho kich ban test 'unauthorized peer' (T11-02): dat 1 gia tri KHONG khop uid THAT cua tien
    trinh test dang goi, buoc MOI ket noi (ke ca ket noi hop le tu client THAT) bi tu choi, chung
    minh co che kiem tra peer credential THAT SU thuc thi."""
    sample_key = os.urandom(32)
    hmac_key = os.urandom(32)
    socket_dir = os.path.dirname(socket_path) or "."
    # T11-02: signing service tu choi khoi dong neu thu muc cha khong phai 1 thu muc RIENG mode
    # 0700 — tao no o day (thay vi bat caller tu lo) va CHMOD TUONG MINH bat ke umask cua tien
    # trinh goi (os.makedirs mode= chi ap dung LUC TAO, umask van co the lam mode thap hon du dinh).
    os.makedirs(socket_dir, mode=0o700, exist_ok=True)
    os.chmod(socket_dir, 0o700)
    if os.path.lexists(socket_path):
        os.unlink(socket_path)
    env = os.environ.copy()
    env["STAGE0P_SIGNING_SOCKET"] = socket_path
    env["M4_SAMPLE_KEY_B64"] = base64.b64encode(sample_key).decode()
    env["M4_TRANSCRIPT_HMAC_KEY_B64"] = base64.b64encode(hmac_key).decode()
    if allowed_uid is not None:
        env["STAGE0P_SIGNING_ALLOWED_UID"] = str(allowed_uid)
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


async def wait_signing_service_exit(proc: asyncio.subprocess.Process, *,
                                    timeout: float = 5.0) -> tuple[int, str]:
    """T11-02 evidence: cho tien trinh signing service TU THOAT (kich ban khoi dong bi tu choi vi
    thu muc/socket khong an toan) — tra ve (returncode, stdout+stderr da giai ma). Dung cho kich
    ban 'permissive directory mode'/'symlink socket path' — KHONG goi neu mong doi service chay
    binh thuong (dung `start_signing_service`)."""
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        return proc.returncode if proc.returncode is not None else -1, "(timeout - da terminate)"
    out = await proc.stdout.read()
    return proc.returncode, out.decode(errors="replace")


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
    socket_dir = os.path.dirname(socket_path) or "."
    try:
        os.rmdir(socket_dir)
    except OSError:
        pass  # khong rong/khong ton tai - khong sao, chi don dep best-effort
