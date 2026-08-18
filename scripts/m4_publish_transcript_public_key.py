#!/usr/bin/env python
"""I-B M4 H2 — cong bo PUBLIC key cua backend ky vao registry (`m4_stage0p_transcript_public_keys`).

DAY LA BUOC VAN HANH, KHONG PHAI BUOC KY
Migration 044 doi hang registry `(key_id, key_version)` phai co SAN truoc khi ghi bat ky chu ky nao
— vi the phai co mot buoc doc public key tu backend roi cong bo vao DB. Voi managed KMS o giai doan
2, day chinh la "doc public key tu API cua KMS"; voi Vault sandbox thi cung mot duong.

VI SAO SCRIPT NAY XOA DUOC MOT MON NO
Khi lam F-H2A2-02, harness E2E khong co cach nao biet public key cua signer (khoa sinh trong RAM cua
tien trinh rieng), nen Dev phai them `M4_LOCALDEV_SIGNING_SEED_B64` de harness doan truoc duoc khoa.
Co duong cong bo that roi thi harness dung DUNG duong ma production dung, va khong con can biet
truoc khoa nua.

CHI GHI PUBLIC MATERIAL. Script khong doc, khong log, khong luu bat ky private material nao — no
khong co duong nao de lam viec do, vi `KmsTransport` chi co `sign` va `public_key`.

Dung:
    M4_KMS_TRANSPORT=vault M4_KMS_KEY_ID=... M4_KMS_KEY_VERSION=1 \
    M4_VAULT_ADDR=... M4_VAULT_TOKEN=... DATABASE_URL=... \
    python scripts/m4_publish_transcript_public_key.py [--kiem-tra]

    --kiem-tra : chi doc va so sanh, KHONG ghi (dung cho preflight/evidence)

Exit: 0 cong bo/khop | 1 lech voi hang da co | 2 loi van hanh
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402

from app.services.pii.kms_transport import get_kms_transport  # noqa: E402
from app.services.pii.signing_backend import (  # noqa: E402
    SIGNATURE_ALGORITHM,
    SigningBackendError,
)

_PUBLIC_KEY_BYTES = 32


async def _chay(chi_kiem_tra: bool) -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("thieu DATABASE_URL", file=sys.stderr)
        return 2
    try:
        transport, key_id, key_version = get_kms_transport()
        pub = transport.public_key(key_id, key_version)
    except SigningBackendError as exc:
        print(f"khong lay duoc public key: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if len(pub) != _PUBLIC_KEY_BYTES:
        print(f"public key dai {len(pub)} byte, cho doi {_PUBLIC_KEY_BYTES}", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(dsn.replace("+asyncpg", ""))
    try:
        dang_co = await conn.fetchval(
            "SELECT public_key FROM m4_stage0p_transcript_public_keys "
            " WHERE key_id=$1 AND key_version=$2", key_id, key_version)
        if dang_co is not None:
            # Bang nay BAT BIEN (trigger 044 chan UPDATE moi cot tru retired_at). Neu khac nhau thi
            # day la tin hieu nghiem trong: hoac backend da bi thay, hoac ai do dang cong bo nham
            # khoa. Khong tu sua — bao de nguoi that dieu tra.
            if bytes(dang_co) == pub:
                print(f"da co san va KHOP: {key_id}@{key_version}")
                return 0
            print(f"LECH: registry da co {key_id}@{key_version} voi public key KHAC. "
                  "Khong ghi de (bang bat bien). Dieu tra truoc khi tiep tuc.", file=sys.stderr)
            return 1
        if chi_kiem_tra:
            print(f"CHUA CO trong registry: {key_id}@{key_version} (che do --kiem-tra, khong ghi)")
            return 0
        await conn.execute(
            "INSERT INTO m4_stage0p_transcript_public_keys "
            "  (key_id, key_version, algorithm, public_key) VALUES ($1,$2,$3,$4)",
            key_id, key_version, SIGNATURE_ALGORITHM, pub)
        print(f"da cong bo: {key_id}@{key_version} ({SIGNATURE_ALGORITHM}, {len(pub)} byte public)")
        return 0
    finally:
        await conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Cong bo public key cua backend ky vao registry.")
    p.add_argument("--kiem-tra", action="store_true", help="chi doc/so sanh, khong ghi")
    args = p.parse_args()
    try:
        return asyncio.run(_chay(args.kiem_tra))
    except Exception as exc:  # noqa: BLE001
        print(f"LOI VAN HANH: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
