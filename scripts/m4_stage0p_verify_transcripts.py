"""I-B M4 H2-A — verifier transcript DOC LAP, chay NGOAI DB va NGOAI signer.

VI SAO CAN MOT TIEN TRINH RIENG
Hom nay `m4_stage0p_record_sample` verify chu ky HMAC ngay trong DB. Nhung DB giu khoa doi xung,
nen chinh DB cung la ben GIA MAO duoc — "nguoi kiem" va "nguoi co the lam gia" la mot. Sau H2-A,
chu ky Ed25519 duoc verify o day, bang PUBLIC key, boi mot tien trinh:

  * KHONG import `crypto.py` / `stage0p_signing_service.py` — khong cham duoc duong ky;
  * KHONG doc secret nao — chi can public key trong `m4_stage0p_transcript_public_keys`;
  * chay duoc boi BAT KY AI, ke ca nguoi khong tin DB va khong tin Dev.

Do chinh la dieu bien non-repudiation thanh that. Neu verifier nay can mot bi mat de chay thi H2
that bai — nen viec no chi import `verify_signature` (thuan toan hoc) la mot rang buoc thiet ke,
khong phai tinh co.

PHAM VI: CHI DOC. Script khong INSERT/UPDATE/DELETE bat ky bang nao. Khong tao khoa, khong ky.

CACH DUNG
    python scripts/m4_stage0p_verify_transcripts.py                 # toan bo
    python scripts/m4_stage0p_verify_transcripts.py --batch <uuid>  # 1 batch
    python scripts/m4_stage0p_verify_transcripts.py --json          # xuat JSON cho evidence

EXIT CODE
    0  moi chu ky verify dat (hoac khong co hang nao de verify)
    1  co it nhat 1 chu ky KHONG dat  <- fail-closed cho CI
    2  loi van hanh (khong ket noi duoc DB, thieu tham so...)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pii.signing_backend import verify_signature  # noqa: E402

_SQL = """
SELECT s.sample_id, s.transcript, s.sig_alg, s.sig_key_id, s.sig_key_ver, s.signature,
       s.created_at, k.public_key, k.retired_at, k.algorithm AS key_algorithm,
       r.selection_batch
  FROM m4_stage0p_transcript_signatures s
  JOIN m4_stage0p_transcript_public_keys k
    ON k.key_id = s.sig_key_id AND k.key_version = s.sig_key_ver
  LEFT JOIN m4_shadow_review_samples r ON r.sample_id = s.sample_id
 WHERE ($1::uuid IS NULL OR r.selection_batch = $1::uuid)
 ORDER BY s.created_at
"""


def _kiem_mot_hang(row) -> tuple[bool, str]:
    """Tra (dat, ly_do). Ly do KHONG bao gio chua noi dung transcript (T11-03)."""
    if row["sig_alg"] != "Ed25519" or row["key_algorithm"] != "Ed25519":
        return False, f"thuat toan khong phai Ed25519 (sig={row['sig_alg']}, key={row['key_algorithm']})"

    if not verify_signature(bytes(row["public_key"]), bytes(row["transcript"]),
                            bytes(row["signature"])):
        return False, "CHU KY KHONG HOP LE voi public key cua dung key_version da ghi"

    # Thu hoi: chu ky tao SAU thoi diem thu hoi la khong hop le. Chu ky tao TRUOC van hop le —
    # do chinh la ngu nghia CA yeu cau ("transcript truoc rotation con verify duoc").
    retired = row["retired_at"]
    if retired is not None and row["created_at"] > retired:
        return False, f"chu ky tao luc {row['created_at']} SAU khi khoa bi thu hoi luc {retired}"

    # Rang buoc noi dung: transcript phai tu khai dung sample_id no thuoc ve.
    try:
        trans = json.loads(bytes(row["transcript"]).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, "transcript khong phai JSON UTF-8 hop le"
    if trans.get("sample_id") != str(row["sample_id"]):
        return False, "sample_id trong transcript khong khop hang DB"

    return True, "dat"


async def _chay(batch: str | None) -> dict:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("thieu DATABASE_URL")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(_SQL, batch)
    finally:
        await conn.close()

    ket_qua = []
    theo_key: dict[str, dict] = defaultdict(lambda: {"dat": 0, "hong": 0})
    for row in rows:
        dat, ly_do = _kiem_mot_hang(row)
        khoa = f"{row['sig_key_id']}@{row['sig_key_ver']}"
        theo_key[khoa]["dat" if dat else "hong"] += 1
        if not dat:
            ket_qua.append({"sample_id": str(row["sample_id"]), "key": khoa, "ly_do": ly_do})

    tong = len(rows)
    hong = sum(v["hong"] for v in theo_key.values())
    return {
        "kiem_luc_utc": datetime.now(timezone.utc).isoformat(),
        "pham_vi": {"batch": batch or "TAT CA"},
        "tong_chu_ky": tong,
        "dat": tong - hong,
        "hong": hong,
        # CA yeu cau verifier "publish ro key-id/key-version".
        "theo_key_version": {k: dict(v) for k, v in sorted(theo_key.items())},
        "chi_tiet_hong": ket_qua,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Verify chu ky Ed25519 cua transcript — CHI DOC.")
    p.add_argument("--batch", help="chi verify 1 selection batch (UUID)")
    p.add_argument("--json", action="store_true", help="xuat JSON canonical cho evidence")
    args = p.parse_args()

    try:
        bc = asyncio.run(_chay(args.batch))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"LOI VAN HANH: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(bc, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"kiem luc      : {bc['kiem_luc_utc']}")
        print(f"pham vi       : {bc['pham_vi']['batch']}")
        print(f"tong chu ky   : {bc['tong_chu_ky']}")
        print(f"dat / hong    : {bc['dat']} / {bc['hong']}")
        for khoa, dem in bc["theo_key_version"].items():
            print(f"  {khoa}: dat={dem['dat']} hong={dem['hong']}")
        for h in bc["chi_tiet_hong"]:
            print(f"  HONG {h['sample_id']} [{h['key']}]: {h['ly_do']}")
        if bc["tong_chu_ky"] == 0:
            print("KHONG co chu ky nao de verify — day KHONG phai bang chung dat, chi la khong co du lieu.")

    return 1 if bc["hong"] else 0


if __name__ == "__main__":
    sys.exit(main())
