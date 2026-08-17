"""I-B M4 H2-A — kich ban sandbox E2E: ky that, ghi that, verify that.

CHI CHAY TREN SANDBOX. Script tu tu choi neu `APP_ENV` la production/staging (xem guard cua
`LocalDevBackend`) va no dung `LocalDevBackend` — thu von KHONG duoc phep song o production.

Kich ban chung minh BON dieu, moi dieu la mot cau hoi CA da dat:

  1. Duong ky Ed25519 chay tron ven: ky -> ghi DB -> verifier NGOAI DB xac nhan dat.
  2. Transcript ky TRUOC rotation VAN verify duoc sau khi khoa cu bi thu hoi.
  3. DB KHONG PHAT HIEN duoc chu ky sai mat ma (no khong verify Ed25519 duoc) nhung verifier
     ngoai DB PHAT HIEN. Day la ly do ton tai cua verifier, khong phai mot buoc thua.
  4. Chu ky ghi vao roi thi bat bien.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pii.signing_backend import LocalDevBackend  # noqa: E402

KEY_ID = "m4-transcript-ed25519"


def _transcript(sample_id: str, txid: int) -> bytes:
    """Canonical signed bytes — cung dang JSON sort_keys+compact ma HMAC dang ky."""
    return json.dumps({"v": 1, "sample_id": sample_id, "txid": txid,
                       "canonical_digest": "00" * 32, "canonical_len": 5},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


async def _fixture(conn) -> str:
    norm = await conn.fetchval(
        "SELECT version FROM m4_stage0p_normalization_registry WHERE is_current")
    batch = uuid.uuid4()
    await conn.execute(
        """INSERT INTO m4_selection_batches(batch_id, window_start, window_end, eligible_count,
             selected_count, algorithm_seed, locked_conversation_ids, purpose_code,
             normalization_version)
           VALUES ($1, now()-interval '1 day', now(), 10, 1, 'seed', ARRAY[1]::bigint[],
                   'P12_PII_DETECTOR_EVAL', $2)""", batch, norm)
    return str(batch)


async def _them_sample(conn, batch: str) -> str:
    sid = uuid.uuid4()
    norm = await conn.fetchval(
        "SELECT version FROM m4_stage0p_normalization_registry WHERE is_current")
    await conn.execute(
        """INSERT INTO m4_shadow_review_samples(sample_id, customer_ref, conversation_ref,
             encrypted_message, canonical_text_len, expires_at, purpose_code,
             normalization_version, selection_batch)
           VALUES ($1,'c','v','\\x00'::bytea,5, now()+interval '30 day',
                   'P12_PII_DETECTOR_EVAL',$2,$3)""", sid, norm, uuid.UUID(batch))
    return str(sid)


async def main() -> int:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    backend = LocalDevBackend(key_id=KEY_ID, app_env=os.environ.get("APP_ENV", "development"))
    batch = await _fixture(conn)
    print(f"batch sandbox: {batch}")

    # --- [1] duong ky binh thuong -------------------------------------------------
    v1 = backend.key_version()
    await conn.execute(
        """INSERT INTO m4_stage0p_transcript_public_keys(key_id,key_version,algorithm,public_key)
           VALUES ($1,$2,'Ed25519',$3)""", KEY_ID, v1, backend.public_key_raw())
    s1 = await _them_sample(conn, batch)
    t1 = _transcript(s1, 101)
    await conn.execute("SELECT m4_stage0p_record_transcript_signature($1,$2,$3,'Ed25519',$4,$5)",
                       uuid.UUID(s1), t1, backend.sign(t1), KEY_ID, v1)
    print(f"[1] da ky + ghi 1 chu ky that bang {v1}")

    # --- [2] rotation: ky bang v1 o tren, gio xoay sang v2 roi THU HOI v1 ----------
    v2 = backend.rotate()
    await conn.execute(
        """INSERT INTO m4_stage0p_transcript_public_keys(key_id,key_version,algorithm,public_key)
           VALUES ($1,$2,'Ed25519',$3)""", KEY_ID, v2, backend.public_key_raw())
    s2 = await _them_sample(conn, batch)
    t2 = _transcript(s2, 102)
    await conn.execute("SELECT m4_stage0p_record_transcript_signature($1,$2,$3,'Ed25519',$4,$5)",
                       uuid.UUID(s2), t2, backend.sign(t2), KEY_ID, v2)
    await conn.execute(
        "UPDATE m4_stage0p_transcript_public_keys SET retired_at=now() WHERE key_id=$1 AND key_version=$2",
        KEY_ID, v1)
    print(f"[2] da xoay sang {v2} va THU HOI {v1} — chu ky cu phai VAN verify duoc")

    # --- [3] chu ky SAI MAT MA: DB khong the phat hien, verifier phai phat hien ----
    # Ky bang mot khoa HOAN TOAN KHAC nhung KHAI la {v2}. DB chi kiem cau truc nen se NHAN.
    ke_gia_mao = LocalDevBackend(key_id=KEY_ID, app_env="development")
    s3 = await _them_sample(conn, batch)
    t3 = _transcript(s3, 103)
    try:
        await conn.execute(
            "SELECT m4_stage0p_record_transcript_signature($1,$2,$3,'Ed25519',$4,$5)",
            uuid.UUID(s3), t3, ke_gia_mao.sign(t3), KEY_ID, v2)
        print("[3] DB DA NHAN mot chu ky sai mat ma  <- dung nhu du doan: DB khong verify Ed25519 duoc")
    except Exception as exc:  # noqa: BLE001
        print(f"[3] BAT NGO: DB tu choi ({type(exc).__name__}) — kiem lai gia dinh")
        return 1

    # --- [4] bat bien --------------------------------------------------------------
    try:
        await conn.execute(
            "UPDATE m4_stage0p_transcript_signatures SET signature=$1 WHERE sample_id=$2",
            b"\x22" * 64, uuid.UUID(s1))
        print("[4] LOI: sua duoc chu ky da ghi")
        return 1
    except asyncpg.PostgresError:
        print("[4] sua chu ky da ghi: bi tu choi (bat bien)")

    await conn.close()
    print(f"\nSANDBOX_BATCH={batch}")
    print(f"KY_VONG: tong 3 chu ky — 2 dat (sample {s1[:8]}, {s2[:8]}), 1 hong (sample {s3[:8]})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
