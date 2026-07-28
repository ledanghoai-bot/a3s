#!/usr/bin/env python3
"""M2 CA F-R1-01 remediation evidence — split fresh-seed assertion khoi operational post-migration validation.

Chung minh (CA R1 review §6.4-6.7):
  [1] FRESH DB   : `migrate.py up` exit0 (operational validation in-path PASS) + `fresh-validate` (exact canonical) exit0.
  [2] EXISTING+extra valid tiers: `migrate.py up` exit0 (operational TOLERATES extra tiers) + extra tiers PRESERVED;
                   `fresh-validate` exit!=0 (canonical exact REJECTS extra) -> chung minh vi sao canonical NGOAI `up`.
  [3] NEGATIVE existing-data: operational validation REJECT wrong description / non-NULL serving / missing product / no tier.
  [4] FULL-CHAIN 018->028: existing DB o 018 -> `migrate.py up` 019..028 exit0 (operational in-path) -> head 028.
  [5] NEGATIVE qua RUNNER deploy path: `migrate.py validate` exit!=0 tren wrong description.

Khong PII trong output (chi rc/count/boolean). Chay:
  docker run --rm --network alpha3s_default -v <worktree>:/srv -w /srv --entrypoint python alpha3s-api scripts/m2_r1_remediation_test.py
"""
import asyncio
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
ADMIN = "postgresql://alpha3s:alpha3s@db:5432/postgres"
OP_SQL = (ROOT / "scripts" / "operational_seed_validation.sql").read_text(encoding="utf-8")

_ms = importlib.util.spec_from_file_location("migrate_mod", ROOT / "scripts" / "migrate.py")
migrate_mod = importlib.util.module_from_spec(_ms)
_ms.loader.exec_module(migrate_mod)

_fail = []


def ck(cond, label):
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        _fail.append(label)


def _url(name):
    return f"postgresql://alpha3s:alpha3s@db:5432/{name}"


def run_migrate(name, *args):
    env = dict(os.environ)
    env["DATABASE_URL"] = _url(name)
    env["MIGRATE_ACTOR"] = "r1remed"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "migrate.py"), *args],
                       cwd=str(ROOT), env=env, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)


async def recreate(admin, name):
    await admin.execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{name}' AND pid<>pg_backend_pid()")
    await admin.execute(f"DROP DATABASE IF EXISTS {name}")
    await admin.execute(f"CREATE DATABASE {name}")


async def apply_through(conn, through):
    migs = migrate_mod.discover()
    await migrate_mod.ensure_table(conn)
    for m in migs:
        if int(m["version"][:3]) > through:
            break
        if m["transactional"]:
            async with conn.transaction():
                await conn.execute(m["text"])
                await conn.execute(
                    "INSERT INTO schema_migrations(version,checksum,applied_by,transactional) "
                    "VALUES($1,$2,'rehearsal',$3) ON CONFLICT (version) DO NOTHING",
                    m["version"], m["checksum"], m["transactional"])
        else:
            await conn.execute(m["text"])
            await conn.execute(
                "INSERT INTO schema_migrations(version,checksum,applied_by,transactional) "
                "VALUES($1,$2,'rehearsal',$3) ON CONFLICT (version) DO NOTHING",
                m["version"], m["checksum"], m["transactional"])


async def expect_reject(conn, mutate_sql, label):
    tr = conn.transaction()
    await tr.start()
    await conn.execute(mutate_sql)
    raised = False
    try:
        await conn.execute(OP_SQL)
    except asyncpg.PostgresError:
        raised = True
    await tr.rollback()
    ck(raised, label)


