"""I-B M4 Stage 0P — helper DUNG CHUNG boi cac evidence script (kill_test.py/sampling_test.py/
signing_service_test.py) de khoi dong/dung `app.services.pii.stage0p_signing_service` nhu 1 TIEN
TRINH RIENG THAT SU (F-M4-0P-T10-02) — khong phai app code, CHI cho muc dich test/evidence.

Tien trinh con nhan 3 khoa (`M4_SAMPLE_KEY_B64`/`M4_TRANSCRIPT_HMAC_KEY_B64`/
`M4_SIGNING_AUTH_VERIFY_KEY_B64`) qua MOI TRUONG CUA CHINH NO (tien trinh cha (script test, dong
vai "collector") KHONG BAO GIO dat 3 bien nay trong `os.environ`/`settings` cua CHINH no, chung
minh collector process THAT SU khong giu khoa).

REV12 (F-M4-0P-T11-02): `run_signing_service()` tu choi khoi dong neu thu muc cha cua socket
KHONG PHAI 1 thu muc RIENG mode 0700 (vd `/tmp` mode 1777 se bi tu choi) — helper nay TU TAO thu
muc do.

REV13 (F-M4-0P-T12-01): CA yeu cau signer/collector chay duoi 2 UID HE DIEU HANH THAT KHAC NHAU
(khong con "tu tin chinh minh" — mac dinh allowed_uid=chinh no). `ensure_service_accounts()` tao
(idempotent) 2 tai khoan he thong `m4-signer`/`m4-collector` + 1 group chia se `m4-signing-ipc` (ca
2 la thanh vien) — dung `useradd`/`groupadd` (can quyen root, dung trong container test/dev nay).
`start_signing_service(..., run_as_uid=..., allowed_uid=..., shared_gid=...)` spawn tien trinh
signing service THAT SU duoi UID `run_as_uid` (qua tham so `user=` cua `subprocess`/
`asyncio.create_subprocess_exec`, chi hoat dong khi tien trinh GOI dang la root — dung trong
container nay). `request_signature_as_uid()` goi `request_signature()` TU 1 tien trinh con THAT
chay duoi 1 UID cu the (qua `_stage0p_signing_client_as_uid_helper.py`) — chung minh 2 principal
THAT khac nhau trong evidence, khong chi 1 process tu doi gia tri `allowed_uid` mong doi."""

import asyncio
import base64
import json
import os
import pwd
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_AS_UID_HELPER = str(Path(__file__).resolve().parent / "_stage0p_signing_client_as_uid_helper.py")

# PHAI khop CHINH XAC hang so cung ten trong stage0p_signing_service.py - dung de biet mode CUOI
# CUNG can doi (sau chmod/chown) truoc khi coi socket la san sang, tranh race o start_signing_service().
_SOCKET_FILE_MODE = 0o600
_SOCKET_FILE_MODE_SHARED = 0o660

_SIGNING_GROUP = "m4-signing-ipc"
_SIGNER_USER = "m4-signer"
_COLLECTOR_USER = "m4-collector"
_OTHER_USER = "m4-other"  # T12-01 evidence: 1 UID thu 3, KHONG phai signer/collector, KHONG thuoc group


def _run_root_cmd(*args: str) -> None:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"lenh {args!r} that bai (exit={result.returncode}): "
                           f"{result.stdout}{result.stderr}")


def _ensure_group(name: str) -> int:
    try:
        result = subprocess.run(["getent", "group", name], capture_output=True, text=True)
        if result.returncode == 0:
            return int(result.stdout.split(":")[2])
    except FileNotFoundError:
        pass
    _run_root_cmd("groupadd", "-f", name)
    result = subprocess.run(["getent", "group", name], capture_output=True, text=True)
    return int(result.stdout.split(":")[2])


