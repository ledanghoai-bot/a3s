"""Connection pool dung chung cho asyncpg (issue #9 Bat 1; chuan hoa I-B M0.2).

Truoc day moi ham tu mo `asyncpg.connect()` roi dong ngay — overhead handshake moi lan goi.
Module nay cung cap 1 POOL dung chung, tao LAZY o lan `await` dau tien trong event loop cua MOI
process -> KHONG tao pool truoc fork (uvicorn --workers / arq). Sizing tu settings (min/max moi
process + command timeout), CA-REVIEW-M0-DEV §9.

Hai kieu dung:
- Service moi: `async with (await get_pool()).acquire() as conn: ...`
- Service cu dung try/finally: `conn = await acquire()` / `await release(conn)` (giu nguyen cau truc,
  chi doi nguon connection — diff toi thieu khi chuyen 8 service).

CA Directive 404 §2A + Review 406 — vong doi pool an toan dong thoi:
- KHOI TAO: nhieu coroutine (cron outbox/m7/expiry... cung giay dau sau restart) cung thay `_pool is None` -> truoc
  day moi coroutine tao 1 pool, `_pool` bi ghi de -> connection tra nham pool (`InterfaceError: ... is not a member of
  this pool`). Nay: khoi tao duoi asyncio.Lock (double-checked) -> MOT pool / process / loop.
- OWNERSHIP: `acquire()` ghi nhan pool da cap; `release()` tra ve DUNG pool do. Owner GIU cho toi khi release xong
  (ke ca khi pool dang dong). Khong xac dinh duoc owner -> LOI RO (RuntimeError), KHONG fallback sang pool hien hanh.
- DONG: `close_pool()` tach pool (duoi lock) va danh dau "dang dong"; `get_pool()` CHO toi khi dong xong moi tao pool
  moi (khong 2 pool song song). `pool.close()` cho connection dang muon duoc tra (release van dung owner cu); qua
  CLOSE_TIMEOUT_S (vd coroutine dang giu connection lai cho get_pool) -> terminate() -> khong deadlock vo han.

Lifecycle: `close_pool()` goi tu FastAPI lifespan (app/main.py) + arq on_shutdown (app/workers/tasks.py).
"""
import asyncio

import asyncpg

from app.config import settings

CLOSE_TIMEOUT_S = 10.0

_pool: asyncpg.Pool | None = None
_lock: asyncio.Lock | None = None
_lock_loop = None
_close_done: asyncio.Event | None = None   # != None va chua set -> dang dong pool cu
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


def _closing() -> bool:
    return _close_done is not None and not _close_done.is_set()


async def get_pool() -> asyncpg.Pool:
    """Tra ve pool dung chung, lazy-init DUNG 1 lan ke ca khi nhieu coroutine goi dong thoi; neu pool cu dang dong
    thi CHO dong xong roi moi tao pool moi."""
    global _pool, pools_created
    while True:
        if _pool is not None:
            return _pool
        if _closing():
            await _close_done.wait()
            continue
        async with _get_lock():
            if _pool is None and not _closing():   # double-checked
                _pool = await asyncpg.create_pool(
                    _db_url(),
                    min_size=settings.db_pool_min_size,
                    max_size=settings.db_pool_max_size,
                    command_timeout=settings.db_command_timeout,
                )
                pools_created += 1


async def acquire():
    """Lay 1 connection tu pool (cho service dung try/finally). Nho `await release(conn)`."""
    pool = await get_pool()
    conn = await pool.acquire()
    _owner[id(conn)] = pool
    return conn


async def release(conn) -> None:
    """Tra connection ve DUNG pool da cap. Khong ro owner -> RuntimeError (khong tra nham pool, khong bo im lang)."""
    pool = _owner.get(id(conn))
    if pool is None:
        raise RuntimeError("db_pool.release: connection khong do db_pool.acquire() cap (khong ro pool) — "
                           "tu choi tra nham pool")
    try:
        await pool.release(conn)
    except asyncpg.InterfaceError:
        if pool is not _pool and getattr(pool, "_closed", False):
            # pool cu da bi terminate (qua CLOSE_TIMEOUT_S) -> connection da dong cung pool, khong con gi de tra.
            print("[db_pool] release vao pool da terminate — connection da dong cung pool (bo qua)")
            return
        raise
    finally:
        _owner.pop(id(conn), None)


async def close_pool(timeout: float = CLOSE_TIMEOUT_S) -> None:
    """Dong pool luc app/worker shutdown. An toan voi connection dang muon va get_pool() dong thoi."""
    global _pool, _close_done
    async with _get_lock():
        pool = _pool
        if pool is None:
            return
        _pool = None
        _close_done = asyncio.Event()
    done = _close_done
    try:
        await asyncio.wait_for(pool.close(), timeout)
    except asyncio.TimeoutError:
        print(f"[db_pool] close qua {timeout}s (con connection dang muon) -> terminate")
        pool.terminate()
    finally:
        # KHONG xoa owner cua connection con dang muon: release() muon van can biet pool cu (Review 406).
        done.set()
