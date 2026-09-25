"""CA Directive 387 §5/§7 — rehearsal migration 072 (legacy backfill validation) tren DB SCRATCH rieng.

  docker run --rm --network m5lab -e PYTHONPATH=/srv -e ADMIN_DSN=postgresql://alpha3s:alpha3s@m5lab-db:5432/postgres \
    -v D:/alpha3s:/srv -w /srv alpha3s-api:latest python scripts/d387_migration_rehearsal.py

Chung minh (KHONG dung DB that/prod):
  1. Fresh DB -> 001..071 -> seed legacy: tg:/manual:/numeric PSID + 1 dong KHONG khop quy tac + order thieu origin_channel.
  2. Ap 072 -> RAISE (guard) -> transaction rollback: KHONG cot moi, KHONG gan gia tri gia.
  3. Xu ly dong khong khop (mo phong hanh dong PO/CA per-row) -> ap 072 OK: backfill dung quy tac, NOT NULL, UNIQUE
     (channel, external_chat_id), order legacy lay kenh cua customer; re-apply 072 idempotent.
  4. Status 'cancelled' hop le cho shipments/payments/fulfillment_conversations; payment_instruction_voids append-only;
     don dashboard MOI thieu staff -> bi CHECK chan.
"""
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / "migrations"
DBNAME = "d387_rehearsal"
_fail: list[str] = []


def check(cond, label):
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        _fail.append(label)


async def apply(conn, path: Path):
    async with conn.transaction():
        await conn.execute(path.read_text(encoding="utf-8"))