def _ensure_user(name: str, *, primary_group: str | None) -> int:
    """Tao 1 tai khoan he thong (khong login, khong home dir). `primary_group=None` -> useradd tu
    tao 1 group RIENG cung ten (mac dinh Debian) - dung cho `_OTHER_USER` de dam bao no KHONG vo
    tinh roi vao group chia se."""
    try:
        return pwd.getpwnam(name).pw_uid
    except KeyError:
        pass
    args = ["useradd", "-r", "-M", "-s", "/usr/sbin/nologin"]
    if primary_group is not None:
        args += ["-g", primary_group]
    args.append(name)
    _run_root_cmd(*args)
    return pwd.getpwnam(name).pw_uid


def ensure_service_accounts() -> tuple[int, int, int, int]:
    """T12-01 (REV13): tao (idempotent) 3 tai khoan he thong THAT + 1 group chia se — tra ve
    (signer_uid, collector_uid, other_uid, shared_gid). `signer`/`collector` co primary group LA
    group chia se (thanh vien tu dong). `other_uid` la 1 UID thu 3 co group RIENG (KHONG thuoc
    group chia se) — dung lam 'unauthorized peer' THAT SU trong evidence (khac voi Correction #12
    — chi doi gia tri allowed_uid EXPECTED tren CUNG 1 principal, CA tu choi coi la du)."""
    shared_gid = _ensure_group(_SIGNING_GROUP)
    signer_uid = _ensure_user(_SIGNER_USER, primary_group=_SIGNING_GROUP)
    collector_uid = _ensure_user(_COLLECTOR_USER, primary_group=_SIGNING_GROUP)
    other_uid = _ensure_user(_OTHER_USER, primary_group=None)
    return signer_uid, collector_uid, other_uid, shared_gid


