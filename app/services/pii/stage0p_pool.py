"""I-B M4 Stage 0P — real connection-pool integration cho pinned-actor lifecycle (F-M4-0P-T8-01,
REV10 F-M4-0P-T9-01/T9-02).

CA Technical Re-review #8 (F-M4-0P-T8-01): Correction #8 (T7-01) chi dong truong hop actor A
HOAN TAT 1 hanh dong nghiep vu THANH CONG roi actor B muon lai CUNG connection (consume-on-use xoa
row pin ngay sau thanh cong). Nhung Correction #8 tu ghi nhan 1 khoang cach con lai: neu actor A
pin THANH CONG roi request bi huy/loi TRUOC khi lam hanh dong nghiep vu nao, row pin + session_nonce
VAN CON. CA yeu cau tich hop 1 pool THAT (`asyncpg.create_pool`) va chung minh bang integration
test THAT rang pool checkout luon bat dau unpinned, checkin/release unpin ke ca exception/cancel,
va actor B fail-closed khi checkout lai CUNG connection ma actor A da bo do.

CA Technical Re-review #9 (F-M4-0P-T9-01, P1): thiet ke REV9 dung `asyncio.shield()` boc 1 lan goi
cleanup MOI cho moi lan `__aexit__` chay — neu OUTER task nhan 1 lan cancel THEM trong luc dang
`await asyncio.shield(_cleanup())`, chinh await do nem CancelledError NGAY (dung thiet ke cua
`asyncio.shield` — no chi bao ve INNER task khoi bi huy boi chinh no bi huy, khong bao ve outer
await khoi 1 lan cancel rieng nham vao outer) — trong khi cleanup task VAN chay nen. Nhanh
`except CancelledError: pass` REV9 di thang toi `finally: pool.release(conn)`, tra connection ve
pool TRUOC KHI cleanup that su xong — actor B ke tiep co the nhan connection dang con bi cleanup cu
RESET ROLE/SET ROLE/unpin_actor() tren CHINH no, tao race giua 2 request.

Sua REV10: `__aexit__` tao 1 `asyncio.Task` cleanup TUONG MINH (khong phai coroutine boc lai moi
lan shield), roi LAP LAI `await asyncio.shield(cleanup_task)` cho toi khi `cleanup_task.done()` La
THAT — moi lan CancelledError tu 1 lan cancel THEM chi lam vong lap thu lai (task cleanup goc VAN
LA CUNG 1 task, khong bi huy, khong bi tao lai), khong bao gio roi vong lap som. Neu tong thoi gian
cho vuot qua `_CLEANUP_MAX_WAIT_SECONDS` (backstop cho kich ban cleanup THAT SU treo — vd network
partition giua chung), goi `conn.terminate()` (dong ket noi VAT LY NGAY LAP TUC, khac `close()`
la dong "lich su") de buoc cleanup_task dang cho tren connection do phai ket thuc (moi await tren
1 connection da terminate deu raise), roi discard (khong con connection do de release binh thuong
nua — `pool.release()` van duoc goi de pool tu thay the, xem `_release_or_discard`). Neu cleanup
task hoan tat nhung tu BAO LOI (SQL/network that bai giua chung — vd RESET ROLE hoac unpin_actor
tu no RAISE thay vi chi log), connection cung bi terminate+discard thay vi release binh thuong —
khong bao gio tra 1 connection co the con o trang thai session/role khong xac dinh ve pool cho
request khac dung lai.

Sua REV10 F-M4-0P-T9-02 (P1): `business_role` REV9 la 1 `str` bat ky, noi suy truc tiep vao
`SET ROLE {business_role}` — khong allowlist, khong quote identifier, "goi wrapper" tro thanh
role-selection authority (caller chon duoc BAT KY role M4 nao, ke ca role khong lien quan hanh
dong dinh lam). Sua: `business_role` gio PHAI la 1 thanh vien enum `Stage0PBusinessRole` (khong
con nhan chuoi tuy y — Python tu chan o compile-time/type-check, khong the "inject" 1 gia tri
khong ton tai trong enum). Enum CHI liet ke DUNG 4 role DB THAT SU goi
`m4_stage0p_require_pinned_actor()` ben trong (ra soat truc tiep `migrations/039_m4_stage0p.sql`
— 8 loi goi, tat ca thuoc 4 role nay; `alpha3s_m4_sample_collector` KHONG nam trong danh sach vi
`record_sample`/`fetch_message_content` khong doi hoi pinned actor, chi doi hoi capability
one-time nonce T4-01 — dua no vao enum se ngam dinh sai rang no can pin). Gia tri enum van duoc
quote identifier an toan (double-quote + escape) truoc khi dua vao `SET ROLE` — phong thu THEM
(defense-in-depth) du ban than enum da loai tru injection tu nguon.

Con lai CHUA dong (F-M4-0P-T9-03, P1 activation blocker — ngoai pham vi T8-01/T9-01/T9-02, CA da
ghi nhan rieng o Review #9): `pin_secret`/`staff_id` van do caller truyen (bespoke credential),
KHONG phai identity authority production that su — Stage 0P hien khong co lop HTTP/JWT auth THAT
de derive staff identity tu 1 authenticated application principal. `pinned_actor_session()` PHAI
nhan 1 verified principal context (khong phai raw staff_id/pin_secret tu request body) truoc khi
duoc cap production-data-access/activation — CA yeu cau ro rang nay khong duoc coi la dong boi
round nay, chi duoc phep giu nguyen trong pham vi synthetic dev/test.

CA Technical Re-review #10 (F-M4-0P-T10-03, P1): REV10 `__aenter__()` chi boc try/except quanh
`pin_actor()` — loi tai `SET ROLE alpha3s_m4_actor_binder` ban dau, safety-unpin, `RESET ROLE`
sau pin, hay `SET ROLE <business_role>` KHONG duoc xu ly boi 1 resource guard THONG NHAT: business
`SET ROLE` that bai SAU KHI pin thanh cong co the de lai 1 connection dang checked-out VOI PIN CON
SONG ma `__aexit__()` khong bao gio chay (vi `__aenter__()` chua "hoan tat" — Python khong goi
`__aexit__` neu `__aenter__` tu no raise). Safety-unpin REV10 con "nuot" MOI exception roi tiep
tuc coi nhu binh thuong — 1 loi unpin THAT (vd mat ket noi/quyen) khong nen la no-op.

Sua REV11: TOAN BO chuoi acquire/setup (`SET ROLE actor_binder` -> safety-unpin -> `pin_actor` ->
`RESET ROLE` -> `SET ROLE business_role`) nam trong 1 `try` DUY NHAT; BAT KY that bai nao (tru
`pin_actor` tu choi vi sai staff/secret — van la 1 "loi nghiep vu binh thuong", khong phai loi ha
tang) deu di qua CUNG 1 primitive cleanup/discard ma `__aexit__()` dung (`_wait_cleanup_and_release`
— tach ra tu logic REV10, dung chung ca 2 nhanh) — dam bao KHONG BAO GIO co 1 connection roi
`__aenter__()` (du bang exception) ma van con dang checked-out voi pin/role chua don dep.
Safety-unpin gio PHAN BIET RAISE THAT (permission/connection loi — `m4_stage0p_unpin_actor()` la
1 DELETE don gian, KHONG RAISE cho truong hop binh thuong "chua tung co pin", nen bat ky
`PostgresError` nao o day la dau hieu that bai ha tang THAT) voi truong hop "chua tung pin" (khong
co gi de bat, ham SQL tu no khong RAISE) — loi that bay gio FAIL CLOSED (rethrow, discard
connection), khong con bi nuot roi tiep tuc."""

