"""CA Directive 387 — huy don thong nhat + nguoi nhan theo don + identity kenh tuong minh.

Pure (CI-safe): ly do 5-500 (service + envelope), identity helper, status reply don huy, legacy PATCH khong con huy.
DB (skipif not M6_TEST_DB): cascade day du (don chua tien), idempotency/replay, RBAC (thieu order.cancel /
order.cancel.exception), shipment gate + exception, don co tien -> refund_required (khong tu hoan), rollback toan
transaction khi cascade loi, kho nha DUNG 1 lan, loc conversation/worker/outbox, nguoi nhan theo don (M6 board/detail),
identity Dashboard (ChatID noi bo, staff, khong outbox), khach khong bi ghi de ten boi don sau.
"""
import os
import uuid

import pytest

from app.services import customer_identity as ci
from app.services.command import errors, lifecycle, registry
from app.services.command.envelope import Actor
from app.services.fulfillment import cancel_cascade as cc
from app.services.fulfillment import status_reply

REASON = "Khách đổi ý, không mua nữa"


# ============================================================ pure
def test_reason_bounds_after_trim():
    for bad in (None, "", "    ", "abcd", "  abcd  ", "x" * 501, 12345):
        with pytest.raises(ValueError):
            cc.normalize_reason(bad)
    assert cc.normalize_reason("  abcde  ") == "abcde"
    assert cc.normalize_reason("x" * 500) == "x" * 500


def test_cancel_envelope_requires_reason():
    for bad in ({"order_id": 1}, {"order_id": 1, "reason": "ab"}, {"order_id": 1, "reason": "y" * 501}):
        with pytest.raises(errors.CommandError):
            lifecycle.build_lifecycle_envelope(command_type=registry.ORDER_CANCEL, payload=bad,
                                               actor=Actor("staff", "1"), channel="dashboard", idempotency_key="k")
    env = lifecycle.build_lifecycle_envelope(command_type=registry.ORDER_CANCEL,
                                             payload={"order_id": 1, "reason": f"  {REASON}  "},
                                             actor=Actor("staff", "1"), channel="dashboard", idempotency_key="k")
    assert env.payload["reason"] == REASON


def test_identity_helpers():
    assert ci.external_chat_id("telegram_customer", "tg:12345") == "12345"
    assert ci.external_chat_id("messenger", "998877") == "998877"
    with pytest.raises(ci.IdentityError):
        ci.external_chat_id("telegram_customer", "12345")        # khong theo quy uoc listener
    with pytest.raises(ci.IdentityError):
        ci.external_chat_id("zalo", "x")
    a, b = ci.new_dashboard_identity(7), ci.new_dashboard_identity(7)
    assert a.startswith("dashboard:7:") and a != b
    for bad in (0, -1, None, True, "7"):
        with pytest.raises(ci.IdentityError):
            ci.new_dashboard_identity(bad)


def test_status_reply_cancelled_hides_payment():
    t = status_reply.format_status({"id": 9, "order_status": "cancelled", "method": "BANK_TRANSFER",
                                    "pay_status": "awaiting", "transfer_content": "SEVQR 9", "amount_due_vnd": 1})
    assert "đã được huỷ" in t and "SEVQR" not in t and "chuyển khoản" not in t


# ============================================================ DB
DB = os.environ.get("M6_TEST_DB") == "1"
dbonly = pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


async def _staff(conn, role):
    return await conn.fetchval(
        "INSERT INTO staff_users(username,password_hash,password_salt,role_key) VALUES($1,'x','x',$2) RETURNING id",
        f"t387-{role}-{uuid.uuid4().hex[:8]}", role)


