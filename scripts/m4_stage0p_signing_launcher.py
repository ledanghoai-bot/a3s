#!/usr/bin/env python
"""I-B M4 Stage 0P — production launcher cho `app.services.pii.stage0p_signing_service`
(A08-COR-01, dap lai PHASE1B-M4-AMENDMENT-08-EXECUTION-ATTEMPT-1-REVIEW-VI.md F-A08-EXEC-01 va
PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-DIRECTIVE-VI.md).

Boi canh: lan execute Amendment 08 dau tien (11/8) that bai vi signing service CHUA TUNG duoc
khoi dong THAT tren production -- `m4_stage0p_signing_socket` de trong CO Y (lop phong thu doc
lap thu 2: neu capture lo bat, buoc ky van fail-closed vi khong co signing service song). Script
nay la buoc van hanh TUONG MINH, duoc version-control + review, de THAT SU khoi dong service do
khi (va CHI khi) 1 ceremony rehearsal can no -- khong lam thay doi hanh vi fail-closed mac dinh
(dormant deploy KHONG tu chay script nay, KHONG co trong `docker-compose.prod.yml`/`deploy.sh`).

Tai su dung NGUYEN VEN logic da qua 14 vong CA Technical Review (T10-T13) trong
`_stage0p_signing_service_helper.py` (`ensure_service_accounts`/`start_signing_service`) --
KHONG viet lai process-spawn/UID-separation/socket-permission logic o day, chi them lop CLI
start/stop/status DETACHED (song sot qua nhieu lan goi rieng biet, khac voi cach helper duoc
test-script goi trong CUNG 1 tien trinh Python).

3 subcommand:
    start   -- doc 3 khoa tu M4_SAMPLE_KEY_B64/M4_TRANSCRIPT_HMAC_KEY_B64/
               M4_SIGNING_AUTH_VERIFY_KEY_B64 (CUNG 3 bien `provision-keys` da dung -- operator
               phai truyen CUNG gia tri cho ca 2 lenh), tao (idempotent) 2 tai khoan he thong that
               `m4-signer`/`m4-collector` + 1 group chia se, spawn signing service THAT SU duoi UID
               `m4-signer`, cho socket san sang roi thoat (tien trinh con van chay tiep, detached).
    stop    -- doc pidfile, xac minh dung tien trinh (doi chieu cmdline, tranh giet nham PID bi tai
               su dung), SIGTERM roi SIGKILL neu can, xoa pidfile + socket + thu muc.
    status  -- bao cao JSON (khong bao gio in secret): running/pid/socket_path/socket_mode.

Khong bao gio in raw key/token/PIN. Runbook (docs/VPS-RUNBOOK-VI.md/-EN.md) mo ta trinh tu day du:
provision-keys -> signing_launcher start -> dry-run -> run (execute that) -> signing_launcher
stop -> retire-keys.
"""

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _stage0p_signing_service_helper import (  # noqa: E402
    ensure_service_accounts,
    start_signing_service,
)

KEY_LEN = 32  # khop app/services/pii/crypto.py _KEY_LEN / m4_stage0p_rehearsal_runner.py

_DEFAULT_RUN_DIR = "/run/m4-signing"
SOCKET_PATH = os.environ.get("M4_SIGNING_LAUNCHER_SOCKET_PATH", f"{_DEFAULT_RUN_DIR}/signing.sock")
PIDFILE_PATH = os.environ.get("M4_SIGNING_LAUNCHER_PIDFILE", "/run/m4-signing-launcher.pid")
_STOP_WAIT_SECONDS = 5.0


def _log(event: str, **fields) -> None:
    print("[m4-signing-launcher] " + json.dumps({"event": event, **fields},
                                                  ensure_ascii=False, sort_keys=True, default=str))


def _require_key_env(name: str) -> bytes:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"thieu bien moi truong bat buoc {name} (dung CUNG gia tri da truyen cho "
                         "`m4_stage0p_rehearsal_runner.py provision-keys`)")
    raw = base64.b64decode(val, validate=True)
    if len(raw) != KEY_LEN:
        raise SystemExit(f"{name}: phai la {KEY_LEN} byte sau khi decode base64")
    return raw


