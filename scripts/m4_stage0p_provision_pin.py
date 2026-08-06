#!/usr/bin/env python
"""I-B M4 Stage 0P — provisioning PIN nghiep vu (`m4_stage0p_actor_credentials.pin_secret_hash`)
CHO CHINH NGUOI CHAY SCRIPT NAY, dap lai
`PHASE1B-M4-REHEARSAL-PRINCIPAL-ASSIGNMENT-REVIEW-1-VI.md` finding P-M4-PA-02 — "moi principal
phai tu dat PIN rieng qua 1 co che duoc mo ta va kiem soat; DEV khong duoc nhin thay PIN cua
approval recorder hoac PO Reviewer".

THIET KE BAO MAT (tai sao script nay khac han `_provision_pin_secret()` dung trong cac evidence
script khac cua du an — NHUNG cai do nhan PIN nhu 1 tham so Python thuong, chi phu hop cho test
tu dong, KHONG phu hop cho nguoi that tu dat PIN):

1. PIN KHONG BAO GIO la CLI argument — argparse CHI dinh nghia `--staff-id`, KHONG co
   `--pin`/`--secret`/`--password` nao ca (kiem tra duoc bang `--help`: khong thay). Neu co, PIN
   se nam trong shell history/process list (`ps aux`) - dung chinh dieu nay la vi du cho
   "khong duoc" trong toan bo du an nay (xem docstring `m4_stage0p_rehearsal_runner.py`
   `_require_env`).
2. PIN doc qua `getpass.getpass()` — KHONG echo ra terminal, KHONG luu shell history (khac
   `input()`).
3. PIN CHI ton tai trong bo nho tien trinh nay, trong thoi gian NGAN (tu luc nhap toi luc
   `crypt()` xong) — `del` tuong minh 2 bien ngay sau khi dung, khong bao gio duoc `print`/log.
4. Nguoi chay PHAI tu SSH vao VPS va tu go lenh nay — Dev (dieu khien qua tool goi lenh SSH/
   Bash) KHONG BAO GIO la nguoi thuc thi script nay cho nguoi khac, vi tool cua Dev chi thay
   command + output, KHONG co kenh nhap TTY rieng cho 1 nguoi thu 3 go PIN ma Dev khong thay
   duoc. Day la ly do CHINH quy trinh van hanh (xem
   `PHASE1B-M4-REHEARSAL-PIN-PROVISIONING-PROCEDURE-VI.md`) yeu cau tung principal tu SSH vao,
   khong nho Dev chay ho.
5. Output CUOI CUNG chi xac nhan "row ton tai" + metadata KHONG mat (provisioned_at,
   failed_attempts, locked_until) — KHONG BAO GIO in `pin_secret_hash` (du la hash, khong phai
   PIN goc, van khong can thiet phai lo ra ngoai evidence theo yeu cau CA "khong dua secret vao
   evidence").

Chay (nguoi dam nhan vai tro TU CHAY, tren chinh may/SSH session cua ho):
    docker exec -it alpha3s-api-1 python scripts/m4_stage0p_provision_pin.py --staff-id 5
"""

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MIN_PIN_LEN = 8


def _db_url() -> str:
    return os.environ.get("DATABASE_URL") or "postgresql://alpha3s:alpha3s@db:5432/alpha3s"


async def provision(staff_id: int, *, pin_reader=getpass.getpass) -> int:
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

        print(f"Dat PIN M4 cho staff_id={staff_id} username={staff['username']!r}")
        print("PIN se KHONG hien thi khi go va KHONG luu vao shell history.")
        pin = pin_reader("Nhap PIN M4 moi (>=8 ky tu): ")
        pin_confirm = pin_reader("Nhap lai de xac nhan: ")

        if pin != pin_confirm:
            print("LOI: 2 lan nhap khong khop - huy, KHONG ghi gi", file=sys.stderr)
            return 1
        if len(pin) < MIN_PIN_LEN:
            print(f"LOI: PIN can toi thieu {MIN_PIN_LEN} ky tu - huy, KHONG ghi gi", file=sys.stderr)
            return 1

        async with conn.transaction():
            await conn.execute(
                "INSERT INTO m4_stage0p_actor_credentials "
                "  (staff_id, pin_secret_hash, provisioned_by) "
                "VALUES ($1, crypt($2, gen_salt('bf')), $1) "
                "ON CONFLICT (staff_id) DO UPDATE SET "
                "  pin_secret_hash = crypt($2, gen_salt('bf')), "
                "  failed_attempts = 0, locked_until = NULL, provisioned_at = now()",
                staff_id, pin)
        del pin, pin_confirm  # khong bao gio giu lai trong bo nho lau hon can thiet

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
        description="Dat PIN M4 nghiep vu cho CHINH nguoi chay script (interactive only).")
    parser.add_argument("--staff-id", type=int, required=True)
    args = parser.parse_args()
    return asyncio.run(provision(args.staff_id))


if __name__ == "__main__":
    sys.exit(main())
