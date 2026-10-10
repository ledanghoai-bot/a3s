"""CA Directive 405 §2.4/§2.5/§4.1 — quet footprint dinh danh khach (CHI DOC, output da mask).

Hai che do:
  --legacy   : §2.5 dem customer da tombstone o psid nhung external_chat_id CON ChatID that (theo channel) + vi du mask.
  (mac dinh) : §2.4/§4.1 quet MOI bang public (row::text LIKE) + Redis (key chua ID, dead-letter, arq job) tim dinh danh
               goc cua 1 khach. Dinh danh doc tu BIEN MOI TRUONG (khong nhan qua argv, khong in ra): DSR_REF = psid dang
               luu (Messenger PSID hoac 'tg:<chat_id>'). Telegram tu them needle chat_id tran.

Chay trong container api (PYTHONPATH=/srv, DATABASE_URL/REDIS_URL san):
  DSR_REF=<psid> python scripts/d405_dsr_footprint.py            # truoc va sau khi xoa (baseline/postflight)
  python scripts/d405_dsr_footprint.py --legacy
Transaction READ ONLY — khong ghi DB/Redis. Bang khong co quyen doc -> 'no_access' (khong dung).
"""
import argparse
import asyncio
import os
import sys

import asyncpg
import redis.asyncio as aioredis

from app.services.safe_log import mask_ref

_DEAD_LETTER_KEY = "dead_letter:messages"


def _dsn() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "")


async def legacy() -> int:
    conn = await asyncpg.connect(_dsn())
    try:
        async with conn.transaction(readonly=True):
            rows = await conn.fetch(
                "SELECT channel, count(*) AS n, array_agg(external_chat_id ORDER BY id) AS ids FROM customers "
                "WHERE psid LIKE 'deleted:%' AND external_chat_id NOT LIKE 'deleted:%' GROUP BY channel ORDER BY 1")
            total_tomb = await conn.fetchval("SELECT count(*) FROM customers WHERE psid LIKE 'deleted:%'")
            reqs = await conn.fetch("SELECT status, count(*) AS n FROM data_deletion_requests GROUP BY 1 ORDER BY 1")
    finally:
        await conn.close()
    print(f"customers_tombstoned_psid={total_tomb}")
    print("deletion_requests=" + (",".join(f"{r['status']}:{r['n']}" for r in reqs) or "0"))
    if not rows:
        print("legacy_rows_needing_patch=0")
        return 0
    for r in rows:
        print(f"legacy channel={r['channel']} n={r['n']} examples={[mask_ref(x) for x in r['ids'][:3]]}")
    return sum(r["n"] for r in rows)


async def scan(ref: str) -> int:
    needles = [ref]
    if ref.startswith("tg:") and len(ref) > 3:
        needles.append(ref[3:])
    total = 0
    conn = await asyncpg.connect(_dsn())
    try:
        async with conn.transaction(readonly=True):
            tables = [r["table_name"] for r in await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public' "
                "AND table_type='BASE TABLE' ORDER BY 1")]
            for t in tables:
                for nd in needles:
                    try:
                        async with conn.transaction():  # savepoint: bang cam doc khong lam hong ca lan quet
                            n = await conn.fetchval(
                                f'SELECT count(*) FROM public."{t}" x WHERE x::text LIKE \'%\' || $1 || \'%\'', nd)
                    except asyncpg.InsufficientPrivilegeError:
                        print(f"db {t} needle={mask_ref(nd)} no_access")
                        continue
                    if n:
                        total += n
                        print(f"db {t} needle={mask_ref(nd)} rows={n}")
    finally:
        await conn.close()
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=False)
    try:
        bneedles = [nd.encode() for nd in needles]
        keys = 0
        arq_hits = 0
        async for k in r.scan_iter(count=500):
            if any(b in k for b in bneedles):
                keys += 1
            elif k.startswith(b"arq:") and await r.type(k) == b"string":
                v = await r.get(k) or b""
                if any(b in v for b in bneedles):
                    arq_hits += 1
        dl = [x for x in await r.lrange(_DEAD_LETTER_KEY, 0, -1) if any(b in x for b in bneedles)]
    finally:
        await r.aclose()
    for label, n in (("redis keys_containing_id", keys), ("redis arq_values_containing_id", arq_hits),
                     ("redis dead_letter_entries", len(dl))):
        print(f"{label}={n}")
        total += n
    print(f"TOTAL_HITS={total} ref={mask_ref(ref)}")
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy", action="store_true")
    a = ap.parse_args()
    if a.legacy:
        asyncio.run(legacy())
        return 0
    ref = os.environ.get("DSR_REF", "").strip()
    if not ref:
        print("can DSR_REF (psid dang luu) trong bien moi truong", file=sys.stderr)
        return 2
    asyncio.run(scan(ref))
    return 0


if __name__ == "__main__":
    sys.exit(main())
