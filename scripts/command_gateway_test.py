#!/usr/bin/env python3
"""Order gateway routing evidence (I-B M1 Slice 4).

Chung minh:
  FLAG ON  + command_ctx: tools.create_order (AI) va orders.create_order_manual (staff) route qua
             command service -> co command_executions row + order + receipt; duplicate idempotent.
  FLAG OFF + command_ctx : giu nguyen legacy -> KHONG tao command row (backward-compat).
  FLAG ON  + ctx=None    : giu nguyen legacy (partial rollout an toan).

Chay tren throwaway DB da migrate 001-019:
  docker exec -e DATABASE_URL=...m1_itest -e PYTHONPATH=/srv -w /srv api python scripts/command_gateway_test.py
"""
import asyncio
import sys
import uuid

import asyncpg

from app.config import settings
from app.services import auth_service, orders, tools

C = {"customer_name": "Le Thi B", "phone": "0987654321", "address": "5 Tran Hung Dao, HN"}


def _db() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def cmd_count(conn, key) -> int:
    return await conn.fetchval("SELECT count(*) FROM command_executions WHERE idempotency_key=$1", key)


async def orders_count(conn) -> int:
    return await conn.fetchval("SELECT count(*) FROM orders")


async def reset(conn):
    await conn.execute("TRUNCATE order_items, orders, command_executions, outbox_events, "
                       "delivery_attempts, price_overrides RESTART IDENTITY CASCADE")
    await conn.execute("UPDATE products SET stock=1000 WHERE sku='3S-100G'")


async def main() -> int:  # noqa: C901
    conn = await asyncpg.connect(_db())
    fails: list[str] = []
    try:
        await reset(conn)
        st = await auth_service.create_staff_user("gw_staff", "pw12345678", "GW", role_key="admin")
        staff_id = str(st["id"])

        # === FLAG ON: AI path routes -> command + receipt (CR-04R: gateway derive key từ provider
        # message id + business identity; command_ctx KHÔNG precompute key, KHÔNG dùng tool_call_id) ===
        settings.m1_reliable_order_command = True
        ctx_ai = {"channel": "messenger", "actor_type": "customer", "actor_id": "psid-gw",
                  "conversation_id": None, "causation_id": "mid-gw-1", "provider_message_id": "mid-gw-1"}
        r = await tools.create_order(psid="psid-gw", sku="3S-100G", quantity=1, command_ctx=ctx_ai, **C)
        if "error" in r or "receipt" not in r or not r.get("order_id"):
            fails.append(f"ON/AI: khong route qua command: {r}")
        if r.get("duplicate") is not False:
            fails.append(f"ON/AI: lan dau phai duplicate=False: {r.get('duplicate')}")
        if await conn.fetchval("SELECT count(*) FROM command_executions WHERE idempotency_scope=$1",
                               "order.create:messenger:psid-gw") != 1:
            fails.append("ON/AI: khong co command_executions row (scope)")

        # duplicate: cùng provider message id + cùng nội dung -> duplicate True, khong order moi
        n0 = await orders_count(conn)
        r2 = await tools.create_order(psid="psid-gw", sku="3S-100G", quantity=1, command_ctx=ctx_ai, **C)
        if not (r2.get("duplicate") and r2.get("order_id") == r.get("order_id")):
            fails.append(f"ON/AI: duplicate khong tra receipt cu: {r2}")
        if await orders_count(conn) != n0:
            fails.append("ON/AI: duplicate tao order moi")

        # === FLAG ON: manual staff path routes ===
        man_key = "gw-manual-" + uuid.uuid4().hex
        ctx_man = {"channel": "dashboard", "actor_type": "staff", "actor_id": staff_id,
                   "idempotency_key": man_key}
        rm = await orders.create_order_manual(sku="3S-100G", quantity=2, unit_price_vnd=140000,
                                              psid=None, command_ctx=ctx_man, **C)
        if "error" in rm or "receipt" not in rm or not rm.get("order_id"):
            fails.append(f"ON/manual: khong route qua command: {rm}")
        if rm.get("unit_price_vnd") != 140000 or rm.get("total_vnd") != 280000:
            fails.append(f"ON/manual: gia staff sai: {rm.get('unit_price_vnd')}/{rm.get('total_vnd')}")
        if await cmd_count(conn, man_key) != 1:
            fails.append("ON/manual: khong co command row")

        # === FLAG ON + ctx=None -> legacy (khong command) ===
        c_before = await conn.fetchval("SELECT count(*) FROM command_executions")
        rn = await tools.create_order(psid="psid-legacy1", sku="3S-100G", quantity=1, command_ctx=None, **C)
        if "receipt" in rn or "error" in rn:
            fails.append(f"ON/ctx=None: phai legacy: {rn}")
        if await conn.fetchval("SELECT count(*) FROM command_executions") != c_before:
            fails.append("ON/ctx=None: legacy van tao command row")

        # === FLAG OFF + ctx present -> legacy (khong command) ===
        settings.m1_reliable_order_command = False
        c_before = await conn.fetchval("SELECT count(*) FROM command_executions")
        ro = await tools.create_order(psid="psid-legacy2", sku="3S-100G", quantity=1,
                                      command_ctx=ctx_ai, **C)
        if "receipt" in ro or "error" in ro or not ro.get("order_id"):
            fails.append(f"OFF: phai legacy tao order: {ro}")
        if await conn.fetchval("SELECT count(*) FROM command_executions") != c_before:
            fails.append("OFF: legacy van tao command row (flag khong chan)")
    finally:
        settings.m1_reliable_order_command = False
        await conn.close()

    if fails:
        print("COMMAND-GATEWAY FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("COMMAND-GATEWAY PASS: ON/AI route+receipt+dup-idempotent; ON/manual staff-priced route; "
          "ON/ctx=None legacy; OFF legacy (flag gate dung, khong tao command row).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