async def main():  # noqa: C901
    admin = await asyncpg.connect(ADMIN)
    dbs = ["r1_fresh", "r1_exist", "r1_chain", "r1_negrun"]
    try:
        print("[1] FRESH DB — migrate up (operational in-path) + fresh-validate (canonical exact)")
        await recreate(admin, "r1_fresh")
        rc, out = run_migrate("r1_fresh", "up")
        ck(rc == 0, f"fresh: migrate up exit 0 [rc={rc}]")
        ck("Post-migration validations pass" in out, "fresh: operational validation ran inside up")
        rc2, _ = run_migrate("r1_fresh", "fresh-validate")
        ck(rc2 == 0, f"fresh: fresh-validate (exact canonical 3 tiers) exit 0 [rc={rc2}]")
        c = await asyncpg.connect(_url("r1_fresh"))
        head = await c.fetchval("SELECT max(version) FROM schema_migrations")
        await c.close()
        ck(head.startswith("028"), f"fresh: head=028 ({head})")

        print("[2] EXISTING + extra valid tiers — up exit0 + preserved; fresh-validate rejects")
        await recreate(admin, "r1_exist")
        rc, _ = run_migrate("r1_exist", "up")
        ck(rc == 0, f"exist: initial up exit 0 [rc={rc}]")
        c = await asyncpg.connect(_url("r1_exist"))
        pid = await c.fetchval("SELECT id FROM products WHERE sku='3S-100G'")
        n0 = await c.fetchval("SELECT count(*) FROM price_tiers WHERE product_id=$1", pid)
        await c.execute("INSERT INTO price_tiers(product_id,min_qty,unit_price_vnd) VALUES ($1,10,150000),($1,50,130000)", pid)
        n1 = await c.fetchval("SELECT count(*) FROM price_tiers WHERE product_id=$1", pid)
        await c.close()
        ck(n1 == n0 + 2, f"exist: added 2 extra valid tiers ({n0}->{n1})")
        rc, _ = run_migrate("r1_exist", "up")
        ck(rc == 0, f"exist+extra: migrate up exit 0 (operational tolerates extra tiers) [rc={rc}]")
        c = await asyncpg.connect(_url("r1_exist"))
        n2 = await c.fetchval("SELECT count(*) FROM price_tiers WHERE product_id=$1", pid)
        await c.close()
        ck(n2 == n1, f"exist+extra: extra tiers PRESERVED (count={n2})")
        rcf, _ = run_migrate("r1_exist", "fresh-validate")
        ck(rcf != 0, f"exist+extra: fresh-validate REJECTS non-canonical exit!=0 [rc={rcf}] (vi sao canonical ngoai up)")

        print("[3] NEGATIVE existing-data — operational validation must REJECT")
        c = await asyncpg.connect(_url("r1_fresh"))
        await expect_reject(c, "UPDATE products SET description='mo ta sai chua duyet' WHERE sku='3S-100G'",
                            "reject: wrong/unapproved description")
        await expect_reject(c, "UPDATE products SET serving_size_g=50 WHERE sku='3S-100G'",
                            "reject: non-NULL serving_size_g")
        await expect_reject(c, "UPDATE products SET sku='3S-100G-BROKEN' WHERE sku='3S-100G'",
                            "reject: missing required product (sku 3S-100G absent)")
        await expect_reject(c, "DELETE FROM price_tiers WHERE product_id=(SELECT id FROM products WHERE sku='3S-100G')",
                            "reject: no price tier")
        okpass = True
        try:
            await c.execute(OP_SQL)
        except asyncpg.PostgresError as e:  # noqa: BLE001
            okpass = False
            print(f"   [control] operational raised on clean canonical: {e}")
        ck(okpass, "control: operational PASSES on clean canonical")
        await c.close()

        print("[4] FULL-CHAIN 018->028 synthetic (existing at 018 -> migrate up 019..028)")
        await recreate(admin, "r1_chain")
        c = await asyncpg.connect(_url("r1_chain"))
        await apply_through(c, 18)
        head18 = await c.fetchval("SELECT max(version) FROM schema_migrations")
        await c.close()
        ck(head18.startswith("018"), f"chain: seeded existing at {head18}")
        rc, _ = run_migrate("r1_chain", "up")
        ck(rc == 0, f"chain: migrate up 019..028 exit 0 (operational in-path) [rc={rc}]")
        c = await asyncpg.connect(_url("r1_chain"))
        head28 = await c.fetchval("SELECT max(version) FROM schema_migrations")
        nmig = await c.fetchval("SELECT count(*) FROM schema_migrations")
        await c.close()
        ck(head28.startswith("028") and nmig == 28, f"chain: head=028 count=28 ({head28}/{nmig})")

        print("[5] NEGATIVE via runner deploy path — migrate validate exit != 0")
        await recreate(admin, "r1_negrun")
        rc, _ = run_migrate("r1_negrun", "up")
        ck(rc == 0, f"negrun: baseline up exit 0 [rc={rc}]")
        c = await asyncpg.connect(_url("r1_negrun"))
        await c.execute("UPDATE products SET description='mo ta sai' WHERE sku='3S-100G'")
        await c.close()
        rcv, outv = run_migrate("r1_negrun", "validate")
        ck(rcv != 0 and "VALIDATION FAIL" in outv, f"negrun: migrate validate exit!=0 tren wrong description [rc={rcv}]")
    finally:
        for n in dbs:
            try:
                await admin.execute(
                    f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{n}' AND pid<>pg_backend_pid()")
                await admin.execute(f"DROP DATABASE IF EXISTS {n}")
            except Exception:  # noqa: BLE001
                pass
        await admin.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — F-R1-01 remediation: operational (existing-safe) trong up; canonical fresh-only goi tuong minh; "
          "existing+extra tiers up exit0 + preserved; negatives reject; full-chain 018->028 exit0; no PII")


if __name__ == "__main__":
    asyncio.run(main())
