"""Connection pool dung chung cho asyncpg (issue #9, Bat 1).

Truoc day, MOI ham trong tung service tu mo 1 connection moi
(`asyncpg.connect()`) roi dong ngay sau khi dung xong - dung duoc nhung tao
overhead handshake TCP/TLS + auth moi lan goi, ro net khi nhieu tin nhan den
cung luc (moi lan xu ly 1 tin nhan co the mo 5-10 connection rieng le).

Module nay cung cap 1 POOL dung chung, tao 1 lan duy nhat luc app/worker khoi
dong, tai su dung connection giua cac lan goi. Dung `get_pool()` (async) o dau
moi ham thay vi `asyncpg.connect()` truc tiep.

QUAN TRONG - pham vi hien tai (17/7): chi moi ap dung cho 2 module goi
nhieu nhat moi luot chat (`conversation_log.py`, `products.py`). Cac service
con lai (`handoff.py`, `orders.py`, `price_overrides.py`, `knowledge_entries.py`,
`metrics.py`, `auth_service.py`, `tools.py`, `rag.py`) VAN dung
`asyncpg.connect()` truc tiep nhu cu - se di chuyen dan trong cac Bat sau cua
issue #9, khong lam 1 lan vi pham vi qua rong (~15 file).
"""

import asyncpg

from app.config import settings

_pool: asyncpg.Pool | None = None


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def get_pool() -> asyncpg.Pool:
    """Tra ve pool dung chung, tu tao neu chua co (lazy init - an toan goi
    nhieu lan, chi tao pool 1 lan duy nhat nho check `_pool is None`)."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            _db_url(),
            min_size=2,
            max_size=10,
        )
    return _pool


async def close_pool() -> None:
    """Dong pool luc app/worker shutdown (goi tu FastAPI lifespan/arq
    on_shutdown neu can dong sach - hien chua bat buoc vi container restart
    la du don, nhung de san day cho lan tich hop sau)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
