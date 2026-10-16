"""CA Directive 421 §2.2 — huy don khi inventory ledger OFF phai hoan products.stock DUNG 1 lan.

DB (skipif not M6_TEST_DB): tao don qua DUONG THAT (command bus order_service, ledger OFF -> tru thang stock) ->
huy lifecycle -> stock hoan dung; replay cung key / huy lai key moi / huy DONG THOI -> khong hoan 2 lan; huy ngoai le
tu processing -> hoan; huy sau giao that bai (EFFECT_NONE) / don 'shipped' -> KHONG hoan; don co reservation (ledger)
-> khong chay nhanh legacy (khong hoan trung).
"""
import asyncio
import os
import uuid

import pytest

DB = os.environ.get("M6_TEST_DB") == "1"
pytestmark = pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


async def _staff(conn, role="admin"):
    return await conn.fetchval("INSERT INTO staff_users(username,password_hash,password_salt,role_key) "
                               "VALUES ($1,'x','x',$2) RETURNING id", f"t421-{role}-{uuid.uuid4().hex[:8]}", role)


async def _product(conn, stock=50):
    return await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock) VALUES ($1,'CF421',100000,$2) "
                               "RETURNING id", f"T421-{uuid.uuid4().hex[:8]}", stock)


async def _create_order(conn, staff_id, qty=3, stock=50):
    """Tao don qua command bus THAT (channel dashboard, ledger OFF mac dinh) -> stock -= qty."""
    from app.services.command import order_service
    from app.services.command.envelope import Actor, build_order_create_envelope
    pid = await _product(conn, stock)
    sku = await conn.fetchval("SELECT sku FROM products WHERE id=$1", pid)
    env = build_order_create_envelope(
        raw_payload=dict(customer_name="Khách 421", phone="0912345678", address="1 Nguyen Hue", sku=sku,
                         quantity=qty, unit_price_vnd=100000),
        actor=Actor("staff", str(staff_id)), channel="dashboard", idempotency_key=uuid.uuid4().hex)
    rc = await order_service.execute_order_create(env)
    assert rc.outcome == "succeeded", rc
    oid = rc.resource["id"] if rc.resource else rc.result["order_id"]
    return oid, pid


async def _cancel(oid, sid, key=None):
    from app.services.command import lifecycle, registry
    from app.services.command.envelope import Actor
    env = lifecycle.build_lifecycle_envelope(
        command_type=registry.ORDER_CANCEL, payload={"order_id": oid, "reason": "Khách đổi ý — test 421"},
        actor=Actor("staff", str(sid)), channel="dashboard", idempotency_key=key or uuid.uuid4().hex)
    return await lifecycle.execute_lifecycle(env)


async def _stock(conn, pid):
    return await conn.fetchval("SELECT stock FROM products WHERE id=$1", pid)


async def _restores(conn, oid):
    return await conn.fetchval("SELECT count(*) FROM order_events WHERE order_id=$1 "
                               "AND event_type='inventory.legacy_stock_restore'", oid)


