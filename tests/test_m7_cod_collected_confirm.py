"""M7 COD-collected confirmation (CA Directive 293) — focused tests.

- notify_payment routing (kind->event) la logic co the kiem qua rehearsal DB; o day giu 2 test THUAN (sync, CI-safe):
  contract _ADVANCE + _settle_status cho COD (293 semantics) — khong DB, khong asyncio.
- Cac invariant tien/notify/idempotency day du o scripts/m7_cod_collected_confirm_rehearsal.py (DB, m5lab).
- 1 test DB (skipif not M6_TEST_DB) chay exact cod_collected e2e (received once + status collected + 1 confirmation).
"""
import os

import pytest

from app.services.payment import payment_service as P


def test_cod_settle_status_is_collected_not_reconciled():
    # CA Directive 293: COD exact settle -> 'collected' (KHONG 'reconciled'); reconciled chi qua buoc rieng.
    assert P._settle_status("COD") == "collected"
    assert P._settle_status("BANK_TRANSFER") == "confirmed"


def test_advance_map_cod_semantics():
    # cod_collected = cod_settle (mốc tiền+confirm); reconciled = cod_reconcile chỉ từ 'collected'.
    assert P._ADVANCE[("COD", "cod_collected")][0] == "cod_settle"
    assert P._ADVANCE[("COD", "reconciled")] == ("cod_reconcile", ("collected",))
    # BANK_TRANSFER giữ nguyên settle semantics.
    assert P._ADVANCE[("BANK_TRANSFER", "shop_confirmed_received")][0] == "settle"


DB = os.environ.get("M6_TEST_DB") == "1"


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_cod_collected_exact_confirms_and_completes():
    """exact cod_collected -> received==due (1 lần), status collected, conversation completed, đúng 1 confirmation;
    reconciled sau đó -> accounting-only (received không đổi, 0 notify mới)."""
    import time

    import asyncpg

    from app.services.fulfillment import shipment_service as ship

    dsn = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    try:
        tag = f"CODT-{int(time.time()*1000)}"
        psid = f"tg:{tag}"
        cid = await conn.fetchval("INSERT INTO customers (psid, channel, external_chat_id, name,phone) VALUES ($1, 'telegram_customer', $1, 'T','0900000000') RETURNING id", psid)
        pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
                                  "VALUES($1,'CF',100000,999,300,'hũ') RETURNING id", tag)
        oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                                  "VALUES($1,'confirmed',200000,'telegram_customer') RETURNING id", cid)
        await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,2,100000)",
                           oid, pid)
        rid = await conn.fetchval(
            "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,"
            "method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,'66','24169','current',1.0) "
            "RETURNING id")
        await conn.execute("INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,"
                           "dataset_version,verification_method,bound_by) VALUES($1,$2,'66','24169','V','test','t')",
                           oid, rid)
        async with conn.transaction():
            await ship.auto_quote(conn, oid, actor="s")
            p = await P.ensure_payment(conn, oid, method="COD", actor="s")
            await conn.execute("INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,method,"
                               "policy_version) VALUES($1,'telegram_customer',$2,'cod_handoff','COD',1)", oid, psid)
        due = p["amount_due_vnd"]

        async def notif():
            return await conn.fetchval("SELECT count(*) FROM outbox_events WHERE (payload->>'order_id')::bigint=$1 "
                                       "AND event_type='payment.confirmed.notify'", oid)
        async with conn.transaction():
            r = await P.record_evidence(conn, oid, kind="cod_collected", amount_vnd=due, recorded_by="d",
                                        command_key=f"{tag}:coll")
        recv = await conn.fetchval("SELECT amount_received_vnd FROM payments WHERE order_id=$1", oid)
        step = await conn.fetchval("SELECT step FROM fulfillment_conversations WHERE order_id=$1", oid)
        assert r["status"] == "collected" and recv == due and step == "completed" and await notif() == 1

        # CA Review 294-01: confirmation enqueued tại collected phải KHÔNG stale sau khi reconcile (successor),
        # nếu không outbox worker sẽ hủy -> khách mất confirmation.
        from app.services.command import outbox_worker as ow
        evrow = await conn.fetchrow("SELECT payload FROM outbox_events WHERE (payload->>'order_id')::bigint=$1 "
                                    "AND event_type='payment.confirmed.notify'", oid)
        pl = evrow["payload"]
        pl = __import__("json").loads(pl) if isinstance(pl, str) else pl
        sc = pl["stale_check"]
        assert await ow._is_stale(conn, sc) is False   # status collected -> not stale

        async with conn.transaction():
            rr = await P.record_evidence(conn, oid, kind="reconciled", amount_vnd=None, recorded_by="po",
                                         command_key=f"{tag}:rec")
        recv2 = await conn.fetchval("SELECT amount_received_vnd FROM payments WHERE order_id=$1", oid)
        assert rr["status"] == "reconciled" and recv2 == due and await notif() == 1  # no 2nd notify
        assert await ow._is_stale(conn, sc) is False   # 294-01: reconciled (successor) -> vẫn KHÔNG stale
    finally:
        await conn.close()
