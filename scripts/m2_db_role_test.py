#!/usr/bin/env python3
"""M2 Slice 1 evidence — migration chain 001..024 + runtime DB-role least-privilege (AC-M2-14).

Chay tren throwaway DB (m2s1_itest) trong postgres container:
  docker exec alpha3s-api-1 python scripts/m2_db_role_test.py

Chung minh:
  1. Toan bo migrations 001..024 ap duoc tu fresh DB (moi migration tu-validate postcondition).
  2. Runtime role `alpha3s_app` least-privilege bang SET ROLE (doc lap voi trigger):
     - CO: INSERT/SELECT/UPDATE tren bang van hanh.
     - KHONG: UPDATE/DELETE append-only ledger (inventory_movements, order_events, delivery_attempts).
     - KHONG: UPDATE/DELETE audit_log (no audit bypass).
     - KHONG: DDL (CREATE TABLE).
     - KHONG: ghi schema_migrations.
     - KHONG: superuser/createrole/createdb.
"""
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
ADMIN_DB = os.environ.get("ADMIN_DB_URL", "postgresql://alpha3s:alpha3s@db:5432/postgres")
TEST_DB = "m2s1_itest"
TEST_URL = "postgresql://alpha3s:alpha3s@db:5432/" + TEST_DB

_fail = []


def check(cond: bool, label: str):
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        _fail.append(label)


async def expect_denied(conn, sql: str, label: str):
    """Assert SQL raises insufficient_privilege (SQLSTATE 42501)."""
    try:
        await conn.execute(sql)
        check(False, label + " (expected denied, but SUCCEEDED)")
    except asyncpg.InsufficientPrivilegeError:
        check(True, label + " (denied 42501)")
    except asyncpg.PostgresError as e:
        # van coi la fail neu loi khac privilege
        check(False, f"{label} (unexpected {e.sqlstate}: {e})")


async def main():
    # --- (re)create throwaway DB ---
    admin = await asyncpg.connect(ADMIN_DB)
    await admin.execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{TEST_DB}' AND pid<>pg_backend_pid()"
    )
    await admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    await admin.execute(f"CREATE DATABASE {TEST_DB}")
    await admin.close()

    conn = await asyncpg.connect(TEST_URL)
    try:
        # --- schema_migrations phai ton tai TRUOC 024 (migrate.py tao luc startup) de REVOKE fire ---
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT, "
            "transactional BOOLEAN NOT NULL DEFAULT true)"
        )
        # --- apply migrations 001..024 in order (moi file mot transaction) ---
        files = sorted(p for p in MIG.glob("*.sql") if p.name[:3].isdigit())
        print(f"[1] Applying {len(files)} migrations on fresh {TEST_DB} ...")
        for p in files:
            sql = p.read_text(encoding="utf-8")
            try:
                async with conn.transaction():
                    await conn.execute(sql)
            except Exception as e:  # noqa: BLE001
                check(False, f"apply {p.name}: {e}")
                raise
        check(True, f"all {len(files)} migrations applied (postconditions passed)")

        # --- role exists + not overprivileged ---
        row = await conn.fetchrow(
            "SELECT rolsuper, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname='alpha3s_app'"
        )
        check(row is not None, "runtime role alpha3s_app exists")
        if row:
            check(
                not (row["rolsuper"] or row["rolcreaterole"] or row["rolcreatedb"]),
                "runtime role NOT super/createrole/createdb",
            )

        # --- seed a location+balance as OWNER so runtime co du lieu de thao tac ---
        await conn.execute(
            "INSERT INTO inventory_locations (code,name,location_type,is_default) "
            "VALUES ('KHO-CHINH','Kho chinh','fulfillment',true)"
        )
        loc = await conn.fetchval("SELECT id FROM inventory_locations WHERE code='KHO-CHINH'")
        prod = await conn.fetchval("INSERT INTO products (sku,name,price_vnd,stock) "
                                   "VALUES ('T-1','Test',170000,100) RETURNING id")
        await conn.execute(
            "INSERT INTO inventory_balances (location_id,product_id,on_hand,reserved) "
            "VALUES ($1,$2,100,0)", loc, prod,
        )

        # ================= SET ROLE alpha3s_app : least privilege =================
        print("[2] SET ROLE alpha3s_app — privilege assertions ...")
        await conn.execute("SET ROLE alpha3s_app")

        # POSITIVE: van hanh binh thuong
        try:
            await conn.execute(
                "UPDATE inventory_balances SET reserved=reserved+1 WHERE location_id=$1 AND product_id=$2",
                loc, prod,
            )
            check(True, "runtime CAN UPDATE inventory_balances (operational)")
        except asyncpg.PostgresError as e:
            check(False, f"runtime UPDATE balances failed: {e}")

        try:
            await conn.fetchval("SELECT count(*) FROM orders")
            check(True, "runtime CAN SELECT orders (operational)")
        except asyncpg.PostgresError as e:
            check(False, f"runtime SELECT orders failed: {e}")

        # runtime CAN INSERT append-only (append la hop le)
        try:
            await conn.execute(
                "INSERT INTO inventory_movements (id,location_id,product_id,movement_type,"
                "on_hand_delta,reserved_delta,before_on_hand,after_on_hand,before_reserved,after_reserved,"
                "reference_type,reference_id,idempotency_key,actor_type,actor_id,correlation_id) "
                "VALUES (gen_random_uuid(),$1,$2,'reserve',0,1,100,100,0,1,'test','r1','k-mv-1','system','t',gen_random_uuid())",
                loc, prod,
            )
            check(True, "runtime CAN INSERT inventory_movements (append)")
        except asyncpg.PostgresError as e:
            check(False, f"runtime INSERT movement failed: {e}")

        # NEGATIVE: append-only ledgers — no UPDATE/DELETE (privilege, doc lap trigger)
        await expect_denied(conn, "UPDATE inventory_movements SET reason='x'",
                            "runtime CANNOT UPDATE inventory_movements")
        await expect_denied(conn, "DELETE FROM inventory_movements",
                            "runtime CANNOT DELETE inventory_movements")
        await expect_denied(conn, "UPDATE order_events SET reason='x'",
                            "runtime CANNOT UPDATE order_events")
        await expect_denied(conn, "DELETE FROM delivery_attempts",
                            "runtime CANNOT DELETE delivery_attempts")
        # audit no bypass
        await expect_denied(conn, "DELETE FROM audit_log",
                            "runtime CANNOT DELETE audit_log")
        await expect_denied(conn, "UPDATE audit_log SET action='x'",
                            "runtime CANNOT UPDATE audit_log")
        # no DDL
        await expect_denied(conn, "CREATE TABLE runtime_should_not (id int)",
                            "runtime CANNOT CREATE TABLE (no DDL)")
        # no migration tracking write
        await expect_denied(conn, "INSERT INTO schema_migrations (version) VALUES ('999_x')",
                            "runtime CANNOT write schema_migrations")

        await conn.execute("RESET ROLE")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)} checks) -> " + "; ".join(_fail))
        sys.exit(1)
    print("RESULT: PASS — migration chain 001..024 + AC-M2-14 least-privilege proven")


if __name__ == "__main__":
    asyncio.run(main())
