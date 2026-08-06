#!/usr/bin/env python
"""I-B M4 Stage 0P — provisioning PIN nghiep vu (`m4_stage0p_actor_credentials.pin_secret_hash`)
qua single-use bootstrap token, dap lai
`PHASE1B-M4-REHEARSAL-READINESS-SNAPSHOT-REVIEW-1-VI.md` F-M4-PIN-R1-01 — "tool khong bind
nguoi chay voi staff_id... bat ky ai co quyen chay docker exec deu co the chon staff_id 3, 4
hoac 5 va dat lai PIN cua principal khac".

REV2 (dap CA Review #1 tren PR #7): xoa han tham so `--staff-id` khoi subcommand dat PIN — CALLER
KHONG CON tu chon staff_id duoc nua duoi bat ky hinh thuc nao. Thay vao do:

1. `issue-token` (Dev/nguoi issue chay TRUOC, ngoai luong): BUOC 1 token ngau nhien (32 byte,
   `secrets.token_urlsafe`) VOI 1 staff_id CU THE ngay luc tao — chi luu `sha256(token)` vao bang
   moi `m4_stage0p_pin_bootstrap_tokens` (migration 040), KHONG BAO GIO luu token goc. In token
   goc RA MAN HINH DUY NHAT 1 LAN de Dev chuyen cho dung nguoi qua kenh rieng (Signal/Telegram/
   noi truc tiep — KHONG qua kenh ma nguoi khac doc lai duoc). Token KHONG PHAI PIN — no la ve
   "duoc phep dat PIN cho DUNG staff_id nay", Dev biet token khong sao (no khong tu no la
   credential nghiep vu), nhung VAN KHONG BIET PIN thuc te nguoi do se go (buoc 2 duoi day hoan
   toan tach biet, van qua getpass).
2. `provision-pin` (nguoi dam nhan vai tro TU chay, tren chinh SSH session cua ho): CHI hoi
   token (getpass, khong echo) — staff_id duoc SERVER-SIDE RESOLVE tu chinh token do (khong con
   la input cua caller). Token tieu thu 1 lan, CUNG 1 transaction voi viec ghi PIN — that bai
   xac nhan PIN (mismatch/qua ngan) KHONG tieu thu token (cho phep thu lai voi CUNG token); chi
   thanh cong that su moi tieu thu.

Thiet ke bao mat con lai giu nguyen tu REV1: khong CLI argument nao mang PIN, doc qua
`getpass.getpass()`, `del` bien PIN ngay sau dung, output CHI xac nhan row/metadata ton tai
(KHONG BAO GIO in `pin_secret_hash`).

QUAN TRONG: KHONG chay file nay tren production truoc khi PR merge/deploy qua dung merge/
deploy-dormant gate rieng (F-M4-PIN-R1-02) — chay file untracked tren VPS bi CA tu choi ro rang.

Chay (Dev, issue token TRUOC cho tung staff_id):
    docker exec -it alpha3s-api-1 python scripts/m4_stage0p_provision_pin.py issue-token \\
        --staff-id 5 --issued-by 4 --ttl-minutes 30

Chay (nguoi dam nhan vai tro, TU chay tren SSH session cua chinh ho):
    docker exec -it alpha3s-api-1 python scripts/m4_stage0p_provision_pin.py provision-pin
"""

import argparse
import asyncio
import getpass
import hashlib
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MIN_PIN_LEN = 8
DEFAULT_TTL_MINUTES = 30


def _db_url() -> str:
    return os.environ.get("DATABASE_URL") or "postgresql://alpha3s:alpha3s@db:5432/alpha3s"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_token(staff_id: int, issued_by: int, ttl_minutes: int) -> int:
    conn = await asyncpg.connect(_db_url())
    try:
        staff = await conn.fetchrow(
            "SELECT id, username, is_active FROM staff_users WHERE id = $1", staff_id)
        if staff is None:
            print(f"LOI: staff_id {staff_id} khong ton tai", file=sys.stderr)
            return 1
        if not staff["is_active"]:
            print(f"LOI: staff_id {staff_id} ({staff['username']}) khong active", file=sys.stderr)
            return 1
        issuer = await conn.fetchrow(
            "SELECT id FROM staff_users WHERE id = $1 AND is_active", issued_by)
        if issuer is None:
            print(f"LOI: issued_by {issued_by} khong ton tai hoac khong active", file=sys.stderr)
            return 1

        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        await conn.execute(
            "INSERT INTO m4_stage0p_pin_bootstrap_tokens "
            "  (token_hash, staff_id, issued_by, expires_at) VALUES ($1, $2, $3, $4)",
            token_hash, staff_id, issued_by, expires_at)
        del token_hash  # khong can giu lai, chi la du lieu trung gian

        print(f"Token da phat cho staff_id={staff_id} username={staff['username']!r}, "
              f"het han luc {expires_at.isoformat()} ({ttl_minutes} phut).")
        print("Chuyen CHINH XAC chuoi duoi day cho DUNG nguoi qua kenh RIENG (khong dan vao "
              "noi nguoi khac doc lai duoc) — token nay dung DUOC DUNG 1 LAN:")
        print(token)
        return 0
    finally:
        await conn.close()


