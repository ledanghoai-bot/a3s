"""Connection pool dung chung cho asyncpg (issue #9 Bat 1; chuan hoa I-B M0.2).

Truoc day moi ham tu mo `asyncpg.connect()` roi dong ngay — overhead handshake moi lan goi.
Module nay cung cap 1 POOL dung chung, tao LAZY o lan `await` dau tien trong event loop cua MOI
process -> KHONG tao pool truoc fork (uvicorn --workers / arq). Sizing tu settings (min/max moi
process + command timeout), CA-REVIEW-M0-DEV §9.

Hai kieu dung:
- Service moi: `async with (await get_pool()).acquire() as conn: ...`
- Service cu dung try/finally: `conn = await acquire()` / `await release(conn)` (giu nguyen cau truc,
  chi doi nguon connection — diff toi thieu khi chuyen 8 service).

Lifecycle: `close_pool()` goi tu FastAPI lifespan (app/main.py) + arq on_shutdown (app/workers/tasks.py).
"""
import asyncpg

from app.config import settings

_pool: asyncpg.Pool | None = None


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def get_pool() -> asyncpg.Pool:
    """Tra ve pool dung chung, lazy-init 1 lan (an toan goi nhieu lan)."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            _db_url(),
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
            command_timeout=settings.db_command_timeout,
        )
    return _pool


async def acquire():
    """Lay 1 connection tu pool (cho service dung try/finally). Nho `await release(conn)`."""
    return await (await get_pool()).acquire()


async def release(conn) -> None:
    """Tra connection ve pool."""
    if _pool is not None:
        await _pool.release(conn)


async def close_pool() -> None:
    """Dong pool luc app/worker shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
