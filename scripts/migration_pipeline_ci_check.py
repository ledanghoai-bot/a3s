#!/usr/bin/env python3
"""F-MIG-01 — chay 5 kich ban migration pipeline TRONG CI va xuat JSON canonical.

VI SAO SCRIPT NAY TON TAI
PR #25 ban dau chi co sandbox Dev chay TAY. CA (F-MIG-01) chi ro: nhu vay mot thay doi sau nay vao
compose/deploy/healthcheck co the regression ma CI van xanh — dung lop loi false-green ma chinh du
an da gap nhieu lan. Script nay bien 5 kich ban do thanh mot CI job THAT SU DO duoc.

NGUYEN TAC CUA HARNESS
  * Moi assert deu co gia tri DO DUOC (`thuc_te`) ghi vao JSON, khong chi True/False.
  * Gia tri rong / truy van loi => FAIL, khong bao gio duoc coi la "bang nhau".
  * Kich ban [3] va [4] la ca NEGATIVE: chung PHAI do duoc mot that bai. Neu chung "thanh cong"
    theo nghia khong co gi hong, do la harness sai chu khong phai he thong tot.
  * Exit != 0 neu bat ky assert nao fail.

CHAY:
    python scripts/migration_pipeline_ci_check.py [--json-out duong/dan.json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Khi harness chay TRONG container nhung dieu khien daemon cua HOST (docker-out-of-docker), moi
# bind-mount `-v` phai dung duong dan cua HOST — daemon khong thay duong dan trong container.
# Trong CI (chay truc tiep tren runner) hai gia tri nay bang nhau nen khong anh huong gi.
HOST_ROOT = os.environ.get("HOST_PROJECT_DIR", ROOT)
COMPOSE = os.path.join(ROOT, "scripts", "migration_pipeline_sandbox.compose.yml")
DOCKERFILE = os.path.join(ROOT, "scripts", "migration_pipeline_sandbox.Dockerfile")
QUERY = os.path.join(ROOT, "scripts", "migration_pipeline_query.py")
PROJECT = "mpci"
IMG = "alpha3s-migrate-sandbox"

LEDGER_SQL = "SELECT md5(string_agg(version||checksum, chr(10) ORDER BY version)) FROM schema_migrations"
SCHEMA_SQL = ("SELECT md5(string_agg(table_name||column_name, chr(10) ORDER BY table_name, column_name)) "
              "FROM information_schema.columns WHERE table_schema='public'")


def sh(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, cwd=ROOT, **kw)


def dc(*args: str, tag: str = "sandbox") -> subprocess.CompletedProcess:
    env = {**os.environ, "MIGRATE_TAG": tag}
    return sh(["docker", "compose", "-f", COMPOSE, "-p", PROJECT, *args], env=env)


def q(sql: str) -> str:
    """Truy van mot gia tri. Tra chuoi rong neu loi/rong — caller PHAI coi do la FAIL."""
    r = dc("run", "--rm", "--no-deps", "-T", "-v", f"{HOST_ROOT.rstrip(chr(47))}/scripts:/q",
           "migrate", "python", "/q/migration_pipeline_query.py", sql)
    if r.returncode != 0:
        return ""
    return r.stdout.strip().splitlines()[-1].strip() if r.stdout.strip() else ""


def exit_code(service: str, tag: str = "sandbox") -> int | None:
    r = dc("ps", "-a", "--format", "{{.Service}} {{.ExitCode}}", tag=tag)
    for line in r.stdout.splitlines():
        p = line.split()
        if len(p) == 2 and p[0] == service:
            return int(p[1])
    return None


def state(service: str, tag: str = "sandbox") -> str:
    r = dc("ps", "-a", "--format", "{{.Service}} {{.State}}", tag=tag)
    for line in r.stdout.splitlines():
        p = line.split()
        if len(p) == 2 and p[0] == service:
            return p[1]
    return "ABSENT"


class KichBan:
    def __init__(self, ma: str, mo_ta: str) -> None:
        self.ma, self.mo_ta, self.asserts = ma, mo_ta, []

    def check(self, ten: str, thuc_te, ky_vong, so_sanh="==") -> None:
        if so_sanh == "==":
            dat = thuc_te == ky_vong
        elif so_sanh == "!=":
            dat = thuc_te != ky_vong
        elif so_sanh == "khac_rong_va_bang":
            dat = bool(thuc_te) and thuc_te == ky_vong
        elif so_sanh == "chua":
            dat = ky_vong in str(thuc_te)
        else:
            raise ValueError(so_sanh)
        self.asserts.append({"ten": ten, "thuc_te": thuc_te, "ky_vong": ky_vong,
                             "so_sanh": so_sanh, "dat": dat})

    @property
    def dat(self) -> bool:
        return bool(self.asserts) and all(a["dat"] for a in self.asserts)

    def to_dict(self) -> dict:
        return {"ma": self.ma, "mo_ta": self.mo_ta, "dat": self.dat, "asserts": self.asserts}


def dem_file_migration() -> int:
    d = os.path.join(ROOT, "migrations")
    return len([f for f in os.listdir(d) if f.endswith(".sql")])


def kb1_fresh() -> KichBan:
    k = KichBan("1_fresh_db", "DB moi tinh: migration chay dung thu tu, app CHI start sau khi migrate exit 0")
    dc("down", "-v")
    up = dc("up", "app")
    k.check("migrate_exit_code", exit_code("migrate"), 0)
    k.check("app_state", state("app"), "exited")
    k.check("app_log_co_dong_khoi_dong", "APP DA START" in (up.stdout + up.stderr), True)
    k.check("so_migration_trong_ledger", q("SELECT count(*)::text FROM schema_migrations"),
            str(dem_file_migration()))
    k.check("044_trong_ledger",
            q("SELECT EXISTS(SELECT 1 FROM schema_migrations WHERE version LIKE '044%')::text"), "True")
    k.check("hai_bang_h2a_ton_tai",
            q("SELECT ((to_regclass('m4_stage0p_transcript_public_keys') IS NOT NULL) AND "
              "(to_regclass('m4_stage0p_transcript_signatures') IS NOT NULL))::text"), "True")
    return k


def kb2_idempotent() -> KichBan:
    k = KichBan("2_idempotent", "DB da migrate: chay lai khong doi ledger/schema")
    l1, s1 = q(LEDGER_SQL), q(SCHEMA_SQL)
    k.check("ledger_hash_truoc_khac_rong", bool(l1), True)
    k.check("schema_hash_truoc_khac_rong", bool(s1), True)
    dc("up", "app")
    k.check("migrate_exit_code", exit_code("migrate"), 0)
    k.check("ledger_hash_khong_doi", q(LEDGER_SQL), l1, "khac_rong_va_bang")
    k.check("schema_hash_khong_doi", q(SCHEMA_SQL), s1, "khac_rong_va_bang")
    return k


def kb3_that_bai() -> KichBan:
    k = KichBan("3_migration_that_bai", "Migration loi PHAI chan rollout ung dung")
    # image co y hong: them mot file .sql sai cu phap
    sh(["docker", "build", "-q", "-t", f"{IMG}:broken", "-f", "-", ROOT],
       input=f"FROM {IMG}:sandbox\nRUN printf 'CREATE TABLE loi_co_y ( khong dong ngoac' "
             f"> migrations/999_co_y_loi.sql\n")
    dc("down")  # xoa container, GIU volume (named) -> DB van da migrate
    k.check("app_khong_con_container_cu", state("app", tag="broken"), "ABSENT")
    up = dc("up", "app", tag="broken")
    k.check("migrate_exit_code_khac_0", exit_code("migrate", tag="broken"), 0, "!=")
    k.check("app_state_la_created_chua_tung_chay", state("app", tag="broken"), "created")
    k.check("app_KHONG_in_dong_khoi_dong", "APP DA START" in (up.stdout + up.stderr), False)
    k.check("ledger_khong_ghi_migration_loi",
            q("SELECT count(*)::text FROM schema_migrations WHERE version LIKE '999%'"), "0")
    return k


def kb4_concurrency() -> KichBan:
    k = KichBan("4_concurrency", "Hai runner dong thoi: KHONG ap cung migration hai lan")
    dc("up", "-d", "db")
    for _ in range(60):
        if dc("exec", "-T", "db", "pg_isready", "-h", "127.0.0.1", "-U", "alpha3s",
              "-d", "alpha3s", "-q").returncode == 0:
            break
        time.sleep(2)
    # tao lai dung 1 migration pending
    dc("run", "--rm", "--no-deps", "-T", "-v", f"{HOST_ROOT.rstrip(chr(47))}/scripts:/q", "migrate",
       "python", "-c",
       "import asyncio,asyncpg,os\n"
       "async def m():\n"
       "    c=await asyncpg.connect(os.environ['DATABASE_URL'])\n"
       "    await c.execute('DROP TABLE IF EXISTS m4_stage0p_transcript_signatures')\n"
       "    await c.execute('DROP TABLE IF EXISTS m4_stage0p_transcript_public_keys')\n"
       "    await c.execute(\"DELETE FROM schema_migrations WHERE version LIKE '044%'\")\n"
       "asyncio.run(m())")
    k.check("044_dang_pending_truoc_khi_dua",
            q("SELECT (NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version LIKE '044%'))::text"),
            "True")

    def chay() -> subprocess.CompletedProcess:
        return dc("run", "--rm", "--no-deps", "-T", "migrate", "python", "scripts/migrate.py", "up")

    with ThreadPoolExecutor(max_workers=2) as ex:
        r1, r2 = ex.submit(chay), ex.submit(chay)
        a, b = r1.result(), r2.result()
    rcs = sorted([a.returncode, b.returncode])
    outs = (a.stdout + a.stderr + b.stdout + b.stderr)
    k.check("dung_mot_runner_thanh_cong", rcs.count(0), 1)
    k.check("runner_con_lai_that_bai", rcs[1] != 0, True)
    k.check("co_thong_bao_advisory_lock", outs, "advisory lock", "chua")
    k.check("044_dung_MOT_hang_trong_ledger",
            q("SELECT count(*)::text FROM schema_migrations WHERE version LIKE '044%'"), "1")
    return k


def kb5_schema() -> KichBan:
    k = KichBan("5_schema_044_public_only", "Bang H2-A dung schema, KHONG co private material")
    k.check("cot_public_keys",
            q("SELECT string_agg(column_name, ',' ORDER BY ordinal_position) FROM information_schema.columns "
              "WHERE table_name='m4_stage0p_transcript_public_keys'"),
            "key_id,key_version,algorithm,public_key,created_at,retired_at")
    k.check("cot_signatures",
            q("SELECT string_agg(column_name, ',' ORDER BY ordinal_position) FROM information_schema.columns "
              "WHERE table_name='m4_stage0p_transcript_signatures'"),
            "sample_id,transcript,sig_alg,sig_key_id,sig_key_ver,signature,created_at")
    k.check("so_cot_private_secret_hmac",
            q("SELECT count(*)::text FROM information_schema.columns WHERE table_name IN "
              "('m4_stage0p_transcript_public_keys','m4_stage0p_transcript_signatures') "
              "AND column_name ~* 'private|secret|hmac'"), "0")
    k.check("so_hang_public_keys", q("SELECT count(*)::text FROM m4_stage0p_transcript_public_keys"), "0")
    k.check("so_hang_signatures", q("SELECT count(*)::text FROM m4_stage0p_transcript_signatures"), "0")
    k.check("ham_ghi_chu_ky_ton_tai",
            q("SELECT count(*)::text FROM pg_proc WHERE proname='m4_stage0p_record_transcript_signature'"), "1")
    k.check("so_trigger_bat_bien",
            q("SELECT count(*)::text FROM pg_trigger WHERE tgname LIKE 'trg_m4_h2a%'"), "2")
    return k


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default="migration_pipeline_ci_result.json")
    args = ap.parse_args()

    build = sh(["docker", "build", "-q", "-t", f"{IMG}:sandbox", "-f", DOCKERFILE, ROOT])
    if build.returncode != 0:
        print(f"KHONG build duoc image sandbox:\n{build.stderr}", file=sys.stderr)
        return 2

    ket_qua = []
    try:
        for f in (kb1_fresh, kb2_idempotent, kb3_that_bai, kb4_concurrency, kb5_schema):
            k = f()
            ket_qua.append(k)
            print(f"[{'DAT ' if k.dat else 'HONG'}] {k.ma}: {k.mo_ta}")
            for a in k.asserts:
                if not a["dat"]:
                    print(f"    HONG {a['ten']}: thuc_te={a['thuc_te']!r} "
                          f"{a['so_sanh']} ky_vong={a['ky_vong']!r}")
    finally:
        dc("down", "-v")
        sh(["docker", "rmi", "-f", f"{IMG}:broken"])

    head = sh(["git", "rev-parse", "HEAD"]).stdout.strip()
    bc = {
        "phien_ban": "migration-pipeline-ci-v1",
        "git_head": head,
        "so_file_migration": dem_file_migration(),
        "compose_file": os.path.relpath(COMPOSE, ROOT),
        "tat_ca_dat": all(k.dat for k in ket_qua),
        "so_kich_ban": len(ket_qua),
        "so_assert": sum(len(k.asserts) for k in ket_qua),
        "kich_ban": [k.to_dict() for k in ket_qua],
    }
    with open(args.json_out, "w", encoding="utf-8") as fh:
        json.dump(bc, fh, ensure_ascii=False, sort_keys=True, indent=2)
    print(json.dumps({k: bc[k] for k in ("git_head", "tat_ca_dat", "so_kich_ban", "so_assert")},
                     ensure_ascii=False))
    return 0 if bc["tat_ca_dat"] else 1


if __name__ == "__main__":
    sys.exit(main())
