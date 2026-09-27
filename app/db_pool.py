"""Connection pool dung chung cho asyncpg (issue #9 Bat 1; chuan hoa I-B M0.2).

Truoc day moi ham tu mo `asyncpg.connect()` roi dong ngay — overhead handshake moi lan goi.
Module nay cung cap 1 POOL dung chung, tao LAZY o lan `await` dau tien trong event loop cua MOI
process -> KHONG tao pool truoc fork (uvicorn --workers / arq). Sizing tu settings (min/max moi
process + command timeout), CA-REVIEW-M0-DEV §9.

Hai kieu dung:
- Service moi: `async with (await get_pool()).acquire() as conn: ...`
- Service cu dung try/finally: `conn = await acquire()` / `await release(conn)` (giu nguyen cau truc,
  chi doi nguon connection — diff toi thieu khi chuyen 8 service).

CA Directive 404 §2A (race khoi tao/restart): nhieu coroutine (cron outbox/m7/expiry... cung giay dau sau restart)
cung thay `_pool is None` -> moi coroutine tao MOT pool rieng, `_pool` bi ghi de -> connection lay tu pool A bi tra
ve pool B -> `InterfaceError: Pool.release() ... is not a member of this pool` (connection A ro ri, vong drain outbox
bi bo). Sua: (1) khoi tao duoi asyncio.Lock (double-checked) -> dung MOT pool/process/loop; (2) `release` tra
connection ve DUNG pool da cap (ghi nhan luc acquire), khong phu thuoc `_pool` hien hanh.

Lifecycle: `close_pool()` goi tu FastAPI lifespan (app/main.py) + arq on_shutdown (app/workers/tasks.py).
"""
import asyncio

import asyncpg

from app.config import settings

_pool: asyncpg.Pool | None = None
_lock: asyncio.Lock | None = None
_lock_loop = None
# id(connection proxy) -> pool da cap (proxy song suot thoi gian muon -> id duy nhat trong khoang do)
_owner: dict[int, asyncpg.Pool] = {}
pools_created = 0   # dem so pool tao trong process (regression test / quan sat)


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _get_lock() -> asyncio.Lock:
    """Lock theo event loop hien hanh (test tao loop moi moi test; worker/api 1 loop)."""
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock, _lock_loop = asyncio.Lock(), loop
    return _lock


async def get_pool() -> asyncpg.Pool:
    """Tra ve pool dung chung, lazy-init DUNG 1 lan ke ca khi nhieu coroutine goi dong thoi."""
    global _pool, pools_created
    if _pool is not None:
        return _pool
    async with _get_lock():
        if _pool is None:           # double-checked: coroutine thu 2 tro di dung pool vua tao
            _pool = await asyncpg.create_pool(
                _db_url(),
                min_size=settings.db_pool_min_size,
                max_size=settings.db_pool_max_size,
                command_timeout=settings.db_command_timeout,
            )
            pools_created += 1
    return _pool


async def acquire():
    """Lay 1 connection tu pool (cho service dung try/finally). Nho `await release(conn)`."""
    pool = await get_pool()
    conn = await pool.acquire()
    _owner[id(conn)] = pool
    return conn


async def release(conn) -> None:
    """Tra connection ve DUNG pool da cap (khong phai `_pool` hien hanh — co the da doi sau close/restart)."""
    pool = _owner.pop(id(conn), None) or _pool
    if pool is not None:
        await pool.release(conn)


async def close_pool() -> None:
    """Dong pool luc app/worker shutdown."""
    global _pool
    if _pool is not None:
        pool, _pool = _pool, None
        for k in [k for k, p in _owner.items() if p is pool]:
            _owner.pop(k, None)
        await pool.close()
