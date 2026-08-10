"""F-EX-B2-02 (Amendment 07 Execution Blocker 1 follow-up): helper DSN normalization dung
CHUNG cho moi M4 operational tool ket noi truc tiep bang `asyncpg` (khong qua SQLAlchemy) -
truoc day `m4_stage0p_provision_pin.py` va `m4_stage0p_rehearsal_runner.py` co 2 ban sao rieng
biet cua CUNG 1 logic, dan toi runner bi bo sot khi PIN tool duoc sua o PR #9 (F-EX-B1-01/
PIN-TOOL-DSN-COMPAT-REVIEW-1 F-DSN-R1-01). Module nay la nguon DUY NHAT cho ca 2 tool - sua 1
lan, ca 2 tool tu dong nhat quan, khong the lech nhau nua.

`asyncpg.connect()`/`asyncpg.create_pool()` chi hieu scheme "postgresql"/"postgres" - KHONG hieu
scheme co driver suffix kieu SQLAlchemy ("postgresql+asyncpg") ma production DATABASE_URL dang
dung (app chinh dung SQLAlchemy async engine, xem app/db_pool.py). Allowlist tuong minh, CHI
thay phan scheme (truoc "://" dau tien) - khong dung replace() khong gioi han vi mat khau/query
string co the chua chuoi trung ten scheme mot cach tinh co.

2 thong bao loi la HANG SO CO DINH - KHONG bao gio noi suy bat ky phan nao cua input goc vao do,
ke ca phan "scheme" da tach ra (van co the tinh co chua secret/ky tu dieu khien neu DATABASE_URL
bi malformed/gia mao)."""

import os
import sys

_DB_SCHEME_NORMALIZE = {
    "postgresql": "postgresql",
    "postgres": "postgres",
    "postgresql+asyncpg": "postgresql",
}

DB_URL_MISSING_SCHEME_SEP_MSG = (
    "LOI: DATABASE_URL khong hop le (thieu '://') - tu choi truoc khi ket noi DB "
    "(fail-closed). Ho tro: postgresql://, postgres://, postgresql+asyncpg://.")
DB_URL_UNSUPPORTED_SCHEME_MSG = (
    "LOI: DATABASE_URL scheme khong duoc ho tro - tu choi truoc khi ket noi DB (fail-closed). "
    "Ho tro: postgresql://, postgres://, postgresql+asyncpg://.")
DB_URL_EMPTY_MSG = (
    "LOI: DATABASE_URL duoc set nhung rong/toan khoang trang - tu choi truoc khi ket noi DB "
    "(fail-closed). Khong tu dong dung gia tri mac dinh khi bien MOI TRUONG da ton tai.")


def normalized_db_url(default: str = "postgresql://alpha3s:alpha3s@db:5432/alpha3s") -> str:
    """Doc DATABASE_URL tu moi truong, normalize scheme cho asyncpg.

    F-RCR-R1-02: phai phan biet bien moi truong ABSENT (chua tung set - khi do `default` moi
    duoc dung, danh cho chay local khong co env) voi bien PRESENT-BUT-EMPTY (da set nhung la
    chuoi rong/toan khoang trang - truong hop nay la fail-closed, KHONG duoc am tham chuyen sang
    `default` vi co the che giau 1 loi cau hinh that su tren production khien tool ket noi nham
    DB thay vi dung lai)."""
    if "DATABASE_URL" not in os.environ:
        raw = default
    else:
        raw = os.environ["DATABASE_URL"]
        if not raw.strip():
            sys.exit(DB_URL_EMPTY_MSG)
    if "://" not in raw:
        sys.exit(DB_URL_MISSING_SCHEME_SEP_MSG)
    scheme, rest = raw.split("://", 1)
    normalized = _DB_SCHEME_NORMALIZE.get(scheme)
    if normalized is None:
        sys.exit(DB_URL_UNSUPPORTED_SCHEME_MSG)
    return f"{normalized}://{rest}"