def _read_pidfile() -> int | None:
    try:
        return int(Path(PIDFILE_PATH).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _process_cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except FileNotFoundError:
        return ""


def _is_signing_service_process(pid: int) -> bool:
    """An toan khi stop/status doc lai PID tu pidfile qua nhieu lan goi CLI rieng biet -- xac minh
    PID do THAT SU dang chay dung module nay (tranh truong hop PID da bi he dieu hanh tai su dung
    cho 1 tien trinh khong lien quan sau khi signer that su da thoat)."""
    return "app.services.pii.stage0p_signing_service" in _process_cmdline(pid)


def cmd_start(_args) -> int:
    existing_pid = _read_pidfile()
    if existing_pid is not None and _is_signing_service_process(existing_pid):
        raise SystemExit(f"signing service da chay (pid={existing_pid}) -- `stop` truoc neu can "
                         "khoi dong lai (vd rotate key)")

    sample_key = _require_key_env("M4_SAMPLE_KEY_B64")
    hmac_key = _require_key_env("M4_TRANSCRIPT_HMAC_KEY_B64")
    auth_verify_key = _require_key_env("M4_SIGNING_AUTH_VERIFY_KEY_B64")

    signer_uid, collector_uid, _other_uid, shared_gid = ensure_service_accounts()

    async def _do_start() -> int:
        proc, _s, _h, _a = await start_signing_service(
            socket_path=SOCKET_PATH, allowed_uid=collector_uid,
            sample_key=sample_key, hmac_key=hmac_key, auth_verify_key=auth_verify_key,
            run_as_uid=signer_uid, shared_gid=shared_gid, detach=True)
        # Tien trinh da detached (start_new_session=True) - van SONG SOT sau khi ham nay tra ve.
        # QUAN TRONG: KHONG dong `proc._transport` o day - da kiem chung THAT (khong doan) rang
        # lam vay gui SIGKILL/dong pipe toi CHINH tien trinh con, giet chet no ngay lap tuc du
        # start_new_session=True (transport van "so huu" tien trinh cho toi khi ta CHU DONG buong
        # no ra theo dung API). Chi tra ve pid (int) - asyncio se tu in 1 canh bao GC vo hai
        # ("Event loop is closed") khi Process/transport object bi finalize sau khi asyncio.run()
        # dong loop; day CHI la noise tren stderr, khong anh huong ket qua/exit code, chap nhan
        # duoc thay vi rui ro giet nham tien trinh dang chay that.
        return proc.pid

    pid = asyncio.run(_do_start())
    Path(PIDFILE_PATH).write_text(str(pid))
    _log("signing_service_started", pid=pid, socket_path=SOCKET_PATH,
         signer_uid=signer_uid, collector_uid=collector_uid, shared_gid=shared_gid,
         note="tien trinh detached -- van chay sau khi lenh CLI nay thoat. Chay "
              "rehearsal_runner.py voi `docker exec --user m4-collector` VA "
              f"`-e M4_STAGE0P_SIGNING_SOCKET={SOCKET_PATH}` de collector that su ket noi duoc "
              "(peer UID phai khop collector_uid o tren).")
    return 0


def cmd_stop(_args) -> int:
    pid = _read_pidfile()
    if pid is None:
        _log("signing_service_not_running", note="khong co pidfile")
        return 0
    if not _is_signing_service_process(pid):
        _log("signing_service_stale_pidfile", pid=pid,
             note="PID trong pidfile khong con la signing service (co the da thoat/bi tai su dung) "
                  "-- chi xoa pidfile, khong gui tin hieu toi tien trinh khac")
        Path(PIDFILE_PATH).unlink(missing_ok=True)
        return 0

    os.kill(pid, 15)  # SIGTERM
    deadline = time.monotonic() + _STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        if not _is_signing_service_process(pid):
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)  # SIGKILL -- van con song sau SIGTERM + doi
        time.sleep(0.2)

    Path(PIDFILE_PATH).unlink(missing_ok=True)
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass
    try:
        os.rmdir(os.path.dirname(SOCKET_PATH))
    except OSError:
        pass  # khong rong/khong ton tai -- best-effort, khong phai loi
    _log("signing_service_stopped", pid=pid)
    return 0


def cmd_status(_args) -> int:
    pid = _read_pidfile()
    running = pid is not None and _is_signing_service_process(pid)
    socket_exists = os.path.lexists(SOCKET_PATH)
    _log("signing_service_status", running=running, pid=pid if running else None,
         socket_path=SOCKET_PATH, socket_exists=socket_exists)
    return 0


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("start").set_defaults(func=cmd_start)
    sub.add_parser("stop").set_defaults(func=cmd_stop)
    sub.add_parser("status").set_defaults(func=cmd_status)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
