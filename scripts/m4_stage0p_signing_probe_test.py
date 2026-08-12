#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence cho `scripts/m4_stage0p_signing_probe.py` VA topology
docker-compose moi (A08-COR-01 REV1, dap
PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-1-VI.md F-A08-R1-01/02/03).

Chay (sandbox RIENG, KHONG production):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@<sandbox-db>:5432/alpha3s \
      -e REDIS_URL=redis://<sandbox-redis>:6379/0 \
      alpha3s-m4-test python scripts/m4_stage0p_signing_probe_test.py

Kich ban:
  [P-01] Canary probe THANH CONG khi signing service that dang chay, dung khoa - proto day du
      (peer UID/rate-limit/nonce/chu ky/canonicalize/encrypt/sign) hoat dong dung.
  [P-02] Canary probe THAT BAI sach (khong crash, ok=false) khi dung SAI auth key (chu ky khong
      khop) - khong tiet lo gi ngoai ok=false.
  [P-03] Canary probe THAT BAI sach khi khong co signing service nao dang chay (socket khong
      ton tai) - loi ket noi duoc bat gon, khong traceback lot ra CLI.
  [P-04] Probe output KHONG BAO GIO chua noi dung canary/ciphertext/plaintext - chi cac truong
      tom tat (key_version/canonical_len/canonical_digest_matches).
  [P-05] F-A08-R1-02 (static audit): docker-compose.prod.yml - CHI service `m4-signer` yeu cau
      3 khoa signing; KHONG service nao khac (api/worker/telegram_bot/telegram_customer_bot/
      dashboard) tham chieu M4_TRANSCRIPT_HMAC_KEY_B64/M4_SIGNING_AUTH_VERIFY_KEY_B64 trong
      environment/env_file cua no.
  [P-06] F-A08-R1-01 (static audit): `m4-signer` co `profiles: [m4-signing]` (dormant default
      OFF - khong bao gio khoi dong boi `docker compose up -d` thuong) va `restart: "no"`
      (CO Y, khong auto-restart 1 tien trinh giu khoa nhay cam).
  [P-07] F-A08-R1-01 (static audit): Dockerfile tao UID/GID CO DINH (m4-signer=5001,
      m4-collector=5002, group m4-signing-ipc=5000) luc BUILD IMAGE (khong con `useradd` o
      script Python nao chay luc container dang hoat dong).