@pytest.mark.asyncio
async def test_cancel_restores_exactly_once_with_replay_and_recancel():
    from app.config import settings
    assert settings.m2_inventory_ledger is False                     # tai hien dung dieu kien prod
    conn = await _conn()
    try:
        admin = await _staff(conn)
        oid, pid = await _create_order(conn, admin, qty=3, stock=50)
        assert await _stock(conn, pid) == 47                          # duong tao don tru thang stock
        assert await conn.fetchval("SELECT inventory_status FROM orders WHERE id=$1", oid) == "unreserved"
        key = uuid.uuid4().hex
        r = await _cancel(oid, admin, key)
        assert r.outcome == "succeeded", r
        assert await _stock(conn, pid) == 50 and await _restores(conn, oid) == 1
        assert await conn.fetchval("SELECT inventory_status FROM orders WHERE id=$1", oid) == "released"
        meta = await conn.fetchval("SELECT metadata_redacted::text FROM order_events WHERE order_id=$1 "
                                   "AND event_type='inventory.legacy_stock_restore'", oid)
        assert '"qty": 3' in meta
        r2 = await _cancel(oid, admin, key)                           # replay cung key
        assert r2.duplicate and await _stock(conn, pid) == 50
        r3 = await _cancel(oid, admin)                                # huy lai key moi -> illegal
        assert r3.outcome == "rejected" and await _stock(conn, pid) == 50 and await _restores(conn, oid) == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_concurrent_cancels_restore_once():
    conn = await _conn()
    try:
        admin = await _staff(conn)
        oid, pid = await _create_order(conn, admin, qty=4, stock=20)
        assert await _stock(conn, pid) == 16
        res = await asyncio.gather(*[_cancel(oid, admin) for _ in range(4)], return_exceptions=True)
        ok = [x for x in res if not isinstance(x, Exception) and x.outcome == "succeeded"]
        assert len(ok) == 1, res
        assert await _stock(conn, pid) == 20 and await _restores(conn, oid) == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_cancel_by_exception_from_processing_restores():
    conn = await _conn()
    try:
        admin = await _staff(conn)
        oid, pid = await _create_order(conn, admin, qty=2, stock=10)
        await conn.execute("UPDATE orders SET status='processing' WHERE id=$1", oid)
        r = await _cancel(oid, admin)
        assert r.outcome == "succeeded", r
        assert await conn.fetchval("SELECT status FROM orders WHERE id=$1", oid) == "cancelled_by_exception"
        assert await _stock(conn, pid) == 10 and await _restores(conn, oid) == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_no_restore_after_delivery_failed_or_shipped(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "m3_delivered_lifecycle", True)
    conn = await _conn()
    try:
        admin = await _staff(conn)
        # giao that bai -> huy (EFFECT_NONE): hang da roi kho, xu ly qua return_inspect -> KHONG hoan tu dong
        oid, pid = await _create_order(conn, admin, qty=2, stock=10)
        await conn.execute("UPDATE orders SET status='delivery_failed' WHERE id=$1", oid)
        r = await _cancel(oid, admin)
        assert r.outcome == "succeeded", r
        assert await _stock(conn, pid) == 8 and await _restores(conn, oid) == 0
        # legacy 'shipped' -> huy khong hop le -> khong doi stock
        oid2, pid2 = await _create_order(conn, admin, qty=1, stock=5)
        await conn.execute("UPDATE orders SET status='shipped' WHERE id=$1", oid2)
        r2 = await _cancel(oid2, admin)
        assert r2.outcome == "rejected" and await _stock(conn, pid2) == 4 and await _restores(conn, oid2) == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_reserved_order_uses_ledger_branch_not_legacy():
    conn = await _conn()
    try:
        admin = await _staff(conn)
        pid = await _product(conn, stock=30)
        cid = await conn.fetchval("INSERT INTO customers(psid,channel,external_chat_id,name) VALUES ($1,"
                                  "'telegram_customer',$2,'K') RETURNING id", f"tg:421-{uuid.uuid4().hex[:8]}",
                                  uuid.uuid4().hex[:8])
        oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel,inventory_status) "
                                  "VALUES ($1,'confirmed',1,'telegram_customer','reserved') RETURNING id", cid)
        item = await conn.fetchval("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) "
                                   "VALUES ($1,$2,2,1) RETURNING id", oid, pid)
        loc = await conn.fetchval("INSERT INTO inventory_locations(code,name,location_type) VALUES ($1,'T','warehouse') "
                                  "RETURNING id", f"T421-{uuid.uuid4().hex[:8]}")
        await conn.execute("INSERT INTO inventory_balances(location_id,product_id,on_hand,reserved) VALUES ($1,$2,30,2)",
                           loc, pid)
        await conn.execute("INSERT INTO inventory_reservations(id,order_id,order_item_id,location_id,product_id,"
                           "quantity_initial,quantity_remaining,status,idempotency_key) VALUES ($1,$2,$3,$4,$5,2,2,"
                           "'active',$6)", uuid.uuid4(), oid, item, loc, pid, f"t421:{uuid.uuid4().hex}")
        r = await _cancel(oid, admin)
        assert r.outcome == "succeeded", r
        assert await _restores(conn, oid) == 0 and await _stock(conn, pid) == 30          # khong cong legacy
        assert await conn.fetchval("SELECT reserved FROM inventory_balances WHERE location_id=$1", loc) == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_dashboard_legacy_manual_order_cancel_restores():
    """Dung ca CA 413: don Dashboard tao qua orders.create_order_manual (legacy, M1 OFF) -> huy -> hoan stock."""
    from app.services import orders as orders_service
    conn = await _conn()
    try:
        admin = await _staff(conn)
        pid = await _product(conn, stock=12)
        sku = await conn.fetchval("SELECT sku FROM products WHERE id=$1", pid)
        r = await orders_service.create_order_manual(customer_name="TEST 421", phone="0912345678",
                                                     address="1 Nguyen Hue", sku=sku, quantity=5,
                                                     unit_price_vnd=100000, created_by_staff_id=admin)
        assert "error" not in r, r
        oid = r["order_id"]
        assert await _stock(conn, pid) == 7
        res = await _cancel(oid, admin)
        assert res.outcome == "succeeded", res
        assert await _stock(conn, pid) == 12 and await _restores(conn, oid) == 1
    finally:
        await conn.close()