import asyncio
import enum
import json
import time

import asyncpg

from app.services.pii.stage0p_control import ActorNotPinnedError, pin_actor, unpin_actor

# T9-01: backstop cho kich ban cleanup THAT SU treo (vd network partition giua chung) — binh
# thuong cleanup hoan tat trong vai chuc ms (vai lenh RESET ROLE/SET ROLE/DELETE 1 row); day KHONG
# phai latency ky vong, chi la tran tren cung truoc khi buoc terminate connection.
_CLEANUP_MAX_WAIT_SECONDS = 10.0
_CLEANUP_STATEMENT_TIMEOUT_SECONDS = 3.0


class Stage0PBusinessRole(enum.Enum):
    """T9-02: allowlist BAT BIEN cho `business_role` — CHI 4 gia tri nay, xac nhan bang cach ra
    soat truc tiep moi loi goi `m4_stage0p_require_pinned_actor()` trong migration 039 (8 loi goi,
    dung 4 role nay). Them 1 role M4 khac vao day PHAI di kem xac nhan lai rang ham nghiep vu
    tuong ung THAT SU doi hoi pinned actor — khong duoc "them cho chac"."""

    CONTROL_PLANE = "alpha3s_m4_control_plane"          # m4_stage0p_set_capture (m4.stage0p.operate)
    APPROVAL_RECORDER = "alpha3s_m4_approval_recorder"  # record/revoke_approval, set_current_normalization_version, record/revoke_normalization_approval (m4.stage0p.approve)
    SAMPLE_REVIEWER_API = "alpha3s_m4_sample_reviewer_api"  # m4_stage0p_seal_labels (m4.stage0p.review)
    SAMPLE_EVALUATOR = "alpha3s_m4_sample_evaluator"        # m4_stage0p_complete_evaluation (m4.stage0p.evaluate)