"""

import asyncio
import base64
import os
import pwd
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _stage0p_signing_service_helper import (  # noqa: E402
    ensure_service_accounts,
    start_signing_service,
    stop_signing_service,
)

_fail: list[str] = []
_PROBE_SCRIPT = str(Path(__file__).resolve().parent / "m4_stage0p_signing_probe.py")


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


async def _run_probe_as_uid(uid: int, *, socket_path: str, auth_key_b64: str,
                            timeout: float = 10.0) -> tuple[int, str]:
    """Chay THAT `scripts/m4_stage0p_signing_probe.py` nhu 1 tien trinh con RIENG duoi UID `uid`
    (khong phai goi ham noi bo tu tien trinh test dang chay - test tu no chay duoi root, se bi
    peer-UID check tu choi neu goi truc tiep) - khop CHINH XAC cach van hanh that
    (`docker compose exec --user m4-collector`). Tra ve (returncode, stdout)."""
    env = os.environ.copy()
    env["M4_STAGE0P_SIGNING_SOCKET"] = socket_path
    if auth_key_b64:
        env["M4_SIGNING_AUTH_VERIFY_KEY_B64"] = auth_key_b64
    else:
        env.pop("M4_SIGNING_AUTH_VERIFY_KEY_B64", None)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, _PROBE_SCRIPT, cwd=str(ROOT), env=env,
        user=uid, group=pwd.getpwuid(uid).pw_gid,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, stdout.decode(errors="replace")


async def scenario_p01_probe_succeeds() -> None:
    print("== [P-01] Canary probe THANH CONG voi signing service that + dung khoa, chay THAT "
          "duoi UID m4-collector (khop dung cach van hanh production) ==")
    signer_uid, collector_uid, _other_uid, shared_gid = ensure_service_accounts()
    socket_path = f"/tmp/m4-probe-p01-{os.getpid()}/sock"
    proc, _sk, _hk, auth_key = await start_signing_service(
        socket_path=socket_path, allowed_uid=collector_uid,
        run_as_uid=signer_uid, shared_gid=shared_gid)
    try:
        rc, out = await _run_probe_as_uid(
            collector_uid, socket_path=socket_path,
            auth_key_b64=base64.b64encode(auth_key).decode())
        check(rc == 0, f"[P-01] probe chay duoi UID m4-collector THAT SU exit 0 (thuc te {rc}, "
                       f"output={out!r})")
        check('"ok": true' in out, f"[P-01] output JSON co \"ok\": true (thuc te {out!r})")
        check('"canonical_digest_matches": true' in out,
              f"[P-01] digest canary khop tu chinh service tu tinh (thuc te {out!r})")
    finally:
        await stop_signing_service(proc, socket_path)


async def scenario_p02_probe_fails_wrong_key() -> None:
    print("== [P-02] Canary probe THAT BAI sach voi SAI auth key (chu ky khong khop) ==")
    signer_uid, collector_uid, _other_uid, shared_gid = ensure_service_accounts()
    socket_path = f"/tmp/m4-probe-p02-{os.getpid()}/sock"
    proc, _sk, _hk, _real_auth_key = await start_signing_service(
        socket_path=socket_path, allowed_uid=collector_uid,
        run_as_uid=signer_uid, shared_gid=shared_gid)
    try:
        wrong_key_b64 = base64.b64encode(os.urandom(32)).decode()
        rc, out = await _run_probe_as_uid(
            collector_uid, socket_path=socket_path, auth_key_b64=wrong_key_b64)
        check(rc == 1, f"[P-02] SAI auth key -> probe exit 1 sach, khong crash (thuc te {rc})")
        check('"ok": false' in out, f"[P-02] output JSON co \"ok\": false (thuc te {out!r})")
    finally:
        await stop_signing_service(proc, socket_path)


async def scenario_p03_probe_fails_no_service() -> None:
    print("== [P-03] Canary probe THAT BAI sach khi khong co signing service nao dang chay ==")
    _signer_uid, collector_uid, _other_uid, _shared_gid = ensure_service_accounts()
    socket_path = f"/tmp/m4-probe-p03-nonexistent-{os.getpid()}/sock"
    fake_key_b64 = base64.b64encode(os.urandom(32)).decode()
    rc, out = await _run_probe_as_uid(
        collector_uid, socket_path=socket_path, auth_key_b64=fake_key_b64)
    check(rc == 1, f"[P-03] khong co service -> probe exit 1 sach (thuc te {rc})")
    check('"ok": false' in out, f"[P-03] output JSON co \"ok\": false, khong phai traceback thoat "
                                f"thang (thuc te {out!r})")
    check("Traceback" not in out, "[P-03] khong co raw traceback lot ra ngoai")


async def scenario_p04_probe_never_leaks_content() -> None:
    print("== [P-04] Probe output (chay THAT duoi UID m4-collector) KHONG BAO GIO chua noi dung "
          "canary/ciphertext/khoa ==")
    signer_uid, collector_uid, _other_uid, shared_gid = ensure_service_accounts()
    socket_path = f"/tmp/m4-probe-p04-{os.getpid()}/sock"
    proc, _sk, _hk, auth_key = await start_signing_service(
        socket_path=socket_path, allowed_uid=collector_uid,
        run_as_uid=signer_uid, shared_gid=shared_gid)
    try:
        auth_key_b64 = base64.b64encode(auth_key).decode()
        rc, out = await _run_probe_as_uid(
            collector_uid, socket_path=socket_path, auth_key_b64=auth_key_b64)
        check(rc == 0, f"[P-04] probe exit 0 (thuc te {rc})")
        check("KHONG PHAI DU LIEU THAT" not in out,
              "[P-04] output KHONG chua chuoi noi dung canary goc")
        check("ciphertext" not in out.lower(),
              "[P-04] output KHONG chua truong ciphertext (chi tom tat, khong du lieu ma hoa)")
        check(auth_key_b64 not in out,
              "[P-04] output KHONG chua gia tri khoa (dau vao) duoi bat ky dang nao")
    finally:
        await stop_signing_service(proc, socket_path)


def _load_compose_prod() -> dict:
    with (ROOT / "docker-compose.prod.yml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


async def scenario_p05_secret_scoped_to_signer_only() -> None:
    print("== [P-05] F-A08-R1-02: chi m4-signer yeu cau khoa signing, KHONG service nao khac "
          "tham chieu 2 khoa nhay cam nay ==")
    compose = _load_compose_prod()
    services = compose.get("services", {})
    check("m4-signer" in services, "[P-05] service m4-signer ton tai trong docker-compose.prod.yml")

    signer_env = services.get("m4-signer", {}).get("environment", [])
    signer_env_text = "\n".join(signer_env) if isinstance(signer_env, list) else str(signer_env)
    for key_name in ("M4_TRANSCRIPT_HMAC_KEY_B64", "M4_SIGNING_AUTH_VERIFY_KEY_B64",
                     "M4_SAMPLE_KEY_B64"):
        check(key_name in signer_env_text,
              f"[P-05] m4-signer.environment co tham chieu {key_name}")

    sensitive = ("M4_TRANSCRIPT_HMAC_KEY_B64", "M4_SIGNING_AUTH_VERIFY_KEY_B64")
    for svc_name, svc_def in services.items():
        if svc_name == "m4-signer":
            continue
        env = svc_def.get("environment", [])
        env_text = "\n".join(env) if isinstance(env, list) else str(env)
        for key_name in sensitive:
            check(key_name not in env_text,
                  f"[P-05] service {svc_name!r} KHONG tham chieu {key_name} trong environment "
                  "(khoa signing CHI song trong m4-signer)")


async def scenario_p06_dormant_default_and_no_autorestart() -> None:
    print("== [P-06] F-A08-R1-01: m4-signer co profile rieng (dormant default OFF) va "
          "restart: \"no\" (CO Y, khong auto-restart) ==")
    compose = _load_compose_prod()
    signer = compose["services"]["m4-signer"]
    check(signer.get("profiles") == ["m4-signing"],
          f"[P-06] m4-signer.profiles == ['m4-signing'] (thuc te {signer.get('profiles')}) - "
          "khong bao gio khoi dong boi 'docker compose up -d' thuong")
    check(signer.get("restart") == "no",
          f"[P-06] m4-signer.restart == 'no' (thuc te {signer.get('restart')!r}) - khong "
          "auto-restart tien trinh giu khoa nhay cam")
    check("healthcheck" in signer, "[P-06] m4-signer co khai bao healthcheck")

    api = compose["services"]["api"]
    api_volumes = api.get("volumes", [])
    check(any("m4_signing_socket" in v for v in api_volumes),
          f"[P-06] api service mount chung volume m4_signing_socket voi m4-signer "
          f"(thuc te volumes={api_volumes})")
    top_volumes = compose.get("volumes", {})
    check("m4_signing_socket" in top_volumes,
          "[P-06] volume m4_signing_socket duoc khai bao o top-level volumes:")


async def scenario_p07_dockerfile_bakes_fixed_uids() -> None:
    print("== [P-07] F-A08-R1-01: Dockerfile tao UID/GID CO DINH luc BUILD (khong con runtime "
          "useradd) ==")
    dockerfile_text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    check("groupadd -g 5000 m4-signing-ipc" in dockerfile_text,
          "[P-07] Dockerfile tao group m4-signing-ipc voi GID co dinh 5000")
    check("-u 5001" in dockerfile_text and "m4-signer" in dockerfile_text,
          "[P-07] Dockerfile tao user m4-signer voi UID co dinh 5001")
    check("-u 5002" in dockerfile_text and "m4-collector" in dockerfile_text,
          "[P-07] Dockerfile tao user m4-collector voi UID co dinh 5002")
    check("m4_stage0p_signing_launcher" not in dockerfile_text,
          "[P-07] khong con tham chieu launcher REV0 (asyncio-spawn) nao trong Dockerfile")
    launcher_path = ROOT / "scripts" / "m4_stage0p_signing_launcher.py"
    check(not launcher_path.exists(),
          "[P-07] scripts/m4_stage0p_signing_launcher.py (REV0, asyncio-spawn) da bi xoa - "
          "docker compose la supervisor duy nhat, khong con Python tu spawn process")


async def main() -> int:
    await scenario_p01_probe_succeeds()
    await scenario_p02_probe_fails_wrong_key()
    await scenario_p03_probe_fails_no_service()
    await scenario_p04_probe_never_leaks_content()
    await scenario_p05_secret_scoped_to_signer_only()
    await scenario_p06_dormant_default_and_no_autorestart()
    await scenario_p07_dockerfile_bakes_fixed_uids()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)} kich ban that bai)")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