async def _seed(conn, *, status="confirmed", ship=None, pay=None, received=0, evidence=None, step="awaiting_transfer",
                reserve=2, channel="telegram_customer", name="Người Nhận A"):
    tag = uuid.uuid4().hex[:10]
    psid = f"tg:387-{tag}" if channel == "telegram_customer" else f"dashboard:1:{tag}"
    cid = await conn.fetchval(
        "INSERT INTO customers(psid,channel,external_chat_id,name,phone) VALUES($1,$2,$3,'Chủ TK','0900000000') "
        "RETURNING id", psid, channel, psid[3:] if channel == "telegram_customer" else psid)
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock) VALUES($1,'CF',100000,50) RETURNING id",
                              f"T387-{tag}")
    oid = await conn.fetchval(
        "INSERT INTO orders(customer_id,status,total_vnd,origin_channel,shipping_name,shipping_phone,shipping_address,"
        "created_by_staff_id) VALUES($1,$2,200000,$3,$4,'0911222333','12 Le Loi',$5) RETURNING id",
        cid, status, channel, name, 1 if channel == "dashboard" else None)
    item = await conn.fetchval("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) "
                               "VALUES($1,$2,$3,100000) RETURNING id", oid, pid, reserve or 1)
    loc = None
    if reserve:
        loc = await conn.fetchval("INSERT INTO inventory_locations(code,name,location_type) VALUES($1,'T','warehouse') "
                                  "RETURNING id", f"T387-{tag}")
        await conn.execute("INSERT INTO inventory_balances(location_id,product_id,on_hand,reserved) VALUES($1,$2,10,$3)",
                           loc, pid, reserve)
        await conn.execute(
            "INSERT INTO inventory_reservations(id,order_id,order_item_id,location_id,product_id,quantity_initial,"
            "quantity_remaining,status,idempotency_key) VALUES($1,$2,$3,$4,$5,$6,$6,'active',$7)",
            uuid.uuid4(), oid, item, loc, pid, reserve, f"t387:{tag}")
        await conn.execute("UPDATE orders SET inventory_status='reserved', inventory_location_id=$2 WHERE id=$1",
                           oid, loc)
    if ship:
        await conn.execute("INSERT INTO shipments(order_id,status,zone,fee_status) VALUES($1,$2,'province','unknown')",
                           oid, ship)
    iid = None
    if pay:
        payid = await conn.fetchval(
            "INSERT INTO payments(order_id,method,amount_due_vnd,amount_received_vnd,status) VALUES($1,$2,200000,$3,$4) "
            "RETURNING id", oid, "BANK_TRANSFER", received, pay)
        bank = await conn.fetchval("INSERT INTO bank_accounts(bank,account_number,holder_name,active,is_test) "
                                   "VALUES('TESTBANK','0001','T',false,true) RETURNING id")
        iid = await conn.fetchval(
            "INSERT INTO payment_instructions(order_id,payment_id,bank_account_id,account_version,bank_snapshot,"
            "account_number_snapshot,holder_snapshot,transfer_content,amount_vnd,is_test,command_key) "
            "VALUES($1,$2,$3,1,'{}'::jsonb,'0001','T',$4,200000,true,$5) RETURNING id",
            oid, payid, bank, f"SEVQR {oid}", f"t387:{tag}")
        if evidence:
            await conn.execute("INSERT INTO payment_events(payment_id,kind,amount_vnd,recorded_by,command_key) "
                               "VALUES($1,$2,$3,'t',$4)", payid, evidence, received or 0, f"t387ev:{tag}")
    if step:
        await conn.execute(
            "INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,policy_version,instruction_id,"
            "transfer_started_at,method) VALUES($1,$2,$3,$4,1,$5,now() - interval '20 minutes',$6)",
            oid, channel, psid, step, iid, "BANK_TRANSFER" if pay else None)
        await conn.execute("INSERT INTO staff_attention(order_id,reason,detail,created_by) "
                           "VALUES($1,'payment_timeout','{}'::jsonb,'t')", oid)
    return {"oid": oid, "cid": cid, "psid": psid, "pid": pid, "loc": loc}


async def _cancel(oid, staff_id, key=None, reason=REASON):
    env = lifecycle.build_lifecycle_envelope(
        command_type=registry.ORDER_CANCEL, payload={"order_id": oid, "reason": reason},
        actor=Actor("staff", str(staff_id)), channel="dashboard", idempotency_key=key or uuid.uuid4().hex)
    return await lifecycle.execute_lifecycle(env)


