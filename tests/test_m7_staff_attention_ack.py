"""M7 staff_attention acknowledgement (CA Review 292-02) — bot ack 1 lần (rate-limit) thay vì im hoàn toàn.

- staff_ack_text: thuần, CI-safe (không hứa đã xử lý xong, không nói tiền/giao).
- DB test (skipif not M6_TEST_DB): tin đầu -> ack; tin sau trong cooldown -> SILENT; retry cùng command_key -> replay
  cùng ack; KHÔNG đổi order/payment/shipment.
"""
import os

import pytest

from app.services.fulfillment import conversation as C


def test_staff_ack_text_truthful():
    t = C.staff_ack_text(245)
    assert "#245" in t and "nhân viên" in t
    low = t.lower()
    # KHÔNG hứa đã nhận tiền / đã giao / đã xử lý xong
    assert "đã nhận thanh toán" not in low and "đã thu tiền" not in low and "đã giao" not in low


DB = os.environ.get("M6_TEST_DB") == "1"


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_staff_attention_ack_then_silent_ratelimited():
    import time

    import asyncpg

    dsn = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    try:
        tag = f"ACK-{int(time.time()*1000)}"
        psid = f"tg:{tag}"
        cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'A','0900000000') RETURNING id", psid)
        oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                                  "VALUES($1,'confirmed',200000,'telegram_customer') RETURNING id", cid)
        await conn.execute("INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,policy_version,"
                           "attention_reason,attention_at) VALUES($1,'telegram_customer',$2,'staff_attention',1,"
                           "'quote',now())", oid, psid)

        async def say(text, key):
            async with conn.transaction():
                return await C.handle_customer_text(conn, psid, text, command_key=key)

        r1 = await say("chuyển khoản", f"{tag}-1")           # tin đầu -> ack
        r2 = await say("alo shop ơi", f"{tag}-2")            # tin sau trong cooldown -> SILENT
        r1replay = await say("chuyển khoản", f"{tag}-1")     # retry cùng command_key -> replay cùng ack
        assert isinstance(r1, str) and "nhân viên" in r1
        assert r2 is C.SILENT
        assert r1replay == r1                                 # replay, không ack lần 2
        # KHÔNG tạo/đổi payment/shipment
        assert await conn.fetchval("SELECT count(*) FROM payments WHERE order_id=$1", oid) == 0
        assert await conn.fetchval("SELECT count(*) FROM shipments WHERE order_id=$1", oid) == 0
        # step vẫn staff_attention (không tự đổi)
        assert await conn.fetchval("SELECT step FROM fulfillment_conversations WHERE order_id=$1", oid) == "staff_attention"
        # đúng 1 staff_ack event trong episode
        acks = await conn.fetchval("SELECT count(*) FROM fulfillment_conversation_events WHERE order_id=$1 "
                                   "AND (detail->>'staff_ack')='1'", oid)
        assert acks == 1
    finally:
        await conn.close()
