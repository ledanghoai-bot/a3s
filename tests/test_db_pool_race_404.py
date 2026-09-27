"""CA Directive 404 §2A — regression: race khoi tao pool luc restart worker + outbox khong mat/khong gui trung.

Tai hien DUNG duong loi prod (log postflight D399: `[outbox] drain loi: InterfaceError: Pool.release() ... is not a
member of this pool`): sau restart `_pool=None`, nhieu cron (outbox/m7/expiry...) cung giay dau goi acquire() dong
thoi -> truoc ban sua moi coroutine tao 1 pool, `_pool` bi ghi de, release tra connection ve nham pool.
DB (skipif not M6_TEST_DB): 1 pool duy nhat, release dung pool, drain outbox dong thoi xu ly event DUNG 1 lan theo
dedupe_key; pool chua san sang (create_pool loi) -> event giu pending (khong mat, khong danh dau delivered) roi lan
sau xu ly dung 1 lan.
"""
import asyncio
import os
import uuid

import pytest

import app.db_pool as P

DB = os.environ.get("M6_TEST_DB") == "1"
dbonly = pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")


def _reset():
    P._pool = None
    if hasattr(P, "_owner"):          # ban cu (truoc sua) khong co -> test van chay de TAI HIEN loi
        P._owner.clear()


@pytest.fixture
def pool_count(monkeypatch):
    """Dem so pool that su tao (ca ban cu lan ban sua) bang cach boc asyncpg.create_pool."""
    import asyncpg
    real = asyncpg.create_pool
    box = {"n": 0}

    async def counting(*a, **k):
        box["n"] += 1
        return await real(*a, **k)
    monkeypatch.setattr(asyncpg, "create_pool", counting)
    return box


async def _insert_event(dedupe: str) -> str:
    import asyncpg

    from app.services.command import repository as repo
    c = await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    try:
        ev = await repo.insert_outbox(c, command_id=None, event_type="fulfillment.staff.notify", event_version=1,
                                      destination="telegram_admin", dedupe_key=dedupe,
                                      payload={"kind": "staff_attention", "order_id": None, "reason": "other",
                                               "detail_text": "d404", "attention_id": 0}, max_attempts=8)
        # dat dau hang doi claim (lab co the con backlog pending) -> vong drain dau tien chac chan thay event nay
        await c.execute("UPDATE outbox_events SET available_at='2000-01-01', created_at='2000-01-01' WHERE id=$1", ev)
        return ev
    finally:
        await c.close()


async def _event(ev_id):
    import asyncpg
    c = await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    try:
        return dict(await c.fetchrow("SELECT status, attempt_count, delivered_at FROM outbox_events WHERE id=$1", ev_id))
    finally:
        await c.close()


def _fake_send(counter: dict, dedupe: str):
    from app.services.command.outbox_worker import SendResult

    async def send(destination, payload):
        await asyncio.sleep(0.02)
        if payload.get("detail_text") == "d404" and counter.get("key") == dedupe:
            counter["n"] = counter.get("n", 0) + 1
        return SendResult(ok=True, http_status=200, provider_message_id=f"m-{uuid.uuid4().hex[:6]}")
    return send


@dbonly
@pytest.mark.asyncio
async def test_concurrent_startup_single_pool_and_correct_release(pool_count):
    _reset()

    async def worker():
        c = await P.acquire()
        await asyncio.sleep(0.01)
        await c.fetchval("SELECT 1")
        await P.release(c)
    # 12 coroutine cung "giay dau sau restart" — truoc ban sua: nhieu pool + InterfaceError khi release
    res = await asyncio.gather(*[worker() for _ in range(12)], return_exceptions=True)
    assert [r for r in res if isinstance(r, Exception)] == []
    assert pool_count["n"] == 1
    await P.close_pool()


@dbonly
@pytest.mark.asyncio
async def test_restart_concurrent_drain_delivers_exactly_once(pool_count):
    from app.services.command import outbox_worker as ow
    dedupe = f"d404-race-{uuid.uuid4().hex}"
    ev_id = await _insert_event(dedupe)
    _reset()
    counter = {"key": dedupe}
    send = _fake_send(counter, dedupe)
    # restart: 4 vong drain + 4 coroutine khac cung khoi tao pool dong thoi
    other = [P.acquire() for _ in range(4)]
    res = await asyncio.gather(*[ow.run_once(send_fn=send) for _ in range(4)], *other, return_exceptions=True)
    errs = [r for r in res if isinstance(r, Exception)]
    assert errs == [], errs
    for c in res[4:]:
        await P.release(c)
    assert pool_count["n"] == 1
    assert counter.get("n") == 1                      # gui DUNG 1 lan
    ev = await _event(ev_id)
    assert ev["status"] == "delivered" and ev["attempt_count"] == 1
    # drain lai: khong gui lai
    await ow.run_once(send_fn=send)
    assert counter.get("n") == 1
    await P.close_pool()


@dbonly
@pytest.mark.asyncio
async def test_pool_not_ready_keeps_event_pending_then_exactly_once(monkeypatch):
    import asyncpg

    from app.services.command import outbox_worker as ow
    dedupe = f"d404-notready-{uuid.uuid4().hex}"
    ev_id = await _insert_event(dedupe)
    _reset()
    real_create = asyncpg.create_pool
    calls = {"n": 0}

    async def flaky_create(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("db chua san sang (restart)")
        return await real_create(*a, **k)
    monkeypatch.setattr(asyncpg, "create_pool", flaky_create)
    counter = {"key": dedupe}
    send = _fake_send(counter, dedupe)
    with pytest.raises(OSError):
        await ow.run_once(send_fn=send)               # job bao ve bat loi nay (deliver_outbox_job) — khong crash worker
    ev = await _event(ev_id)
    assert ev["status"] == "pending" and ev["attempt_count"] == 0 and ev["delivered_at"] is None
    assert P._pool is None                            # khong giu pool hong
    await ow.run_once(send_fn=send)                   # vong sau (pool san sang) -> xu ly DUNG 1 lan
    ev = await _event(ev_id)
    assert ev["status"] == "delivered" and ev["attempt_count"] == 1 and counter.get("n") == 1
    await P.close_pool()


@dbonly
@pytest.mark.asyncio
async def test_release_returns_to_owner_pool_after_pool_swap():
    """Connection muon truoc khi pool bi thay (close/restart) phai tra ve DUNG pool cu, khong raise."""
    _reset()
    c = await P.acquire()
    old = P._pool
    P._pool = None                                    # mo phong pool bi thay giua chung
    c2 = await P.acquire()
    assert P._pool is not old
    await P.release(c)                                # truoc ban sua: InterfaceError not a member
    await P.release(c2)
    await old.close()
    await P.close_pool()