@dbonly
@pytest.mark.asyncio
async def test_unpaid_cancel_full_cascade_idempotent_one_release():
    from app.services.command import outbox_worker as ow
    from app.services.fulfillment import conversation as C
    conn = await _conn()
    try:
        admin = await _staff(conn, "admin")
        s = await _seed(conn, ship="pending_prep", pay="awaiting")
        oid = s["oid"]
        key = uuid.uuid4().hex
        r = await _cancel(oid, admin, key)
        assert r.outcome == "succeeded", r
        o = await conn.fetchrow("SELECT status, inventory_status FROM orders WHERE id=$1", oid)
        assert (o["status"], o["inventory_status"]) == ("cancelled", "released")
        # order_event + audit mang ly do, before/after, command id
        ev = await conn.fetchrow("SELECT from_status,to_status,reason,actor_id,command_id FROM order_events "
                                 "WHERE order_id=$1 AND event_type='order.cancel'", oid)
        assert ev["from_status"] == "confirmed" and ev["to_status"] == "cancelled" and ev["reason"] == REASON
        assert ev["actor_id"] == str(admin) and str(ev["command_id"]) == r.command_id
        aud = await conn.fetchrow("SELECT after, actor_staff_id FROM audit_log WHERE action='order.cancel' "
                                  "AND entity_id=$1 ORDER BY id DESC LIMIT 1", str(oid))
        assert aud["actor_staff_id"] == admin and REASON in aud["after"]
        # M7 conversation -> cancelled + journal; attention resolved
        fc = await conn.fetchrow("SELECT step FROM fulfillment_conversations WHERE order_id=$1", oid)
        assert fc["step"] == "cancelled"
        j = await conn.fetchrow("SELECT detail FROM fulfillment_conversation_events WHERE order_id=$1 AND command_key=$2",
                                oid, f"order_cancel:{r.command_id}")
        assert j is not None and REASON in j["detail"]
        assert await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND status='open'", oid) == 0
        # M6: shipment/payment cancelled, instruction void
        assert await conn.fetchval("SELECT status FROM shipments WHERE order_id=$1", oid) == "cancelled"
        assert await conn.fetchval("SELECT status FROM payments WHERE order_id=$1", oid) == "cancelled"
        assert await conn.fetchval("SELECT count(*) FROM payment_instructions pi LEFT JOIN payment_instruction_voids v "
                                   "ON v.instruction_id=pi.id WHERE pi.order_id=$1 AND v.instruction_id IS NULL", oid) == 0
        # kho: nha 2 dung 1 lan
        bal = await conn.fetchrow("SELECT reserved FROM inventory_balances WHERE location_id=$1", s["loc"])
        assert bal["reserved"] == 0
        # tin khach chung (khong lo ly do)
        ob = await conn.fetch("SELECT payload::text AS p FROM outbox_events WHERE dedupe_key=$1",
                              f"order_status:{oid}:cancelled")
        assert len(ob) == 1 and REASON not in ob[0]["p"]
        # loc: bot/worker/outbox khong con chon
        assert await C.get_by_customer(conn, s["psid"]) is None
        async with conn.transaction():
            await C.run_due(conn)
        assert await conn.fetchval("SELECT count(*) FROM fulfillment_reminders r JOIN payment_instructions i "
                                   "ON i.id=r.payment_instruction_id WHERE i.order_id=$1", oid) == 0
        assert await ow._is_stale(conn, {"kind": "fulfillment", "order_id": oid, "step": "awaiting_transfer"})
        assert await ow._is_stale(conn, {"kind": "shipment", "order_id": oid, "to_status": "in_transit"})
        # replay cung key -> duplicate, KHONG effect lan 2
        n_mov = await conn.fetchval("SELECT count(*) FROM inventory_movements WHERE order_id=$1", oid)
        r2 = await _cancel(oid, admin, key)
        assert r2.duplicate and r2.outcome == "succeeded"
        # key moi -> reject (da huy), khong doi gi
        r3 = await _cancel(oid, admin)
        assert r3.outcome == "rejected" and r3.error_code == "illegal_order_transition"
        assert await conn.fetchval("SELECT count(*) FROM inventory_movements WHERE order_id=$1", oid) == n_mov == 1
        assert await conn.fetchval("SELECT count(*) FROM order_events WHERE order_id=$1 AND event_type='order.cancel'",
                                   oid) == 1
        assert (await conn.fetchrow("SELECT reserved FROM inventory_balances WHERE location_id=$1", s["loc"]))[0] == 0
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_rbac_viewer_rejected_nothing_changes():
    conn = await _conn()
    try:
        viewer = await _staff(conn, "viewer")
        s = await _seed(conn, ship="pending_prep", pay="awaiting")
        r = await _cancel(s["oid"], viewer)
        assert r.outcome == "rejected" and r.error_code == "forbidden"
        assert await conn.fetchval("SELECT status FROM orders WHERE id=$1", s["oid"]) == "confirmed"
        assert await conn.fetchval("SELECT step FROM fulfillment_conversations WHERE order_id=$1", s["oid"]) \
            == "awaiting_transfer"
        assert await conn.fetchval("SELECT status FROM payments WHERE order_id=$1", s["oid"]) == "awaiting"
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_paid_order_keeps_ledger_opens_refund_required():
    conn = await _conn()
    try:
        admin = await _staff(conn, "admin")
        s = await _seed(conn, ship="pending_prep", pay="confirmed", received=200000,
                        evidence="shop_confirmed_received", step="completed")
        r = await _cancel(s["oid"], admin)
        assert r.outcome == "succeeded", r
        p = await conn.fetchrow("SELECT status, amount_received_vnd FROM payments WHERE order_id=$1", s["oid"])
        assert (p["status"], p["amount_received_vnd"]) == ("confirmed", 200000)      # KHONG tu hoan / xoa
        assert await conn.fetchval("SELECT count(*) FROM payment_instruction_voids WHERE order_id=$1", s["oid"]) == 0
        att = await conn.fetchrow("SELECT detail FROM staff_attention WHERE order_id=$1 AND reason='refund_required' "
                                  "AND status='open'", s["oid"])
        assert att is not None and '"amount_received_vnd": 200000' in att["detail"]
        # staff queue van hien attention hau-huy
        from app.services.fulfillment import attention
        assert any(a["order_id"] == s["oid"] and a["reason"] == "refund_required"
                   for a in await attention.list_open(conn, limit=5000))
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_shipment_handed_off_gate_and_exception():
    conn = await _conn()
    try:
        sales = await _staff(conn, "sales")          # co order.cancel, KHONG co order.cancel.exception
        admin = await _staff(conn, "admin")
        s = await _seed(conn, ship="in_transit", pay="awaiting", step=None)
        r = await _cancel(s["oid"], sales)
        assert r.outcome == "rejected" and r.error_code == "shipment_handed_off"
        # rollback toan bo (order/kho khong doi)
        assert await conn.fetchval("SELECT status FROM orders WHERE id=$1", s["oid"]) == "confirmed"
        assert (await conn.fetchrow("SELECT reserved FROM inventory_balances WHERE location_id=$1", s["loc"]))[0] == 2
        r2 = await _cancel(s["oid"], admin)
        assert r2.outcome == "succeeded", r2
        assert await conn.fetchval("SELECT status FROM shipments WHERE order_id=$1", s["oid"]) == "in_transit"
        assert await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND status='open' "
                                   "AND reason='order_cancel_exception'", s["oid"]) == 1
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_cascade_failure_rolls_back_everything(monkeypatch):
    from app.services.fulfillment import attention
    conn = await _conn()
    try:
        admin = await _staff(conn, "admin")
        s = await _seed(conn, ship="pending_prep", pay="awaiting")

        async def boom(*a, **k):
            raise RuntimeError("injected cascade failure")
        monkeypatch.setattr(attention, "resolve", boom)
        with pytest.raises(RuntimeError):
            await _cancel(s["oid"], admin)
        assert await conn.fetchval("SELECT status FROM orders WHERE id=$1", s["oid"]) == "confirmed"
        assert await conn.fetchval("SELECT step FROM fulfillment_conversations WHERE order_id=$1", s["oid"]) \
            == "awaiting_transfer"
        assert await conn.fetchval("SELECT status FROM shipments WHERE order_id=$1", s["oid"]) == "pending_prep"
        assert (await conn.fetchrow("SELECT reserved FROM inventory_balances WHERE location_id=$1", s["loc"]))[0] == 2
        assert await conn.fetchval("SELECT count(*) FROM order_events WHERE order_id=$1", s["oid"]) == 0
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_dashboard_identity_order_and_no_customer_outbox():
    from app.services.command import order_service
    from app.services.command.envelope import build_order_create_envelope
    conn = await _conn()
    try:
        admin = await _staff(conn, "admin")
        sku = f"T387D-{uuid.uuid4().hex[:8]}"
        await conn.execute("INSERT INTO products(sku,name,price_vnd,stock) VALUES($1,'CF',100000,50)", sku)
        env = build_order_create_envelope(
            raw_payload=dict(customer_name="Khách Quầy", phone="0912345678", address="1 Nguyen Hue", sku=sku,
                             quantity=1, unit_price_vnd=100000),
            actor=Actor("staff", str(admin)), channel="dashboard", idempotency_key=uuid.uuid4().hex)
        rc = await order_service.execute_order_create(env)
        assert rc.outcome == "succeeded", rc
        oid = rc.resource["id"] if rc.resource else rc.result["order_id"]
        row = await conn.fetchrow("SELECT o.origin_channel, o.created_by_staff_id, c.channel, c.external_chat_id, c.psid "
                                  "FROM orders o JOIN customers c ON c.id=o.customer_id WHERE o.id=$1", oid)
        assert row["origin_channel"] == "dashboard" and row["created_by_staff_id"] == admin
        assert row["channel"] == "dashboard" and row["external_chat_id"].startswith(f"dashboard:{admin}:")
        r = await _cancel(oid, admin)
        assert r.outcome == "succeeded", r
        assert await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key LIKE $1 "
                                   "AND destination IN ('telegram_customer','messenger')", f"order_status:{oid}:%") == 0
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_recipient_per_order_account_not_overwritten():
    from app.api import m6_fulfillment as m6
    conn = await _conn()
    try:
        psid = f"tg:387r-{uuid.uuid4().hex[:10]}"
        cid1 = await ci.ensure_customer(conn, channel="telegram_customer", psid=psid, name="Chủ TK", phone="0900")
        cid2 = await ci.ensure_customer(conn, channel="telegram_customer", psid=psid, name="Người B", phone="0911")
        assert cid1 == cid2
        c = await conn.fetchrow("SELECT name, phone, channel, external_chat_id FROM customers WHERE id=$1", cid1)
        assert (c["name"], c["phone"], c["channel"], c["external_chat_id"]) == ("Chủ TK", "0900", "telegram_customer",
                                                                             psid[3:])
        o1 = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel,shipping_name,"
                                 "shipping_phone) VALUES($1,'new',1,'telegram_customer','Người A','0901') RETURNING id",
                                 cid1)
        o2 = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel,shipping_name,"
                                 "shipping_phone) VALUES($1,'new',1,'telegram_customer','Người B','0902') RETURNING id",
                                 cid1)
        board = {r["order_id"]: r for r in await m6.board(limit=5000)}
        assert board[o1]["customer_name"] == "Người A" and board[o2]["customer_name"] == "Người B"
        assert board[o1]["account_name"] == "Chủ TK" and board[o1]["recipient_phone"] == "0901"
        d = await m6.detail(o2)
        assert d["order"]["customer_name"] == "Người B" and d["order"]["phone"] == "0902"
    finally:
        await conn.close()


@dbonly
@pytest.mark.asyncio
async def test_m6_actions_blocked_on_cancelled_order():
    from fastapi import HTTPException

    from app.api import m6_fulfillment as m6
    conn = await _conn()
    try:
        admin = await _staff(conn, "admin")
        s = await _seed(conn, ship="pending_prep", pay="awaiting")
        assert (await _cancel(s["oid"], admin)).outcome == "succeeded"
        staff = {"id": 1, "username": "t", "rbac_provisioned": True, "permissions": {"shipment.manage"}}
        async with conn.transaction():
            with pytest.raises(HTTPException) as e:
                await m6.guard_order_active(conn, s["oid"], staff)
        assert e.value.status_code == 409
        # co order.cancel.exception -> van thao tac duoc (xu ly ngoai le/hoan tien)
        staff["permissions"] = {"order.cancel.exception"}
        async with conn.transaction():
            await m6.guard_order_active(conn, s["oid"], staff, exception_ok=True)
    finally:
        await conn.close()
