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
        cid = await conn.fetchval("INSERT INTO customers (psid, channel, external_chat_id, name,phone) VALUES ($1, 'telegram_customer', $1, 'A','0900000000') RETURNING id", psid)
        oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                                  "VALUES($1,'confirmed',200000,'telegram_customer') RETURNING id", cid)
        await conn.execute("INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,policy_version,"
                           "attention_reason,attention_at) VALUES($1,'telegram_customer',$2,'staff_attention',1,"
                           "'quote',now())", oid, psid)

        async def say(text, key):
            async with conn.transaction():
                return await C.handle_customer_text(conn, psid, text, command_key=key)

        def would_send(reply):
            # CA 299-01: mô phỏng quyết định gửi của listener/orchestrator (isinstance str + strip).
            return isinstance(reply, str) and bool(reply.strip())

        r1 = await say("chuyển khoản", f"{tag}-1")           # tin đầu -> ack (would-send)
        r2 = await say("alo shop ơi", f"{tag}-2")            # tin sau trong cooldown -> SILENT
        r1replay = await say("chuyển khoản", f"{tag}-1")     # CA 299-01: duplicate command_key -> replay SILENT (KHÔNG resend)
        assert isinstance(r1, str) and "nhân viên" in r1 and would_send(r1)
        assert r2 is C.SILENT and not would_send(r2)
        assert r1replay is C.SILENT and not would_send(r1replay)   # replay KHÔNG khiến sender gửi lần 2
        # KHÔNG tạo/đổi payment/shipment
        assert await conn.fetchval("SELECT count(*) FROM payments WHERE order_id=$1", oid) == 0
        assert await conn.fetchval("SELECT count(*) FROM shipments WHERE order_id=$1", oid) == 0
        assert await conn.fetchval("SELECT step FROM fulfillment_conversations WHERE order_id=$1", oid) == "staff_attention"
        acks = await conn.fetchval("SELECT count(*) FROM fulfillment_conversation_events WHERE order_id=$1 "
                                   "AND (detail->>'staff_ack')='1'", oid)
        assert acks == 1
    finally:
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_staff_ack_cooldown_scoped_to_current_episode():
    """CA 299-02: ack cũ trước attention_at mới KHÔNG suppress tin đầu episode mới; ack trong episode suppress tin sau."""
    import time

    import asyncpg

    dsn = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    try:
        tag = f"EPI-{int(time.time()*1000)}"
        psid = f"tg:{tag}"
        cid = await conn.fetchval("INSERT INTO customers (psid, channel, external_chat_id, name,phone) VALUES ($1, 'telegram_customer', $1, 'E','0900000000') RETURNING id", psid)
        oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                                  "VALUES($1,'confirmed',200000,'telegram_customer') RETURNING id", cid)
        # Episode 1: attention_at = 40 phút trước; đã có 1 staff_ack cũ (trong episode cũ).
        await conn.execute("INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,policy_version,"
                           "attention_reason,attention_at) VALUES($1,'telegram_customer',$2,'staff_attention',1,"
                           "'quote',now()-interval '40 min')", oid, psid)
        await conn.execute("INSERT INTO fulfillment_conversation_events(order_id,command_key,source,from_step,to_step,"
                           "detail,reply_text,created_at) VALUES($1,$2,'customer','staff_attention','staff_attention',"
                           "'{\"staff_ack\":\"1\"}'::jsonb,NULL,now()-interval '38 min')", oid, f"{tag}-old")

        async def say(text, key):
            async with conn.transaction():
                return await C.handle_customer_text(conn, psid, text, command_key=key)

        # Re-escalate: episode MỚI -> attention_at = now (ack cũ 38' trước NẰM NGOÀI episode mới).
        await conn.execute("UPDATE fulfillment_conversations SET attention_at=now() WHERE order_id=$1", oid)
        r_new = await say("shop ơi", f"{tag}-new1")     # tin đầu episode mới -> ack (KHÔNG bị ack cũ suppress)
        r_next = await say("còn đó không", f"{tag}-new2")  # tin sau trong episode -> SILENT
        assert isinstance(r_new, str) and "nhân viên" in r_new
        assert r_next is C.SILENT
        # có 1 ack MỚI trong episode hiện tại (created_at >= attention_at)
        new_acks = await conn.fetchval(
            "SELECT count(*) FROM fulfillment_conversation_events e "
            "JOIN fulfillment_conversations c ON c.order_id=e.order_id "
            "WHERE e.order_id=$1 AND (e.detail->>'staff_ack')='1' AND e.created_at >= c.attention_at", oid)
        assert new_acks == 1
    finally:
        await conn.close()
