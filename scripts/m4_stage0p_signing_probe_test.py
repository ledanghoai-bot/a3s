#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence cho `scripts/m4_stage0p_signing_probe.py` VA topology
docker-compose (A08-COR-01 REV1, dap
PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-1-VI.md F-A08-R1-01/02/03), sua theo
PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-2-VI.md F-A08-R2-02: probe REV2 tach
`mint-token` (danh tinh operator, giu khoa)/`submit` (danh tinh m4-collector, KHONG giu khoa).

Chay (sandbox RIENG, KHONG production):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@<sandbox-db>:5432/alpha3s \
      -e REDIS_URL=redis://<sandbox-redis>:6379/0 \
      alpha3s-m4-test python scripts/m4_stage0p_signing_probe_test.py

Kich ban:
  [P-01] mint-token (danh tinh operator, KHONG m4-collector) + submit (danh tinh m4-collector,
      KHONG duoc dua M4_SIGNING_AUTH_VERIFY_KEY_B64) THANH CONG khi signing service that dang
      chay, dung khoa - proto day du (peer UID/rate-limit/nonce/chu ky/canonicalize/encrypt/sign).
  [P-02] mint-token voi SAI auth key -> submit THAT BAI sach (chu ky khong khop), khong crash.
  [P-03] submit THAT BAI sach khi khong co signing service nao dang chay (socket khong ton tai).
  [P-04] Output ca 2 buoc KHONG BAO GIO chua noi dung canary/ciphertext/plaintext/khoa.
  [P-05] F-A08-R1-02 (static audit): docker-compose.prod.yml - CHI service `m4-signer` yeu cau
      3 khoa signing; KHONG service nao khac tham chieu 2 khoa nhay cam.
  [P-06] F-A08-R1-01 (static audit): `m4-signer` dormant default OFF + restart: "no".
  [P-07] F-A08-R1-01 (static audit): Dockerfile tao UID/GID CO DINH luc BUILD IMAGE.
  [P-08] F-A08-R2-02 (static audit): `cmd_submit`/`_submit` KHONG chua bat ky tham chieu nao toi
      M4_SIGNING_AUTH_VERIFY_KEY_B64 hay `_sign_canary_authorization` trong source code cua no -
      m4-collector KHONG CO code path nao de tu doc/dung khoa nay du bien co bi lo vao env.
  [P-09] F-A08-R2-02: submit chay THAT duoi UID m4-collector VOI M4_SIGNING_AUTH_VERIFY_KEY_B64
      CO MAT trong env (mo phong operator lo tay dat nham) - ket qua KHONG doi (van thanh cong/
      that bai giong het khi bien vang mat) - chung minh bien nay hoan toan tro (inert) voi submit.
  [P-10] F-A08-R2-02 (negative, tamper): 1 token mint-token hop le, SUA 1 truong (sample_id)
      TRUOC khi submit qua UID m4-collector - server tu choi (chu ky khong con khop) - chung minh
      m4-collector, du CO token that trong tay VA CO toan bo source code thuat toan, KHONG THE tu
      mint 1 authorization HOP LE cho noi dung KHAC vi thieu khoa - chi replay duoc DUNG NGUYEN
      token da duoc cap, khong sua duoc.