def _quote_role_ident(role_name: str) -> str:
    """Quote 1 Postgres identifier an toan (double-quote + escape double-quote noi bo) — phong
    thu THEM ben canh viec `role_name` chi co the den tu `Stage0PBusinessRole` (T9-02)."""
    return '"' + role_name.replace('"', '""') + '"'


def _log(event: str, **fields) -> None:
    print("[m4-stage0p-pool] " + json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))


async def create_stage0p_pool(dsn: str, *, min_size: int = 1, max_size: int = 4,
                              command_timeout: float | None = 10.0) -> asyncpg.Pool:
    """Tao 1 pool RIENG cho Stage 0P (tach biet pool chung cua app `app/db_pool.py` — Stage 0P van
    chua noi vao production, xem CLAUDE.md muc 6 'Kien truc — ranh gioi trach nhiem quan trong').
    Goi `await pool.close()` khi xong (vd cuoi integration test / shutdown)."""
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size,
                                     command_timeout=command_timeout)


class _PinnedSession:
    """Trien khai async context manager cho `pinned_actor_session()` — xem module docstring cho
    thiet ke day du. Khong dung truc tiep tu ben ngoai module nay."""

    def __init__(self, pool: asyncpg.Pool, *, staff_id: int, pin_secret: str,
                business_role: Stage0PBusinessRole):
        if not isinstance(business_role, Stage0PBusinessRole):
            raise TypeError(
                "pinned_actor_session: business_role phai la 1 thanh vien Stage0PBusinessRole "
                f"(T9-02, khong con nhan str tuy y) — nhan duoc {business_role!r}")
        self._pool = pool
        self._staff_id = staff_id
        self._pin_secret = pin_secret
        self._business_role = business_role
        self._conn = None

    async def __aenter__(self):
        conn = await self._pool.acquire()
        self._conn = conn
        try:
            await conn.execute("SET ROLE alpha3s_m4_actor_binder")
            # T10-03: luoi an toan chu dong - xoa BAT KY pin nao con sot lai tren CHINH connection
            # vat ly nay tu lan checkout truoc. `m4_stage0p_unpin_actor()` la 1 DELETE don gian,
            # KHONG RAISE cho truong hop binh thuong "chua tung co pin" — bat ky PostgresError nao
            # o day la 1 loi ha tang THAT (quyen/ket noi), KHONG con bi nuot roi tiep tuc nhu REV10.
            await conn.execute("SELECT m4_stage0p_unpin_actor()")
            await pin_actor(conn, staff_id=self._staff_id, pin_secret=self._pin_secret)
            await conn.execute("RESET ROLE")
            # T9-02: gia tri enum + quote identifier an toan (2 lop, xem module docstring).
            await conn.execute(f"SET ROLE {_quote_role_ident(self._business_role.value)}")
        except Exception:
            # T10-03: BAT KY that bai nao sau acquire() (safety-unpin/pin_actor/RESET ROLE/SET
            # ROLE business_role) deu di qua CUNG 1 primitive cleanup/discard voi __aexit__ —
            # khong con 1 nhanh rieng de sot buoc, khong con connection "mo cong" ma khong ai
            # cleanup vi __aenter__ tu raise (Python khong goi __aexit__ khi __aenter__ raise).
            await _wait_cleanup_and_release(self._pool, conn)
            self._conn = None
            raise
        return conn

    async def __aexit__(self, exc_type, exc, tb):
        conn = self._conn
        if conn is None:
            return False
        await _wait_cleanup_and_release(self._pool, conn)
        self._conn = None
        return False


