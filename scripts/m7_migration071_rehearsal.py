#!/usr/bin/env python3
"""CA Directive 357 §4.6 — migration 071 rehearsal + rollback rehearsal (m5lab, KHONG doi business data).

Toan bo chay trong MOT transaction va ROLLBACK o cuoi -> DB tra ve nguyen trang.
M1 apply lai 071 -> idempotent (khong loi, khong nhan doi constraint).
M2 rollback batch (khoi phuc PK/unique cu, bo cot mode) -> chay duoc, so dong business KHONG doi.
M3 re-apply 071 sau rollback -> ve dung hinh dang moi, du lieu cu = 'staging' (backfill mac dinh).
M4 forward-guard: sau 071, (provider,kind,key) trung nhau nhung KHAC mode -> ton tai song song (tach that su).
"""
import asyncio
import os
import pathlib
import re
import sys

import asyncpg

DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")
ROOT = pathlib.Path(__file__).resolve().parents[1]
SQL_071 = (ROOT / "migrations" / "071_carrier_mode_separation.sql").read_text(encoding="utf-8")
FAILS = []


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


def rollback_sql() -> str:
    """Trich batch rollback tu chinh file migration (cac dong comment sau moc ROLLBACK) -> bo '-- '."""
    tail = SQL_071.split("ROLLBACK (batch, chay tay khi can)")[1]
    out = [re.sub(r"^--\s?", "", ln) for ln in tail.splitlines() if ln.strip().startswith("-- ALTER")]
    return "\n".join(out)


async def counts(conn) -> dict:
    d = {}
    for t in ("carrier_master_data", "carrier_master_snapshot", "carrier_address_map", "orders", "shipments"):
        d[t] = await conn.fetchval(f"SELECT count(*) FROM {t}")
    return d


async def cons(conn, name) -> bool:
    return bool(await conn.fetchval("SELECT 1 FROM pg_constraint WHERE conname=$1", name))


async def has_col(conn, table, col) -> bool:
    return bool(await conn.fetchval("SELECT 1 FROM information_schema.columns WHERE table_name=$1 AND column_name=$2",
                                    table, col))


async def main():
    conn = await asyncpg.connect(DSN)
    tr = conn.transaction()
    await tr.start()
    try:
        before = await counts(conn)
        print(f"  baseline counts: {before}")

        # ---- M1 apply lai 071 (idempotent) ----
        err = ""
        try:
            await conn.execute(SQL_071)
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
        n_pk = await conn.fetchval("SELECT count(*) FROM pg_constraint WHERE conname='carrier_master_data_mode_pkey'")
        ck("M1 apply lai 071 -> idempotent (khong loi, 1 PK duy nhat, counts khong doi)",
           not err and n_pk == 1 and await counts(conn) == before, f"err={err or '-'} pk={n_pk}")

        # ---- M2 rollback batch ----
        rb = rollback_sql()
        ck("M2a trich duoc batch rollback tu file migration (>=9 lenh ALTER)", rb.count("ALTER TABLE") >= 9,
           rb.count("ALTER TABLE"))
        err2 = ""
        try:
            await conn.execute(rb)
        except Exception as e:  # noqa: BLE001
            err2 = f"{type(e).__name__}: {e}"
        gone = not await has_col(conn, "carrier_master_data", "mode") and \
               not await has_col(conn, "carrier_address_map", "mode")
        old_back = await cons(conn, "carrier_master_data_pkey") and await cons(conn, "uq_carrier_addr_map")
        after_rb = await counts(conn)
        ck("M2b rollback chay duoc: cot mode bi bo, PK/unique cu quay lai, so dong business KHONG doi",
           not err2 and gone and old_back and after_rb == before,
           f"err={err2 or '-'} gone={gone} old={old_back} counts_same={after_rb == before}")

        # ---- M3 re-apply sau rollback ----
        err3 = ""
        try:
            await conn.execute(SQL_071)
        except Exception as e:  # noqa: BLE001
            err3 = f"{type(e).__name__}: {e}"
        modes = await conn.fetch("SELECT DISTINCT mode FROM carrier_address_map")
        ck("M3 re-apply 071 sau rollback -> hinh dang moi tro lai, du lieu cu backfill 'staging'",
           not err3 and await cons(conn, "carrier_master_data_mode_pkey") and await cons(conn, "uq_carrier_addr_map_mode")
           and all(r["mode"] == "staging" for r in modes) and await counts(conn) == before,
           f"err={err3 or '-'} modes={[r['mode'] for r in modes]}")

        # ---- M4 forward guard: cung key khac mode ton tai song song ----
        await conn.execute("INSERT INTO carrier_master_data (provider, mode, kind, key, parent_key, name, payload) "
                           "VALUES ('ghn','staging','province','99071',NULL,'X','{}'::jsonb) ON CONFLICT DO NOTHING")
        await conn.execute("INSERT INTO carrier_master_data (provider, mode, kind, key, parent_key, name, payload) "
                           "VALUES ('ghn','production','province','99071',NULL,'X','{}'::jsonb) ON CONFLICT DO NOTHING")
        n = await conn.fetchval("SELECT count(*) FROM carrier_master_data WHERE provider='ghn' AND key='99071'")
        bad_mode = ""
        try:
            await conn.execute("INSERT INTO carrier_master_data (provider, mode, kind, key, parent_key, name, payload) "
                               "VALUES ('ghn','prod','province','99072',NULL,'X','{}'::jsonb)")
        except Exception as e:  # noqa: BLE001
            bad_mode = type(e).__name__
        ck("M4 cung (provider,kind,key) khac mode -> 2 dong doc lap; mode ngoai allowlist bi CHECK chan",
           n == 2 and bad_mode != "", f"rows={n} bad_mode={bad_mode or 'KHONG CHAN'}")

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        await tr.rollback()
        await conn.close()
        print("  (transaction rolled back — m5lab nguyen trang)")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