async def provision_pin(*, token_reader=getpass.getpass, pin_reader=getpass.getpass) -> int:
    conn = await asyncpg.connect(_db_url())
    try:
        token = token_reader("Nhap token da duoc cap (khong hien thi khi go): ")
        token_hash = _hash_token(token)
        del token

        token_row = await conn.fetchrow(
            "SELECT staff_id FROM m4_stage0p_pin_bootstrap_tokens "
            "WHERE token_hash = $1 AND consumed_at IS NULL AND expires_at > now()", token_hash)
        if token_row is None:
            print("LOI: token khong hop le, da dung, hoac het han - huy", file=sys.stderr)
            return 1
        staff_id = token_row["staff_id"]

        staff = await conn.fetchrow(
            "SELECT username, is_active FROM staff_users WHERE id = $1", staff_id)
        if staff is None or not staff["is_active"]:
            print(f"LOI: staff_id {staff_id} (tu token) khong ton tai/khong active", file=sys.stderr)
            return 1

        print(f"Token hop le - dang dat PIN M4 cho staff_id={staff_id} username={staff['username']!r}")
        print("PIN se KHONG hien thi khi go va KHONG luu shell history.")
        pin = pin_reader("Nhap PIN M4 moi (>=8 ky tu): ")
        pin_confirm = pin_reader("Nhap lai de xac nhan: ")

        if pin != pin_confirm:
            print("LOI: 2 lan nhap khong khop - huy, KHONG ghi gi (token VAN con dung duoc lai)",
                  file=sys.stderr)
            return 1
        if len(pin) < MIN_PIN_LEN:
            print(f"LOI: PIN can toi thieu {MIN_PIN_LEN} ky tu - huy, KHONG ghi gi "
                  "(token VAN con dung duoc lai)", file=sys.stderr)
            return 1

        async with conn.transaction():
            # Tieu thu token VA ghi PIN trong CUNG 1 transaction — token CHI thuc su "dung 1
            # lan" khi lan dung do THANH CONG; mismatch/qua ngan o tren khong cham toi day nen
            # token chua bao gio bi tieu thu trong cac truong hop do.
            consumed = await conn.fetchrow(
                "UPDATE m4_stage0p_pin_bootstrap_tokens SET consumed_at = now() "
                "WHERE token_hash = $1 AND consumed_at IS NULL AND expires_at > now() "
                "RETURNING staff_id", token_hash)
            if consumed is None:
                print("LOI: token vua bi dung/het han o noi khac giua chung (race) - huy",
                      file=sys.stderr)
                return 1
            await conn.execute(
                "INSERT INTO m4_stage0p_actor_credentials "
                "  (staff_id, pin_secret_hash, provisioned_by) "
                "VALUES ($1, crypt($2, gen_salt('bf')), $1) "
                "ON CONFLICT (staff_id) DO UPDATE SET "
                "  pin_secret_hash = crypt($2, gen_salt('bf')), "
                "  failed_attempts = 0, locked_until = NULL, provisioned_at = now()",
                staff_id, pin)
        del pin, pin_confirm

        row = await conn.fetchrow(
            "SELECT staff_id, provisioned_at, failed_attempts, locked_until "
            "FROM m4_stage0p_actor_credentials WHERE staff_id = $1", staff_id)
        print(f"OK - credential row ton tai: staff_id={row['staff_id']} "
              f"provisioned_at={row['provisioned_at'].isoformat()} "
              f"failed_attempts={row['failed_attempts']} locked_until={row['locked_until']}")
        print("(KHONG in pin_secret_hash - chi xac nhan row/metadata, dung yeu cau P-M4-PA-02)")
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dat PIN M4 nghiep vu qua single-use bootstrap token (F-M4-PIN-R1-01).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_issue = sub.add_parser("issue-token", help="Dev: phat 1 token BUOC voi 1 staff_id cu the")
    p_issue.add_argument("--staff-id", type=int, required=True)
    p_issue.add_argument("--issued-by", type=int, required=True)
    p_issue.add_argument("--ttl-minutes", type=int, default=DEFAULT_TTL_MINUTES)

    sub.add_parser("provision-pin", help="Nguoi dam nhan vai tro TU chay - chi hoi token + PIN")

    args = parser.parse_args()
    if args.command == "issue-token":
        return asyncio.run(issue_token(args.staff_id, args.issued_by, args.ttl_minutes))
    return asyncio.run(provision_pin())


if __name__ == "__main__":
    sys.exit(main())
