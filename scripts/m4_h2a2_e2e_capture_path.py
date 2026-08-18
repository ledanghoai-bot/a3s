#!/usr/bin/env python
"""I-B M4 H2-A-2 (F-H2A2-02) — E2E sandbox cho DUONG THAT ma PR #27 vua noi.

VI SAO SCRIPT NAY TON TAI
CA doc PR #27 va ket luan dung: 10 test contract/fail-closed chi chung minh HOP DONG giua client
va service, khong chung minh duong THAT SU chay duoc tu dau den cuoi. Nguyen van yeu cau (CA
PHASE1B-M4-H2A2-PR27-SUBSTANTIVE-REVIEW-1-VI, F-H2A2-02):

  1. signing service THAT -> giao thuc unix socket THAT -> collector/fenced unit THAT -> ham cua
     migration 044, tren mot DB dung mot lan;
  2. duong thanh cong luu transcript + chu ky Ed25519 + sig_alg + key_id + key_ver, va verifier
     NGOAI DB dung public key registry verify DAT tren dung transcript da luu;
  3. tamper transcript hoac chu ky -> verify NGOAI DB that bai;
  4. backend loi hoac thieu the asym -> fenced unit KHONG commit sample, KHONG de lai
     transcript-signature orphan;
  5. mutation proof: pha mot diem cua duong that -> test tuong ung phai DO.

Script nay chay ca 5, moi kich ban deu goi CODE THAT (stage0p_sampling.run_collector,
stage0p_signing_service chay nhu MOT TIEN TRINH RIENG, m4_stage0p_verify_transcripts.py chay nhu
MOT TIEN TRINH RIENG). KHONG doan nao tai tao lai logic roi tu kiem chinh no — do dung la lop loi
ma ban test dau tien cua H2-A-2 mac phai.

RANH GIOI (directive H2-A/H2-A-2 van hieu luc)
  * CHI SANDBOX. LocalDevBackend tu tu choi neu APP_ENV la production/staging.
  * KHONG provision KMS, KHONG tao secret/PIN production, KHONG cham DB production.
  * DB dung mot lan: tro DATABASE_URL vao mot DB rac (script xoa du lieu cu truoc khi chay).

CACH CHAY (trong container sandbox, DB rac rieng) — xem docs/M4-H2A2-E2E-SANDBOX-VI.md.

EXIT CODE
    0  moi kich ban dat
    1  co kich ban khong dat  <- fail-closed cho CI
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402
from _stage0p_signing_service_helper import (  # noqa: E402
    start_signing_service,
    stop_signing_service,
)

from app.config import settings  # noqa: E402
from app.services.pii import stage0p_sampling as s  # noqa: E402
from app.services.pii.crypto import TRANSCRIPT_KEY_VERSION  # noqa: E402
from app.services.pii.signing_backend import LocalDevBackend  # noqa: E402
from app.services.pii.stage0p_control import (  # noqa: E402
    pin_actor,
    record_capture_approval,
    set_capture_enabled,
)

DB_URL = (os.environ.get("DATABASE_URL")
          or "postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/m4_h2a2_e2e").replace("+asyncpg", "")
REDIS_URL = os.environ.get("REDIS_URL") or "redis://alpha3s-m4-redis:6379/0"
VERIFIER = str(ROOT / "scripts" / "m4_stage0p_verify_transcripts.py")

PIN_SECRET = "h2a2-e2e-pin-secret"
STAFF_USERNAME = "m4-h2a2-e2e-staff"
SIG_TABLE = "m4_stage0p_transcript_signatures"

_fail: list[str] = []


def check(cond: bool, label: str) -> bool:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)
    return bool(cond)


# ===========================================================================
# Ha tang sandbox
# ===========================================================================
async def _pin(conn, staff_id: int) -> None:
    await conn.execute("SET ROLE alpha3s_m4_actor_binder")
    await pin_actor(conn, staff_id=staff_id, pin_secret=PIN_SECRET)
    await conn.execute("RESET ROLE")


async def _don_dep(admin) -> None:
    """Xoa du lieu cua LAN CHAY TRUOC. Chi dung tren DB rac."""
    for tbl in (SIG_TABLE, "m4_shadow_review_samples", "m4_stage0p_capture_progress",
                "m4_selection_batches", "audit_log", "messages", "orders", "conversations",
                "customers"):
        await admin.execute("DELETE FROM " + tbl)
    await admin.execute("UPDATE m4_stage0p_control SET capture_enabled=false WHERE id=1")
    await admin.execute(
        "DELETE FROM m4_stage0p_capture_approvals WHERE approval_ref LIKE 'H2A2-%'")
    for tbl in ("m4_stage0p_staff_permissions", "m4_stage0p_actor_session",
                "m4_stage0p_actor_credentials"):
        await admin.execute(
            "DELETE FROM " + tbl + " WHERE staff_id IN "
            "(SELECT id FROM staff_users WHERE username=$1)", STAFF_USERNAME)
    await admin.execute("DELETE FROM staff_users WHERE username=$1", STAFF_USERNAME)
    # Registry public key la bang BAT BIEN (trigger chan UPDATE/DELETE) — phai tat trigger moi don
    # duoc. Chi lam duoc voi quyen chu bang tren DB rac; chinh kha nang do la mot phan cua bang
    # chung [S2]: DBA sua duoc DB nhung van khong gia mao duoc chu ky.
    await admin.execute("ALTER TABLE m4_stage0p_transcript_public_keys DISABLE TRIGGER "
                        "trg_m4_h2a_public_keys_immutable")
    await admin.execute("DELETE FROM m4_stage0p_transcript_public_keys")
    await admin.execute("ALTER TABLE m4_stage0p_transcript_public_keys ENABLE TRIGGER "
                        "trg_m4_h2a_public_keys_immutable")


async def _fixture_hoi_thoai(admin, psid: str, so_tin: int) -> tuple[int, int]:
    """1 khach + 1 don hang (dieu kien eligibility) + 1 hoi thoai + N tin nhan cua khach."""
    cust = await admin.fetchrow(
        "INSERT INTO customers (psid,name) VALUES ($1,'khach sandbox') RETURNING id", psid)
    conv = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id",
        cust["id"])
    await admin.execute("INSERT INTO orders (customer_id, created_at) VALUES ($1, now())",
                        cust["id"])
    for i in range(so_tin):
        await admin.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer',$2)",
            conv["id"], "tin nhan sandbox so " + str(i) + " — noi dung gia lap")
    return cust["id"], conv["id"]


async def _khoa_batch(admin, conversation_id: int) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return await s.lock_batch(
        admin, window_start=now - datetime.timedelta(days=14), window_end=now,
        eligible_count=1, selected=[{"conversation_id": conversation_id}])


async def _bat_capture(admin, ref: str) -> tuple[int, asyncpg.Connection]:
    """Bat capture qua DUNG duong control-plane that: PIN -> approval -> set_capture_enabled.

    Moi kich ban dung mot `ref` approval RIENG: approval la ban ghi co thoi han/ly do rieng, dung
    lai ref cua kich ban truoc se lam audit trail doc sai ("ai cho phep cai gi").
    """
    staff = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ($1,'x','x',true) ON CONFLICT (username) DO UPDATE SET is_active=true "
        "RETURNING id", STAFF_USERNAME)
    for perm in ("m4.stage0p.approve", "m4.stage0p.operate"):
        await admin.execute(
            "INSERT INTO m4_stage0p_staff_permissions (staff_id, permission, granted_by) "
            "VALUES ($1,$2,$1) ON CONFLICT DO NOTHING", staff["id"], perm)
    await admin.execute(
        "INSERT INTO m4_stage0p_actor_credentials (staff_id, pin_secret_hash, provisioned_by) "
        "VALUES ($1, crypt($2, gen_salt('bf')), $1) ON CONFLICT (staff_id) DO UPDATE SET "
        "pin_secret_hash=crypt($2, gen_salt('bf')), failed_attempts=0, locked_until=NULL",
        staff["id"], PIN_SECRET)

    now = datetime.datetime.now(datetime.timezone.utc)
    ap = await asyncpg.connect(DB_URL)
    await _pin(ap, staff["id"])
    await ap.execute("SET ROLE alpha3s_m4_approval_recorder")
    await record_capture_approval(ap, approval_ref=ref, requested_enabled=True,
                                  valid_from=now - datetime.timedelta(hours=1),
                                  valid_until=now + datetime.timedelta(hours=1))
    await ap.execute("RESET ROLE")
    await ap.close()

    cp = await asyncpg.connect(DB_URL)
    await _pin(cp, staff["id"])
    await cp.execute("SET ROLE alpha3s_m4_control_plane")
    await set_capture_enabled(cp, enabled=True, approval_ref=ref)
    return staff["id"], cp


async def _tat_capture(cp, staff_id: int, ref: str) -> None:
    await _pin(cp, staff_id)
    await cp.execute("SET ROLE alpha3s_m4_control_plane")
    await set_capture_enabled(cp, enabled=False, approval_ref=ref + "-OFF")
    await cp.execute("RESET ROLE")


async def _chay_collector(batch_id) -> dict:
    """Goi run_collector THAT, voi 2 role that (collector/pending-checker) nhu production."""
    col = await asyncpg.connect(DB_URL)
    await col.execute("SET ROLE alpha3s_m4_sample_collector")
    pend = await asyncpg.connect(DB_URL)
    await pend.execute("SET ROLE alpha3s_m4_pending_checker")
    try:
        return await s.run_collector(col, pend, batch_id=batch_id)
    finally:
        await col.close()
        await pend.close()


# ===========================================================================
# Signer that + registry public key + verifier ngoai DB
# ===========================================================================
# Seed sandbox co dinh: harness can BIET TRUOC public key de provision registry (migration 044 doi
# hang khoa co san TRUOC khi ghi chu ky). Voi KMS that, buoc nay la "doc public key tu API cua
# KMS"; sandbox khong co KMS nen seed dong vai tro do. Private material van CHI song trong tien
# trinh signer khi ky — moi chu ky trong kich ban nay deu do signer that tao ra.
KEY_SEED_B64 = base64.b64encode(hashlib.sha256(b"m4-h2a2-e2e-sandbox").digest()).decode("ascii")


def _dat_moi_truong_signer(backend: str | None) -> None:
    """Chuan bi moi truong ma TIEN TRINH SIGNER se ke thua (start_signing_service copy os.environ).

    backend=None mo phong dung kich ban F-H2A2-01: bien M4_SIGNING_BACKEND KHONG duoc dat (deploy
    dormant). Signer van khoi dong duoc, nhung moi request ky PHAI fail-closed.
    """
    os.environ["APP_ENV"] = "sandbox"
    os.environ["M4_ALLOW_LOCALDEV_SIGNING"] = "1"
    os.environ["M4_LOCALDEV_SIGNING_SEED_B64"] = KEY_SEED_B64
    os.environ["REDIS_URL"] = REDIS_URL
    if backend is None:
        os.environ.pop("M4_SIGNING_BACKEND", None)
    else:
        os.environ["M4_SIGNING_BACKEND"] = backend


async def _khoi_dong_signer(admin, socket_path: str, *, backend: str | None = "localdev"):
    """Spawn TIEN TRINH signer that (python -m app.services.pii.stage0p_signing_service).

    Tra ve process. Ba khoa doi xung (sample/HMAC transcript/signing-auth) do chinh helper sinh va
    CHI nam trong moi truong cua tien trinh con; script nay (dong vai collector) khong giu chung
    trong settings cua no.
    """
    _dat_moi_truong_signer(backend)
    proc, _sample_key, hmac_key, auth_key = await start_signing_service(
        socket_path=socket_path, allowed_uid=os.getuid())
    await admin.execute(
        "INSERT INTO m4_stage0p_transcript_signing_keys (key_version, hmac_key) VALUES ($1,$2) "
        "ON CONFLICT (key_version) DO UPDATE SET hmac_key=EXCLUDED.hmac_key, retired_at=NULL",
        TRANSCRIPT_KEY_VERSION, hmac_key)
    await admin.execute(
        "INSERT INTO m4_stage0p_signing_auth_keys (key_version, hmac_key) VALUES ($1,$2) "
        "ON CONFLICT (key_version) DO UPDATE SET hmac_key=EXCLUDED.hmac_key, retired_at=NULL",
        "m4-signing-auth-v1", auth_key)
    settings.m4_stage0p_signing_socket = socket_path
    return proc


async def _cong_bo_public_key(admin) -> tuple[str, str]:
    """Cong bo PUBLIC key cua signer vao registry (buoc van hanh, khong phai buoc ky).

    Tra ve (key_id, key_version). Chi PUBLIC material di vao DB — dung nhu thiet ke 044.
    """
    b = LocalDevBackend(app_env="sandbox")
    await admin.execute(
        "INSERT INTO m4_stage0p_transcript_public_keys (key_id,key_version,algorithm,public_key) "
        "VALUES ($1,$2,'Ed25519',$3) ON CONFLICT DO NOTHING",
        b.key_id(), b.key_version(), b.public_key_raw())
    return b.key_id(), b.key_version()


async def _chay_verifier(batch: str | None = None) -> tuple[int, dict]:
    """Chay verifier NHU MOT TIEN TRINH RIENG, voi moi truong TOI THIEU.

    Moi truong truyen vao chi co PATH + DATABASE_URL: khong secret nao, khong bien M4_* nao. Do la
    dieu H2 phai chung minh — nguoi verify khong can giu bat ky bi mat nao.
    """
    env = {"PATH": os.environ.get("PATH", ""), "DATABASE_URL": DB_URL}
    args = [sys.executable, VERIFIER, "--json"]
    if batch:
        args += ["--batch", str(batch)]
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=str(ROOT), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode == 2:
        raise RuntimeError("verifier loi van hanh: " + err.decode(errors="replace")[:400])
    return proc.returncode, json.loads(out.decode("utf-8"))


async def _sua_lieu_cap_dba(admin, sample_id, *, transcript=None, signature=None) -> None:
    """Sua thang bang chu ky O CAP DBA — phai TAT trigger bat bien moi lam duoc.

    Day la mo hinh de doa dung cua H2: ke tan cong/DBA co toan quyen tren DB. Ho sua duoc BANG,
    nhung khong ky lai duoc bang khoa rieng (khoa do chua bao gio nam trong DB), nen verifier ngoai
    DB van phat hien.
    """
    await admin.execute("ALTER TABLE " + SIG_TABLE + " DISABLE TRIGGER "
                        "trg_m4_h2a_signatures_immutable")
    try:
        if transcript is not None:
            await admin.execute(
                "UPDATE " + SIG_TABLE + " SET transcript=$1 WHERE sample_id=$2",
                transcript, sample_id)
        if signature is not None:
            await admin.execute(
                "UPDATE " + SIG_TABLE + " SET signature=$1 WHERE sample_id=$2",
                signature, sample_id)
    finally:
        await admin.execute("ALTER TABLE " + SIG_TABLE + " ENABLE TRIGGER "
                            "trg_m4_h2a_signatures_immutable")


# ===========================================================================
# [S1] Duong that: signer -> socket -> fenced unit -> 044 -> verifier ngoai DB
# ===========================================================================
async def _s1_duong_that(admin, key_id: str, key_ver: str) -> tuple[str, list]:
    print("== [S1] duong that: ky -> ghi -> verify ngoai DB ==")
    _cust, conv = await _fixture_hoi_thoai(admin, "h2a2-s1", 3)
    batch = await _khoa_batch(admin, conv)
    staff_id, cp = await _bat_capture(admin, "H2A2-S1")
    try:
        kq = await _chay_collector(batch)
    finally:
        await _tat_capture(cp, staff_id, "H2A2-S1")
        await cp.close()

    check(kq["inserted"] == 3, "collector ghi du 3 sample (thuc te " + str(kq["inserted"]) + ")")

    rows = await admin.fetch(
        "SELECT r.sample_id, r.canonical_text_len, g.transcript, g.sig_alg, g.sig_key_id, "
        "       g.sig_key_ver, octet_length(g.signature) AS sig_len "
        "  FROM m4_shadow_review_samples r "
        "  LEFT JOIN " + SIG_TABLE + " g ON g.sample_id = r.sample_id "
        " WHERE r.selection_batch = $1 ORDER BY r.captured_at", batch)
    check(len(rows) == 3, "co dung 3 sample trong batch")
    co_du_chu_ky = all(r["transcript"] is not None for r in rows)
    check(co_du_chu_ky, "MOI sample deu co hang chu ky asym (khong sample nao thieu bang chung)")
    if not co_du_chu_ky:
        return batch, rows

    check(all(r["sig_alg"] == "Ed25519" for r in rows), "sig_alg = Ed25519 tren ca 3 hang")
    check(all(r["sig_key_id"] == key_id for r in rows),
          "sig_key_id khop khoa signer da cong bo: " + key_id)
    check(all(r["sig_key_ver"] == key_ver for r in rows), "sig_key_ver khop: " + key_ver)
    check(all(r["sig_len"] == 64 for r in rows), "chu ky dung 64 byte tren ca 3 hang")

    # Transcript da luu phai NOI VE dung sample do (khong phai mot transcript bat ky ky hop le).
    khop_noi_dung = True
    for r in rows:
        t = json.loads(bytes(r["transcript"]).decode("utf-8"))
        if t.get("sample_id") != str(r["sample_id"]) or t.get("canonical_len") != r["canonical_text_len"]:
            khop_noi_dung = False
    check(khop_noi_dung,
          "transcript tu khai dung sample_id va canonical_len khop hang sample da luu")

    rc, bc = await _chay_verifier(batch)
    check(rc == 0, "verifier NGOAI DB (tien trinh rieng, khong secret) tra exit 0")
    check(bc["tong_chu_ky"] == 3, "verifier doc dung 3 chu ky (thuc te " + str(bc["tong_chu_ky"]) + ")")
    check(bc["hong"] == 0, "verifier: 0 chu ky hong")
    check(list(bc["theo_key_version"]) == [key_id + "@" + key_ver],
          "verifier cong bo dung key-id@key-version: " + str(list(bc["theo_key_version"])))
    return batch, rows


# ===========================================================================
# [S2] Tamper -> verifier ngoai DB phat hien
# ===========================================================================
async def _s2_tamper(admin, batch: str, rows: list) -> None:
    print("== [S2] tamper transcript / chu ky -> verify NGOAI DB phai that bai ==")
    nan_nhan = rows[-1]
    goc_transcript = bytes(nan_nhan["transcript"])
    goc_sig = await admin.fetchval(
        "SELECT signature FROM " + SIG_TABLE + " WHERE sample_id=$1", nan_nhan["sample_id"])

    # (a) doi NOI DUNG transcript nhung giu JSON hop le — de phep thu cham vao KIEM TRA MAT MA,
    # khong phai cham vao loi parse.
    t = json.loads(goc_transcript.decode("utf-8"))
    t["canonical_len"] = int(t.get("canonical_len", 0)) + 1
    gia_mao = json.dumps(t, sort_keys=True, separators=(",", ":")).encode("utf-8")
    await _sua_lieu_cap_dba(admin, nan_nhan["sample_id"], transcript=gia_mao)
    rc, bc = await _chay_verifier(batch)
    check(rc == 1, "transcript bi sua -> verifier exit 1")
    check(bc["hong"] == 1 and bc["dat"] == 2, "dung 1 hang hong, 2 hang con lai van dat")
    ly_do = (bc["chi_tiet_hong"] or [{}])[0].get("ly_do", "")
    check("CHU KY KHONG HOP LE" in ly_do, "ly do dung la chu ky khong hop le: " + ly_do)

    await _sua_lieu_cap_dba(admin, nan_nhan["sample_id"], transcript=goc_transcript)
    rc, bc = await _chay_verifier(batch)
    check(rc == 0 and bc["hong"] == 0, "khoi phuc transcript goc -> verifier lai dat (xac dinh)")

    # (b) doi CHU KY, giu nguyen transcript.
    sig_gia = bytes(goc_sig)
    sig_gia = sig_gia[:-1] + bytes([sig_gia[-1] ^ 0x01])
    await _sua_lieu_cap_dba(admin, nan_nhan["sample_id"], signature=sig_gia)
    rc, bc = await _chay_verifier(batch)
    check(rc == 1 and bc["hong"] == 1, "chu ky bi lat 1 bit -> verifier exit 1")

    await _sua_lieu_cap_dba(admin, nan_nhan["sample_id"], signature=bytes(goc_sig))
    rc, bc = await _chay_verifier(batch)
    check(rc == 0 and bc["hong"] == 0, "khoi phuc chu ky goc -> verifier lai dat")


async def _dem_toan_cuc(admin) -> tuple[int, int]:
    return (await admin.fetchval("SELECT count(*) FROM m4_shadow_review_samples"),
            await admin.fetchval("SELECT count(*) FROM " + SIG_TABLE))


async def _kich_ban_fail_closed(admin, ten: str, psid: str, *, mong_doi: str) -> None:
    """Chay mot batch trong dieu kien duong ky HONG, roi kiem: khong sample, khong orphan.

    Dung CHUNG cho [S3] (backend hong) va [S4] (khoa bi thu hoi o registry) vi dieu can chung minh
    la MOT: neu bat ky manh nao cua bang chung khong ghi duoc thi sample cung KHONG duoc commit.
    """
    sample_truoc, sig_truoc = await _dem_toan_cuc(admin)
    _cust, conv = await _fixture_hoi_thoai(admin, psid, 2)
    batch = await _khoa_batch(admin, conv)
    staff_id, cp = await _bat_capture(admin, "H2A2-" + ten.strip("[]"))
    loi = None
    try:
        kq = await _chay_collector(batch)
    except Exception as exc:  # noqa: BLE001 — bat de KIEM, khong de nuot
        loi = exc
        kq = None
    finally:
        await _tat_capture(cp, staff_id, "H2A2-" + ten.strip("[]"))
        await cp.close()

    check(loi is not None or (kq or {}).get("inserted") == 0,
          ten + ": collector KHONG ghi duoc sample nao (loi=" + type(loi).__name__ + ")")
    if loi is not None:
        print("         loi that: " + type(loi).__name__ + ": " + str(loi)[:160])

    trong_batch = await admin.fetchval(
        "SELECT count(*) FROM m4_shadow_review_samples WHERE selection_batch=$1", batch)
    check(trong_batch == 0, ten + ": 0 sample duoc commit trong batch nay")

    sample_sau, sig_sau = await _dem_toan_cuc(admin)
    check(sample_sau == sample_truoc, ten + ": tong so sample toan cuc khong doi")
    check(sig_sau == sig_truoc, ten + ": tong so hang chu ky khong doi (khong co orphan)")

    orphan = await admin.fetchval(
        "SELECT count(*) FROM " + SIG_TABLE + " g LEFT JOIN m4_shadow_review_samples r "
        "ON r.sample_id=g.sample_id WHERE r.sample_id IS NULL")
    check(orphan == 0, ten + ": khong hang chu ky nao mo coi (khong tro toi sample nao)")
    print("         (" + mong_doi + ")")


# ===========================================================================
# [S3] Backend ky hong -> khong sample, khong orphan
# [S4] Bang chung khong ghi duoc (khoa thu hoi) -> sample cung KHONG duoc commit
# ===========================================================================
async def _s3_backend_hong(admin, socket_path: str) -> None:
    """CA F-H2A2-01 bang chung #2: THU khoi dong signer khi backend unset/khong hop le.

    Hai nua cua mot doi: Compose parse duoc khi dormant (bang chung rieng, khong dung DB), nhung
    SIGNER thi phai tu choi khoi dong. O day ta thu THAT: spawn tien trinh signer that va doc exit
    code + thong diep cua chinh no.
    """
    print("== [S3] backend ky HONG -> signer tu choi KHOI DONG, capture khong ghi gi ==")
    for nhan, gia_tri in (("unset", None), ("gia tri la 'hmac'", "hmac")):
        loi = None
        try:
            proc = await _khoi_dong_signer(admin, socket_path, backend=gia_tri)
            await stop_signing_service(proc, socket_path)
        except RuntimeError as exc:
            loi = exc
        check(loi is not None, "[S3] " + nhan + ": signer KHONG khoi dong duoc")
        if loi is not None:
            thong_diep = str(loi)
            check("M4_SIGNING_BACKEND" in thong_diep,
                  "[S3] " + nhan + ": thong diep noi ro bien cau hinh nao sai")
            check("exit=2" in thong_diep, "[S3] " + nhan + ": exit code 2 (tu choi khoi dong)")
            print("         signer noi: " + thong_diep.strip().splitlines()[-1][:150])

    # Khong co signer -> chay capture that: van khong duoc phep ghi bat ky sample nao.
    settings.m4_stage0p_signing_socket = socket_path
    await _kich_ban_fail_closed(
        admin, "[S3]", "h2a2-s3",
        mong_doi="signer khong ton tai -> capture khong the ghi sample thieu bang chung")


async def _s4_khoa_thu_hoi(admin, socket_path: str, key_id: str, key_ver: str) -> None:
    print("== [S4] ghi chu ky that bai (khoa bi thu hoi) -> sample KHONG duoc commit ==")
    proc = await _khoi_dong_signer(admin, socket_path, backend="localdev")
    try:
        await admin.execute(
            "UPDATE m4_stage0p_transcript_public_keys SET retired_at=now() "
            " WHERE key_id=$1 AND key_version=$2", key_id, key_ver)
        await _kich_ban_fail_closed(
            admin, "[S4]", "h2a2-s4",
            mong_doi="signer ky duoc, nhung 044 tu choi ghi -> ca fenced unit cuon lai")
    finally:
        await stop_signing_service(proc, socket_path)


# ===========================================================================
# [S5] Chu ky cu VAN verify duoc sau khi khoa bi thu hoi
# ===========================================================================
async def _s5_sau_thu_hoi(batch: str) -> None:
    print("== [S5] sau khi thu hoi khoa: chu ky ky TRUOC do van phai verify duoc ==")
    rc, bc = await _chay_verifier(batch)
    check(rc == 0 and bc["hong"] == 0 and bc["tong_chu_ky"] == 3,
          "3 chu ky cu van dat sau khi khoa bi thu hoi (thu hoi khong xoa qua khu)")


# ===========================================================================
# Dieu phoi
# ===========================================================================
async def _chay_tat_ca() -> int:
    settings.database_url = DB_URL
    settings.redis_url = REDIS_URL
    socket_path = "/tmp/m4-h2a2-e2e-" + str(os.getpid()) + "/sock"

    admin = await asyncpg.connect(DB_URL)
    proc = None
    try:
        await _don_dep(admin)
        proc = await _khoi_dong_signer(admin, socket_path, backend="localdev")
        key_id, key_ver = await _cong_bo_public_key(admin)
        print("signer that: PID " + str(proc.pid) + ", socket " + socket_path)
        print("khoa cong bo trong registry: " + key_id + "@" + key_ver + " (chi PUBLIC material)")

        batch, rows = await _s1_duong_that(admin, key_id, key_ver)
        if rows and rows[0]["transcript"] is not None:
            await _s2_tamper(admin, batch, rows)
        else:
            check(False, "[S2] bi bo qua vi [S1] khong tao duoc chu ky nao")
    finally:
        if proc is not None:
            await stop_signing_service(proc, socket_path)

    try:
        await _s3_backend_hong(admin, socket_path)
        await _s4_khoa_thu_hoi(admin, socket_path, key_id, key_ver)
        await _s5_sau_thu_hoi(batch)
    finally:
        await admin.close()

    print("")
    if _fail:
        print("KHONG DAT (" + str(len(_fail)) + "):")
        for f in _fail:
            print("  - " + f)
        return 1
    print("TAT CA KICH BAN DAT.")
    return 0


# ===========================================================================
# Bang chung MUTATION — pha mot diem cua duong THAT, doi kich ban phai DO
# ===========================================================================
# Moi muc: (duong dan file THAT, doan can thay, doan thay the, kich ban du kien do).
# Khong mutation nao dung vao test/harness — tat ca deu va vao code chay production path, dung
# yeu cau cua CA ("khong chap nhan test chi inspect source/reimplement code").
MUTATIONS = {
    "bo-ghi-chu-ky-xuong-db": (
        "app/services/pii/stage0p_sampling.py",
        '        await collector_conn.execute(\n'
        '            "SELECT m4_stage0p_record_transcript_signature($1,$2,$3,$4,$5,$6)",',
        '        if False:  # MUTATION: bo hoan toan buoc ghi chu ky asym\n'
        '            await collector_conn.execute(\n'
        '            "SELECT m4_stage0p_record_transcript_signature($1,$2,$3,$4,$5,$6)",',
        "[S1] moi sample deu co hang chu ky asym"),
    "ky-nham-chuoi-byte": (
        "app/services/pii/stage0p_signing_service.py",
        "    signature_asym = backend.sign(transcript_bytes)",
        '    signature_asym = backend.sign(transcript_bytes + b"x")  # MUTATION: ky khac transcript',
        "[S1] verifier ngoai DB phat hien chu ky khong khop transcript da luu"),
}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _chay_mutation_proof() -> int:
    """Va source THAT, chay lai toan bo kich ban, doi exit != 0, roi HOAN NGUYEN va doi chieu sha256.

    Hoan nguyen nam trong `finally` va duoc XAC MINH bang sha256 — mot lan chay do dang cung khong
    duoc de lai source da bi va.
    """
    tong_loi = 0
    for ten, (rel, cu, moi, kich_ban) in MUTATIONS.items():
        path = ROOT / rel
        # Doc/ghi BINARY, khong qua che do text: tren may dev Windows (core.autocrlf) file tren dia
        # co the la CRLF, va mot vong read_text/write_text se am tham doi het xuong LF — hoan
        # nguyen kieu do KHONG con la hoan nguyen. sha256 o duoi la cho de bat dung viec nay.
        goc = path.read_bytes()
        sha_truoc = _sha256_file(path)
        print("")
        print("=== MUTATION: " + ten + " (" + rel + ") ===")
        print("  sha256 truoc : " + sha_truoc)
        cu_b, moi_b = cu.encode("utf-8"), moi.encode("utf-8")
        # Cac may dev Windows cua du an nay dung core.autocrlf, nen file TREN DIA co the la CRLF
        # trong khi doan mau o day viet bang LF. Dich mau theo dung EOL cua file thay vi dich file
        # theo mau — doi chieu sha256 o duoi chi con y nghia neu ta khong bao gio ghi de EOL.
        eol_crlf = bytes([13, 10])
        if eol_crlf in goc:
            cu_b = cu_b.replace(bytes([10]), eol_crlf)
            moi_b = moi_b.replace(bytes([10]), eol_crlf)
        if goc.count(cu_b) != 1:
            print("  KHONG AP DUNG DUOC: doan can va xuat hien " + str(goc.count(cu_b)) + " lan "
                  "(code da doi -> phai cap nhat mutation nay truoc khi tin ket qua)")
            tong_loi += 1
            continue
        try:
            path.write_bytes(goc.replace(cu_b, moi_b))
            print("  sha256 sau va : " + _sha256_file(path))
            r = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                               cwd=str(ROOT), env=os.environ.copy(),
                               capture_output=True, text=True)
            print("  exit code khi va: " + str(r.returncode))
            for dong in r.stdout.splitlines():
                if dong.startswith("  FAIL") or dong.startswith("KHONG DAT"):
                    print("    " + dong.strip())
            if r.returncode == 0:
                print("  KET LUAN: HONG — va duong that ma kich ban VAN XANH. Kich ban khong gac "
                      "duoc hoi quy: " + kich_ban)
                tong_loi += 1
            else:
                print("  KET LUAN: DAT — kich ban DO dung nhu mong doi (" + kich_ban + ")")
        finally:
            path.write_bytes(goc)
            sha_sau = _sha256_file(path)
            print("  sha256 sau khi hoan nguyen: " + sha_sau)
            if sha_sau != sha_truoc:
                print("  CANH BAO: hoan nguyen KHONG khop sha256 goc")
                tong_loi += 1
    print("")
    if tong_loi:
        print("MUTATION PROOF KHONG DAT: " + str(tong_loi) + " van de.")
        return 1
    print("MUTATION PROOF DAT: moi mutation deu lam kich ban tuong ung DO.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="E2E sandbox H2-A-2 (F-H2A2-02) — CHI SANDBOX.")
    p.add_argument("--mutation-proof", action="store_true",
                   help="va source that de chung minh kich ban gac duoc hoi quy, roi hoan nguyen")
    args = p.parse_args()
    if args.mutation_proof:
        return _chay_mutation_proof()
    return asyncio.run(_chay_tat_ca())


if __name__ == "__main__":
    sys.exit(main())