async def start_signing_service(
        *, socket_path: str, allowed_uid: int,
        sample_key: bytes | None = None, hmac_key: bytes | None = None,
        auth_verify_key: bytes | None = None,
        run_as_uid: int | None = None,
        shared_gid: int | None = None) -> tuple[asyncio.subprocess.Process, bytes, bytes, bytes]:
    """Khoi dong tien trinh signing service, tra ve
    (process, sample_key_bytes, hmac_key_bytes, auth_verify_key_bytes). Cho toi khi socket THAT SU
    xuat hien truoc khi tra ve (khong doan thoi gian sleep co dinh).

    `allowed_uid`: T12-01 (REV13) — BAT BUOC (khong con optional/mac dinh tu do) - chinh la vi du
    ro rang cho 'khong con tu tin chinh minh': caller PHAI tu quyet dinh UID nao duoc phep.

    `run_as_uid`: neu duoc truyen, spawn TIEN TRINH signing service THAT SU duoi UID nay (can
    quyen root o tien trinh GOI - dung trong container test). Mac dinh None = chay CUNG uid voi
    tien trinh goi (mo hinh don-gian REV11/REV12, kill_test.py/sampling_test.py van dung).

    `shared_gid`: neu duoc truyen (cung voi `run_as_uid` khac uid tien trinh goi), thu muc socket
    duoc tao mode 0710 + chown ve (run_as_uid, shared_gid) — cho phep 1 UID KHAC (thanh vien cung
    group) mo duoc socket file (T12-01, xem `stage0p_signing_service.py` docstring)."""
    sample_key = sample_key or os.urandom(32)
    hmac_key = hmac_key or os.urandom(32)
    auth_verify_key = auth_verify_key or os.urandom(32)
    socket_dir = os.path.dirname(socket_path) or "."
    if run_as_uid is not None and shared_gid is not None:
        os.makedirs(socket_dir, exist_ok=True)
        os.chown(socket_dir, run_as_uid, shared_gid)
        os.chmod(socket_dir, 0o710)
    else:
        # T11-02: signing service tu choi khoi dong neu thu muc cha khong phai 1 thu muc RIENG
        # mode 0700 — tao no o day (thay vi bat caller tu lo) va CHMOD TUONG MINH bat ke umask.
        os.makedirs(socket_dir, mode=0o700, exist_ok=True)
        os.chmod(socket_dir, 0o700)
        if run_as_uid is not None:
            os.chown(socket_dir, run_as_uid, -1)
    if os.path.lexists(socket_path):
        os.unlink(socket_path)
    env = os.environ.copy()
    env["STAGE0P_SIGNING_SOCKET"] = socket_path
    env["M4_SAMPLE_KEY_B64"] = base64.b64encode(sample_key).decode()
    env["M4_TRANSCRIPT_HMAC_KEY_B64"] = base64.b64encode(hmac_key).decode()
    env["M4_SIGNING_AUTH_VERIFY_KEY_B64"] = base64.b64encode(auth_verify_key).decode()
    env["STAGE0P_SIGNING_ALLOWED_UID"] = str(allowed_uid)
    if shared_gid is not None:
        env["STAGE0P_SIGNING_SHARED_GID"] = str(shared_gid)
    kwargs = {}
    if run_as_uid is not None:
        # subprocess/asyncio `user=` CHI setuid - KHONG tu dong setgid theo primary group cua
        # user do (khac gia dinh ban dau khi viet ham nay - xac nhan bang thuc nghiem truc tiep:
        # tien trinh con van giu GID cua tien trinh CHA/root neu khong truyen `group=` tuong minh,
        # lam moi chown/permission-check dua tren group deu sai). PHAI truyen ca `group=` = primary
        # gid THAT cua user do.
        kwargs["user"] = run_as_uid
        kwargs["group"] = pwd.getpwuid(run_as_uid).pw_gid
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.services.pii.stage0p_signing_service",
        cwd=str(ROOT), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        **kwargs,
    )
    # T12-01: `asyncio.start_unix_server()` tao FILE socket ngay luc bind() - TRUOC KHI dong code
    # cua chinh chung ta (chown/chmod ve mode cuoi cung, 0660 shared_gid hoac 0600 don-UID) kip
    # chay. Neu chi doi "file ton tai" se co RACE THAT (da tai hien): 1 client ket noi dung luc
    # file con o mode mac dinh tu bind() (truoc chmod) co the thanh cong/that bai SAI ly do. Doi
    # THEM ca mode cuoi cung dung nhu mong doi truoc khi coi la "san sang".
    expected_mode = _SOCKET_FILE_MODE_SHARED if shared_gid is not None else _SOCKET_FILE_MODE
    deadline = time.monotonic() + 5.0
    while True:
        if os.path.exists(socket_path):
            try:
                if stat.S_IMODE(os.stat(socket_path).st_mode) == expected_mode:
                    break
            except OSError:
                pass
        if proc.returncode is not None:
            out = await proc.stdout.read()
            raise RuntimeError(
                f"signing service thoat som (exit={proc.returncode}): {out.decode(errors='replace')}")
        if time.monotonic() > deadline:
            proc.terminate()
            raise RuntimeError("signing service khong tao socket (dung mode) trong 5s")
        await asyncio.sleep(0.05)
    return proc, sample_key, hmac_key, auth_verify_key


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


async def request_signature_as_uid(uid: int, req: dict, *, timeout: float = 10.0) -> dict:
    """T12-01 (REV13): goi `request_signature()` TU 1 TIEN TRINH CON THAT SU chay duoi UID `uid`
    (khong phai tien trinh test dang chay) — chung minh 2 principal THAT khac nhau, khong chi 1
    process tu doi gia tri `allowed_uid` mong doi (dung khac Correction #12, CA tu choi vi ly do
    nay). Tra ve dict {"ok": True, ...} hoac {"ok": False, "error": "..."}; khong bao gio raise cho
    loi nghiep vu binh thuong (chi raise neu chinh co che goi subprocess/giao thuc bi loi ha
    tang)."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, _AS_UID_HELPER,
        cwd=str(ROOT), user=uid, group=pwd.getpwuid(uid).pw_gid,  # xem ghi chu trong start_signing_service()
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(json.dumps(req).encode("utf-8")), timeout=timeout)
    if proc.returncode != 0:
        return {"ok": False,
                "error": f"subprocess exit={proc.returncode}: {stderr.decode(errors='replace')[:500]}"}
    return json.loads(stdout.decode("utf-8"))