async def main():
    admin_dsn = os.environ.get("ADMIN_DSN", "postgresql://alpha3s:alpha3s@m5lab-db:5432/postgres")
    admin = await asyncpg.connect(admin_dsn)
    await admin.execute(f"DROP DATABASE IF EXISTS {DBNAME}")
    await admin.execute(f"CREATE DATABASE {DBNAME}")
    await admin.close()
    conn = await asyncpg.connect(admin_dsn.rsplit("/", 1)[0] + "/" + DBNAME)
    try:
        migs = sorted(p for p in MIG.glob("*.sql") if p.name[:3].isdigit())
        m072 = next(p for p in migs if p.name.startswith("072_"))
        for p in migs:
            if p.name < "072_":
                await apply(conn, p)
        print(f"[1] applied {sum(1 for p in migs if p.name < '072_')} migrations 001..071")

        # --- seed legacy (quy uoc luu tru truoc 387) ---
        ids = {}
        for k, psid in (("tg", "tg:5550001"), ("manual", "manual:abc123"), ("msg", "24681357"), ("bad", "weird:x1")):
            ids[k] = await conn.fetchval("INSERT INTO customers (psid, name) VALUES ($1, 'Legacy') RETURNING id", psid)
        o_tg = await conn.fetchval("INSERT INTO orders (customer_id, status, total_vnd) VALUES ($1,'new',1) RETURNING id",
                                   ids["tg"])
        o_bad = await conn.fetchval("INSERT INTO orders (customer_id, status, total_vnd) VALUES ($1,'new',1) "
                                    "RETURNING id", ids["bad"])
        o_msg = await conn.fetchval("INSERT INTO orders (customer_id, status, total_vnd, origin_channel) "
                                    "VALUES ($1,'new',1,'messenger') RETURNING id", ids["msg"])

        # --- [2] guard: dong khong khop -> RAISE, rollback sach ---
        raised = None
        try:
            await apply(conn, m072)
        except asyncpg.PostgresError as e:
            raised = str(e)
        check(raised is not None and "khong khop quy tac identity" in raised, "[2] 072 RAISE khi co customer khong khop quy tac")
        check(await conn.fetchval("SELECT count(*) FROM information_schema.columns WHERE table_name='customers' "
                                  "AND column_name='channel'") == 0, "[2] rollback sach: customers.channel KHONG ton tai")
        check(await conn.fetchval("SELECT to_regclass('payment_instruction_voids')") is None,
              "[2] rollback sach: payment_instruction_voids KHONG ton tai")

        # --- [3] xu ly per-row (mo phong quyet dinh PO/CA: dong test khong co ChatID that -> xoa) ---
        await conn.execute("DELETE FROM orders WHERE id=$1", o_bad)
        await conn.execute("DELETE FROM customers WHERE id=$1", ids["bad"])
        await apply(conn, m072)
        rows = {r["psid"]: (r["channel"], r["external_chat_id"]) for r in
                await conn.fetch("SELECT psid, channel, external_chat_id FROM customers")}
        check(rows["tg:5550001"] == ("telegram_customer", "5550001"), "[3] tg: -> telegram_customer, ChatID bo tien to")
        check(rows["manual:abc123"] == ("dashboard", "manual:abc123"), "[3] manual: -> dashboard")
        check(rows["24681357"] == ("messenger", "24681357"), "[3] numeric -> messenger")
        check(await conn.fetchval("SELECT origin_channel FROM orders WHERE id=$1", o_tg) == "telegram_customer",
              "[3] order legacy NULL origin_channel -> kenh cua chinh customer")
        check(await conn.fetchval("SELECT origin_channel FROM orders WHERE id=$1", o_msg) == "messenger",
              "[3] order co san origin_channel giu nguyen")
        nn = await conn.fetch("SELECT table_name, column_name FROM information_schema.columns WHERE is_nullable='NO' AND "
                              "((table_name='customers' AND column_name IN ('channel','external_chat_id')) OR "
                              "(table_name='orders' AND column_name IN ('customer_id','origin_channel')))")
        check(len(nn) == 4, "[3] NOT NULL: customers.channel/external_chat_id, orders.customer_id/origin_channel")
        dup = None
        try:
            await conn.execute("INSERT INTO customers (psid, channel, external_chat_id) VALUES ('tg:x2','telegram_customer',"
                               "'5550001')")
        except asyncpg.UniqueViolationError as e:
            dup = e.constraint_name
        check(dup == "uq_customers_channel_chat", "[3] UNIQUE (channel, external_chat_id)")
        bad_ch = False
        try:
            await conn.execute("INSERT INTO customers (psid, channel, external_chat_id) VALUES ('z1','zalo','z1')")
        except asyncpg.CheckViolationError:
            bad_ch = True
        check(bad_ch, "[3] ck_customers_channel chan kenh ngoai danh sach")
        no_ch = False
        try:
            await conn.execute("INSERT INTO customers (psid) VALUES ('tg:no-channel')")
        except asyncpg.NotNullViolationError:
            no_ch = True
        check(no_ch, "[3] customer moi THIEU channel -> bi chan (khong suy tu psid)")
        await apply(conn, m072)
        check(True, "[3] re-apply 072 idempotent (khong loi)")

        # --- [4] lifecycle cancelled + void append-only + dashboard staff ---
        cid = ids["tg"]
        oid = await conn.fetchval("INSERT INTO orders (customer_id,status,total_vnd,origin_channel) "
                                  "VALUES ($1,'new',1,'telegram_customer') RETURNING id", cid)
        await conn.execute("INSERT INTO shipments(order_id,status,zone,fee_status) VALUES($1,'cancelled','province','unknown')",
                           oid)
        pay = await conn.fetchval("INSERT INTO payments(order_id,method,amount_due_vnd,status) "
                                  "VALUES($1,'BANK_TRANSFER',1,'cancelled') RETURNING id", oid)
        await conn.execute("INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step) "
                           "VALUES($1,'telegram_customer','tg:5550001','cancelled')", oid)
        check(True, "[4] 'cancelled' hop le cho shipments/payments/fulfillment_conversations")
        bank = await conn.fetchval("INSERT INTO bank_accounts(bank,account_number,holder_name,active,is_test) "
                                   "VALUES('B','1','H',false,true) RETURNING id")
        iid = await conn.fetchval(
            "INSERT INTO payment_instructions(order_id,payment_id,bank_account_id,account_version,bank_snapshot,"
            "account_number_snapshot,holder_snapshot,transfer_content,amount_vnd,is_test,command_key) "
            "VALUES($1,$2,$3,1,'{}'::jsonb,'1','H','X',1,true,'k') RETURNING id", oid, pay, bank)
        await conn.execute("INSERT INTO payment_instruction_voids(instruction_id,order_id,reason,voided_by) "
                           "VALUES($1,$2,'order cancelled: test','t')", iid, oid)
        blocked = False
        try:
            await conn.execute("UPDATE payment_instruction_voids SET reason='x' WHERE instruction_id=$1", iid)
        except asyncpg.RaiseError:
            blocked = True
        check(blocked, "[4] payment_instruction_voids append-only (UPDATE bi chan)")
        dash_blocked = False
        try:
            await conn.execute("INSERT INTO orders (customer_id,status,total_vnd,origin_channel) VALUES ($1,'new',1,'dashboard')",
                               ids["manual"])
        except asyncpg.CheckViolationError:
            dash_blocked = True
        check(dash_blocked, "[4] don dashboard MOI thieu created_by_staff_id -> bi chan")
    finally:
        await conn.close()
        admin = await asyncpg.connect(admin_dsn)
        await admin.execute(f"DROP DATABASE IF EXISTS {DBNAME}")
        await admin.close()
    print("RESULT:", "ALL PASS" if not _fail else f"{len(_fail)} FAIL: {_fail}")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    asyncio.run(main())