"""

import ast
import asyncio
import base64
import inspect
import json
import os
import pwd
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import m4_stage0p_signing_probe as probe_module  # noqa: E402
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


async def _run_mint(*, auth_key_b64: str | None, timeout: float = 10.0) -> tuple[int, str]:
    """`mint-token` khong can chay duoi danh tinh m4-collector (F-A08-R2-02: chinh diem cua REV2
    la KHONG dua khoa cho collector) - o day chay duoi danh tinh mac dinh cua tien trinh test
    (khong --user), khop dung runbook (khong `--user m4-collector`)."""
    env = os.environ.copy()
    if auth_key_b64:
        env["M4_SIGNING_AUTH_VERIFY_KEY_B64"] = auth_key_b64
    else:
        env.pop("M4_SIGNING_AUTH_VERIFY_KEY_B64", None)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, _PROBE_SCRIPT, "mint-token", cwd=str(ROOT), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, stdout.decode(errors="replace").strip()


async def _run_submit_as_uid(uid: int, *, socket_path: str, token_b64: str | None,
                             extra_env: dict | None = None,
                             timeout: float = 10.0) -> tuple[int, str]:
    """Chay THAT `submit` nhu 1 tien trinh con RIENG duoi UID `uid` (khong phai goi ham noi bo tu
    tien trinh test dang chay duoi root - se bi peer-UID check tu choi neu goi truc tiep) - khop
    CHINH XAC cach van hanh that (`docker compose exec --user m4-collector`)."""
    env = os.environ.copy()
    env["M4_STAGE0P_SIGNING_SOCKET"] = socket_path
    if token_b64:
        env["M4_SIGNING_PROBE_TOKEN"] = token_b64
    else:
        env.pop("M4_SIGNING_PROBE_TOKEN", None)
    if extra_env:
        env.update(extra_env)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, _PROBE_SCRIPT, "submit", cwd=str(ROOT), env=env,
        user=uid, group=pwd.getpwuid(uid).pw_gid,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, stdout.decode(errors="replace")


async def scenario_p01_mint_then_submit_succeeds() -> None:
    print("== [P-01] mint-token (danh tinh operator) + submit (danh tinh m4-collector, KHONG co "
          "khoa trong env) THANH CONG voi signing service that ==")
    signer_uid, collector_uid, _other_uid, shared_gid = ensure_service_accounts()
    socket_path = f"/tmp/m4-probe-p01-{os.getpid()}/sock"
    proc, _sk, _hk, auth_key = await start_signing_service(
        socket_path=socket_path, allowed_uid=collector_uid,
        run_as_uid=signer_uid, shared_gid=shared_gid)
    try:
        mint_rc, token_b64 = await _run_mint(auth_key_b64=base64.b64encode(auth_key).decode())
        check(mint_rc == 0, f"[P-01] mint-token exit 0 (thuc te {mint_rc})")
        rc, out = await _run_submit_as_uid(
            collector_uid, socket_path=socket_path, token_b64=token_b64)
        check(rc == 0, f"[P-01] submit chay duoi UID m4-collector THAT SU exit 0 (thuc te {rc}, "
                       f"output={out!r})")
        check('"ok": true' in out, f"[P-01] output JSON co \"ok\": true (thuc te {out!r})")
        check('"canonical_digest_matches": true' in out,
              f"[P-01] digest canary khop tu chinh service tu tinh (thuc te {out!r})")
    finally:
        await stop_signing_service(proc, socket_path)


async def scenario_p02_wrong_key_fails_cleanly() -> None:
    print("== [P-02] mint-token voi SAI auth key -> submit THAT BAI sach (chu ky khong khop) ==")
    signer_uid, collector_uid, _other_uid, shared_gid = ensure_service_accounts()
    socket_path = f"/tmp/m4-probe-p02-{os.getpid()}/sock"
    proc, _sk, _hk, _real_auth_key = await start_signing_service(
        socket_path=socket_path, allowed_uid=collector_uid,
        run_as_uid=signer_uid, shared_gid=shared_gid)
    try:
        wrong_key_b64 = base64.b64encode(os.urandom(32)).decode()
        mint_rc, token_b64 = await _run_mint(auth_key_b64=wrong_key_b64)
        check(mint_rc == 0, f"[P-02] mint-token van thanh cong (tu ky duoc, chi ky SAI khoa) "
                            f"(thuc te {mint_rc})")
        rc, out = await _run_submit_as_uid(
            collector_uid, socket_path=socket_path, token_b64=token_b64)
        check(rc == 1, f"[P-02] SAI auth key -> submit exit 1 sach, khong crash (thuc te {rc})")
        check('"ok": false' in out, f"[P-02] output JSON co \"ok\": false (thuc te {out!r})")
    finally:
        await stop_signing_service(proc, socket_path)


async def scenario_p03_no_service_fails_cleanly() -> None:
    print("== [P-03] submit THAT BAI sach khi khong co signing service nao dang chay ==")
    _signer_uid, collector_uid, _other_uid, _shared_gid = ensure_service_accounts()
    socket_path = f"/tmp/m4-probe-p03-nonexistent-{os.getpid()}/sock"
    fake_key_b64 = base64.b64encode(os.urandom(32)).decode()
    mint_rc, token_b64 = await _run_mint(auth_key_b64=fake_key_b64)
    check(mint_rc == 0, f"[P-03] mint-token thanh cong (khong can service dang chay) "
                        f"(thuc te {mint_rc})")
    rc, out = await _run_submit_as_uid(
        collector_uid, socket_path=socket_path, token_b64=token_b64)
    check(rc == 1, f"[P-03] khong co service -> submit exit 1 sach (thuc te {rc})")
    check('"ok": false' in out, f"[P-03] output JSON co \"ok\": false, khong phai traceback thoat "
                                f"thang (thuc te {out!r})")
    check("Traceback" not in out, "[P-03] khong co raw traceback lot ra ngoai")


async def scenario_p04_never_leaks_content() -> None:
    print("== [P-04] Output mint-token + submit (chay THAT) KHONG BAO GIO chua noi dung canary/"
          "ciphertext/khoa ==")
    signer_uid, collector_uid, _other_uid, shared_gid = ensure_service_accounts()
    socket_path = f"/tmp/m4-probe-p04-{os.getpid()}/sock"
    proc, _sk, _hk, auth_key = await start_signing_service(
        socket_path=socket_path, allowed_uid=collector_uid,
        run_as_uid=signer_uid, shared_gid=shared_gid)
    try:
        auth_key_b64 = base64.b64encode(auth_key).decode()
        mint_rc, token_b64 = await _run_mint(auth_key_b64=auth_key_b64)
        check(mint_rc == 0, f"[P-04] mint-token exit 0 (thuc te {mint_rc})")
        check(auth_key_b64 not in token_b64,
              "[P-04] output mint-token KHONG chua gia tri khoa dau vao duoi bat ky dang nao")
        rc, out = await _run_submit_as_uid(
            collector_uid, socket_path=socket_path, token_b64=token_b64)
        check(rc == 0, f"[P-04] submit exit 0 (thuc te {rc})")
        check("KHONG PHAI DU LIEU THAT" not in out,
              "[P-04] output submit KHONG chua chuoi noi dung canary goc")
        check("ciphertext" not in out.lower(),
              "[P-04] output submit KHONG chua truong ciphertext (chi tom tat)")
        check(auth_key_b64 not in out,
              "[P-04] output submit KHONG chua gia tri khoa duoi bat ky dang nao")
    finally:
        await stop_signing_service(proc, socket_path)


def _load_compose_prod() -> dict:
    with (ROOT / "docker-compose.prod.yml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


async def scenario_p05_secret_scoped_to_signer_only() -> None:
    print("== [P-05] F-A08-R1-02/F-A08-R2-01: chi m4-signer yeu cau khoa signing (qua DUONG DAN "
          "FILE, KHONG con gia tri THO trong environment:), KHONG service nao khac tham chieu 2 "
          "khoa nhay cam nay ==")
    compose = _load_compose_prod()
    services = compose.get("services", {})
    check("m4-signer" in services, "[P-05] service m4-signer ton tai trong docker-compose.prod.yml")

    signer = services.get("m4-signer", {})
    signer_env = signer.get("environment", [])
    signer_env_text = "\n".join(signer_env) if isinstance(signer_env, list) else str(signer_env)
    for key_name in ("M4_TRANSCRIPT_HMAC_KEY_B64", "M4_SIGNING_AUTH_VERIFY_KEY_B64",
                     "M4_SAMPLE_KEY_B64"):
        check(f"{key_name}_FILE" in signer_env_text,
              f"[P-05] m4-signer.environment co tham chieu {key_name}_FILE (duong dan, khong phai "
              "gia tri)")
        check(f"{key_name}=${{" not in signer_env_text,
              f"[P-05] F-A08-R2-01: m4-signer.environment KHONG con gia tri THO {key_name}=${{...}} "
              "(REV1 cu lam vay, docker inspect se hien gia tri o Config.Env - REV2 chi con duong "
              "dan file)")

    signer_volumes = signer.get("volumes", [])
    check(any("/run/m4-signing-secrets" in v and v.rstrip().endswith(":ro") for v in signer_volumes),
          f"[P-05] F-A08-R2-01: m4-signer mount /run/m4-signing-secrets READ-ONLY (thuc te "
          f"volumes={signer_volumes})")

    sensitive = ("M4_TRANSCRIPT_HMAC_KEY_B64", "M4_SIGNING_AUTH_VERIFY_KEY_B64")
    for svc_name, svc_def in services.items():
        if svc_name == "m4-signer":
            continue
        env = svc_def.get("environment", [])
        env_text = "\n".join(env) if isinstance(env, list) else str(env)
        for key_name in sensitive:
            check(key_name not in env_text,
                  f"[P-05] service {svc_name!r} KHONG tham chieu {key_name} (thang hay _FILE) "
                  "trong environment (khoa signing CHI song trong m4-signer)")


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


async def scenario_p08_submit_code_never_references_auth_key() -> None:
    print("== [P-08] F-A08-R2-02 (static): cmd_submit/_submit KHONG chua bat ky tham chieu nao "
          "toi M4_SIGNING_AUTH_VERIFY_KEY_B64 hay ham ky - m4-collector KHONG CO code path de tu "
          "doc/dung khoa nay ==")
    # Bo docstring truoc khi kiem - docstring giai thich (bang loi) VI SAO khong dung bien nay
    # se tu nhien chua ten bien do; chi CODE THAT SU (os.environ.get(...)/os.environ[...]) moi la
    # dieu can chan tuyet doi, khong phai van ban giai thich. Dung AST (khong phai str.replace,
    # vi inspect.getdoc() chuan hoa thut le khac voi van ban goc trong source, str.replace se
    # khong khop va am tham khong xoa duoc gi).
    def _strip_docstring(fn) -> str:
        src = inspect.getsource(fn)
        tree = ast.parse(src)
        func_node = tree.body[0]
        if (func_node.body and isinstance(func_node.body[0], ast.Expr)
                and isinstance(func_node.body[0].value, ast.Constant)
                and isinstance(func_node.body[0].value.value, str)):
            doc_node = func_node.body[0]
            lines = src.splitlines(keepends=True)
            del lines[doc_node.lineno - 1:doc_node.end_lineno]
            return "".join(lines)
        return src
    code_only = _strip_docstring(probe_module.cmd_submit) + _strip_docstring(probe_module._submit)
    check("M4_SIGNING_AUTH_VERIFY_KEY_B64" not in code_only,
          "[P-08] cmd_submit()/_submit() KHONG tham chieu bien M4_SIGNING_AUTH_VERIFY_KEY_B64 "
          "trong CODE THAT SU (da loai docstring giai thich khoi phep kiem)")
    check("_sign_canary_authorization" not in code_only,
          "[P-08] cmd_submit()/_submit() KHONG goi _sign_canary_authorization (ham CAN khoa) - "
          "chi mint-token moi duoc goi ham nay")
    mint_src = inspect.getsource(probe_module.cmd_mint_token)
    check("_sign_canary_authorization" in mint_src,
          "[P-08] xac nhan nguoc: cmd_mint_token() (danh tinh operator) MOI la noi duy nhat goi "
          "ham ky - dam bao khong co duong nao khac lam viec nay")


async def scenario_p09_leaked_key_in_collector_env_is_inert() -> None:
    print("== [P-09] F-A08-R2-02: submit chay duoi UID m4-collector VOI "
          "M4_SIGNING_AUTH_VERIFY_KEY_B64 CO MAT trong env (mo phong lo tay) - ket qua KHONG doi, "
          "chung minh bien nay hoan toan tro voi submit ==")
    signer_uid, collector_uid, _other_uid, shared_gid = ensure_service_accounts()
    socket_path = f"/tmp/m4-probe-p09-{os.getpid()}/sock"
    proc, _sk, _hk, auth_key = await start_signing_service(
        socket_path=socket_path, allowed_uid=collector_uid,
        run_as_uid=signer_uid, shared_gid=shared_gid)
    try:
        auth_key_b64 = base64.b64encode(auth_key).decode()
        mint_rc, token_b64 = await _run_mint(auth_key_b64=auth_key_b64)
        check(mint_rc == 0, f"[P-09] mint-token exit 0 (thuc te {mint_rc})")
        # Co y dat khoa THAT vao env cua submit (mo phong operator lo tay) - neu code co bat ky
        # nhanh nao am tham doc bien nay, ket qua se khac voi [P-01] (vd log them thong tin, hoac
        # thanh cong theo con duong khac) - o day ta xac nhan HANH VI GIONG HET [P-01].
        rc, out = await _run_submit_as_uid(
            collector_uid, socket_path=socket_path, token_b64=token_b64,
            extra_env={"M4_SIGNING_AUTH_VERIFY_KEY_B64": auth_key_b64})
        check(rc == 0, f"[P-09] submit van thanh cong binh thuong du khoa co mat trong env "
                       f"(thuc te {rc}) - hanh vi khong doi so voi [P-01]")
        check('"ok": true' in out, f"[P-09] output JSON co \"ok\": true, giong het [P-01] "
                                   f"(thuc te {out!r})")
    finally:
        await stop_signing_service(proc, socket_path)


async def scenario_p10_tampered_token_rejected() -> None:
    print("== [P-10] F-A08-R2-02 (negative, tamper): token hop le bi SUA 1 truong TRUOC khi "
          "submit -> server tu choi - m4-collector KHONG THE tu mint 1 authorization HOP LE cho "
          "noi dung KHAC du co token that + toan bo source code thuat toan trong tay ==")
    signer_uid, collector_uid, _other_uid, shared_gid = ensure_service_accounts()
    socket_path = f"/tmp/m4-probe-p10-{os.getpid()}/sock"
    proc, _sk, _hk, auth_key = await start_signing_service(
        socket_path=socket_path, allowed_uid=collector_uid,
        run_as_uid=signer_uid, shared_gid=shared_gid)
    try:
        auth_key_b64 = base64.b64encode(auth_key).decode()
        mint_rc, token_b64 = await _run_mint(auth_key_b64=auth_key_b64)
        check(mint_rc == 0, f"[P-10] mint-token exit 0 (thuc te {mint_rc})")

        blob = json.loads(base64.b64decode(token_b64))
        blob["sample_id"] = blob["sample_id"] + "-tampered"
        tampered_token_b64 = base64.b64encode(
            json.dumps(blob, sort_keys=True).encode("utf-8")).decode("ascii")

        rc, out = await _run_submit_as_uid(
            collector_uid, socket_path=socket_path, token_b64=tampered_token_b64)
        check(rc == 1, f"[P-10] token bi sua sample_id -> submit exit 1 (thuc te {rc})")
        check('"ok": false' in out, f"[P-10] output JSON co \"ok\": false - server tu choi token "
                                    f"da bi sua (thuc te {out!r})")

        # Xac nhan doc lap: token GOC (chua sua) van con hop le VA CHUA bi dung (nonce chua tieu
        # thu) - chung minh that bai o tren la DO SUA TOKEN, khong phai do socket/service loi.
        rc2, out2 = await _run_submit_as_uid(
            collector_uid, socket_path=socket_path, token_b64=token_b64)
        check(rc2 == 0, f"[P-10] token GOC (chua sua) van submit thanh cong binh thuong "
                        f"(thuc te {rc2}) - xac nhan that bai o tren la do tamper, khong phai "
                        "do moi truong")
    finally:
        await stop_signing_service(proc, socket_path)


async def main() -> int:
    await scenario_p01_mint_then_submit_succeeds()
    await scenario_p02_wrong_key_fails_cleanly()
    await scenario_p03_no_service_fails_cleanly()
    await scenario_p04_never_leaks_content()
    await scenario_p05_secret_scoped_to_signer_only()
    await scenario_p06_dormant_default_and_no_autorestart()
    await scenario_p07_dockerfile_bakes_fixed_uids()
    await scenario_p08_submit_code_never_references_auth_key()
    await scenario_p09_leaked_key_in_collector_env_is_inert()
    await scenario_p10_tampered_token_rejected()

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