async def _wait_cleanup_and_release(pool: asyncpg.Pool, conn) -> None:
    """T9-01/T10-03: primitive cleanup/discard DUY NHAT, dung chung boi `__aenter__` (khi setup
    that bai giua chung) VA `__aexit__` (duong binh thuong). Tao 1 Task cleanup TUONG MINH, LAP
    LAI `await asyncio.shield(cleanup_task)` cho toi khi `cleanup_task.done()` la THAT — 1 lan
    cancel THEM chi lam vong lap thu lai (cleanup_task KHONG bi huy, KHONG bi tao lai), khong bao
    gio cho phep tien toi release() truoc khi cleanup that su ket thuc. Deadline backstop
    `_CLEANUP_MAX_WAIT_SECONDS`: neu vuot qua, `conn.terminate()` (dong VAT LY ngay lap tuc) roi
    discard thay vi release binh thuong; cleanup_task tu bao loi cung discard, khong bao gio tra
    1 connection co the o trang thai session/role khong xac dinh ve pool."""
    cleanup_task = asyncio.ensure_future(_cleanup_connection(conn))
    deadline = time.monotonic() + _CLEANUP_MAX_WAIT_SECONDS
    terminated = False
    while not cleanup_task.done():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _log("m4_pool_cleanup_deadline_exceeded_terminating_connection")
            conn.terminate()
            terminated = True
            break
        try:
            await asyncio.wait_for(asyncio.shield(cleanup_task), timeout=remaining)
        except asyncio.CancelledError:
            continue
        except asyncio.TimeoutError:
            continue
        except Exception as e:  # noqa: BLE001 - cleanup_task tu raise, xu ly duoi day qua .exception()
            _log("m4_pool_cleanup_task_raised", error_type=type(e).__name__)
            break

    cleanup_failed = terminated or cleanup_task.cancelled() or (
        cleanup_task.done() and cleanup_task.exception() is not None)
    if cleanup_failed and not terminated:
        _log("m4_pool_cleanup_failed_terminating_connection")
        conn.terminate()
        terminated = True

    await _release_or_discard(pool, conn, discard=terminated)


async def _cleanup_connection(conn) -> None:
    """T9-01: 1 don vi cleanup DUY NHAT, chay nhu 1 Task tuong minh (khong phai coroutine tao lai
    moi lan `__aexit__` lap) — moi lenh co timeout rieng (`_CLEANUP_STATEMENT_TIMEOUT_SECONDS`) de
    tu no khong bao gio treo VO THOI HAN, danh backstop `_CLEANUP_MAX_WAIT_SECONDS` cua caller cho
    truong hop hiem hon (vd connection object con "song" ve mat Python nhung socket that su da
    chet theo kieu khong the phat hien qua 1 lenh timeout don le)."""
    await conn.execute("RESET ROLE", timeout=_CLEANUP_STATEMENT_TIMEOUT_SECONDS)
    await conn.execute("SET ROLE alpha3s_m4_actor_binder", timeout=_CLEANUP_STATEMENT_TIMEOUT_SECONDS)
    await unpin_actor(conn)
    await conn.execute("RESET ROLE", timeout=_CLEANUP_STATEMENT_TIMEOUT_SECONDS)


async def _release_or_discard(pool: asyncpg.Pool, conn, *, discard: bool) -> None:
    """T9-01: neu cleanup KHONG the xac nhan hoan tat sach (terminate/exception/cancel), discard
    connection thay vi tra ve pool cho request khac tai su dung o 1 trang thai khong xac dinh —
    dong VAT LY (`close()`, an toan goi lai du da `terminate()`) TRUOC khi `pool.release()`; asyncpg
    tu phat hien connection da dong va thay the bang 1 connection MOI cho lan acquire tiep theo
    thay vi tra lai chinh no."""
    if discard:
        try:
            await conn.close(timeout=1.0)
        except Exception as e:  # noqa: BLE001
            _log("m4_pool_discard_close_failed", error_type=type(e).__name__)
    await pool.release(conn)


def pinned_actor_session(pool: asyncpg.Pool, *, staff_id: int, pin_secret: str,
                         business_role: Stage0PBusinessRole) -> _PinnedSession:
    """Context manager DUY NHAT de lay 1 connection tu pool VA lam viec nhu 1 actor da pin, vd:

        async with pinned_actor_session(pool, staff_id=1, pin_secret="...",
                                        business_role=Stage0PBusinessRole.CONTROL_PLANE) as conn:
            await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", True, ref)

    Connection KHONG BAO GIO thoat khoi khoi `async with` trong luc pin con hieu luc — day la
    invariant CA yeu cau (T8-01, gach dau dong 3). Neu `pin_actor` that bai (staff sai/pin_secret
    sai/rate-limit), connection duoc tra ve pool NGAY (khong pin) va `ActorNotPinnedError` duoc
    nem cho caller — xem `_PinnedSession.__aenter__`. `business_role` PHAI la 1 thanh vien
    `Stage0PBusinessRole` (T9-02) — truyen gia tri khac se `TypeError` NGAY, TRUOC khi bat ky cau
    SQL nao duoc gui."""
    return _PinnedSession(pool, staff_id=staff_id, pin_secret=pin_secret, business_role=business_role)


__all__ = [
    "create_stage0p_pool",
    "pinned_actor_session",
    "ActorNotPinnedError",
    "Stage0PBusinessRole",
]
