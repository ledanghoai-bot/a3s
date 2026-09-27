"""Test fixtures dung chung.

pytest-asyncio mac dinh tao event loop MOI moi test (function scope). `app.db_pool._pool` la pool GLOBAL
cache theo loop tao ra no -> test thu 2 tro di dung pool cua loop da dong -> 'Event loop is closed'.
Fixture autouse duoi reset pool (va ownership/trang thai dong — CA 404) ve rong truoc/sau moi test ->
get_pool() tao lai tren loop hien tai. Test khong dung DB khong bi anh huong (khong bao gio goi get_pool)."""
import pytest

import app.db_pool as _db_pool


def _reset():
    _db_pool._pool = None
    _db_pool._close_done = None
    _db_pool._owner.clear()


@pytest.fixture(autouse=True)
def _reset_db_pool():
    _reset()
    yield
    _reset()
