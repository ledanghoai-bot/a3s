#!/usr/bin/env python
"""I-B M4 H2 — E2E sandbox cho capture path chay bang BACKEND KMS THAT (Vault Transit).

DAP DELIVERABLE 3 CUA `PHASE1B-M4-H2-KMS-SANDBOX-ADAPTER-PREPARATION-DIRECTIVE-VI`:
signing process rieng, verify public key ngoai DB, va ba che do hong — unavailable /
unauthorized / revoked-key — deu KHONG duoc commit sample; rotation phai giu verify duoc
chu ky lich su.

VI SAO DUNG VAULT THAT CHU KHONG PHAI FAKE TRANSPORT
Directive cho phep chon mot trong hai. Chon Vault vi ba che do hong o tren tro thanh phep thu
VAT LY chu khong phai gia lap: TAT container (unavailable), DOI token (unauthorized), VO HIEU
phien ban khoa (revoked). Mot fake transport chi chung minh duoc rang ta biet nem dung ngoai le
cua chinh minh.

QUAN HE VOI KICH BAN H2-A-2
Kich ban nay dung LAI toan bo ha tang cua `m4_h2a2_e2e_capture_path.py` (fixture, control-plane,
collector, verifier) — chi thay backend ky. Nho vay khac biet duy nhat giua hai lan chay la
BACKEND, khong phai harness, nen ket qua so sanh duoc.

KHAC BIET DANG CHU Y: kich ban nay KHONG dung `M4_LOCALDEV_SIGNING_SEED_B64`. Public key duoc lay
qua duong VAN HANH that (`scripts/m4_publish_transcript_public_key.py`), dung nhu production se lam
voi managed KMS.

CHI SANDBOX. Khong provision KMS/cloud, khong cham production. Vault o day la sandbox voi khoa THU.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import asyncpg  # noqa: E402
import httpx  # noqa: E402
from _stage0p_signing_service_helper import (  # noqa: E402
    start_signing_service,
    stop_signing_service,
)

# Dung lai NGUYEN VEN ha tang da duoc CA chap nhan o F-H2A2-02.
from m4_h2a2_e2e_capture_path import (  # noqa: E402
    DB_URL,
    REDIS_URL,
    _bat_capture,
    _chay_collector,
    _chay_verifier,
    _dem_toan_cuc,
    _don_dep,
    _fixture_hoi_thoai,
    _khoa_batch,
    _tat_capture,
    check,
)
from m4_h2a2_e2e_capture_path import _fail as _fail_chung  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.pii.crypto import TRANSCRIPT_KEY_VERSION  # noqa: E402

VAULT_ADDR = os.environ.get("M4_VAULT_ADDR", "http://a3s-vault-sandbox:8200")
VAULT_TOKEN = os.environ.get("M4_VAULT_TOKEN", "sandbox-root-token")
VAULT_CONTAINER = os.environ.get("M4_VAULT_CONTAINER", "a3s-vault-sandbox")
KEY_ID = os.environ.get("M4_KMS_KEY_ID", "m4-e2e-key")


def _vault_admin(method: str, duong_dan: str, payload: dict | None = None) -> int:
    """Thao tac QUAN TRI Vault qua HTTP — dong vai NGUOI VAN HANH, khong phai signer.

    Co y tach hai duong: signer chi duoc `sign`/`public_key` qua `KmsTransport`; con tao khoa,
    rotate, vo hieu phien ban di duong admin rieng nay. Do dung la phan cong quyen se ap o
    production, va cung la ly do phep thu "signer khong export duoc khoa" co y nghia.

    Dung HTTP chu khong dung CLI vi kich ban chay BEN TRONG container ung dung — noi khong co (va
    khong nen co) docker CLI hay quyen dieu khien container khac.
    """
    r = httpx.request(method, f"{VAULT_ADDR}/v1/{duong_dan}",
                      headers={"X-Vault-Token": VAULT_TOKEN}, json=payload, timeout=10.0)
    return r.status_code


def _moi_truong_signer(*, token: str = VAULT_TOKEN, key_version: str = "1",
                       addr: str = VAULT_ADDR) -> None:
    os.environ["APP_ENV"] = "sandbox"
    os.environ["REDIS_URL"] = REDIS_URL
    os.environ["M4_SIGNING_BACKEND"] = "kms"
    os.environ["M4_KMS_TRANSPORT"] = "vault"
    os.environ["M4_KMS_KEY_ID"] = KEY_ID
    os.environ["M4_KMS_KEY_VERSION"] = key_version
    os.environ["M4_VAULT_ADDR"] = addr
    os.environ["M4_VAULT_TOKEN"] = token
    os.environ.pop("M4_LOCALDEV_SIGNING_SEED_B64", None)
    os.environ.pop("M4_ALLOW_LOCALDEV_SIGNING", None)


async def _khoi_dong(admin, socket_path: str):
    proc, _sk, hmac_key, auth_key = await start_signing_service(
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


def _cong_bo_public_key(key_version: str) -> int:
    """Chay CHINH script van hanh — khong tai tao logic cong bo trong test."""
    env = os.environ.copy()
    env.update({"DATABASE_URL": DB_URL, "M4_KMS_TRANSPORT": "vault", "M4_KMS_KEY_ID": KEY_ID,
                "M4_KMS_KEY_VERSION": key_version, "M4_VAULT_ADDR": VAULT_ADDR,
                "M4_VAULT_TOKEN": VAULT_TOKEN})
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "m4_publish_transcript_public_key.py")],
                       cwd=str(ROOT), env=env, capture_output=True, text=True)
    print("         " + (r.stdout or r.stderr).strip().splitlines()[-1])
    return r.returncode


async def _chay_mot_batch(admin, psid: str, ref: str, so_tin: int = 2):
    """Chay capture that mot batch. Tra (batch_id, ket_qua|None, ngoai_le|None)."""
    _cust, conv = await _fixture_hoi_thoai(admin, psid, so_tin)
    batch = await _khoa_batch(admin, conv)
    staff_id, cp = await _bat_capture(admin, ref)
    loi = kq = None
    try:
        kq = await _chay_collector(batch)
    except Exception as exc:  # noqa: BLE001 - bat de KIEM, khong de nuot
        loi = exc
    finally:
        await _tat_capture(cp, staff_id, ref)
        await cp.close()
    return batch, kq, loi


async def _kiem_fail_closed(admin, ten: str, batch, kq, loi, truoc: tuple[int, int],
                            dau_hieu: str = "") -> None:
    """`dau_hieu`: chuoi PHAI xuat hien trong thong diep loi.

    VI SAO BAT BUOC DOI CHIEU LY DO: lan chay dau tien cua kich ban nay, ca ba ca S2/S3/S4 deu
    "PASS" voi CUNG mot thong diep `IncompleteReadError: 0 bytes read` — tuc chung khong he phan
    biet duoc ba nguyen nhan, va se van xanh y het neu signer chet vi bat ky ly do nao khac. Do la
    dung lop loi "xanh vi khong co gi de kiem" ma du an nay da tra gia nhieu lan. Nen tu day moi ca
    phai chung minh no do VI DUNG NGUYEN NHAN cua no.
    """
    check(loi is not None or (kq or {}).get("inserted") == 0,
          f"{ten}: collector KHONG ghi duoc sample nao")
    thong_diep = f"{type(loi).__name__}: {loi}" if loi is not None else ""
    if loi is not None:
        print(f"         loi that: {thong_diep[:170]}")
    if dau_hieu:
        check(dau_hieu.lower() in thong_diep.lower(),
              f"{ten}: loi do DUNG nguyen nhan (tim thay dau hieu {dau_hieu!r})")
        check("incompleteread" not in thong_diep.lower(),
              f"{ten}: KHONG phai loi transport mu (signer tra ly do tuong minh)")
    trong_batch = await admin.fetchval(
        "SELECT count(*) FROM m4_shadow_review_samples WHERE selection_batch=$1", batch)
    check(trong_batch == 0, f"{ten}: 0 sample duoc commit trong batch nay")
    sau = await _dem_toan_cuc(admin)
    check(sau == truoc, f"{ten}: tong so sample/chu ky toan cuc khong doi (khong orphan)")


async def _chay_tat_ca() -> int:
    settings.database_url = DB_URL
    settings.redis_url = REDIS_URL
    socket_path = f"/tmp/m4-kms-e2e-{os.getpid()}/sock"
    admin = await asyncpg.connect(DB_URL)
    try:
        # `_don_dep` cua harness H2-A-2 chi xoa approval tien to "H2A2-". Approval cua kich ban
        # nay mang tien to rieng ("H2KMS-") nen phai tu don, neu khong chung giu FK toi staff_users
        # va lan chay sau se hong ngay o buoc don dep.
        await admin.execute(
            "DELETE FROM m4_stage0p_capture_approvals WHERE approval_ref LIKE 'H2KMS-%'")
        await _don_dep(admin)

        # Khoa THU cua sandbox: tao moi moi lan chay de ket qua khong phu thuoc lan truoc.
        _vault_admin("POST", f"transit/keys/{KEY_ID}/config",
                     {"deletion_allowed": True})
        _vault_admin("DELETE", f"transit/keys/{KEY_ID}")
        _vault_admin("POST", f"transit/keys/{KEY_ID}", {"type": "ed25519"})

        # ---------------------------------------------------------------- S1
        print("== [S1] duong that qua Vault: ky -> ghi -> verify NGOAI DB ==")
        _moi_truong_signer()
        check(_cong_bo_public_key("1") == 0, "[S1] cong bo public key v1 vao registry (duong van hanh)")
        proc = await _khoi_dong(admin, socket_path)
        try:
            batch, kq, loi = await _chay_mot_batch(admin, "kms-s1", "H2KMS-S1", so_tin=2)
            check(loi is None and (kq or {}).get("inserted") == 2,
                  f"[S1] collector ghi du 2 sample (loi={type(loi).__name__ if loi else None})")
            hang = await admin.fetch(
                "SELECT g.sig_alg, g.sig_key_id, g.sig_key_ver, octet_length(g.signature) AS n "
                "  FROM m4_shadow_review_samples r "
                "  JOIN m4_stage0p_transcript_signatures g ON g.sample_id = r.sample_id "
                " WHERE r.selection_batch=$1", batch)
            check(len(hang) == 2, "[S1] moi sample deu co hang chu ky asym")
            check(all(h["sig_key_id"] == KEY_ID and h["sig_key_ver"] == "1" for h in hang),
                  f"[S1] chu ky khai dung khoa Vault {KEY_ID}@1")
            check(all(h["n"] == 64 and h["sig_alg"] == "Ed25519" for h in hang),
                  "[S1] Ed25519, 64 byte")
            rc, bc = await _chay_verifier(batch)
            check(rc == 0 and bc["hong"] == 0 and bc["tong_chu_ky"] == 2,
                  "[S1] verifier NGOAI DB (khong secret) verify DAT chu ky do Vault tao")
            batch_s1 = batch
        finally:
            await stop_signing_service(proc, socket_path)

        # ---------------------------------------------------------------- S2
        # KHAI BAO CHINH XAC THU DA LAM: kich ban chay ben trong container ung dung nen KHONG
        # dung/khoi dong duoc container Vault. "Unavailable" o day duoc tao bang cach tro signer
        # toi mot dia chi KHONG CO AI LANG NGHE — o tang transport thi day dung la truong hop
        # khong goi duoc backend (ConnectError), giong het luc KMS chet hay mat mang.
        print("== [S2] KMS UNAVAILABLE (khong ket noi duoc backend) -> khong commit sample ==")
        truoc = await _dem_toan_cuc(admin)
        _moi_truong_signer(addr="http://a3s-vault-sandbox:8299")  # cong khong co ai lang nghe
        proc = await _khoi_dong(admin, socket_path)
        try:
            batch, kq, loi = await _chay_mot_batch(admin, "kms-s2", "H2KMS-S2")
            await _kiem_fail_closed(admin, "[S2]", batch, kq, loi, truoc,
                                    dau_hieu="SigningBackendUnavailable")
        finally:
            await stop_signing_service(proc, socket_path)

        # ---------------------------------------------------------------- S3
        print("== [S3] UNAUTHORIZED (token sai) -> khong commit sample ==")
        truoc = await _dem_toan_cuc(admin)
        _moi_truong_signer(token="token-khong-hop-le")
        proc = await _khoi_dong(admin, socket_path)
        try:
            batch, kq, loi = await _chay_mot_batch(admin, "kms-s3", "H2KMS-S3")
            await _kiem_fail_closed(admin, "[S3]", batch, kq, loi, truoc,
                                    dau_hieu="HTTP 403")
        finally:
            await stop_signing_service(proc, socket_path)

        # ---------------------------------------------------------------- S4
        print("== [S4] KHOA BI VO HIEU o phia provider -> khong commit sample ==")
        truoc = await _dem_toan_cuc(admin)
        _vault_admin("POST", f"transit/keys/{KEY_ID}/rotate")
        _vault_admin("POST", f"transit/keys/{KEY_ID}/config",
                     {"min_encryption_version": 2})
        _moi_truong_signer(key_version="1")  # signer van duoc cau hinh ky bang v1 da bi vo hieu
        proc = await _khoi_dong(admin, socket_path)
        try:
            batch, kq, loi = await _chay_mot_batch(admin, "kms-s4", "H2KMS-S4")
            await _kiem_fail_closed(admin, "[S4]", batch, kq, loi, truoc,
                                    dau_hieu="minimum encryption key version")
        finally:
            await stop_signing_service(proc, socket_path)

        # ---------------------------------------------------------------- S5
        print("== [S5] ROTATION: khoa moi ky duoc, chu ky CU van verify duoc ==")
        _moi_truong_signer(key_version="2")
        check(_cong_bo_public_key("2") == 0, "[S5] cong bo public key v2 vao registry")
        proc = await _khoi_dong(admin, socket_path)
        try:
            batch, kq, loi = await _chay_mot_batch(admin, "kms-s5", "H2KMS-S5", so_tin=1)
            check(loi is None and (kq or {}).get("inserted") == 1,
                  f"[S5] ky duoc bang phien ban moi (loi={type(loi).__name__ if loi else None})")
            ver = await admin.fetchval(
                "SELECT g.sig_key_ver FROM m4_shadow_review_samples r "
                "  JOIN m4_stage0p_transcript_signatures g ON g.sample_id=r.sample_id "
                " WHERE r.selection_batch=$1", batch)
            check(ver == "2", f"[S5] chu ky moi khai dung phien ban 2 (thuc te {ver})")
            rc, bc = await _chay_verifier(batch_s1)
            check(rc == 0 and bc["hong"] == 0,
                  "[S5] chu ky ky bang v1 TRUOC rotation VAN verify duoc")
            rc, bc = await _chay_verifier(None)
            check(rc == 0 and bc["hong"] == 0 and bc["tong_chu_ky"] == 3,
                  f"[S5] toan bo 3 chu ky (2 cua v1 + 1 cua v2) deu dat: {bc['theo_key_version']}")
        finally:
            await stop_signing_service(proc, socket_path)
    finally:
        await admin.close()

    print("")
    if _fail_chung:
        print(f"KHONG DAT ({len(_fail_chung)}):")
        for f in _fail_chung:
            print(f"  - {f}")
        return 1
    print("TAT CA KICH BAN DAT.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_chay_tat_ca()))
